"""Async CSV export of the Point Ledger (US-7.9).

Replaces a client-side export that walked the cursor in the browser
(`exportPagedCsv`), which had three problems at group scale: it held every row in
memory in the tab, it gave no progress beyond a spinner, and navigating away
mid-walk produced a silently truncated file. It was also capped at 100k rows.

So the export is a job, matching Admin > Users exactly:

    POST /contributions/group-ledger/export        -> create the job record,
                                                      invoke the worker async,
                                                      return the job id (202)
    (worker)                                       -> page the ledger into a CSV
                                                      in S3, updating `processed`
    GET  /contributions/group-ledger/export/{id}   -> polled for progress; once
                                                      ready it carries a freshly
                                                      minted, short-lived
                                                      presigned download URL

Deliberate decisions carried over from the users export:

* NO delete-on-download. A presigned GET is a direct browser-to-S3 transfer this
  service never observes completing, so "delete when finished" is not
  implementable. Cleanup is the bucket's 1-day lifecycle rule; the 5-minute URL
  TTL bounds reachability meanwhile.
* NO resume across page loads. Navigating away loses the link; the job still
  finishes and the file expires unread. Re-exporting is cheap.
* ONE in-flight export per actor, enforced by a conditional lock write. The
  disabled button is presentation only.

Scope is fail-closed and repeats `ReadService.group_ledger`'s rule rather than
trusting the request: a UGL always exports their own led group whatever the body
says, a CL must name a group, and nobody else may call it. Getting this wrong
here would let a leader export another group's ledger, which is the one thing the
read path is careful to prevent.
"""
from __future__ import annotations

import json
import os

from _conventions.errors import ForbiddenError, NotFoundError, ValidationError
from _conventions.logger import get_logger, log
from models import ROLE_CL, ROLE_UGL, epoch, new_id, now_iso

_logger = get_logger("contributions")

# Job record lifetime. Aligned with the export bucket's 1-day expiry so a status
# lookup never outlives the file it describes, nor the reverse.
EXPORT_JOB_TTL_SECONDS = 86_400

# An export is abandoned after this long, releasing the per-actor lock for a
# retry. Comfortably beyond the worker's own 900 s Lambda timeout.
EXPORT_STALE_AFTER_SECONDS = 1_800

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# Filters the export honours — the same set the Point Ledger table filters by, so
# the CSV matches what the leader is looking at. `groupId` and `quarter` are
# handled separately: they are scope, not optional narrowing.
EXPORT_FILTER_KEYS = ("memberId", "source", "activityType")

KIND_POINT_LEDGER = "point-ledger"


