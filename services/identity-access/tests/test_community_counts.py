"""Nightly community roster snapshot (US-7.1) — the CL dashboard's member figures.

The invariant under test throughout: the Total Members CARD and the membership
growth CHART LINE are the same number for the current quarter. They are read from
one snapshot precisely so they can never disagree.
"""
from __future__ import annotations

import pathlib
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_COMMUNITY_LEADER,
    ROLE_MEMBER,
    ROLE_UGL,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    current_quarter,
    trailing_quarters_asc,
)


def _user(ctx, uid, *, role=ROLE_MEMBER, status=STATUS_ACTIVE, created="2026-07-01T00:00:00Z"):
    ctx.repo.put_user({"id": uid, "email": f"{uid}@company.com", "role": role,
                       "status": status, "firstName": "Dev", "lastName": uid,
                       "createdAt": created})


def _quarter_start(quarter: str) -> str:
    year, _, qn = quarter.partition("-Q")
    return f"{int(year):04d}-{(int(qn) - 1) * 3 + 1:02d}-05T00:00:00Z"


def test_counts_members_only_and_excludes_deactivated(ctx):
    """Leaders and Administrators never earn points, so counting them would
    depress "% active" against a denominator that can never be active."""
    _user(ctx, "m-1")
    _user(ctx, "m-2")
    _user(ctx, "m-gone", status=STATUS_INACTIVE)
    _user(ctx, "ugl-1", role=ROLE_UGL)
    _user(ctx, "cl-1", role=ROLE_COMMUNITY_LEADER)
    _user(ctx, "admin-1", role=ROLE_ADMIN)

    snap = ctx.user_service.recompute_community_counts()

    assert snap["totalMembers"] == 2


def test_new_this_quarter_is_a_subset_of_the_total(ctx):
    """`newByQuarter` counts ACCOUNT CREATION on the same members-only basis, so
    "new" can never exceed "total"."""
    qs = trailing_quarters_asc(4)
    _user(ctx, "m-old", created=_quarter_start(qs[0]))
    _user(ctx, "m-new-1", created=_quarter_start(qs[3]))
    _user(ctx, "m-new-2", created=_quarter_start(qs[3]))
    # Excluded from both figures, not just the total.
    _user(ctx, "ugl-new", role=ROLE_UGL, created=_quarter_start(qs[3]))

    snap = ctx.user_service.recompute_community_counts()

    assert snap["totalMembers"] == 3
    assert snap["newByQuarter"][qs[3]] == 2
    assert snap["newByQuarter"][qs[0]] == 1
    assert sum(snap["newByQuarter"].values()) <= snap["totalMembers"]


def test_current_quarter_of_the_trend_equals_the_total_members_card(ctx):
    """The card and the chart line are ONE figure — this is the discrepancy the
    snapshot exists to prevent."""
    _user(ctx, "m-1")
    _user(ctx, "m-2")
    _user(ctx, "m-3")

    snap = ctx.user_service.recompute_community_counts()

    assert snap["totalByQuarter"][current_quarter()] == snap["totalMembers"] == 3
    # And the read path returns the same, not a recount.
    assert ctx.user_service.community_counts()["totalByQuarter"][current_quarter()] == 3


def test_previously_recorded_quarters_are_carried_forward(ctx):
    """A past quarter's roster cannot be reconstructed once accounts have been
    deactivated, so history is recorded once and never recomputed. The series
    fills in from the first run rather than being backfilled with guesses."""
    qs = trailing_quarters_asc(4)
    ctx.repo.put_community_counts({
        "totalMembers": 40, "newByQuarter": {},
        "totalByQuarter": {qs[0]: 10, qs[1]: 25, qs[2]: 40},
        "computedAt": "2026-04-01T00:00:00Z"})
    _user(ctx, "m-1")
    _user(ctx, "m-2")

    snap = ctx.user_service.recompute_community_counts()

    assert snap["totalByQuarter"] == {qs[0]: 10, qs[1]: 25, qs[2]: 40,
                                      current_quarter(): 2}


def test_trend_window_drops_quarters_older_than_the_window(ctx):
    """The snapshot is a single item, so the series is bounded rather than growing
    without limit."""
    stale = "2019-Q1"
    ctx.repo.put_community_counts({
        "totalMembers": 1, "newByQuarter": {}, "totalByQuarter": {stale: 999},
        "computedAt": "2019-04-01T00:00:00Z"})
    _user(ctx, "m-1")

    snap = ctx.user_service.recompute_community_counts()

    assert stale not in snap["totalByQuarter"]
    assert set(snap["totalByQuarter"]) <= set(trailing_quarters_asc(8))


def test_counts_are_absent_not_faked_before_the_first_run(ctx):
    """The dashboard shows an "as of" disclaimer from `computedAt`; a fabricated
    timestamp would claim freshness the data does not have."""
    out = ctx.user_service.community_counts()

    assert out["totalMembers"] == 0
    assert out["totalByQuarter"] == {}
    assert out["computedAt"] is None
