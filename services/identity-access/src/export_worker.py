"""Worker Lambda for the async admin user CSV export.

Invoked asynchronously (InvocationType="Event") by ExportService.start_export
with {"source": "user-csv-export", "jobId": "<id>"}. Runs as its own function
(UserExportFn) off the same deployment zip as the API — the same arrangement as
indexer.py — so a multi-minute export never occupies an interactive API
container.

ROWS COME FROM OPENSEARCH, not DynamoDB. That is what makes this affordable:

* The index documents are already flat. Serializing from DynamoDB went through
  UserService._serialize, which issued one extra Query PER MEMBER to derive
  group membership — ~25,000 sequential round trips for a 25k export, and the
  CSV then discarded the column anyway.
* `search_after` gives stable deep pagination, and `_count` gives an exact
  denominator for the progress bar for the price of one request.

The tradeoff, accepted deliberately: the index is populated asynchronously from
the DynamoDB stream, so the CSV is a snapshot of the INDEX. It can lag the roster
by seconds-to-minutes, and can omit users whose indexing failed into the DLQ
until the nightly reindex repairs them. There is no reconciliation check.

Memory: the CSV is assembled in memory and written with a single PutObject.
At ~150 bytes/row that is ~4 MB for 25k users, comfortably inside the function's
512 MB. A roster large enough to threaten that would need multipart upload.
"""
from __future__ import annotations

import csv
import io
import os

from _conventions.logger import get_logger, log
from export_service import (
    KIND_GROUP_MEMBERS,
    STATUS_FAILED,
    STATUS_READY,
    STATUS_RUNNING,
)
from models import STATUS_ACTIVE, STATUS_INACTIVE, now_iso
from providers import ExportStorage
from repository import IdentityRepository

_logger = get_logger("identity-access.export")

# Rows fetched per OpenSearch request. Large enough that a 25k export is ~25
# round trips, small enough that one page is a trivial amount of memory.
PAGE_SIZE = 1_000

# Columns, in order. Deliberately identical to what the previous client-side
# export produced (the union of user_public's keys minus the id-ish ones that
# frontend/src/lib/exportCsv.ts stripped), so the file an admin receives does
# not change shape — only how it is produced. `groupIds`/`ledGroupId` were
# always dropped by that filter and are now never computed at all.
COLUMNS = ("email", "firstName", "lastName", "role", "status",
           "city", "country", "professionalRole", "awsProject", "timeZone")

# Columns for the group-roster export (UGL > My Group > Export). The same base
# columns plus the two that only mean anything inside a group, in the order the
# old client-side export produced them: `toCsv` took the union of each row's keys
# in insertion order, and a row was user_public(...) then roleInGroup then
# joinedAt, with the id-ish keys (id, ledGroupId, groupIds) filtered out. So the
# file a leader receives keeps its shape; only how it is produced changes.
GROUP_COLUMNS = (*COLUMNS, "roleInGroup", "joinedAt")

# Rows per page when walking the group roster. Smaller than the OpenSearch page
# size because each row costs a DynamoDB GetItem for the member's profile, so a
# page is real work rather than one bulk read.
GROUP_PAGE_SIZE = 200


def _cell(doc: dict, column: str) -> str:
    """One CSV cell, matching the old client-side rendering.

    Two fields need translation because the OpenSearch document is not shaped
    like the API response the browser used to format:

    * `status` is stored lowercase in the shared index (indexer.py normalises it
      so identity-access's "Active" and member-profiles' "active" agree). Export
      restores the capitalised form the CSV has always carried.
    * `awsProject` is a real boolean in the document; the browser rendered it via
      String(true), so "true"/"false" lowercase is what admins have seen.
    """
    value = doc.get(column)
    if column == "status":
        if not value:
            return ""
        return STATUS_ACTIVE if str(value).lower() == STATUS_ACTIVE.lower() else STATUS_INACTIVE
    if column == "awsProject":
        if value is None or value == "":
            return ""
        return "true" if bool(value) else "false"
    return "" if value is None else str(value)


def _group_cell(row: dict, column: str) -> str:
    """One CSV cell for a group-roster row.

    These rows come from the API serializer (`user_public` + roleInGroup +
    joinedAt), NOT from an OpenSearch document, so the translations `_cell` makes
    do not apply here: `status` already carries its capitalised form and
    `awsProject` is already a real boolean. Only two things need doing.
    """
    value = row.get(column)
    if column == "awsProject":
        # user_public coerces with bool(), so this was always "true"/"false" —
        # never blank, unlike the admin export where the index field can be absent.
        return "true" if bool(value) else "false"
    if column == "joinedAt":
        # Date only. The previous export trimmed this with dateOnly() because the
        # file is read in a spreadsheet, where a time component is noise and
        # invites timezone confusion. Blank for a leader who is not also a member
        # — leadership is not membership, so there is no join date to show.
        return _date_only(value)
    return "" if value is None else str(value)


def _date_only(value) -> str:  # noqa: ANN001
    """ISO timestamp -> its calendar date; anything unrecognised passes through."""
    text = "" if value is None else str(value)
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else text


