"""Domain-event envelope build/parse (BR-4/BR-5, contracts/platform/event-envelope.v1.json).

Reference convention — copied per service by the scaffold generator (FQ1).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .logger import get_correlation_id

ENVELOPE_VERSION_FIELD = "version"


def build_event(event_type: str, source: str, data: dict[str, Any], *, version: int = 1,
                correlation_id: str | None = None) -> dict:
    """Wrap a payload in the standard envelope for EventBridge publication."""
    return {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "version": version,
        "source": source,
        "time": datetime.now(timezone.utc).isoformat(),
        "correlationId": correlation_id or get_correlation_id(),
        "data": data,
    }


def parse_event(envelope: dict) -> dict:
    """Validate required envelope fields and return it. Raises ValueError if malformed."""
    for key in ("id", "type", "version", "source", "time", "data"):
        if key not in envelope:
            raise ValueError(f"event envelope missing required field: {key}")
    return envelope


def event_id(envelope: dict) -> str:
    """The idempotency key for consumers."""
    return envelope["id"]
