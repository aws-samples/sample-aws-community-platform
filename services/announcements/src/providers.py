"""External adapters for Announcements.

- EventPublisher: publishes `AnnouncementPublished` on the platform bus (BR-10).
  Notifications (Unit 10) consumes it and sends email when emailOptIn is true —
  this service never calls SES directly. Best-effort post-commit; never raises.

This service holds no credentials (no Cognito/SES/Secrets Manager).
"""
from __future__ import annotations

import json
import os

from _conventions.envelope import build_event
from _conventions.logger import get_logger, log

_logger = get_logger("announcements")

SOURCE = "announcements"


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
        envelope = build_event(event_type, SOURCE, data, correlation_id=correlation_id)
        if not self.bus:
            log(_logger, 20, "event (no bus configured)", type=event_type)
            return
        try:
            self.client.put_events(Entries=[{
                "EventBusName": self.bus,
                "Source": SOURCE,
                "DetailType": event_type,
                "Detail": json.dumps(envelope, default=str),
            }])
        except Exception:  # noqa: BLE001 — publish failure must not fail the primary write
            log(_logger, 40, "event publish failed (will not block write)", type=event_type)
