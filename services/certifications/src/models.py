"""Domain model for Certifications (Unit 6).

Wire status vocabulary (D1): Pending | Approved | Rejected | Withdrawn |
Revoked | Expired. The SPA renders Approved as "Verified" (mockup wording) —
that mapping lives in the frontend, never here.

The claim IS the holding (D2): an earned certification/badge is a claim row in
Approved state. Badges, revoke, expiry, the catalog Held flag and the duplicate
rule all read the same item — nothing is copied at approval, so nothing drifts.

Serializers are the privacy mechanism (BR-P1): which one runs is decided by who
is asking, so a field can never leak by accident — it simply isn't in the shape.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------- status enums

STATUS_PENDING = "Pending"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"
STATUS_WITHDRAWN = "Withdrawn"
STATUS_REVOKED = "Revoked"
STATUS_EXPIRED = "Expired"

ALL_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
                STATUS_WITHDRAWN, STATUS_REVOKED, STATUS_EXPIRED}
# Statuses that hold the (certId, memberId) claim slot (BR-C2): while one of
# these exists, a new claim for the same pair is a duplicate.
LIVE_STATUSES = {STATUS_PENDING, STATUS_APPROVED}

SCAN_NONE = "None"
SCAN_PENDING = "PendingScan"
SCAN_CLEAN = "Clean"
SCAN_QUARANTINED = "Quarantined"

CATEGORY_AWS = "AWS Certification"
CATEGORY_COMMUNITY = "Community Badge"
CATEGORIES = {CATEGORY_AWS, CATEGORY_COMMUNITY}

ROLE_ADMIN = "Administrator"
ROLE_CL = "CommunityLeader"
ROLE_UGL = "UserGroupLeader"
ROLE_MEMBER = "Member"

SYSTEM_REJECT_REASON = "No longer a member of the credited group"

EVIDENCE_EXTENSIONS = {"pdf": "application/pdf", "png": "image/png",
                       "jpg": "image/jpeg", "jpeg": "image/jpeg"}
# No SVG (script risk, NFR-CT-SEC-2): badges render in every catalog card and
# profile, exactly where an XML payload would execute.
BADGE_EXTENSIONS = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB per file (N2, user decision)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ------------------------------------------------------------- expiry arithmetic

def add_months(day: date, months: int) -> date:
    """Calendar-month addition, clamped to the target month's last day
    (Jan 31 + 1 month = Feb 28/29). stdlib-only by design — no dateutil."""
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day-of-month to the target month's length.
    next_month_start = date(year + (month == 12), month % 12 + 1, 1)
    last_day = (next_month_start - timedelta(days=1)).day
    return date(year, month, min(day.day, last_day))


def parse_iso_date(value: str, field: str = "dateEarned") -> date:
    from _conventions.validation import require
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        require(False, field, "must be an ISO date (YYYY-MM-DD)")
        raise  # unreachable


def compute_expires_at(anchor: date, months: int) -> str:
    """The frozen expiresAt (D8): anchor (dateEarned, else approval date) plus
    the definition's expiry period AT APPROVAL TIME (BR-V6)."""
    return add_months(anchor, months).isoformat()


# ---------------------------------------------------------------- serializers

_DEFINITION_FIELDS = ("id", "name", "description", "category", "points",
                      "expiryPeriodMonths", "badgeImageUrl", "badgeImageStatus",
                      "active", "createdAt", "updatedAt")


def definition_public(item: dict) -> dict:
    return {k: item[k] for k in _DEFINITION_FIELDS if item.get(k) is not None}


_OWNER_CLAIM_FIELDS = ("id", "certId", "certName", "certCategory", "badgeImageUrl",
                       "memberId", "memberName", "creditedGroupId", "creditedGroupName",
                       "status", "evidenceUrl", "evidenceFileName", "hasEvidenceFile",
                       "scanStatus", "notes", "dateEarned", "submittedAt", "decidedAt",
                       "rejectReason", "pointsAwarded", "expiresAt", "revokedAt",
                       "revokeReason")

