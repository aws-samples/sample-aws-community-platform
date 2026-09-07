"""Group trend + tier distribution (US-7.2/7.3) — the UGL dashboard widgets."""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ForbiddenError  # noqa: E402
from models import current_quarter, trailing_quarters  # noqa: E402
from read_service import ReadService  # noqa: E402


def _earn(repo, member_id, group_id, quarter, points, *, name="", ledger_id=None):
    repo.apply_to_rollups({
        "ledgerId": ledger_id or f"led-{member_id}-{quarter}-{points}",
        "memberId": member_id, "memberName": name, "groupId": group_id,
        "quarter": quarter, "points": points, "pillar": 1,
    })


def test_trend_counts_active_members_per_quarter(repo, framework, ugl):
    """activeMembers = members holding a rollup for that quarter (>=1 point)."""
    quarters = trailing_quarters(4)[::-1]        # oldest first
    older, current = quarters[0], quarters[-1]
    _earn(repo, "m-a", "g-serverless", older, 10, name="A")
    _earn(repo, "m-a", "g-serverless", current, 80, name="A")
    _earn(repo, "m-b", "g-serverless", current, 55, name="B")
    # Another group must not leak into this group's trend.
    _earn(repo, "m-c", "g-other", current, 999, name="C")

    reads = ReadService(repo, framework)
    out = reads.group_trend({"quarters": "4"}, principal=ugl)

    assert [i["quarter"] for i in out["items"]] == quarters      # oldest first
    by_q = {i["quarter"]: i for i in out["items"]}
    assert by_q[older]["activeMembers"] == 1
    assert by_q[older]["totalPoints"] == 10
    assert by_q[current]["activeMembers"] == 2
    assert by_q[current]["totalPoints"] == 135


def test_trend_tier_distribution_for_selected_quarter(repo, framework, ugl):
    q = current_quarter()
    _earn(repo, "m-gold", "g-serverless", q, 80, name="Gold Person")     # >=75 Gold
    _earn(repo, "m-silver", "g-serverless", q, 55, name="Silver Person")  # >=50 Silver
    _earn(repo, "m-rising", "g-serverless", q, 5, name="Rising Person")    # >=0 Rising

    reads = ReadService(repo, framework)
    out = reads.group_trend({}, principal=ugl)

    assert out["quarter"] == q
    assert out["tierCounts"] == {"Gold": 1, "Silver": 1, "Rising": 1}


def test_trend_is_forced_to_the_ugls_own_group(repo, framework, ugl):
    """A UGL cannot read another group's trend by passing groupId (BR-A2)."""
    q = current_quarter()
    _earn(repo, "m-x", "g-other", q, 90, name="X")
    reads = ReadService(repo, framework)

    out = reads.group_trend({"groupId": "g-other"}, principal=ugl)

    assert out["groupId"] == "g-serverless"       # their led group, not the request
    assert out["tierCounts"] == {}
    assert all(i["activeMembers"] == 0 for i in out["items"])


def test_trend_lets_a_cl_choose_a_group(repo, framework, cl):
    q = current_quarter()
    _earn(repo, "m-x", "g-other", q, 90, name="X")
    reads = ReadService(repo, framework)

    out = reads.group_trend({"groupId": "g-other"}, principal=cl)

    assert out["groupId"] == "g-other"
    assert out["tierCounts"] == {"Gold": 1}


def test_trend_denied_to_members(repo, framework, member):
    reads = ReadService(repo, framework)
    with pytest.raises(ForbiddenError):
        reads.group_trend({}, principal=member)


def test_trend_window_is_bounded(repo, framework, ugl):
    """A client cannot ask for an unbounded number of snapshots."""
    reads = ReadService(repo, framework)
    assert len(reads.group_trend({"quarters": "999"}, principal=ugl)["items"]) == 12
    assert len(reads.group_trend({"quarters": "0"}, principal=ugl)["items"]) == 1
