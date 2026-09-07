"""Community-wide equal-distribution split (BR-S1/S2, DL12).

For a community-wide event (no groupId), points are divided across the member's
CURRENT groups at award time (DL12 — deliberate deviation from an event-date
snapshot). Equal division; the integer remainder is handed out ONE POINT AT A
TIME, earliest-group-join first, so the per-group parts sum EXACTLY to the
original value. If the member belongs to no group, nothing is awarded.
"""
from __future__ import annotations


def split_points(total: int, groups: list[dict]) -> list[tuple[str, int]]:
    """`groups`: [{groupId, joinedAt}] (the member's current memberships).
    Returns [(groupId, points)] summing exactly to `total`. Empty if no groups.

    Negative totals (possible only via adjustments, which are never community-
    wide) are not expected here; the arithmetic still balances if one occurs.
    """
    if not groups:
        return []
    # Deterministic order: earliest join first, tie-broken by groupId.
    ordered = sorted(groups, key=lambda g: (str(g.get("joinedAt", "")), str(g.get("groupId"))))
    n = len(ordered)
    base = total // n
    remainder = total - base * n  # exact; may be 0..n-1 (or negative-side for total<0)
    result = []
    for i, g in enumerate(ordered):
        pts = base + (1 if i < remainder else 0)
        result.append((g["groupId"], pts))
    return result