def handler(event: dict, context) -> dict:  # noqa: ANN001
    job_id = (event or {}).get("jobId", "")
    if not job_id:
        log(_logger, 40, "export worker invoked without a jobId")
        return {"ok": False, "reason": "missing jobId"}

    import boto3  # noqa: PLC0415 — lazy, consistent with the other entrypoints
    repo = IdentityRepository(boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"]))
    storage = ExportStorage()

    job = repo.get_export_job(job_id)
    if not job:
        # Expired or never written. Nothing to do, and retrying cannot help.
        log(_logger, 30, "export job not found", jobId=job_id)
        return {"ok": False, "reason": "job not found"}
    if job.get("status") == STATUS_READY:
        # Async invocations are retried by Lambda on error, so the same job can
        # arrive twice. A finished export must not be rebuilt.
        log(_logger, 20, "export already complete", jobId=job_id)
        return {"ok": True, "reason": "already complete"}

    actor = job.get("actor", "")
    filters = job.get("filters") or {}
    try:
        # One worker, two row sources. The lifecycle around this call — progress
        # writes, failure handling, lock release, presigned download — is identical
        # for both, which is the reason they share a function rather than each
        # getting a Lambda that would drift.
        if job.get("kind") == KIND_GROUP_MEMBERS:
            rows = _run_group_member_export(repo, storage, job_id, job, filters)
        else:
            rows = _run_export(repo, storage, job_id, job, filters)
    except Exception:  # noqa: BLE001 — every failure must land on the job record
        # Swallowed on purpose, and the function is configured with
        # MaximumRetryAttempts: 0. Re-raising would make Lambda retry the
        # invocation after this handler has already marked the job failed and
        # released the lock, so a retry could flip a job the admin has been told
        # failed back to ready — or run a second export concurrently with a
        # manual retry. One attempt, one clear outcome, admin retries if needed.
        _logger.exception("export failed", extra={"jobId": job_id})
        repo.update_export_job(job_id, {
            "status": STATUS_FAILED,
            # Deliberately generic: this string is shown to the admin, and
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


def _run_export(repo, storage, job_id: str, job: dict, filters: dict) -> int:
    q = filters.get("q") or None
    role = filters.get("role") or None
    status = filters.get("status") or None

    # Exact denominator for the progress bar. Same query builder as the row walk,
    # so the two cannot disagree. None (OpenSearch unconfigured) leaves `total`
    # unset and the UI falls back to an indeterminate bar.
    total = repo.count_users(q=q, role=role, status=status)
    repo.update_export_job(job_id, {
        "status": STATUS_RUNNING,
        "total": total,
        "processed": 0,
    })

    buf = io.StringIO()
    # lineterminator="\n" matches the previous client-side export, which joined
    # rows with "\n"; csv's default is "\r\n" and would change every line of the
    # file for no benefit. QUOTE_MINIMAL matches the old escape rule (quote only
    # when the value contains a comma, quote or newline).
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(COLUMNS)

    processed = 0
    cursor: str | None = None
    while True:
        docs, cursor = repo.search_users(
            q=q, role=role, status=status,
            limit=PAGE_SIZE, sort="name", sort_dir="asc", cursor=cursor,
        )
        for doc in docs:
            writer.writerow([_cell(doc, c) for c in COLUMNS])
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
        # walk, so users created meanwhile would otherwise leave the bar short of
        # 100% on a finished export.
        "total": processed,
        "completedAt": now_iso(),
    })
    return processed


def _run_group_member_export(repo, storage, job_id: str, job: dict, filters: dict) -> int:
    """Build one group's roster CSV.

    Rows come from the AUTHORITATIVE DynamoDB roster via
    GroupService.list_group_members_page, not from OpenSearch. Two reasons, and
    the first is decisive: `joinedAt` lives on the membership projection and is
    not in the search index at all, so an index-sourced export could not produce
    this file's columns. Second, it preserves the choice the previous export
    documented — a roster is read in order to act on people, so it should not
    quietly omit a member whose indexing is lagging.

    The cost is bounded per page, not per group: the projection is a real Query
    with ExclusiveStartKey and profiles are read only for the rows a page
    returns. The leaders-then-members two-block cursor is handled inside
    list_group_members_page, including the case where leaders fill a whole page.
    """
    from group_service import GroupService  # noqa: PLC0415 — lazy, as elsewhere here

    group_id = job.get("groupId") or ""
    if not group_id:
        # A group job with no group cannot be completed, and retrying will not
        # add one. Raise so the handler marks it failed rather than writing an
        # empty CSV that looks like a group with no members.
        raise ValueError("group-member export job has no groupId")

    keyword = filters.get("q") or None

    # Events are never published on the listing path, so a no-op publisher keeps
    # the worker from needing EventBridge permissions it would not use.
    groups = GroupService(repo, _NoEvents())

    group = repo.get_group(group_id)
    leader_ids = (group or {}).get("leaderIds", [])

    # Exact denominator where one is affordable; None when a keyword filter makes
    # it not, which renders an indeterminate bar rather than a fabricated number.
    total = repo.count_group_members(group_id, leader_ids=leader_ids, keyword=keyword)
    repo.update_export_job(job_id, {
        "status": STATUS_RUNNING,
        "total": total,
        "processed": 0,
    })

    buf = io.StringIO()
    # Matches the previous client-side export byte for byte: rows joined with
    # "\n" (csv's default "\r\n" would rewrite every line) and QUOTE_MINIMAL.
    writer = csv.writer(buf, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(GROUP_COLUMNS)

    processed = 0
    cursor: str | None = None
    while True:
        page = groups.list_group_members_page(
            group_id, q=keyword, limit=GROUP_PAGE_SIZE, cursor=cursor)
        rows = page.get("items") or []
        for row in rows:
            writer.writerow([_group_cell(row, c) for c in GROUP_COLUMNS])
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
        # Reconcile the denominator with what was actually written: the count is
        # taken before the walk, so joins or departures during the export would
        # otherwise leave a finished bar short of (or past) 100%.
        "total": processed,
        "completedAt": now_iso(),
    })
    return processed


class _NoEvents:
    """Event publisher stand-in. The roster listing does not publish, and giving
    the worker a real publisher would imply permissions it never exercises."""

    def publish(self, event_type, data, correlation_id=None):  # noqa: ANN001, ANN201, ARG002
        return None
