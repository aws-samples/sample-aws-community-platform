"""Domain constants and serializers for Identity & Access.

Shapes conform to contracts/services/identity-access/openapi.yaml (User, Group,
GroupList, JoinRequest, History, Session). No shared library (FQ1).
"""
from __future__ import annotations

import time
import uuid

# Roles (BR-R1) — mutually exclusive, no inheritance.
ROLE_ADMIN = "Administrator"
ROLE_COMMUNITY_LEADER = "CommunityLeader"
ROLE_UGL = "UserGroupLeader"
ROLE_MEMBER = "Member"
ROLES = {ROLE_ADMIN, ROLE_COMMUNITY_LEADER, ROLE_UGL, ROLE_MEMBER}

# Account type. Every user, including the bootstrap Administrator (US-1.27), is a
# Cognito account — there is no separate local account type (see US-1.27/1.28 tombstone).
ACCOUNT_COGNITO = "cognito"

# Statuses (US-1.6/1.19).
STATUS_ACTIVE = "Active"
STATUS_INACTIVE = "Inactive"

# Group statuses (US-1.11).
GROUP_ACTIVE = "Active"
GROUP_SOFT_DELETED = "SoftDeleted"

# Membership event types (US-1.34).
MEVENT_JOINED = "joined"
MEVENT_APPROVED = "approved"
MEVENT_LEFT = "left"
MEVENT_REMOVED = "removed"
MEVENT_START = {MEVENT_JOINED, MEVENT_APPROVED}
MEVENT_END = {MEVENT_LEFT, MEVENT_REMOVED}

# Join request statuses (US-1.21).
JR_PENDING = "Pending"
JR_APPROVED = "Approved"
JR_REJECTED = "Rejected"
JR_WITHDRAWN = "Withdrawn"


# ---------------------------------------------------------------- quarters
# Membership-growth trends (US-7.3) are reported per calendar quarter. These
# helpers are local to this service by design (FQ1 — no shared library); the
# quarter KEY FORMAT ("YYYY-Qn") deliberately matches Contributions & Scoring so
# the two series can be plotted on one axis.

def quarter_key_for(year: int, month: int) -> str:
    return f"{year}-Q{(month - 1) // 3 + 1}"


def current_quarter() -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return quarter_key_for(now.year, now.month)


def trailing_quarters_asc(count: int) -> list[str]:
    """The `count` most recent quarters OLDEST FIRST — chart x-axis order."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    year, q = now.year, (now.month - 1) // 3 + 1
    out: list[str] = []
    for _ in range(max(1, count)):
        out.append(f"{year}-Q{q}")
        q -= 1
        if q == 0:
            q, year = 4, year - 1
    return list(reversed(out))


def quarter_end_iso(quarter: str) -> str:
    """Exclusive-ish upper bound for a quarter as an ISO string.

    Membership events are stored as ISO-8601 UTC strings, so a lexicographic
    comparison against "<year>-<month>-01T00:00:00" for the month AFTER the
    quarter is a correct "at or before the end of this quarter" test without
    parsing every timestamp.
    """
    year, _, qn = quarter.partition("-Q")
    q = int(qn)
    end_year, end_month = (int(year) + 1, 1) if q == 4 else (int(year), q * 3 + 1)
    return f"{end_year:04d}-{end_month:02d}-01T00:00:00"


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def epoch() -> int:
    return int(time.time())


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


# ---- Serializers (return only contract-visible fields) ----

def user_public(item: dict, group_ids: list | None = None) -> dict:
    """Map a stored user item to the OpenAPI `User` schema (profile fields +
    derived group membership are optional extensions used by Edit User, US-1.26)."""
    out = {
        "id": item.get("id"),
        "email": item.get("email"),
        "firstName": item.get("firstName"),
        "lastName": item.get("lastName"),
        "role": item.get("role"),
        "status": item.get("status", STATUS_ACTIVE),
        "city": item.get("city"),
        "country": item.get("country"),
        "professionalRole": item.get("professionalRole"),
        "awsProject": bool(item.get("awsProject", False)),
        "timeZone": item.get("timeZone"),
    }
    if item.get("ledGroupId"):
        out["ledGroupId"] = item["ledGroupId"]
    if group_ids is not None:
        out["groupIds"] = sorted(group_ids)
    return out


def member_search_key(user: dict) -> str:
    """Lowercase haystack denormalised onto the group-membership projection item
    so a keyword search can be pushed into DynamoDB as a `contains()` filter
    (2026-08-05, 13k+ member groups). Without it, matching a keyword means
    reading every member's profile — 13,000 GetItems for a query that matches
    nothing. Fields mirror the ones the member list searches on.

    firstName/lastName/email are Cognito-owned and read-only in the portal, so
    the only field here that can change after a join is professionalRole, which
    `UserService.edit_user` refreshes explicitly."""
    return " ".join([
        user.get("firstName") or "",
        user.get("lastName") or "",
        user.get("email") or "",
        user.get("professionalRole") or "",
    ]).lower().strip()


def group_public(item: dict, member_count: int | None = None,
                 leaders: list[dict] | None = None) -> dict:
    """Map a stored group item to the OpenAPI `Group` schema. `leaders` is the
    optional resolved display list ({id, firstName, lastName}) — leadership is
    not membership, so leaders may not appear in the members list (US-1.16).
    status/deletedAt surface soft-deleted rows to Community Leaders so the
    grace-period Undo Delete action can be offered (US-1.11)."""
    out = {
        "id": item.get("id"),
        "name": item.get("name"),
        "description": item.get("description", ""),
        "approvalRequired": bool(item.get("approvalRequired", False)),
        "leaderIds": item.get("leaderIds", []),
        "memberCount": member_count if member_count is not None else item.get("memberCount", 0),
        "createdAt": item.get("createdAt"),
        "status": item.get("status", GROUP_ACTIVE),
    }
    if item.get("deletedAt"):
        out["deletedAt"] = item["deletedAt"]
    if leaders is not None:
        out["leaders"] = leaders
    return out


def join_request_public(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "memberId": item.get("memberId"),
        "groupId": item.get("groupId"),
        "status": item.get("status"),
        "message": item.get("message", ""),
        "requestedAt": item.get("requestedAt"),
    }


def history_public(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "memberId": item.get("memberId"),
        "groupId": item.get("groupId"),
        "type": item.get("type"),
        "at": item.get("at"),
    }


def listing(items: list, serializer) -> dict:
    out = [serializer(i) for i in items]
    return {"items": out, "count": len(out)}
