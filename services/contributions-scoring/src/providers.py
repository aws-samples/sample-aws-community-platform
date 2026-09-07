"""External adapters for Contributions & Scoring.

- EventPublisher — PointsAwarded / PointsAdjusted (post-commit, best-effort;
                   never raises to a committed write). No TierAchieved (DL19).
- Metrics        — CloudWatch datapoints backing the shipped alarms.

(Unit 7 consumes Events' per-earner award events DIRECTLY — no read-back client
is needed, which is why there is no EventsClient here.)
"""
from __future__ import annotations

import json
import os

from _conventions.envelope import build_event
from _conventions.errors import AppError
from _conventions.logger import get_logger, log

_logger = get_logger("contributions")

_PUT_EVENTS_BATCH = 10

# ----------------- CSV export storage (S3) -----------------

# Short-lived on purpose. The signature dies with this Lambda role's session
# credentials anyway, so a longer TTL would be illusory, and it is the only thing
# bounding reachability of a generated export — cleanup is the bucket's 1-day
# lifecycle rule (there is no delete-on-download: a presigned GET is a direct
# browser-to-S3 transfer this service never observes completing).
EXPORT_GET_TTL_SECONDS = 300


class ExportStorage:
    """Writes generated Point Ledger CSVs to the shared export bucket and mints
    short-lived presigned GETs.

    Same provider as identity-access', deliberately duplicated rather than
    shared: services in this repo are self-contained (FQ1) and reuse top-level
    module names, so there is no shared package to put it in. It writes under its
    own `contributions/` prefix so the IAM grants for each service's exports stay
    disjoint.
    """

    def __init__(self, client=None, bucket: str | None = None):
        self._c = client
        self.bucket = (bucket if bucket is not None
                       else os.environ.get("CONTRIBUTIONS_EXPORT_BUCKET", ""))

    @property
    def client(self):
        if self._c is None:
            import boto3
            from botocore.config import Config
            # signature_version MUST be explicit. The default presign is legacy
            # and signs Content-Type into the string-to-sign, so any browser —
            # which always sends one — gets 403 SignatureDoesNotMatch. This bit
            # Settings' file-share and Events' uploads before being fixed there;
            # do not "simplify" it away.
            self._c = boto3.client("s3", config=Config(signature_version="s3v4"))
        return self._c

    def _require_bucket(self) -> None:
        if not self.bucket:
            raise AppError(code="NOT_CONFIGURED",
                           message="CSV export storage is not configured.", status=503)

    def put_csv(self, key: str, body: bytes) -> None:
        """Store the finished CSV. Fails loudly — the job must be marked failed
        rather than reporting a file the leader cannot download."""
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


class EventPublisher:
    def __init__(self, client=None, bus: str | None = None, metrics=None):
        self._c = client
        self.bus = bus if bus is not None else os.environ.get("EVENT_BUS_NAME", "")
        self.published: list[dict] = []
        self._metrics = metrics

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("events")
        return self._c

    def publish(self, event_type: str, data: dict, *, correlation_id: str | None = None) -> None:
        envelope = build_event(event_type, "contributions-scoring", data,
                               correlation_id=correlation_id)
        self.published.append(envelope)
        if not self.bus:
            log(_logger, 20, "event (no bus configured)", type=event_type)
            return
        try:
            self.client.put_events(Entries=[{
                "EventBusName": self.bus, "Source": "contributions-scoring",
                "DetailType": event_type, "Detail": json.dumps(envelope, default=str)}])
        except Exception:  # noqa: BLE001 — publish failure must not fail a committed write
            log(_logger, 40, "event publish failed (write already committed)", type=event_type)
            if self._metrics:
                self._metrics.emit("EventPublishFailure", 1)


class Metrics:
    def __init__(self, client=None, namespace: str | None = None):
        self._c = client
        self.namespace = namespace or (
            f"CommunityPortal/contributions-{os.environ.get('STAGE', 'dev')}")
        self.emitted: list[tuple[str, float]] = []

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("cloudwatch")
        return self._c

    def emit(self, name: str, value: float, unit: str = "Count") -> None:
        self.emitted.append((name, value))
        try:
            self.client.put_metric_data(
                Namespace=self.namespace,
                MetricData=[{"MetricName": name, "Value": value, "Unit": unit}])
        except Exception:  # noqa: BLE001 — metrics never break the feature
            log(_logger, 30, "metric emit failed", metric=name)
