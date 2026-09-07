"""Async CSV export of the admin user list.

The synchronous export it replaces could not work at scale, for two independent
reasons: the whole listing had to render inside API Gateway's hard 29 s
integration timeout, and the JSON response crossed Lambda's 6 MB payload limit
somewhere north of ~20k users. Paging the client through the list would fix both
but gives the admin no progress and holds every row in the browser.

So the export is a job:

    POST /users/export        -> create the job record, invoke the worker
                                 asynchronously, return the job id immediately
    (worker)                  -> stream rows from OpenSearch to CSV in S3,
                                 updating `processed` as it goes
    GET  /users/export/{id}   -> polled by the SPA for progress; once ready it
                                 carries a freshly minted, short-lived
                                 presigned download URL

Deliberate product decisions (see the module docstring in export_worker.py for
the ones that shape the worker):

* ROWS COME FROM OPENSEARCH, not DynamoDB. Fast and it makes an exact count
  cheap, but the index is populated asynchronously off the DynamoDB stream, so
  an export is a snapshot of the INDEX and can lag the roster or omit users
  whose indexing failed. Accepted knowingly; there is no reconciliation check.
* NO delete-on-download. A presigned GET is a direct browser-to-S3 transfer that
  this service never observes completing, so "delete when the download finishes"
  is not implementable. Cleanup is the export bucket's 1-day lifecycle rule,
  with the 5-minute URL TTL bounding reachability in the meantime.
* NO resume across page loads. Navigating away loses the link; the job still
  finishes and its file expires unread. Re-exporting is cheap.
"""
from __future__ import annotations

import json
import os

from _conventions.errors import NotFoundError, ValidationError
from _conventions.logger import get_logger, log
from models import epoch, new_id, now_iso

_logger = get_logger("identity-access")

# How long a job record (and its download link's usefulness) survives. Aligned
# with the export bucket's 1-day expiry so status lookups never outlive the file
# they describe, nor vice versa.
EXPORT_JOB_TTL_SECONDS = 86_400

# An export is considered abandoned after this long, releasing the per-admin
# lock for a retry. Matches settings' stuck-run threshold (1800 s) and is
# comfortably beyond the worker's own 900 s Lambda timeout.
EXPORT_STALE_AFTER_SECONDS = 1_800

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_READY = "ready"
STATUS_FAILED = "failed"

# Filters the export honours. The CSV matches the filtered table the admin is
# looking at (deliberate change: the old export ignored filters entirely and
# always dumped the whole roster). `groupId` is absent on purpose — it resolves
# to a per-user id set that would become a `terms` clause of up to 13k values.
EXPORT_FILTER_KEYS = ("q", "role", "status")

# Which listing a job reproduces. Stored on the record so ONE worker serves both
# exports: the lifecycle (job record, per-actor lock, progress writes, presigned
# download) is identical, only the row source differs, and duplicating that
# lifecycle is how the two would drift apart.
KIND_USERS = "users"
KIND_GROUP_MEMBERS = "group-members"

# Filters the group-member export honours. Only the keyword: the roster is
# already scoped to one group, and `roleInGroup` has just two values, so the
# table offers nothing else to narrow by.
GROUP_EXPORT_FILTER_KEYS = ("q",)


