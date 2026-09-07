"""Group membership growth per quarter (US-7.3) — the UGL dashboard trend line."""
from __future__ import annotations

import pathlib
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from models import (  # noqa: E402
    MEVENT_JOINED,
    MEVENT_LEFT,
    quarter_end_iso,
    trailing_quarters_asc,
)


def _event(ctx, member_id, group_id, ev_type, at):
    ctx.repo.append_membership_event({
        "id": f"me-{member_id}-{ev_type}-{at}", "memberId": member_id,
        "groupId": group_id, "type": ev_type, "at": at})


def _quarter_start(quarter: str) -> str:
    """First instant of a quarter — derived from the previous quarter's end."""
    year, _, qn = quarter.partition("-Q")
    q = int(qn)
    return f"{int(year):04d}-{(q - 1) * 3 + 1:02d}-05T00:00:00"


def test_growth_is_cumulative_across_quarters(ctx):
    """Joins accumulate: a member who joined in an early quarter is still counted
    in every later quarter (the user's Q1 100 -> Q4 150 shape)."""
    qs = trailing_quarters_asc(4)
    _event(ctx, "m-1", "g-a", MEVENT_JOINED, _quarter_start(qs[0]))
    _event(ctx, "m-2", "g-a", MEVENT_JOINED, _quarter_start(qs[1]))
    _event(ctx, "m-3", "g-a", MEVENT_JOINED, _quarter_start(qs[3]))
    _event(ctx, "m-4", "g-a", MEVENT_JOINED, _quarter_start(qs[3]))

    out = ctx.group_service.group_growth("g-a", quarters=4)

    assert [i["quarter"] for i in out["items"]] == qs          # oldest first
    assert [i["members"] for i in out["items"]] == [1, 2, 2, 4]


def test_growth_counts_members_who_later_left(ctx):
    """US-7.3/US-1.34: the curve is history — someone who has since LEFT is still
    counted in the quarters they belonged to, and drops out only afterwards."""
    qs = trailing_quarters_asc(4)
    _event(ctx, "m-1", "g-a", MEVENT_JOINED, _quarter_start(qs[0]))
    _event(ctx, "m-2", "g-a", MEVENT_JOINED, _quarter_start(qs[0]))
    _event(ctx, "m-2", "g-a", MEVENT_LEFT, _quarter_start(qs[2]))

    out = ctx.group_service.group_growth("g-a", quarters=4)

    assert [i["members"] for i in out["items"]] == [2, 2, 1, 1]


def test_growth_ignores_other_groups(ctx):
    qs = trailing_quarters_asc(4)
    _event(ctx, "m-1", "g-a", MEVENT_JOINED, _quarter_start(qs[0]))
    _event(ctx, "m-9", "g-b", MEVENT_JOINED, _quarter_start(qs[0]))

    out = ctx.group_service.group_growth("g-a", quarters=4)

    assert [i["members"] for i in out["items"]] == [1, 1, 1, 1]


def test_growth_of_an_empty_group_is_all_zeros(ctx):
    out = ctx.group_service.group_growth("g-empty", quarters=4)
    assert out["count"] == 4
    assert [i["members"] for i in out["items"]] == [0, 0, 0, 0]


def test_quarter_end_bound_rolls_over_the_year():
    assert quarter_end_iso("2026-Q1") == "2026-04-01T00:00:00"
    assert quarter_end_iso("2026-Q4") == "2027-01-01T00:00:00"


def test_trailing_quarters_are_oldest_first_and_contiguous():
    qs = trailing_quarters_asc(5)
    assert len(qs) == 5
    assert qs == sorted(qs, key=lambda q: (int(q[:4]), int(q[-1])))
