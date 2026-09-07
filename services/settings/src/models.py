"""Domain constants and serializers for Platform / Settings.

Shapes conform to contracts/services/settings/openapi.yaml (Settings,
PublicSettings, InternalSettings, Template, FileShareLink). No shared library (FQ1).

The singleton Settings record and email templates live in the settings-owned
single table (see repository.py). Sensible defaults mirror what US-8.3
mandates be present out of the box so a fresh deploy never returns an empty
settings screen (see DEFAULT_SETTINGS).
"""
from __future__ import annotations

import time
import uuid

DEFAULT_SETTINGS = {
    "communityName": "AWS Community Portal",
    "logoUrl": "",
    "defaultTimezone": "Asia/Kolkata",
    "enableSemanticSearch": False,  # not yet implemented — planned for a future release
    "selfRegistrationEnabled": True,  # US-11 addendum — master on/off switch, default ON
    "allowedEmailDomains": [],
    "otpIntervalDays": 30,
    "teamsEnabled": False,
    "teamsTenantId": "",
    "llmDuplicateDetectionEnabled": False,
    "bedrockModel": "anthropic.claude-3-5-sonnet",
    "whatsNewEnabled": True,
    "whatsNewFeedUrl": "",
    "senderName": "AWS Community Portal",
    "senderEmail": "",
    # Shoutout weekly quotas (US-13.3 — Admin-configurable)
    "shoutoutLimitMember": 3,
    "shoutoutLimitUgl": 6,
    "shoutoutLimitCl": 10,
}

DEFAULT_TEMPLATES = [
    {"id": "tpl-welcome", "name": "Welcome", "subject": "Welcome to the AWS Community Portal",
     "body": "Hi {{member_name}}, welcome aboard!"},
    {"id": "tpl-approved", "name": "Contribution Approved", "subject": "Your contribution was approved",
     "body": "Hi {{member_name}}, your submission was approved."},
    {"id": "tpl-tier", "name": "Tier Achieved", "subject": "You reached a new tier!",
     "body": "Congrats {{member_name}}, you reached {{tier_name}}!"},
]

# Settings fields exposed to unauthenticated callers (pre-login) via
# GET /public/settings. That route has NO authorizer and is internet-reachable,
# so everything here is world-readable: keep it to exactly what the login screen
# renders (AuthScreen.tsx destructures these three and nothing else).
# Trimmed 2026-08-28 — defaultTimezone, allowedEmailDomains and otpIntervalDays
# moved to INTERNAL_FIELDS; no pre-login caller read them.
PUBLIC_FIELDS = (
    "communityName", "logoUrl", "selfRegistrationEnabled",
)

# Settings fields served from GET /internal/settings, which is emitted only into
# the PRIVATE API (no internet path — see PRIVATE_ONLY_BASES in
# infra/tools/gen_api_edge.py). Consumed server-side by Identity & Access
# (allow-list, OTP interval) and Events (MS Teams capability gate).
INTERNAL_FIELDS = (
    "selfRegistrationEnabled", "allowedEmailDomains", "otpIntervalDays",
    "teamsEnabled", "defaultTimezone",
)


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def epoch() -> int:
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def settings_public(item: dict) -> dict:
    """Map the stored settings item to the OpenAPI `Settings` schema.

    Coerces each field back to its contract type: DynamoDB returns numbers as
    Decimal, which would otherwise serialize as strings and fail require_int
    on the next save round-trip (deploy regression: every save after the first
    returned 'Validation failed.')."""
    merged = {**DEFAULT_SETTINGS, **(item or {})}
    out = {}
    for k, default in DEFAULT_SETTINGS.items():
        v = merged[k]
        if isinstance(default, bool):
            out[k] = bool(v)
        elif isinstance(default, int):
            out[k] = int(v)
        elif isinstance(default, list):
            out[k] = list(v) if v is not None else []
        else:
            out[k] = v
    return out


def settings_public_subset(item: dict) -> dict:
    """Map the stored settings item to the OpenAPI `PublicSettings` schema."""
    full = settings_public(item)
    return {k: full[k] for k in PUBLIC_FIELDS}


def settings_internal_subset(item: dict) -> dict:
    """Map the stored settings item to the OpenAPI `InternalSettings` schema."""
    full = settings_public(item)
    return {k: full[k] for k in INTERNAL_FIELDS}


def template_public(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "subject": item.get("subject", ""),
        "body": item.get("body", ""),
    }


def file_share_link_public(item: dict) -> dict:
    """One file slot (US-8.13 rework 2026-08-04): folder + fileName -> key.
    No url/expiresAt — presigned URLs are minted fresh per Copy Link and
    never stored; slots live until deleted.

    `uploaded`/`sizeBytes`/`uploadedAt` are STORED (perf rework 2026-08-04),
    maintained by the S3 Object Created/Deleted consumer. They used to be
    computed at list time with one S3 ListObjectsV2 per distinct folder, which
    made page latency grow with the number of folders in the result set.

    `createdByEmail` is denormalized at create time from the caller's `email`
    claim so the Community Leader listing can show a human "Created By" without
    a per-row cross-service lookup. Absent on records created before the rework.
    """
    return {
        "id": item.get("id"),
        "folder": item.get("folder"),
        "fileName": item.get("fileName"),
        "key": item.get("key"),
        "note": item.get("note", ""),
        "createdBy": item.get("createdBy"),
        "createdByEmail": item.get("createdByEmail", ""),
        "createdAt": item.get("createdAt"),
        "revoked": bool(item.get("revoked", False)),
        "uploaded": bool(item.get("uploaded", False)),
        "sizeBytes": item.get("sizeBytes"),
        "uploadedAt": item.get("uploadedAt"),
    }


def listing(items: list, serializer, *, cursor: str | None = None) -> dict:
    out = [serializer(i) for i in items]
    result = {"items": out, "count": len(out)}
    if cursor:
        result["cursor"] = cursor
    return result