class ExportService:
    def __init__(self, repo, storage, lambda_client=None, worker_function: str | None = None):
        self._repo = repo
        self._storage = storage
        self._lambda = lambda_client
        self._worker_function = worker_function or os.environ.get(
            "EXPORT_WORKER_FUNCTION", f"identity-access-user-export-{os.environ.get('STAGE', 'dev')}")

    @staticmethod
    def _stamp() -> str:
        """Timestamp for the download name, so a folder of exports stays sortable
        and a second export never silently overwrites the first in the browser."""
        return now_iso()[:19].replace(":", "").replace("-", "")

    # ---------------- start (POST /users/export) ----------------
    def start_export(self, body: dict, *, actor: str) -> dict:
        filters = {k: (body.get(k) or "").strip() for k in EXPORT_FILTER_KEYS}
        filters = {k: v for k, v in filters.items() if v}
        job_id = new_id("exp")
        return self._start(
            actor=actor, job_id=job_id, kind=KIND_USERS, filters=filters,
            file_name=f"members-{self._stamp()}.csv",
            file_key=f"users/{job_id}.csv",
        )

    # ---------------- start (POST /groups/{id}/members/export) ----------------
    def start_group_member_export(self, group_id: str, body: dict, *, actor: str) -> dict:
        """One group's roster, for the leader's My Group screen.

        Same job pattern as the admin export, but the rows come from the
        AUTHORITATIVE DynamoDB roster rather than OpenSearch. That is not
        incidental: `joinedAt` lives on the membership projection and is not in
        the search index at all, so an index-sourced export could not reproduce
        this CSV's columns. It also preserves the choice the previous
        cursor-following export documented — a roster is read to act on, so it
        should not silently omit a member whose indexing is lagging.
        """
        filters = {k: (body.get(k) or "").strip() for k in GROUP_EXPORT_FILTER_KEYS}
        filters = {k: v for k, v in filters.items() if v}
        job_id = new_id("gexp")
        return self._start(
            actor=actor, job_id=job_id, kind=KIND_GROUP_MEMBERS, filters=filters,
            file_name=f"group-members-{self._stamp()}.csv",
            # Its own prefix, so the IAM grant for this export cannot read the
            # admin roster exports under users/.
            file_key=f"groups/{job_id}.csv",
            extra={"groupId": group_id},
        )

    def _start(self, *, actor: str, job_id: str, kind: str, filters: dict,
               file_name: str, file_key: str, extra: dict | None = None) -> dict:
        """Shared job creation: lock, write the record, dispatch the worker.

        One in-flight export per ACTOR, across both kinds — the lock is keyed on
        the actor alone. A leader who starts a roster export and then an admin
        export would be refused the second, which is the intended reading of "one
        export at a time per person" and keeps the release path unambiguous.
        """
        now = epoch()

        # The SPA also disables the button, but that is presentation only — a
        # refresh re-enables it, and this is the actual control.
        if not self._repo.acquire_export_lock(actor, job_id,
                                              ttl_seconds=EXPORT_STALE_AFTER_SECONDS):
            raise ValidationError(
                message="An export is already running for your account. "
                        "Wait for it to finish before starting another.")

        job = {
            "jobId": job_id,
            "actor": actor,
            "kind": kind,
            "status": STATUS_QUEUED,
            "processed": 0,
            "total": None,
            "filters": filters,
            "fileName": file_name,
            "fileKey": file_key,
            "error": None,
            "startedAt": now_iso(),
            "completedAt": None,
            "expiresAt": now + EXPORT_JOB_TTL_SECONDS,
            "ttl": now + EXPORT_JOB_TTL_SECONDS,
            **(extra or {}),
        }
        self._repo.put_export_job(job)

        # Invoke AFTER the record exists, so the SPA's first poll can never find
        # a job id the worker is already writing to but that does not yet exist.
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
            InvocationType="Event",   # async — returns 202, does not wait
            Payload=json.dumps({"source": "user-csv-export", "jobId": job_id}).encode(),
        )

    # ---------------- status (GET /users/export/{id}) ----------------
    def get_export(self, job_id: str, *, actor: str) -> dict:
        job = self._repo.get_export_job(job_id)
        # Scoped to the requesting admin, and a mismatch is reported as absent
        # rather than forbidden so the response cannot confirm that another
        # admin's job id exists.
        #
        # The kind check keeps each route to its own export: a roster job read
        # here would hand back a group CSV from the admin URL. `kind` defaults to
        # users so job records written before the group export existed still
        # resolve.
        if (not job or job.get("actor") != actor
                or job.get("kind", KIND_USERS) != KIND_USERS):
            raise NotFoundError()

        out = self._public(job)
        if job.get("status") == STATUS_READY:
            # Minted per request and never stored — a URL signed with this
            # Lambda's session credentials dies with them and cannot be revoked.
            out.update(self._storage.download_url(job["fileKey"]))
        return out

    # ---------------- status (GET /groups/{id}/members/export/{jobId}) ----------------
    def get_group_member_export(self, group_id: str, job_id: str, *, actor: str) -> dict:
        """Progress/download for a roster export.

        Checks the job belongs to this ACTOR *and* to the group in the path. The
        group check is not redundant: without it a leader could read any of their
        own jobs through any group's URL, so the route would stop meaning what it
        says and an audit of "who exported group X" could not rely on it. A
        mismatch is reported as absent rather than forbidden, matching the admin
        export — the response must not confirm that a job id exists.
        """
        job = self._repo.get_export_job(job_id)
        if (not job or job.get("actor") != actor
                or job.get("kind") != KIND_GROUP_MEMBERS
                or job.get("groupId") != group_id):
            raise NotFoundError()

        out = self._public(job)
        if job.get("status") == STATUS_READY:
            out.update(self._storage.download_url(job["fileKey"]))
        return out

    # ---------------- serialization ----------------
    @staticmethod
    def _public(job: dict) -> dict:
        total = job.get("total")
        processed = int(job.get("processed") or 0)
        total_int = int(total) if total not in (None, "") else None

        # None => the UI shows an indeterminate bar rather than a fabricated
        # percentage. Clamped because the count is taken once at the start and
        # users can be created while the export runs.
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
