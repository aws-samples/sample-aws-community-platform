"""External adapters for Member Profiles & Directory.

- EventPublisher: publishes `MemberProfileUpserted` on the platform bus (BR-7).
- SettingsCache: cached read of `EnableSemanticSearch` (short TTL per warm
  container) so `browseDirectory` doesn't add a 5th fan-out call to its own
  latency budget on every request (NFR-MP-PERF).

This service holds no credentials (no Cognito/SES/Secrets Manager — smaller
footprint than Identity & Access, per tech-stack-decisions.md).
"""
from __future__ import annotations

import json
import os
import time

from _conventions.envelope import build_event
from _conventions.errors import AppError
from _conventions.logger import get_logger, log

_logger = get_logger("member-profiles")

_SETTINGS_CACHE_TTL_SECONDS = 60


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
        """Best-effort post-commit publish (BR-7). Never raises to the caller."""
        envelope = build_event(event_type, "member-profiles", data, correlation_id=correlation_id)
        if not self.bus:
            log(_logger, 20, "event (no bus configured)", type=event_type)
            return
        try:
            self.client.put_events(Entries=[{
                "EventBusName": self.bus,
                "Source": "member-profiles",
                "DetailType": event_type,
                "Detail": json.dumps(envelope, default=str),
            }])
        except Exception:  # noqa: BLE001 — publish failure must not fail the primary write
            log(_logger, 40, "event publish failed (will not block write)", type=event_type)


# The download link is deliberately short-lived. The signature also dies with the
# Lambda role's session credentials, so a longer value would be illusory anyway,
# and it is the only thing bounding reachability of an export in the meantime —
# cleanup is the export bucket's 1-day lifecycle rule (no delete-on-download,
# since a presigned GET is a direct browser-to-S3 transfer this service never
# observes completing).
EXPORT_GET_TTL_SECONDS = 300


class ExportStorage:
    """Writes generated directory CSVs to the shared export bucket and mints
    short-lived presigned GETs for download.

    Shares identity-access's UserExportBucket rather than adding another bucket,
    but under its OWN `members/` key prefix so the two services' IAM grants stay
    disjoint (this role cannot read or write identity's `users/` exports).
    URLs are minted per request and NEVER stored — a stored URL cannot be revoked
    and dies with the signing session anyway.
    """

    def __init__(self, client=None, bucket: str | None = None):
        self._c = client
        self.bucket = bucket if bucket is not None else os.environ.get("MEMBER_EXPORT_BUCKET", "")

    @property
    def client(self):
        if self._c is None:
            import boto3
            from botocore.config import Config
            # signature_version MUST be explicit. The default presign is legacy
            # and signs Content-Type into the string-to-sign, so any browser —
            # which always sends one — gets 403 SignatureDoesNotMatch. This bit
            # both Settings' file-share and Events' uploads before being fixed
            # there (2026-08-07); do not "simplify" this away.
            self._c = boto3.client("s3", config=Config(signature_version="s3v4"))
        return self._c

    def _require_bucket(self) -> None:
        if not self.bucket:
            raise AppError(code="NOT_CONFIGURED",
                           message="CSV export storage is not configured.", status=503)

    def put_csv(self, key: str, body: bytes) -> None:
        """Store the finished CSV. Fails loudly — the job must be marked failed
        rather than advertising a file the leader cannot download."""
        self._require_bucket()
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=body,
                ContentType="text/csv; charset=utf-8",
            )
        except Exception as err:  # noqa: BLE001 — surfaced as a failed job
            log(_logger, 40, "export upload failed", key=key)
            raise AppError(code="STORAGE_ERROR",
                           message="Unable to store the export file.", status=502) from err

    def download_url(self, key: str) -> dict:
        self._require_bucket()
        try:
            url = self.client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=EXPORT_GET_TTL_SECONDS,
            )
        except Exception as err:  # noqa: BLE001
            log(_logger, 40, "export presign failed", key=key)
            raise AppError(code="STORAGE_ERROR",
                           message="Unable to create the download link.", status=502) from err
        return {"url": url, "expiresInSeconds": EXPORT_GET_TTL_SECONDS}


class AvatarStorage:
    """Presigned-POST broker for profile-picture uploads (US-3.2).

    The browser uploads the picture directly to the SPA bucket under `avatars/`
    (the same bucket CloudFront serves the app from — profile pictures are then
    served at `/avatars/...`, exactly like certification badges use `badges/`).
    A presigned POST (not PUT) is used because only a POST policy can carry a
    `content-length-range` condition, so the size cap and content type are
    enforced by S3 itself at the storage door — never by trusting the client.
    The bucket stays private (OAI-only read); the presigned signature authorises
    the write. `avatarUrl` is the relative served path, which resolves against
    the portal origin and is stable, so denormalised copies never break."""

    _UPLOAD_TTL_SECONDS = 900  # 15 min to complete the browser upload

    def __init__(self, client=None, bucket: str | None = None):
        self._c = client
        self.bucket = bucket if bucket is not None else os.environ.get("SPA_BUCKET", "")

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("s3")
        return self._c

    def public_url(self, key: str) -> str:
        # Served by CloudFront from the SPA bucket at the same-origin path.
        return f"/{key}"

    def grant_upload(self, key: str, *, content_type: str, max_bytes: int) -> dict:
        from _conventions.errors import AppError
        if not self.bucket:
            raise AppError(code="STORAGE_UNAVAILABLE",
                           message="Avatar storage is not configured.", status=503)
        post = self.client.generate_presigned_post(
            Bucket=self.bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
                {"key": key},
            ],
            ExpiresIn=self._UPLOAD_TTL_SECONDS,
        )
        return {"url": post["url"], "fields": post["fields"], "key": key,
                "avatarUrl": self.public_url(key), "expiresInSeconds": self._UPLOAD_TTL_SECONDS}


class SettingsCache:
    """Cached `EnableSemanticSearch` flag. Falls back to the env-var default
    (from the CFN Parameter, same as the mock's ENABLE_SEMANTIC_SEARCH) until a
    live Settings-service read is wired (deferred — Phase 1 scope per NFR design)."""

    def __init__(self):
        self._value: bool | None = None
        self._fetched_at: float = 0.0

    def semantic_search_enabled(self) -> bool:
        now = time.monotonic()
        if self._value is None or (now - self._fetched_at) > _SETTINGS_CACHE_TTL_SECONDS:
            self._value = os.environ.get("ENABLE_SEMANTIC_SEARCH", "false").lower() == "true"
            self._fetched_at = now
        return self._value
