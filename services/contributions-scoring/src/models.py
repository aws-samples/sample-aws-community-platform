"""Domain model for Contributions & Scoring (Unit 7).

The point LEDGER is the system of record (DL1): every award/adjustment/reversal
is one immutable append-only entry. Balances, per-quarter totals, tiers, and
leaderboards are all DERIVED — nothing is stored pre-summed. Rollups (L1/L2/L3)
are a Stream-maintained cache, rebuildable by replaying the ledger.

Tiers are NEVER stored (DL1/US-6.12) — derived on read from a rollup total vs
the current thresholds. `quarter` is derived from `earnedDate` and is what
tiering counts against (BR-Q1); quarters are calendar quarters in UTC.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

# ---------------------------------------------------------------- roles

ROLE_ADMIN = "Administrator"
ROLE_CL = "CommunityLeader"
ROLE_UGL = "UserGroupLeader"
ROLE_MEMBER = "Member"

# ---------------------------------------------------------------- sources

SOURCE_AUTO = "auto"
SOURCE_EVIDENCE = "evidence"
SOURCE_ADJUSTMENT = "adjustment"
SOURCES = (SOURCE_AUTO, SOURCE_EVIDENCE, SOURCE_ADJUSTMENT)

# ---------------------------------------------------------------- activity categories
#
# The Point Ledger filter (US-7.9) needs a FINITE, stable set of activity types,
# but an auto entry stores only a display string (e.g. "Attend: Workshop",
# "Certification: AWS SA Pro") — and the forum/organize display names are
# CL-EDITABLE, so historical rows cannot be reliably re-classified by name.
# Categories are therefore derived from the (immutable) `source` plus the three
# stable, code-generated prefixes. Forum post / accepted reply / organize and any
# other auto award fall into `other-auto` — grouped deliberately because their
# stored name is editable and no category code was ever written on the row.
CATEGORY_LABELS = {
    "event-attendance": "Event Attendance",
    "event-delivery": "Event Delivery",
    "certification": "Certification",
    "other-auto": "Other (auto-awarded)",
    "evidence": "Evidence Submission",
    "adjustment": "Manual Adjustment",
}


def category_of(item: dict) -> str:
    """Derive a stable activity category from an immutable ledger row.

    Only `source` and the three code-generated activity prefixes are used —
    never the editable framework name — so a row's category never changes even
    if a CL later renames an activity.
    """
    source = item.get("source")
    if source == SOURCE_ADJUSTMENT:
        return "adjustment"
    if source == SOURCE_EVIDENCE:
        return "evidence"
    # source == auto (or anything else): classify by the stable prefixes.
    activity = str(item.get("activity") or "")
    if activity.startswith("Attend:"):
        return "event-attendance"
    if activity.startswith("Present:"):
        return "event-delivery"
    if activity.startswith("Certification:"):
        return "certification"
    return "other-auto"

# ---------------------------------------------------------------- pillars

PILLAR_UPSKILLING = 1
PILLAR_PEER_LEARNING = 2
PILLAR_ASSETS = 3
PILLAR_THOUGHT_LEADERSHIP = 4
PILLARS = (PILLAR_UPSKILLING, PILLAR_PEER_LEARNING, PILLAR_ASSETS, PILLAR_THOUGHT_LEADERSHIP)

# Human pillar names. These MUST match frontend/src/lib/pillars.ts — the Point
# Ledger CSV used to be built in the browser, which resolved the pillar number to
# a name there. The server-side export now writes that column, so the same
# strings have to live here or the same export would produce different files
# depending on which code path built it.
PILLAR_LABELS = {
    PILLAR_UPSKILLING: "1 · Upskilling & Deployment",
    PILLAR_PEER_LEARNING: "2 · Peer Learning & Knowledge Sharing",
    PILLAR_ASSETS: "3 · Assets, Demos & Open Source",
    PILLAR_THOUGHT_LEADERSHIP: "4 · Thought Leadership & External Visibility",
}


def pillar_label(pillar) -> str:  # noqa: ANN001
    """Mirrors pillars.ts::pillarLabel — falls back to the raw value, then an
    em-dash, so an unmapped pillar is visible rather than silently blank."""
    try:
        return PILLAR_LABELS[int(pillar)]
    except (TypeError, ValueError, KeyError):
        text = "" if pillar is None else str(pillar)
        return text or "—"

# ---------------------------------------------------------------- submission status

SUB_PENDING = "Pending"
SUB_APPROVED = "Approved"
SUB_REJECTED = "Rejected"
SUB_WITHDRAWN = "Withdrawn"

SYSTEM_REJECT_REASON = "No longer a member of the selected group"

# ---------------------------------------------------------------- event types (8)

EVENT_TYPES = ("Meetup", "Workshop", "Hackathon", "Webinar", "AMA",
               "Conference", "Presentation", "Social")

# System-defined auto-tracked activity ids (BR-F3): fixed, not UI-editable.
# (attendance/delivery live in the Event Points table, not as activity rows.)
SYSTEM_ACTIVITIES = {
    "organize-event", "forum-post", "forum-accepted-reply", "certification-approval",
}

TIERS_ORDER = ("Rising", "Bronze", "Silver", "Gold")  # ascending by threshold


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def epoch() -> int:
    """Unix seconds — used for DynamoDB TTL and the export-lock expiry check."""
    return int(datetime.now(timezone.utc).timestamp())


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------- quarter math

def quarter_of(earned_date: str) -> str:
    """Calendar quarter (UTC) an earnedDate falls in, e.g. '2026-Q2' (BR-Q1)."""
    d = date.fromisoformat(str(earned_date)[:10])
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def current_quarter() -> str:
    return quarter_of(today_iso())


def quarter_bounds(quarter: str) -> tuple[str, str]:
    """(startInclusive, endExclusive) ISO dates for a quarter key."""
    year, q = quarter.split("-Q")
    year, q = int(year), int(q)
    start_month = (q - 1) * 3 + 1
    start = date(year, start_month, 1)
    end = date(year + (q == 4), (start_month + 3 - 1) % 12 + 1, 1)
    return start.isoformat(), end.isoformat()


def trailing_quarters(count: int = 8) -> list[str]:
    """Current quarter + previous (count-1) (US-6.10 selector window)."""
    d = datetime.now(timezone.utc).date()
    year, q = d.year, (d.month - 1) // 3 + 1
    out = []
    for _ in range(count):
        out.append(f"{year}-Q{q}")
        q -= 1
        if q == 0:
            q, year = 4, year - 1
    return out


def days_remaining_in_quarter(quarter: str) -> int:
    _, end_excl = quarter_bounds(quarter)
    end = date.fromisoformat(end_excl)
    today = datetime.now(timezone.utc).date()
    return max(0, (end - today).days)


def derive_tier(points: int, thresholds: list[dict]) -> str | None:
    """Highest tier whose minPoints <= points (BR-T1). None if below all
    (e.g. a negative total from an adjustment). Thresholds: [{tier,minPoints}]."""
    best = None
    best_min = -1
    for t in thresholds:
        m = int(t.get("minPoints", 0))
        if points >= m and m >= best_min:
            best, best_min = t.get("tier"), m
    return best


# ---------------------------------------------------------------- serializers

def ledger_public(item: dict) -> dict:
    """A points-history / export ledger row (US-6.10 history, US-7.9 granular)."""
    return {
        "id": item.get("ledgerId"),
        "memberId": item.get("memberId"),
        "memberName": item.get("memberName"),
        "groupId": item.get("groupId"),
        "activity": item.get("activity"),
        "pillar": item.get("pillar"),
        "points": int(item.get("points", 0)),
        "source": item.get("source"),
        "earnedDate": item.get("earnedDate"),
        "quarter": item.get("quarter"),
        "reason": item.get("reason"),
        "reverses": item.get("reverses"),
    }


def framework_activity_public(item: dict) -> dict:
    return {
        "id": item.get("activityId"),
        "name": item.get("name"),
        "description": item.get("description"),
        "pillar": item.get("pillar"),
        "points": int(item.get("points", 0)),
        "evidenceRequired": bool(item.get("evidenceRequired", True)),
        "auto": not bool(item.get("evidenceRequired", True)),
        "active": bool(item.get("active", True)),
        "systemDefined": bool(item.get("systemDefined", False)),
    }


def event_points_public(item: dict) -> dict:
    return {
        "eventType": item.get("eventType"),
        "attendancePoints": int(item.get("attendancePoints", 0)),
        "deliveryPoints": int(item.get("deliveryPoints", 0)),
    }


def tier_threshold_public(item: dict) -> dict:
    return {
        "tier": item.get("tier"),
        "minPoints": int(item.get("minPoints", 0)),
        "recognitionLabel": item.get("recognitionLabel"),
    }


def submission_public(item: dict) -> dict:
    return {
        "id": item.get("submissionId"),
        "memberId": item.get("memberId"),
        "memberName": item.get("memberName"),
        "groupId": item.get("groupId"),
        "activity": item.get("activity"),
        "pillar": item.get("pillar"),
        "description": item.get("description"),
        "evidence": item.get("evidenceUrl"),
        "activityDate": item.get("activityDate"),
        "status": item.get("status"),
        "submittedAt": item.get("submittedAt"),
        "decidedAt": item.get("decidedAt"),
        "rejectionReason": item.get("rejectionReason"),
    }