# The public projection is the OWNER shape minus everything private (BR-P1):
# evidence refs, notes and reasons never leave the owner/reviewer scopes.
_PUBLIC_CLAIM_FIELDS = ("id", "certId", "certName", "certCategory", "badgeImageUrl",
                        "memberId", "memberName", "creditedGroupId",
                        "creditedGroupName", "status", "dateEarned", "submittedAt",
                        "decidedAt", "expiresAt")

# What a reviewer needs per US-5.6: member, credited group, certification,
# evidence, submission date — plus the scan gate the UI must respect.
_QUEUE_CLAIM_FIELDS = ("id", "certId", "certName", "certCategory", "badgeImageUrl",
                       "memberId", "memberName", "creditedGroupId",
                       "creditedGroupName", "status", "evidenceUrl",
                       "evidenceFileName", "hasEvidenceFile", "scanStatus",
                       "notes", "dateEarned", "submittedAt")


def _project(item: dict, fields: tuple) -> dict:
    out = {k: item[k] for k in fields if item.get(k) is not None}
    # hasEvidenceFile is boolean-meaningful even when False.
    if "hasEvidenceFile" in fields:
        out["hasEvidenceFile"] = bool(item.get("evidenceFileKey"))
    return out


# ------------------------------------------------- ledger + rollup (Unit 6 enh.)

# The ledger shows claims that were ever granted; nothing else appears (BR-L2).
LEDGER_STATUSES = {STATUS_APPROVED, STATUS_EXPIRED, STATUS_REVOKED}

# Rollup scopes (BR-L10): community is maintained directly (= sum of groups) so
# community chart reads stay O(quarters), not O(groups x quarters).
SCOPE_COMMUNITY = "COMMUNITY"


def scope_group(group_id: str) -> str:
    return f"GROUP#{group_id}"


def quarter_of(iso_value: str | None) -> str | None:
    """Calendar quarter key 'YYYY-Qn' for an ISO date/datetime, or None."""
    if not iso_value:
        return None
    try:
        d = date.fromisoformat(str(iso_value)[:10])
    except (ValueError, TypeError):
        return None
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def earned_date_key(claim: dict) -> str:
    """Sort anchor for the granted index: dateEarned if present, else the date
    part of decidedAt (BR-L9 fallback)."""
    return str(claim.get("dateEarned") or claim.get("decidedAt") or "")[:10]


def earned_quarter(claim: dict) -> str | None:
    """Ledger/growth-New bucket: quarter of dateEarned, fallback decidedAt."""
    return quarter_of(claim.get("dateEarned") or claim.get("decidedAt"))


def quarter_end_date(quarter: str) -> str:
    """Inclusive last calendar day (YYYY-MM-DD) of a 'YYYY-Qn' quarter."""
    year_s, q_s = quarter.split("-Q")
    year, q = int(year_s), int(q_s)
    start_month = (q - 1) * 3 + 1
    # Day 0 of the month after the quarter's last month = that quarter's last day.
    end_month_next = start_month + 3
    end_year = year + (end_month_next > 12)
    end_month_next = (end_month_next - 1) % 12 + 1
    return (date(end_year, end_month_next, 1) - timedelta(days=1)).isoformat()


# Fields projected into a ledger row (BR-L7: NO approver field ever).
_LEDGER_ROW_FIELDS = ("id", "certId", "certName", "certCategory", "memberId",
                      "memberName", "creditedGroupId", "creditedGroupName",
                      "status", "dateEarned", "decidedAt", "expiresAt", "revokedAt")


def ledger_row(item: dict) -> dict:
    row = {k: item[k] for k in _LEDGER_ROW_FIELDS if item.get(k) is not None}
    # "Certification Date" = earned date, fallback approval date (BR-L9).
    row["certificationDate"] = item.get("dateEarned") or (
        str(item.get("decidedAt") or "")[:10] or None)
    return row


def owner_claim(item: dict) -> dict:
    return _project(item, _OWNER_CLAIM_FIELDS)


def public_claim(item: dict) -> dict:
    return _project(item, _PUBLIC_CLAIM_FIELDS)


def queue_claim(item: dict) -> dict:
    return _project(item, _QUEUE_CLAIM_FIELDS)
