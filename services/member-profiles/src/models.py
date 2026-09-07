"""Domain constants and serializers for Member Profiles & Directory.

Shapes conform to contracts/services/member-profiles/openapi.yaml (Member).
No shared library (FQ1). The profile-extension record (E1) is a denormalized,
event-sourced cache — identity/role/status/groups are mirrored read-only from
Identity & Access's events; only profile-specific fields are ever written
directly by this service (BR-2).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"

# Profile-editable fields (US-3.2) — never includes identity fields (BR-2).
EDITABLE_FIELDS = ("city", "country", "professionalRole", "timezone", "bio", "skills", "avatar", "awsProject")

# Free-text length caps (US-3.2). Bio is prose and has its OWN cap — it used to
# share a single 500 with city/country/professionalRole/avatar, which silently
# capped a professional bio at the length of a city name (a real 583-char bio was
# rejected with an unreadable "Validation failed."). Named here so the split is
# deliberate and cannot be accidentally re-merged.
SHORT_TEXT_MAX_LEN = 500  # city, country, professionalRole, avatar
BIO_MAX_LEN = 2000
SKILL_MAX_LEN = 60  # per skill/tag item (BR-17 — skills were previously unvalidated)

# Avatar upload (US-3.2). Content type is pinned at the S3 door and maps to the
# stored object extension; size is capped both here and by the presigned POST
# policy. SVG is intentionally excluded (script-injection risk).
AVATAR_CONTENT_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
AVATAR_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def epoch() -> int:
    """Unix seconds — used for DynamoDB TTL and expiry checks on the async
    CSV-export job records (the table has TTL enabled on `ttl`)."""
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def profile_public(item: dict, *, rollup: dict | None = None, tiers: list | None = None,
                   can_shoutout: bool = False,
                    activity_summary: dict | None = None) -> dict:
    """Map a stored profile-extension item to the OpenAPI `Member` schema,
    merging in the (optional) read-time fan-out results (plan Q2)."""
    out = {
        "id": item.get("id"),
        "firstName": item.get("firstName", ""),
        "lastName": item.get("lastName", ""),
        "email": item.get("email", ""),
        "role": item.get("role", "Member"),
        "status": item.get("status", STATUS_ACTIVE),
        "memberGroupIds": [g["groupId"] for g in item.get("groups", [])],
        "groups": item.get("groups", []),
        "city": item.get("city"),
        "country": item.get("country"),
        "professionalRole": item.get("professionalRole"),
        "awsProject": bool(item.get("awsProject", False)),
        "timezone": item.get("timeZone"),
        "bio": item.get("bio"),
        "skills": item.get("skills", []),
        "avatar": item.get("avatar"),
        # Whether the CALLER may send this member a shoutout (US-13.1/13.2/13.11),
        # computed by shoutout_service.can_send_shoutout. Defaults False so a call
        # site that does not pass it hides the button rather than offering an
        # action the server will refuse.
        "canShoutout": can_shoutout,
    }
    out["rollup"] = rollup
    out["tiers"] = tiers if tiers is not None else []
    if activity_summary is not None:
        out["activitySummary"] = activity_summary
    return out


def directory_row_public(item: dict, *, can_shoutout: bool = False) -> dict:
    """Directory listing row (US-3.4) — no points/rollup shown (BR-11)."""
    return {
        "id": item.get("id"),
        "firstName": item.get("firstName", ""),
        "lastName": item.get("lastName", ""),
        "email": item.get("email", ""),
        "role": item.get("role", "Member"),
        "status": item.get("status", STATUS_ACTIVE),
        "memberGroupIds": [g["groupId"] for g in item.get("groups", [])],
        "groups": item.get("groups", []),
        "city": item.get("city"),
        "country": item.get("country"),
        "awsProject": bool(item.get("awsProject", False)),
        "canShoutout": can_shoutout,
    }


def activity_summary_public(basic: dict) -> dict:
    """Basic 4-stat inline block (US-3.1/3.3, BR-12) — no points."""
    return {
        "eventsAttended": basic.get("eventsAttended", 0),
        "forumPosts": basic.get("forumPosts", 0),
        "contributions": basic.get("contributions", 0),
        "certifications": basic.get("certifications", 0),
    }


def listing(items: list, serializer, *, cursor: str | None = None) -> dict:
    out = {"items": [serializer(i) for i in items], "count": len(items)}
    if cursor:
        out["cursor"] = cursor
    return out
