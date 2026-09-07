"""Worker Lambda for the async Member Directory CSV export.

Invoked asynchronously (InvocationType="Event") by ExportService.start_export
with {"source": "member-csv-export", "jobId": "<id>"}. Runs as its own function
(MemberExportFn) off the same deployment zip as the API — the same arrangement as
indexer.py — so a multi-minute export never occupies an interactive API container.

Rows come from OPENSEARCH via `search_members`, which already does stable
`search_after` paging with an `id.keyword` tiebreaker. That replaces the previous
export path's full DynamoDB `Scan` of the entire single table (which also read
every shoutout, recipient copy and reaction marker just to find profiles), and it
makes an exact `_count` cheap so the progress bar can show a real percentage.

The accepted tradeoff, reversing the note in directory_service.py: the CSV is a
snapshot of the INDEX, so it can lag the roster or omit members whose indexing
failed until the nightly reindex repairs them.

Memory: the CSV is assembled in memory and written with one PutObject. Directory
rows are ~120 bytes, so 25k members is ~3 MB — well inside the function's 512 MB.
"""
from __future__ import annotations

import csv
import io
import os

from _conventions.logger import get_logger, log
from export_service import (
    STATUS_FAILED,
    STATUS_READY,
    STATUS_RUNNING,
)
from models import now_iso
from providers import ExportStorage
from repository import ProfileRepository

_logger = get_logger("member-profiles.export")

# Rows fetched per OpenSearch request. A 25k export is then ~25 round trips.
PAGE_SIZE = 1_000

# Columns, in order. Deliberately the SAME set and order the previous
# client-side export produced — directory_row_public's keys minus the id-ish ones
# that frontend/src/lib/exportCsv.ts stripped (`id`, `memberGroupIds`) — so the
# file a leader receives does not change shape.
#
# `groups` is the ONE column whose CONTENT changes, and it is a fix: the browser
# rendered an array of objects via String(), so the old column literally read
# "[object Object],[object Object]". It now carries real group names.
COLUMNS = ("firstName", "lastName", "email", "role", "status",
           "groups", "city", "country", "awsProject")

# Separator for the multi-value groups column. Semicolon, not comma, so the cell
# needs no CSV quoting and stays readable in a spreadsheet.
GROUP_SEPARATOR = "; "


def _group_cell(doc: dict, group_names: dict) -> str:
    """Group membership as human-readable names.

    Falls back to the raw group id for any id missing from the map — which
    happens if the group-name lookup failed at request time, or a group was
    created after the job started. Degraded but never wrong.
    """
    ids = [g.get("groupId") for g in (doc.get("groups") or [])
           if isinstance(g, dict) and g.get("groupId")]
    if not ids:
        # Index docs also carry a flat groupIds array (added by _member_to_doc).
        ids = [g for g in (doc.get("groupIds") or []) if g]
    return GROUP_SEPARATOR.join(group_names.get(gid, gid) for gid in ids)


def _cell(doc: dict, column: str, group_names: dict) -> str:
    """One CSV cell, matching how the browser used to render it.

    Note `status` is NOT title-cased here, unlike identity-access's user export:
    member-profiles stores and serves lowercase "active"/"inactive" natively
    (models.STATUS_ACTIVE), so that is what this CSV has always contained.
    """
    if column == "groups":
        return _group_cell(doc, group_names)
    value = doc.get(column)
    if column == "awsProject":
        # directory_row_public coerced this with bool(), and the browser rendered
        # it via String(), so it was always "true"/"false" — never blank.
        return "true" if bool(value) else "false"
    return "" if value is None else str(value)


def handler(event: dict, context) -> dict:  # noqa: ANN001
    job_id = (event or {}).get("jobId", "")
    if not job_id:
        log(_logger, 40, "export worker invoked without a jobId")
        return {"ok": False, "reason": "missing jobId"}

    import boto3  # noqa: PLC0415 — lazy, consistent with the other entrypoints
    repo = ProfileRepository(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    storage = ExportStorage()

    job = repo.get_export_job(job_id)
    if not job:
        # Expired or never written. Nothing to do, and retrying cannot help.
        log(_logger, 30, "export job not found", jobId=job_id)
        return {"ok": False, "reason": "job not found"}
    if job.get("status") == STATUS_READY:
        # Async invocations can be redelivered; a finished export must not be
        # rebuilt.
        log(_logger, 20, "export already complete", jobId=job_id)
        return {"ok": True, "reason": "already complete"}

    actor = job.get("actor", "")
    try:
        rows = _run_export(repo, storage, job_id, job)
    except Exception:  # noqa: BLE001 — every failure must land on the job record
        # Swallowed on purpose, and the function is configured with
        # MaximumRetryAttempts: 0. Re-raising would make Lambda retry after this
        # handler has already marked the job failed and released the lock, so a
        # retry could flip a job the leader was told failed back to ready.
        _logger.exception("export failed", extra={"jobId": job_id})
        repo.update_export_job(job_id, {
            "status": STATUS_FAILED,
            # Deliberately generic: shown to the leader, and exception text can
            # carry internals.
            "error": "The export could not be completed. Please try again.",
            "completedAt": now_iso(),
        })
        if actor:
            repo.release_export_lock(actor)
        return {"ok": False}

    if actor:
        repo.release_export_lock(actor)
    log(_logger, 20, "export complete", jobId=job_id, rows=rows)
    return {"ok": True, "rows": rows}


def _run_export(repo, storage, job_id: str, job: dict) -> int:
    filters = job.get("filters") or {}
    q = filters.get("q") or None
    role = filters.get("role") or None
    group_id = filters.get("groupId") or None
    group_names = job.get("groupNames") or {}

    # Exact denominator for the progress bar, built from the same query as the row
    # walk so the two cannot disagree. None (OpenSearch unconfigured) leaves
    # `total` unset and the UI falls back to an indeterminate bar.
    total = repo.count_members(q=q, role=role, group_id=group_id)
    repo.update_export_job(job_id, {
        "status": STATUS_RUNNING,
        "total": total,
        "processed": 0,
    })

    buf = io.StringIO()
    # lineterminator="\n" matches the previous client-side export, which joined
    # rows with "\n"; csv's default "\r\n" would change every line of the file for
    # no benefit. QUOTE_MINIMAL matches the old escape rule.
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(COLUMNS)

    processed = 0
    cursor: str | None = None
    while True:
        docs, cursor = repo.search_members(
            q=q, role=role, group_id=group_id,
            limit=PAGE_SIZE, sort="firstName", sort_dir="asc", cursor=cursor,
        )
        for doc in docs:
            writer.writerow([_cell(doc, c, group_names) for c in COLUMNS])
        processed += len(docs)

        # One write per page (~25 for a 25k export), not per row.
        repo.update_export_job(job_id, {"processed": processed})

        if not cursor or not docs:
            break

    storage.put_csv(job["fileKey"], buf.getvalue().encode("utf-8"))
    repo.update_export_job(job_id, {
        "status": STATUS_READY,
        "processed": processed,
        # Reconcile the denominator with reality: the count was taken before the
        # walk, so members created meanwhile would otherwise leave the bar short
        # of 100% on a finished export.
        "total": processed,
        "completedAt": now_iso(),
    })
    return processed
