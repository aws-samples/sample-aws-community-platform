"""Certification Ledger + dashboard chart aggregations (Unit 6 enhancement).

Read-only. Three surfaces, all CL-global / UGL-led-group / Members+Admin denied
(BR-L1; the boundary Admin 403 is applied in authz.py before we get here):

  * list_ledger  — member-wise granted-claim list for one earned quarter, filtered
                   and cursor-paginated over GSI4 (no Scan, BR-L5).
  * growth       — last-N-quarters series: New (by earned quarter) + Total valid
                   holdings as-of-quarter-end, from the rollup counters (BR-L10).
  * snapshot     — per-certification held-as-of-quarter counts, from the rollup.

Neither chart reads claim rows — they read the maintained counters, so cost is
O(quarters)/O(certs), independent of the 30k-200k claim volume.
"""
from __future__ import annotations

from datetime import datetime, timezone

from _conventions.errors import ForbiddenError, ValidationError
from models import (
    LEDGER_STATUSES,
    ROLE_CL,
    ROLE_UGL,
    SCOPE_COMMUNITY,
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_REVOKED,
    ledger_row,
    scope_group,
)

_DEFAULT_PAGE = 25
_MAX_PAGE = 200

# Ledger status filter labels → wire statuses. "Active" = a currently-held badge.
_STATUS_LABELS = {"Active": STATUS_APPROVED, "Expired": STATUS_EXPIRED,
                  "Revoked": STATUS_REVOKED}


def _current_quarter() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


def _trailing_quarters(n: int) -> list[str]:
    """The n most recent quarters, OLDEST first (chart axis order)."""
    now = datetime.now(timezone.utc)
    year, q = now.year, (now.month - 1) // 3 + 1
    out: list[str] = []
    for _ in range(max(1, n)):
        out.append(f"{year}-Q{q}")
        q -= 1
        if q == 0:
            q = 4
            year -= 1
    return list(reversed(out))


def _parse_limit(raw) -> int:
    if raw is None or raw == "":
        return _DEFAULT_PAGE
    try:
        limit = int(raw)
    except (ValueError, TypeError):
        raise ValidationError("limit must be an integer.") from None
    if not 1 <= limit <= _MAX_PAGE:
        raise ValidationError(f"limit must be between 1 and {_MAX_PAGE}.")
    return limit


def _valid_quarter(raw: str | None) -> str:
    if not raw:
        return _current_quarter()
    q = str(raw)
    year_s, sep, qn = q.partition("-Q")
    if not (sep and year_s.isdigit() and len(year_s) == 4 and qn in {"1", "2", "3", "4"}):
        raise ValidationError("quarter must be 'YYYY-Qn'.")
    return q


