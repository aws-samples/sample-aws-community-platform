"""Domain constants and serializers for Events (Unit 4).

Shapes conform to contracts/services/events/openapi.yaml v2.0.0. No shared
library (FQ1) — this module is self-contained.

Two conventions worth noting because they are load-bearing elsewhere:

* `groupId is None` means COMMUNITY-WIDE (BR-S1). The display string
  "Community-wide" is never persisted; `scope_key()` is the single place that
  translates between the two, so scope handling cannot drift between the
  listing index, the Content Library index and authorization.
* Point values are NEVER stored on an event (BR-P1). `event_public` only emits
  `attendancePoints`/`deliveryPoints` when the caller passes values read from
  Contributions at request time; when that read fails the keys are simply
  absent and the UI hides the tag.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

COMMUNITY = "COMMUNITY"

EVENT_TYPES = (
    "Meetup", "Workshop", "Hackathon", "Webinar",
    "AMA / Fireside Chat", "Conference", "Presentation", "Social",
)
DELIVERY_MODES = ("Virtual", "In-Person", "Hybrid")
VIRTUAL_MODES = ("Virtual", "Hybrid")

STATUS_UPCOMING = "Upcoming"
STATUS_COMPLETED = "Completed"
STATUS_CANCELLED = "Cancelled"
STATUSES = (STATUS_UPCOMING, STATUS_COMPLETED, STATUS_CANCELLED)

# Statuses that count as "an event the group has" for reporting (US-7.2): every
# status except Cancelled. Defined once so the "Group Events" stat card and the
# events-by-type chart cannot drift apart — they disagreed exactly because one
# counted Completed only.
COUNTED_STATUSES = (STATUS_UPCOMING, STATUS_COMPLETED)

# Upper bound on the groups one cross-group statistics request may name. This
# service has no group registry, so the ids arrive in the query string; the cap
# stops a hand-built request turning a single call into an unbounded fan-out.
MAX_STAT_GROUPS = 100

# The ONLY legal transitions (BR-L1). Anything else is a 409.
ALLOWED_TRANSITIONS = {
    STATUS_UPCOMING: {STATUS_COMPLETED, STATUS_CANCELLED},
    STATUS_COMPLETED: set(),
    STATUS_CANCELLED: set(),
}

# An event runs from startsAt to endsAt. The span is capped so a mistyped end
# date cannot create an effectively open-ended event; a multi-day hackathon is
# well within it.
MAX_EVENT_SPAN_DAYS = 30


# ---------------------------------------------------------------- quarters
# Quarterly reporting windows (US-7.2/7.3). Local to this service by design
# (FQ1 — no shared library); the key FORMAT ("YYYY-Qn") deliberately matches
# Identity & Access and Contributions & Scoring so all three services' series
# can be plotted on one axis.

def trailing_quarters_asc(count: int) -> list[str]:
    """The `count` most recent quarters OLDEST FIRST — chart x-axis order."""
    now = datetime.now(timezone.utc)
    year, q = now.year, (now.month - 1) // 3 + 1
    out: list[str] = []
    for _ in range(max(1, count)):
        out.append(f"{year}-Q{q}")
        q -= 1
        if q == 0:
            q, year = 4, year - 1
    return list(reversed(out))


def current_quarter() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


def quarter_start_iso(quarter: str) -> str:
    """Inclusive lower bound for a quarter, as a comparable ISO string."""
    year, _, qn = quarter.partition("-Q")
    return f"{int(year):04d}-{(int(qn) - 1) * 3 + 1:02d}-01T00:00:00"


def quarter_end_iso(quarter: str) -> str:
    """Inclusive upper bound for a quarter.

    Event timestamps are ISO-8601 strings carrying an offset (e.g.
    "2026-09-20T10:00:00+00:00"), and the GSI sort key is that raw string. A
    lexicographic upper bound of "...-<last month>-31T23:59:59.999999" therefore
    sorts after every real instant in the quarter without needing to parse them.
    """
    year, _, qn = quarter.partition("-Q")
    last_month = int(qn) * 3
    return f"{int(year):04d}-{last_month:02d}-31T23:59:59.999999"


def quarter_of_iso(stamp: str) -> str:
    """Quarter key an event timestamp falls in. Reads the year and month off the
    ISO string directly — the sort key is a string, so no parsing is warranted."""
    year, month = int(stamp[0:4]), int(stamp[5:7])
    return f"{year}-Q{(month - 1) // 3 + 1}"


CONTENT_TYPES = ("Slides", "PDF", "Doc", "Recording", "Link")

# BR-M4 allow-list. Checked BEFORE a presigned URL is minted, so an unwanted
# type never gets an upload target at all.
ALLOWED_EXTENSIONS = {
    "pdf": "PDF", "ppt": "Slides", "pptx": "Slides", "doc": "Doc", "docx": "Doc",
    "xls": "Doc", "xlsx": "Doc", "png": "Doc", "jpg": "Doc", "jpeg": "Doc", "mp4": "Recording",
}
MAX_MATERIAL_BYTES = 500 * 1024 * 1024  # 500 MB — the number the mockup already shows

# Page size for the bulk group-cancel walk (GroupSoftDeleted consumer).
BULK_PAGE_SIZE = 104
MAX_ATTENDEES_PER_APPLY = 1000   # N4

SCAN_PENDING = "PendingScan"
SCAN_CLEAN = "Clean"
SCAN_QUARANTINED = "Quarantined"

UPLOAD_LINK_EXPIRY_DAYS = (7, 14, 30, 90)
UPLOAD_URL_SECONDS = 900         # 15 min — write side
DOWNLOAD_URL_SECONDS = 300       # 5 min — read side

# Only Members earn (BR-P3). Leaders may be designated but are not eligible.
POINT_ELIGIBLE_ROLES = ("Member",)

KIND_FILE = "file"
KIND_LINK = "link"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def scope_key(group_id: str | None) -> str:
    """The single translation between `groupId` and the index partition value.
    Kept in one place so the listing index, the Content Library index and the
    visibility check can never disagree about what community-wide means."""
    return group_id or COMMUNITY


def visible_scopes(principal) -> list[str]:
    """Scopes a caller may see (BR-S2), community-wide first so the first page
    of a listing is never dominated by one group.

    Administrators get an EMPTY list: they have no event permissions at all
    (BR-A1), and returning [] here means even a mis-wired caller sees nothing.
    """
    if principal.role == "Administrator":
        return []
    if principal.role == "CommunityLeader":
        return []  # sentinel: CL is unscoped; callers branch on role, not on this
    scopes = [COMMUNITY]
    if principal.led_group_id:
        scopes.append(principal.led_group_id)
    for gid in principal.member_group_ids:
        if gid not in scopes:
            scopes.append(gid)
    return scopes


def can_manage(event: dict, principal) -> bool:
    """BR-A4/A5 — the ownership-or-group rule, in exactly one place.

    The first branch keys on the IMMUTABLE `createdBy`, which is what makes a
    demoted creator keep edit/cancel rights on events they created (BR-A5).
    That is the single case where a Member-role principal passes a
    leader-only check, and it is deliberate — US-2.4 requires it.
    """
    if principal.role == "Administrator":
        return False
    if event.get("createdBy") and event["createdBy"] == principal.user_id:
        return True
    if principal.role == "CommunityLeader":
        return True
    if principal.role == "UserGroupLeader" and principal.led_group_id:
        return event.get("groupId") == principal.led_group_id
    return False


def can_view(event: dict, principal) -> bool:
    """BR-S2. Callers turn a False into 404, not 403 (BR-A8), so event
    existence is not disclosed across scope boundaries."""
    if principal.role == "Administrator":
        return False
    if principal.role == "CommunityLeader":
        return True
    group_id = event.get("groupId")
    if not group_id:
        return True  # community-wide
    if principal.led_group_id == group_id:
        return True
    return group_id in (principal.member_group_ids or [])


def content_type_for(file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return ALLOWED_EXTENSIONS.get(ext, "Doc")


def event_public(item: dict, *, principal=None, points: dict | None = None,
                 my_rsvp: dict | None = None) -> dict:
    """Map a stored event to the OpenAPI `Event` schema.

    Numbers are coerced with `int()` because DynamoDB returns Decimal, which
    would serialize as a string and then fail integer validation on the next
    read -> edit -> save round-trip (a regression already paid for in Settings).
    """
    out = {
        "id": item.get("id"),
        "title": item.get("title"),
        "description": item.get("description", ""),
        "type": item.get("type"),
        "deliveryMode": item.get("deliveryMode"),
        "groupId": item.get("groupId"),
        "status": item.get("status"),
        "startsAt": item.get("startsAt"),
        "endsAt": item.get("endsAt"),
        "location": item.get("location", ""),
        "createdBy": item.get("createdBy"),
        "announceOnCreate": bool(item.get("announceOnCreate", False)),
        "announceByEmail": bool(item.get("announceByEmail", False)),
        "teamsMeetingId": item.get("teamsMeetingId"),
        "rsvpYesCount": int(item.get("rsvpYesCount") or 0),
        "rsvpNoCount": int(item.get("rsvpNoCount") or 0),
        "attendedCount": int(item.get("attendedCount") or 0),
        "presenterCount": int(item.get("presenterCount") or 0),
        "organizerCount": int(item.get("organizerCount") or 0),
        "pointsAwarded": int(item["pointsAwarded"]) if item.get("pointsAwarded") is not None else None,
        "completedAt": item.get("completedAt"),
        "cancelledAt": item.get("cancelledAt"),
        "createdAt": item.get("createdAt"),
        "updatedAt": item.get("updatedAt"),
    }
    # Points are additive and OMITTED when unavailable (BR-P1) — absence is the
    # documented degrade signal, not a zero.
    if points:
        if points.get("attendance") is not None:
            out["attendancePoints"] = int(points["attendance"])
        if points.get("delivery") is not None:
            out["deliveryPoints"] = int(points["delivery"])
    if my_rsvp is not None:
        out["myRsvp"] = my_rsvp.get("response")
        out["myAttended"] = bool(my_rsvp.get("attended", False))
    if principal is not None:
        out["canManage"] = can_manage(item, principal)
    return out


def rsvp_public(item: dict) -> dict:
    return {
        "eventId": item.get("eventId"),
        "userId": item.get("userId"),
        "userEmail": item.get("userEmail", ""),
        "userName": item.get("userName", ""),
        "userRole": item.get("userRole", ""),
        "response": item.get("response"),
        "respondedAt": item.get("respondedAt"),
        "attended": bool(item.get("attended", False)),
        "attendedSource": item.get("attendedSource"),
        "pointsAwarded": int(item["pointsAwarded"]) if item.get("pointsAwarded") is not None else None,
    }


def material_public(item: dict, *, download_url: str | None = None) -> dict:
    out = {
        "id": item.get("id"),
        "eventId": item.get("eventId"),
        "kind": item.get("kind", KIND_FILE),
        "name": item.get("name"),
        "contentType": item.get("contentType", "Doc"),
        "link": item.get("link"),
        "sizeBytes": int(item["sizeBytes"]) if item.get("sizeBytes") is not None else None,
        "uploaded": bool(item.get("uploaded", False)),
        "scanState": item.get("scanState", SCAN_CLEAN),
        "postEvent": bool(item.get("postEvent", False)),
        "addedBy": item.get("addedBy"),
        "addedAt": item.get("addedAt"),
    }
    if download_url:
        out["downloadUrl"] = download_url
    for extra in ("eventTitle", "eventDescription", "groupId", "eventStartsAt"):
        if item.get(extra) is not None:
            out[extra] = item[extra]
    return out


def designation_public(item: dict) -> dict:
    external = bool(item.get("external", False))
    # An external presenter's userId is a synthetic slot id ("ext-1") that is an
    # internal detail — never surface it as a name. Fall back to a readable label
    # instead so a missing/blank name can never render as "ext-1" (US-2.18).
    # Portal designees fall back to their userId (the last-resort behavior the
    # denormalized displayName already uses).
    fallback = "External presenter" if external else item.get("userId")
    return {
        "userId": item.get("userId"),
        "displayName": item.get("displayName") or fallback,
        "external": external,
        "kind": item.get("kind"),
        "roleAtDesignation": item.get("roleAtDesignation"),
        "pointsEligible": bool(item.get("pointsEligible", False)),
        "ineligibleReason": item.get("ineligibleReason"),
    }


def upload_link_public(item: dict, *, now: str | None = None) -> dict:
    """`expired` is computed, never stored — storing it would need a writer to
    keep it true, and the only honest source is the current time."""
    now = now or now_iso()
    return {
        "id": item.get("id"),
        "eventId": item.get("eventId"),
        "folderPrefix": item.get("folderPrefix"),
        "expiresAt": item.get("expiresAt"),
        "maxSizeBytes": int(item["maxSizeBytes"]) if item.get("maxSizeBytes") is not None else None,
        "note": item.get("note", ""),
        "revoked": bool(item.get("revoked", False)),
        "expired": bool(item.get("expiresAt") and item["expiresAt"] <= now),
        "uploadCount": int(item.get("uploadCount") or 0),
        "createdBy": item.get("createdBy"),
        "createdByEmail": item.get("createdByEmail", ""),
        "createdAt": item.get("createdAt"),
    }


def uploaded_file_public(item: dict, *, download_url: str | None = None) -> dict:
    return {
        "id": item.get("id"),
        "uploadLinkId": item.get("uploadLinkId"),
        "name": item.get("name"),
        "sizeBytes": int(item.get("sizeBytes") or 0),
        "uploadedAt": item.get("uploadedAt"),
        "downloadUrl": download_url,
        "promotedMaterialId": item.get("promotedMaterialId"),
    }


def teams_batch_public(item: dict) -> dict:
    participants = item.get("participants") or []
    return {
        "id": item.get("id"),
        "eventId": item.get("eventId"),
        "fetchedAt": item.get("fetchedAt"),
        "appliedAt": item.get("appliedAt"),
        "matchedCount": sum(1 for p in participants if p.get("matchStatus") == "matched"),
        "unmatchedCount": sum(1 for p in participants if p.get("matchStatus") != "matched"),
        "participants": [
            {
                "displayName": p.get("displayName", ""),
                "email": p.get("email", ""),
                "joinTime": p.get("joinTime"),
                "leaveTime": p.get("leaveTime"),
                "durationMinutes": int(p.get("durationMinutes") or 0),
                "matchedUserId": p.get("matchedUserId"),
                "matchStatus": p.get("matchStatus", "unmatched"),
                "include": bool(p.get("include", False)),
            }
            for p in participants
        ],
    }


def listing(items: list, serializer, *, cursor: str | None = None, **extra) -> dict:
    out = [serializer(i) for i in items]
    result = {"items": out, "count": len(out)}
    if cursor:
        result["cursor"] = cursor
    result.update(extra)
    return result
