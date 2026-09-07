"""External adapters for Platform / Settings.

- EventPublisher: publishes `SettingsChanged` on the platform bus so consumers
  (Identity & Access, Notifications, Analytics, frontend polling) can react
  without polling every request.
- FileShareStorage: S3 presigned-URL broker for US-8.13 external file sharing
  (reworked 2026-08-04). The bucket is private (no public access). Presigned
  PUT URLs are minted FRESH at Copy-Link time, short-lived (~1h) — never at
  creation time and never stored: URLs signed with the Lambda role's temporary
  credentials die when the session token expires, so a stored URL is dead
  within hours regardless of ExpiresIn, and an issued URL cannot be revoked.
  Owner-side listing/download uses S3 ListObjectsV2 + fresh presigned GET
  URLs, generated on demand (never stored).

All external calls fail closed (RESILIENCY-10, SECURITY-15).
"""
from __future__ import annotations

import json
import os

from _conventions.envelope import build_event
from _conventions.errors import AppError
from _conventions.logger import get_logger, log

_logger = get_logger("settings")

# SigV4 presigned URLs cannot exceed 7 days.
_MAX_PRESIGN_SECONDS = 7 * 24 * 3600


class EventPublisher:
    def __init__(self, client=None):
        self._c = client
        self.bus = os.environ.get("EVENT_BUS_NAME", "")

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("events")
        return self._c

    def publish(self, event_type: str, data: dict, *, correlation_id: str | None = None) -> None:
        """Best-effort post-commit publish. Never raises to the caller."""
        envelope = build_event(event_type, "settings", data, correlation_id=correlation_id)
        if not self.bus:
            log(_logger, 20, "event (no bus configured)", type=event_type)
            return
        try:
            self.client.put_events(Entries=[{
                "EventBusName": self.bus,
                "Source": "settings",
                "DetailType": event_type,
                "Detail": json.dumps(envelope, default=str),
            }])
        except Exception:  # noqa: BLE001 — publish failure must not fail the primary write
            log(_logger, 40, "event publish failed (will not block write)", type=event_type)


class FileShareStorage:
    """Presigned-URL broker over the community files S3 bucket (US-8.13)."""

    def __init__(self, client=None, bucket: str | None = None):
        self._c = client
        self.bucket = bucket or os.environ.get("FILE_SHARE_BUCKET", "")

    @property
    def client(self):
        if self._c is None:
            import boto3
            from botocore.config import Config
            # signature_version MUST be explicit: the default presign is legacy
            # SigV2, which signs Content-Type (as empty) into the string-to-sign.
            # Any client that sends a Content-Type header — every browser, and
            # curl with --data-binary — gets 403 SignatureDoesNotMatch. The
            # curl-only Copy-Link flow survived because `curl -T` sends no
            # Content-Type; fixed alongside the same defect in Events
            # (2026-08-07, first browser presigned-PUT consumer).
            self._c = boto3.client("s3", config=Config(signature_version="s3v4"))
        return self._c

    def presign_put(self, key: str, *, expires_in: int) -> str:
        """Write-only, single-object presigned PUT (upload side). Minted fresh
        per Copy Link; keep expires_in short — the signature also dies with the
        Lambda role's session credentials, so long values are illusory."""
        if not self.bucket:
            raise AppError(code="NOT_CONFIGURED", message="File sharing storage is not configured.", status=503)
        expires_in = min(expires_in, _MAX_PRESIGN_SECONDS)
        try:
            return self.client.generate_presigned_url(
                "put_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in,
            )
        except Exception as err:  # noqa: BLE001 — must fail closed, no partial link
            log(_logger, 40, "presign_put failed", key=key)
            raise AppError(code="STORAGE_ERROR", message="Unable to create the upload link.", status=502) from err

    def presign_get(self, key: str, *, expires_in: int = 300) -> str:
        """Read-only presigned GET (owner download side)."""
        if not self.bucket:
            raise AppError(code="NOT_CONFIGURED", message="File sharing storage is not configured.", status=503)
        try:
            return self.client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in,
            )
        except Exception as err:  # noqa: BLE001
            log(_logger, 40, "presign_get failed", key=key)
            raise AppError(code="STORAGE_ERROR", message="Unable to create the download link.", status=502) from err

    def object_exists(self, key: str) -> bool:
        """Uniqueness pre-check for create (fileName unique per folder).
        No bucket configured (local/dev) -> False: record-level uniqueness
        still applies and minting fails 503 later anyway."""
        if not self.bucket:
            return False
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001 — 404/missing -> treat as free
            return False

    def delete_object(self, key: str) -> None:
        """Hard-delete a slot's file (Delete removes link + file). Fails closed:
        if S3 rejects the delete, the caller must NOT remove the link record,
        or the file would be orphaned with no owning slot."""
        if not self.bucket:
            raise AppError(code="NOT_CONFIGURED", message="File sharing storage is not configured.", status=503)
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as err:  # noqa: BLE001
            log(_logger, 40, "delete_object failed", key=key)
            raise AppError(code="STORAGE_ERROR", message="Unable to delete the uploaded file.", status=502) from err

    def list_top_level_folders(self) -> list[str]:
        """Existing top-level folders (prefixes) for the Create selector.
        Paginated: CommonPrefixes are subject to the same 1000-key page budget
        as Contents, so a bucket with many folders truncated silently."""
        if not self.bucket:
            return []
        prefixes: list[str] = []
        token = None
        try:
            while True:
                kwargs = {"Bucket": self.bucket, "Delimiter": "/"}
                if token:
                    kwargs["ContinuationToken"] = token
                resp = self.client.list_objects_v2(**kwargs)
                prefixes.extend(p["Prefix"].rstrip("/") for p in resp.get("CommonPrefixes", []))
                token = resp.get("NextContinuationToken")
                if not resp.get("IsTruncated") or not token:
                    break
        except Exception:  # noqa: BLE001 — degrade to registry-derived folders only
            log(_logger, 30, "list_top_level_folders failed (degrading to partial)")
        return prefixes

    def list_folder(self, prefix: str) -> list[dict]:
        """Owner-side file listing (name, size, uploaded date) for a folder prefix.
        Paginated — a single ListObjectsV2 returns at most 1000 keys, so a busy
        folder previously listed only its first page with no indication."""
        if not self.bucket:
            return []
        out: list[dict] = []
        token = None
        try:
            while True:
                kwargs = {"Bucket": self.bucket, "Prefix": f"{prefix}/"}
                if token:
                    kwargs["ContinuationToken"] = token
                resp = self.client.list_objects_v2(**kwargs)
                for obj in resp.get("Contents", []):
                    out.append({
                        "name": obj["Key"].split("/")[-1],
                        "sizeBytes": obj.get("Size", 0),
                        "uploadedAt": obj.get("LastModified").isoformat() if obj.get("LastModified") else None,
                    })
                token = resp.get("NextContinuationToken")
                if not resp.get("IsTruncated") or not token:
                    break
        except Exception:  # noqa: BLE001 — degrade to what we have rather than fail the page
            log(_logger, 30, "list_folder failed (degrading to partial)", prefix=prefix)
        return out
