"""Community membership/activity trend (US-7.1/7.3) — the CL growth chart."""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ForbiddenError  # noqa: E402
from consumers import NightlySweep  # noqa: E402
from models import current_quarter, trailing_quarters  # noqa: E402
from read_service import ReadService  # noqa: E402


def _earn(repo, member_id, group_id, quarter, points, *, name="M", ledger=None):
    repo.register_group(group_id)
    repo.apply_to_rollups({
        "ledgerId": ledger or f"led-{member_id}-{group_id}-{quarter}-{points}",
        "memberId": member_id, "memberName": name, "groupId": group_id,
        "quarter": quarter, "points": points, "pillar": 1,
    })


def test_trend_is_oldest_first_and_windowed(repo, framework, cl):
    out = ReadService(repo, framework).community_trend({"quarters": "4"}, principal=cl)

    assert [i["quarter"] for i in out["items"]] == trailing_quarters(4)[::-1]
    assert out["count"] == 4


def test_points_are_live_and_active_members_come_from_the_sweep(repo, framework, cl):
    q = current_quarter()
    _earn(repo, "m-a", "g-a", q, 80, name="A")
    _earn(repo, "m-b", "g-b", q, 55, name="B")
    reads = ReadService(repo, framework)

    # Before the sweep: points are live, active is unknown (NOT zero).
    before = {i["quarter"]: i for i in reads.community_trend({}, principal=cl)["items"]}
    assert before[q]["totalPoints"] == 135
    assert before[q]["activeMembers"] is None

    NightlySweep(repo, framework).run()

    after = {i["quarter"]: i for i in reads.community_trend({}, principal=cl)["items"]}
    assert after[q]["activeMembers"] == 2
    assert after[q]["totalPoints"] == 135


def test_a_member_in_two_groups_counts_once(repo, framework, cl):
    """Summing per-group counts would say 2; the community series must say 1."""
    q = current_quarter()
    _earn(repo, "m-both", "g-a", q, 80, name="Both", ledger="l1")
    _earn(repo, "m-both", "g-b", q, 55, name="Both", ledger="l2")
    NightlySweep(repo, framework).run()

    out = ReadService(repo, framework).community_trend({}, principal=cl)
    row = {i["quarter"]: i for i in out["items"]}[q]

    assert row["activeMembers"] == 1
    assert row["totalPoints"] == 135          # points still sum across groups


def test_unswept_quarters_are_null_while_swept_zeroes_stay_zero(repo, framework, cl):
    """A quarter the sweep has never covered is UNKNOWN (null) — reporting 0 would
    draw the line to the floor and read as "nobody was active".

    A quarter the sweep DID cover and genuinely found empty is a real 0, and must
    keep that value. The sweep window is current + previous, so in a 4-quarter
    series the two oldest are unknown and the previous quarter is a true zero.
    """
    q = current_quarter()
    _earn(repo, "m-a", "g-a", q, 10, name="A")
    NightlySweep(repo, framework).run()

    items = ReadService(repo, framework).community_trend(
        {"quarters": "4"}, principal=cl)["items"]        # oldest -> newest

    assert items[0]["activeMembers"] is None     # never swept
    assert items[1]["activeMembers"] is None     # never swept
    assert items[2]["activeMembers"] == 0        # swept, genuinely empty
    assert items[3]["activeMembers"] == 1        # current quarter
    assert ReadService(repo, framework).community_trend(
        {}, principal=cl)["computedAt"] is not None      # for the "as of" label


def test_only_a_community_leader_may_read_it(repo, framework, ugl, member):
    reads = ReadService(repo, framework)
    for principal in (ugl, member):
        with pytest.raises(ForbiddenError):
            reads.community_trend({}, principal=principal)


def test_window_is_bounded(repo, framework, cl):
    reads = ReadService(repo, framework)
    assert reads.community_trend({"quarters": "999"}, principal=cl)["count"] == 12
    assert reads.community_trend({"quarters": "0"}, principal=cl)["count"] == 1