class LedgerService:
    def __init__(self, repo, identity=None):
        self._repo = repo
        self._identity = identity

    # --------------------------------------------------------------- scoping

    def _led_group(self, principal, bearer_token: str | None) -> str:
        led = getattr(principal, "led_group_id", None)
        if not led and self._identity is not None:
            led = self._identity.led_group_id(principal.user_id, bearer_token=bearer_token)
        if not led:
            raise ForbiddenError(message="Your led group could not be determined.")
        return led

    def _resolve_scope(self, principal, group_id: str | None, bearer_token: str | None):
        """Return (group_filter, scope_key). CL: optional group (None=community).
        UGL: forced to led group (any client groupId ignored — BR-L1)."""
        if principal.role == ROLE_UGL:
            led = self._led_group(principal, bearer_token)
            return led, scope_group(led)
        if principal.role == ROLE_CL:
            if group_id:
                return group_id, scope_group(group_id)
            return None, SCOPE_COMMUNITY
        # Members/Admin never reach here (authz gate), fail closed.
        raise ForbiddenError()

    # ---------------------------------------------------------------- ledger

    def list_ledger(self, filters: dict, *, principal, bearer_token: str | None) -> dict:
        quarter = _valid_quarter(filters.get("quarter"))
        group_filter, _scope = self._resolve_scope(
            principal, filters.get("groupId"), bearer_token)
        cert_filter = filters.get("certId") or None
        member_filter = filters.get("memberId") or None
        # Free-text member name (2026-08-27). The screen used to require picking a
        # member from a directory typeahead, which meant you could not filter by a
        # partial or half-remembered name — and typing without selecting silently
        # filtered nothing. Matched case-insensitively as a substring against the
        # name denormalised on the claim, so it costs nothing extra: memberName is
        # already projected into every ledger row (GSI4 projects ALL).
        #
        # Name only, not email: email is deliberately not denormalised onto claims
        # (see toExportRow in the frontend), and resolving it per row would be the
        # cross-service lookup this ledger exists to avoid.
        name_filter = (filters.get("memberName") or "").strip().lower() or None

        statuses = self._parse_statuses(filters.get("status"))

        def predicate(row: dict) -> bool:
            if row.get("status") not in statuses:
                return False
            if group_filter and row.get("creditedGroupId") != group_filter:
                return False
            if cert_filter and row.get("certId") != cert_filter:
                return False
            if member_filter and row.get("memberId") != member_filter:
                return False
            if name_filter and name_filter not in str(row.get("memberName") or "").lower():
                return False
            return True

        limit = _parse_limit(filters.get("limit"))
        rows, next_cursor = self._repo.query_ledger_page(
            quarter=quarter, limit=limit, cursor=filters.get("cursor") or None,
            predicate=predicate)
        out = {"items": [ledger_row(r) for r in rows], "count": len(rows),
               "quarter": quarter}
        if next_cursor:
            out["cursor"] = next_cursor
        return out

    @staticmethod
    def _parse_statuses(raw) -> set[str]:
        """`status` = csv/repeat of Active|Expired|Revoked → wire statuses.
        Default = all three granted statuses."""
        if not raw:
            return set(LEDGER_STATUSES)
        labels = raw if isinstance(raw, list) else str(raw).split(",")
        out: set[str] = set()
        for label in labels:
            key = label.strip()
            if key not in _STATUS_LABELS:
                raise ValidationError("status must be Active, Expired or Revoked.")
            out.add(_STATUS_LABELS[key])
        return out or set(LEDGER_STATUSES)

    # ---------------------------------------------------------------- growth

    def growth(self, params: dict, *, principal, bearer_token: str | None) -> dict:
        try:
            quarters = int(params.get("quarters") or 4)
        except (ValueError, TypeError):
            raise ValidationError("quarters must be an integer.") from None
        quarters = max(1, min(quarters, 12))
        _group_filter, scope = self._resolve_scope(
            principal, params.get("groupId"), bearer_token)

        counters = self._repo.read_scope_quarter_counters(scope)
        by_q = {c["quarter"]: c for c in counters}
        all_q = sorted(by_q)

        def total_as_of(target: str) -> int:
            total = 0
            for q in all_q:
                if q <= target:
                    total += by_q[q]["activatedCount"] - by_q[q]["deactivatedCount"]
                else:
                    break
            return total

        items = [{"quarter": q,
                  "new": by_q.get(q, {}).get("newCount", 0),
                  "total": total_as_of(q)}
                 for q in _trailing_quarters(quarters)]
        return {"items": items, "scope": scope}

    # -------------------------------------------------------------- snapshot

    def snapshot(self, params: dict, *, principal, bearer_token: str | None) -> dict:
        quarter = _valid_quarter(params.get("quarter"))
        _group_filter, scope = self._resolve_scope(
            principal, params.get("groupId"), bearer_token)

        counters = self._repo.read_scope_cert_counters(scope, upto_quarter=quarter)
        held: dict[str, dict] = {}
        for c in counters:
            slot = held.setdefault(c["certId"], {"certId": c["certId"],
                                                 "certName": None, "count": 0})
            slot["count"] += c["activatedCount"] - c["deactivatedCount"]
            if c.get("certName") and not slot["certName"]:
                slot["certName"] = c["certName"]
        items = [v for v in held.values() if v["count"] > 0]
        items.sort(key=lambda v: v["count"], reverse=True)
        return {"items": items, "quarter": quarter, "scope": scope}
