"""Domain constants and serializers for Announcements (Unit 9).

Shapes conform to contracts/services/announcements/openapi.yaml (Announcement,
v2.0.0). No shared library (FQ1). An announcement is a single stored definition
(E1) — fan-out-on-read, no per-user materialization (BR-7). Display fields
(authorName/authorRoleLabel/source) are denormalized at create (BR-8).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from _conventions.errors import ValidationError

SCOPE_COMMUNITY = "community"
SCOPE_GROUPS = "groups"
SCOPES = {SCOPE_COMMUNITY, SCOPE_GROUPS}

STATUS_ACTIVE = "Active"
STATUS_EXPIRED = "Expired"

# Requirement deviation (2026-08-07): mandatory expiry, default 2 days, max 90 days.
DEFAULT_EXPIRY_DAYS = 2
MAX_EXPIRY_DAYS = 90

COMMUNITY_SOURCE_LABEL = "Community-wide"

ROLE_LABELS = {
    "CommunityLeader": "Community Leader",
    "UserGroupLeader": "User Group Leader",
    "Member": "Member",
    "Administrator": "Administrator",
}

TITLE_MAX = 200


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat()


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 date or datetime. Date-only (YYYY-MM-DD, as the mockup's
    <input type=date> submits) is treated as end-of-that-day UTC so an announcement
    set to expire "today" stays visible through the day."""
    try:
        if len(value) == 10 and value[4] == "-" and value[7] == "-":
            d = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return d + timedelta(hours=23, minutes=59, seconds=59)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValidationError(
            message="Validation failed.",
            details=[{"field": "expiresAt", "message": "must be an ISO-8601 date or datetime"}]) from None


def resolve_expiry(supplied: str | None, *, base: datetime | None = None) -> datetime:
    """Mandatory expiry (BR-5): absent -> base+2d; supplied is clamped to base+90d
    maximum and must be in the future."""
    base = base or now()
    default_at = base + timedelta(days=DEFAULT_EXPIRY_DAYS)
    max_at = base + timedelta(days=MAX_EXPIRY_DAYS)
    if not supplied:
        return default_at
    at = parse_iso(supplied)
    if at <= base:
        raise ValidationError(
            message="Validation failed.",
            details=[{"field": "expiresAt", "message": "must be in the future"}])
    return min(at, max_at)


def epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def is_expired(item: dict, *, at: datetime | None = None) -> bool:
    at = at or now()
    exp = item.get("expiresAt")
    if not exp:
        return False
    return parse_iso(exp) <= at


def status_of(item: dict, *, at: datetime | None = None) -> str:
    return STATUS_EXPIRED if is_expired(item, at=at) else STATUS_ACTIVE


def normalize_target(body: dict, principal, *, group_name_lookup=None) -> tuple[dict, str]:
    """Return (target, source_label). UGL is forced to their led group (BR-2);
    a UGL-supplied target is ignored. CL chooses community or >=1 groups.
    `group_name_lookup(group_id) -> name|None` denormalizes the source label."""
    if principal.role == "UserGroupLeader":
        if not principal.led_group_id:
            raise ValidationError(
                message="Validation failed.",
                details=[{"field": "target", "message": "you do not lead a group"}])
        group_ids = [principal.led_group_id]
        scope = SCOPE_GROUPS
    else:  # CommunityLeader (create already authorized)
        target = body.get("target") or {}
        scope = target.get("scope") or (SCOPE_GROUPS if target.get("groupIds") else SCOPE_COMMUNITY)
        if scope not in SCOPES:
            raise ValidationError(
                message="Validation failed.",
                details=[{"field": "target.scope", "message": f"must be one of {sorted(SCOPES)}"}])
        group_ids = target.get("groupIds") or []
        if scope == SCOPE_GROUPS:
            if not isinstance(group_ids, list) or not group_ids or \
                    not all(isinstance(g, str) and g for g in group_ids):
                raise ValidationError(
                    message="Validation failed.",
                    details=[{"field": "target.groupIds", "message": "must be a non-empty list when scope=groups"}])

    if scope == SCOPE_COMMUNITY:
        return {"scope": SCOPE_COMMUNITY, "groupIds": []}, COMMUNITY_SOURCE_LABEL

    names = []
    for gid in group_ids:
        name = group_name_lookup(gid) if group_name_lookup else None
        names.append(name or gid)
    return {"scope": SCOPE_GROUPS, "groupIds": group_ids}, ", ".join(names)


def announcement_public(item: dict, *, at: datetime | None = None) -> dict:
    """Map a stored item to the OpenAPI `Announcement` shape."""
    scope = item.get("targetScope", SCOPE_COMMUNITY)
    group_ids = item.get("targetGroupIds", []) or []
    source = item.get("source") or (COMMUNITY_SOURCE_LABEL if scope == SCOPE_COMMUNITY else ", ".join(group_ids))
    status = status_of(item, at=at)
    return {
        "id": item.get("id"),
        "title": item.get("title", ""),
        "body": item.get("body", ""),
        "target": {"scope": scope, "groupIds": group_ids},
        "audience": source,          # management-table label (mockup "Audience" column)
        "source": source,            # panel meta label
        "authorId": item.get("authorId"),
        "authorName": item.get("authorName", ""),
        "authorRoleLabel": item.get("authorRoleLabel", ""),
        "emailOptIn": bool(item.get("emailOptIn", False)),
        "emailSent": bool(item.get("emailSent", False)),
        "createdAt": item.get("createdAt"),
        "expiresAt": item.get("expiresAt"),
        "active": status == STATUS_ACTIVE,
        "status": status,
    }


def listing(items: list, *, at: datetime | None = None) -> dict:
    return {"items": [announcement_public(i, at=at) for i in items], "count": len(items)}
