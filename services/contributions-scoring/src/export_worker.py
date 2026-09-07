"""Point Ledger CSV export worker (US-7.9).

Invoked asynchronously by ExportService with {"source": ..., "jobId": ...}. Its
own Lambda off the same code package, so a multi-minute export never occupies an
interactive API container and is not bound by API Gateway's 29 s ceiling — which
is the whole reason it exists.

Rows come from the SAME read path the on-screen table uses
(`ReadService.group_ledger`), not a bespoke query. That is deliberate: the scope
rule, the filter semantics and the per-row enrichment (member email and name from
the projection, the activity fallback for adjustments, the derived activity
category) all live there, and a second implementation would drift from the table
the CSV is supposed to match.
"""
from __future__ import annotations

import csv
import io
import os

from _conventions.logger import get_logger, log
from export_service import (
    KIND_POINT_LEDGER,
    STATUS_FAILED,
    STATUS_READY,
    STATUS_RUNNING,
)
from models import ROLE_CL, now_iso, pillar_label
from providers import ExportStorage
from repository import ContributionsRepository

_logger = get_logger("contributions")

# Page size for the ledger walk. The read path caps `limit` at 200.
PAGE_SIZE = 200

# Column order MUST match pointLedger.ts::toExportRow — the browser built this
# file until now, and an export that changes shape depending on which code path
# produced it would break anyone's saved spreadsheet.
COLUMNS = ("member_name", "member_email", "user_group", "activity_type", "activity",
           "pillar", "points", "source", "earned_date", "quarter")


def _date_only(value) -> str:  # noqa: ANN001
    """ISO timestamp -> its calendar date; anything unrecognised passes through.
    Mirrors the frontend `dateOnly` helper the old export used."""
    text = "" if value is None else str(value)
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else text


def _cell(row: dict, column: str, *, group_name: str):
    """One CSV cell. Reproduces what the browser computed for the three columns
    it derived rather than read straight off the row: `user_group` (resolved from
    the group list), `pillar` (number -> label) and `earned_date` (date only)."""
    if column == "member_name":
        return row.get("memberName") or ""
    if column == "member_email":
        return row.get("memberEmail") or ""
    if column == "user_group":
        return group_name
    if column == "activity_type":
        return row.get("activityCategoryLabel") or row.get("activity") or ""
    if column == "activity":
        return row.get("activity") or ""
    if column == "pillar":
        return pillar_label(row.get("pillar"))
    if column == "points":
        try:
            return int(row.get("points") or 0)
        except (TypeError, ValueError):
            return 0
    if column == "source":
        return row.get("source") or ""
    if column == "earned_date":
        return _date_only(row.get("earnedDate"))
    if column == "quarter":
        return row.get("quarter") or ""
    return ""


class _JobPrincipal:
    """Reconstructs the caller for the read path from the job record.

    The worker has no request and no JWT, but `group_ledger` derives scope from a
    principal. Presenting the job's own group as a CommunityLeader's chosen group
    reproduces exactly the rows the requester was authorised for — the scope was
    already resolved and frozen onto the job when it was created, so this cannot
    widen it. Using CL here rather than the original role keeps the worker from
    depending on `led_group_id`, which may have changed since.
    """

    def __init__(self, actor: str):
        self.user_id = actor
        self.role = ROLE_CL
        self.account_type = "cognito"
        self.led_group_id = None
        self.member_group_ids = []
        self.name = ""


def handler(event: dict, context) -> dict:  # noqa: ANN001
    job_id = (event or {}).get("jobId", "")
    if not job_id:
        log(_logger, 40, "export worker invoked without a jobId")
        return {"ok": False, "reason": "missing jobId"}

    import boto3  # noqa: PLC0415 — lazy, consistent with the other entrypoints
    repo = ContributionsRepository(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    storage = ExportStorage()

    job = repo.get_export_job(job_id)
    if not job:
        # Expired or never written. Nothing to do, and retrying cannot help.
        log(_logger, 30, "export job not found", jobId=job_id)
        return {"ok": False, "reason": "job not found"}
    if job.get("kind") != KIND_POINT_LEDGER:
        log(_logger, 30, "export job of unexpected kind", jobId=job_id,
            kind=str(job.get("kind")))
        return {"ok": False, "reason": "wrong kind"}
    if job.get("status") == STATUS_READY:
        # Async invocations can be delivered twice. A finished export must not be
        # rebuilt.
        log(_logger, 20, "export already complete", jobId=job_id)
        return {"ok": True, "reason": "already complete"}

    actor = job.get("actor", "")
    try:
        rows = _run_export(repo, storage, job_id, job)
    except Exception:  # noqa: BLE001 — every failure must land on the job record
        # Swallowed on purpose; the function is configured MaximumRetryAttempts: 0.
        # Re-raising would let Lambda retry after this handler already marked the
        # job failed and released the lock, which could flip a job the leader was
        # told failed back to ready, or run concurrently with their manual retry.
        _logger.exception("export failed", extra={"jobId": job_id})
        repo.update_export_job(job_id, {
            "status": STATUS_FAILED,
            # Deliberately generic: this string is shown to the leader, and
            # exception text can carry internals.
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
    from framework_service import FrameworkService  # noqa: PLC0415 — lazy, as elsewhere
    from read_service import ReadService  # noqa: PLC0415

    group_id = job.get("groupId") or ""
    if not group_id:
        # A ledger job with no group cannot be completed, and retrying will not
        # add one. Raise so the handler marks it failed rather than writing an
        # empty CSV that looks like a group with no entries.
        raise ValueError("point-ledger export job has no groupId")

    quarter = job.get("quarter") or ""
    filters = job.get("filters") or {}
    group_name = job.get("groupName") or group_id

    # The read path needs a framework (for category labels) and no event
    # publisher, so nothing here requires EventBridge permissions.
    reads = ReadService(repo, FrameworkService(repo, _NoEvents()))
    principal = _JobPrincipal(job.get("actor", ""))

    repo.update_export_job(job_id, {"status": STATUS_RUNNING, "processed": 0})

    buf = io.StringIO()
    # lineterminator="\n" matches the previous client-side export, which joined
    # rows with "\n"; csv's default "\r\n" would change every line of the file for
    # no benefit. QUOTE_MINIMAL matches the old escape rule (quote only when the
    # value contains a comma, quote or newline).
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(COLUMNS)

    processed = 0
    cursor: str | None = None
    while True:
        qs = {"groupId": group_id, "quarter": quarter, "limit": str(PAGE_SIZE), **filters}
        if cursor:
            qs["cursor"] = cursor
        page = reads.group_ledger(qs, principal=principal)
        rows = page.get("items") or []
        for row in rows:
            writer.writerow([_cell(row, c, group_name=group_name) for c in COLUMNS])
        processed += len(rows)

        # One write per page, not per row.
        repo.update_export_job(job_id, {"processed": processed})

        cursor = page.get("cursor")
        if not cursor:
            break

    storage.put_csv(job["fileKey"], buf.getvalue().encode("utf-8"))
    repo.update_export_job(job_id, {
        "status": STATUS_READY,
        "processed": processed,
        # Set the denominator to what was actually written so a finished bar reads
        # exactly 100% (the job starts with the row count unknown). `totalRows`,
        # not `total` — see export_service.start_export on the GSI1 key collision.
        "totalRows": processed,
        "completedAt": now_iso(),
    })
    return processed


class _NoEvents:
    """Event publisher stand-in. The ledger read path does not publish, and giving
    the worker a real publisher would imply permissions it never exercises."""

    def publish(self, event_type, data, correlation_id=None):  # noqa: ANN001, ANN201, ARG002
        return None