class ExportService:
    def __init__(self, repo, storage, lambda_client=None, worker_function: str | None = None):
        self._repo = repo
        self._storage = storage
        self._lambda = lambda_client
        self._worker_function = worker_function or os.environ.get(
            "EXPORT_WORKER_FUNCTION",
            f"contributions-export-{os.environ.get('STAGE', 'dev')}")

    @staticmethod
    def _stamp() -> str:
        """Timestamp for the download name, so a folder of exports stays sortable
        and a second export never silently overwrites the first in the browser."""
        return now_iso()[:19].replace(":", "").replace("-", "")

    # ---------------- start (POST /contributions/group-ledger/export) ----------
    def start_export(self, body: dict, *, principal) -> dict:
        """Create a Point Ledger export job for the caller's group.

        `groupName` is accepted from the client and stored on the job. That is not
        laziness: this service holds group IDS only — it learns of a group when
        one is registered for scoring and never its name — and the CSV's
        `user_group` column carried a NAME when the browser built it. Resolving it
        here would mean a cross-service call from a worker that otherwise needs no
        network. The caller already has the name on screen, only a leader who may
        read that group can reach this, and the value is display-only: it never
        affects which rows are exported.
        """
        # Same fail-closed scope rule as ReadService.group_ledger.
        if principal.role == ROLE_UGL:
            group_id = principal.led_group_id
        elif principal.role == ROLE_CL:
            group_id = (body.get("groupId") or "").strip()
        else:
            raise ForbiddenError()
        if not group_id:
            raise ValidationError(message="A user group is required to export the point ledger.")

        quarter = (body.get("quarter") or "").strip()
        if not quarter:
            raise ValidationError(message="A quarter is required to export the point ledger.")

        filters = {k: (body.get(k) or "").strip() for k in EXPORT_FILTER_KEYS}
        filters = {k: v for k, v in filters.items() if v}

        actor = principal.user_id
        job_id = new_id("plexp")
        now = epoch()

        if not self._repo.acquire_export_lock(actor, job_id,
                                              ttl_seconds=EXPORT_STALE_AFTER_SECONDS):
            raise ValidationError(
                message="An export is already running for your account. "
                        "Wait for it to finish before starting another.")

        job = {
            "jobId": job_id,
            "actor": actor,
            "kind": KIND_POINT_LEDGER,
            "status": STATUS_QUEUED,
            "processed": 0,
            # NOT named `total`: on this table `total` is GSI1's sort key (the
            # leaderboard index, a Number), and DynamoDB rejects any item that
            # carries an index key attribute with a mismatched type — so a job row
            # with `total: None` fails to write at all. Stored as `totalRows` and
            # surfaced as `total` on the wire, which keeps the contract identical
            # to the users export.
            #
            # Left unknown at creation: counting the filtered ledger costs the
            # same walk as the export itself, so the UI shows an indeterminate bar
            # rather than paying twice for a number.
            "totalRows": None,
            "groupId": group_id,
            "groupName": (body.get("groupName") or "").strip(),
            "quarter": quarter,
            "filters": filters,
            "fileName": f"point-ledger-{self._stamp()}.csv",
            # Its own prefix so the IAM grant for this export cannot read another
            # service's exports in the shared bucket.
            "fileKey": f"contributions/{job_id}.csv",
            "error": None,
            "startedAt": now_iso(),
            "completedAt": None,
            "expiresAt": now + EXPORT_JOB_TTL_SECONDS,
            "ttl": now + EXPORT_JOB_TTL_SECONDS,
        }
        self._repo.put_export_job(job)

        # Invoke AFTER the record exists, so the SPA's first poll can never find a
        # job id the worker is already writing to but that does not yet exist.
        try:
            self._invoke_worker(job_id)
        except Exception as exc:  # noqa: BLE001 — reported as a failed job, not a 500
            log(_logger, 40, "export worker invoke failed", jobId=job_id)
            self._repo.update_export_job(job_id, {
                "status": STATUS_FAILED,
                "error": "Could not start the export worker.",
                "completedAt": now_iso(),
            })
            self._repo.release_export_lock(actor)
            raise ValidationError(
                message="Unable to start the export. Please try again.") from exc

        return self._public(job)

    def _invoke_worker(self, job_id: str) -> None:
        client = self._lambda
        if client is None:
            import boto3  # noqa: PLC0415 — lazy, mirrors the other providers
            client = boto3.client("lambda")
        client.invoke(
            FunctionName=self._worker_function,
            InvocationType="Event",   # async — returns immediately, does not wait
            Payload=json.dumps({"source": "point-ledger-csv-export",
                                "jobId": job_id}).encode(),
        )

    # ---------------- status (GET .../export/{jobId}) ----------------
    def get_export(self, job_id: str, *, principal) -> dict:
        """Progress/download for one job.

        Scoped to the requesting actor, and a mismatch is reported as ABSENT
        rather than forbidden so the response cannot confirm that another
        leader's job id exists. The kind check keeps this route to its own export
        even if this service later grows a second one.
        """
        job = self._repo.get_export_job(job_id)
        if (not job or job.get("actor") != principal.user_id
                or job.get("kind") != KIND_POINT_LEDGER):
            raise NotFoundError()

        # A UGL's job must also belong to the group they currently lead. Without
        # this, a leader reassigned to another group could still collect a CSV of
        # their previous group's ledger from a job started before the move.
        if principal.role == ROLE_UGL and job.get("groupId") != principal.led_group_id:
            raise NotFoundError()
        if principal.role not in (ROLE_CL, ROLE_UGL):
            raise ForbiddenError()

        out = self._public(job)
        if job.get("status") == STATUS_READY:
            # Minted per request and never stored — a URL signed with this
            # Lambda's session credentials dies with them and cannot be revoked.
            out.update(self._storage.download_url(job["fileKey"]))
        return out

    # ---------------- serialization ----------------
    @staticmethod
    def _public(job: dict) -> dict:
        # Stored as `totalRows`, exposed as `total` — see the note in start_export
        # about the `total` name colliding with GSI1's sort key on this table.
        total = job.get("totalRows")
        processed = int(job.get("processed") or 0)
        total_int = int(total) if total not in (None, "") else None

        # None => the UI shows an indeterminate bar rather than a fabricated
        # percentage. Clamped because rows can be appended while the export runs.
        percent: int | None = None
        if total_int:
            percent = min(100, int(processed * 100 / total_int))
        elif job.get("status") == STATUS_READY:
            percent = 100

        out = {
            "jobId": job.get("jobId"),
            "status": job.get("status"),
            "processed": processed,
            "total": total_int,
            "percent": percent,
            "fileName": job.get("fileName"),
        }
        if job.get("status") == STATUS_FAILED:
            out["error"] = job.get("error") or "The export failed."
        return out
