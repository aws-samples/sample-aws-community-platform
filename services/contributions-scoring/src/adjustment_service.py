"""Manual point adjustment (US-6.15, DL20 — Option Y, BR-J*, BR-A5).

One mechanism: append an `adjustment` ledger entry to (member, group, quarter,
delta, reason). Path 1 = free delta to a leader-selected quarter. Path 2 =
reverse a specific entry (pre-filled delta = -entry.points, quarter = entry's
quarter, `reverses` link + single-use guard). Below-zero allowed (no floor).
"""
from __future__ import annotations

from _conventions.errors import ConflictError, ForbiddenError, NotFoundError
from _conventions.validation import require, require_int, require_str
from models import (
    ROLE_CL,
    ROLE_UGL,
    SOURCE_ADJUSTMENT,
    current_quarter,
    ledger_public,
    new_id,
    now_iso,
    trailing_quarters,
)


class AdjustmentService:
    def __init__(self, repo, publisher=None):
        self._repo = repo
        self._events = publisher

    def _authorize(self, principal, group_id: str) -> None:
        # BR-A5: CL any group; UGL only their led group.
        if principal.role == ROLE_CL:
            return
        if principal.role == ROLE_UGL and group_id and group_id == principal.led_group_id:
            return
        raise ForbiddenError()

    # ---- Path 1: free delta (quarter-selectable, DL20) ----------------------

    def adjust(self, body: dict, *, principal) -> dict:
        member_id = require_str(body.get("memberId", ""), "memberId", max_len=128)
        group_id = require_str(body.get("groupId", ""), "groupId", max_len=128)
        self._authorize(principal, group_id)
        delta = require_int(body.get("delta"), "delta", minimum=-100000, maximum=100000)
        require(delta != 0, "delta", "must be non-zero")
        reason = require_str(body.get("reason", ""), "reason", max_len=1000)
        quarter = body.get("quarter") or current_quarter()
        require(quarter in trailing_quarters(8), "quarter", "must be within the last 8 quarters")
        member_name = require_str(body.get("memberName", "") or " ", "memberName",
                                  max_len=200, min_len=1)
        # earnedDate = a representative date within the chosen quarter is not
        # needed — quarter is stored explicitly; earnedDate = now for audit order.
        entry = self._write(member_id, member_name, group_id, quarter, delta, reason,
                            principal, reverses=None)
        return ledger_public(entry)

    # ---- Path 2: reverse a specific entry (single-use, BR-J2) ---------------

    def reverse(self, body: dict, *, principal) -> dict:
        member_id = require_str(body.get("memberId", ""), "memberId", max_len=128)
        ledger_id = require_str(body.get("ledgerId", ""), "ledgerId", max_len=128)
        earned_date = require_str(body.get("earnedDate", ""), "earnedDate", max_len=32)
        target = self._repo.get_ledger_entry(member_id, earned_date, ledger_id)
        if not target:
            raise NotFoundError("Ledger entry not found.")
        self._authorize(principal, target.get("groupId"))
        # single-use guard (BR-J2)
        if self._repo.reversal_exists(ledger_id) or not self._repo.mark_reversed(ledger_id):
            raise ConflictError(message="This entry has already been reversed.")
        reason = require_str(body.get("reason", ""), "reason", max_len=1000)
        entry = self._write(
            member_id, target.get("memberName", ""), target["groupId"],
            target.get("quarter"), -int(target["points"]), reason, principal,
            reverses=ledger_id, earned_date=target.get("earnedDate"),
            pillar=int(target.get("pillar") or 0))
        return ledger_public(entry)

    # ---- list a member's ledger (reverse browser, US-6.15) ------------------

    def member_ledger(self, qs: dict, *, principal) -> dict:
        member_id = require_str(qs.get("memberId", ""), "memberId", max_len=128)
        group_id = qs.get("groupId")
        if principal.role == ROLE_UGL:
            group_id = principal.led_group_id  # UGL scoped to their group
        elif principal.role != ROLE_CL:
            raise ForbiddenError()
        rows = self._repo.list_member_ledger(member_id, group_id=group_id)
        items = [ledger_public(r) for r in rows]
        return {"items": items, "count": len(items)}

    # ---- shared write -------------------------------------------------------

    def _write(self, member_id, member_name, group_id, quarter, delta, reason,
               principal, *, reverses, earned_date=None, pillar=0) -> dict:
        entry = {
            "ledgerId": new_id("led"), "memberId": member_id, "memberName": member_name,
            "groupId": group_id, "activity": "Manual adjustment", "pillar": pillar or None,
            "points": delta, "source": SOURCE_ADJUSTMENT,
            "earnedDate": earned_date or now_iso()[:10], "quarter": quarter,
            "reason": reason, "adjustorId": principal.user_id, "reverses": reverses,
        }
        self._repo.append_ledger(entry)
        if self._events:
            self._events.publish("PointsAdjusted", {
                "memberId": member_id, "groupId": group_id, "quarter": quarter,
                "delta": delta, "reason": reason, "adjustorId": principal.user_id,
                "reverses": reverses})
        return entry
