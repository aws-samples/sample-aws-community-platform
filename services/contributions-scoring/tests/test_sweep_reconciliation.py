"""The nightly sweep's figures must RECONCILE with each other.

A dashboard that contradicts itself is worse than no dashboard, so every sweep
record satisfies:  sum(tierCounts) + unranked == activeContributorCount.

Regressions these lock down:
  * group activeContributorCount counted rows the deactivated-member filter had
    already removed from tierCounts;
  * the community tier distribution summed per-group counts, double-counting a
    member who belongs to two groups, while the contributor count de-duplicated;
  * a member with a negative net total gets no tier and vanished from the
    distribution entirely.
"""
from __future__ import annotations

import pathlib
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from consumers import NightlySweep  # noqa: E402
from models import current_quarter  # noqa: E402


def _earn(repo, member_id, group_id, quarter, points, *, name="M", ledger=None):
    repo.register_group(group_id)
    repo.apply_to_rollups({
        "ledgerId": ledger or f"led-{member_id}-{group_id}-{points}",
        "memberId": member_id, "memberName": name, "groupId": group_id,
        "quarter": quarter, "points": points, "pillar": 1,
    })


def _sweep(repo, framework):
    NightlySweep(repo, framework).run()


def _assert_reconciles(sweep: dict, label: str):
    tiers = sum((sweep.get("tierCounts") or {}).values())
    unranked = int(sweep.get("unranked") or 0)
    active = int(sweep.get("activeContributorCount") or 0)
    assert tiers + unranked == active, (
        f"{label}: tierCounts({tiers}) + unranked({unranked}) != active({active}) "
        f"-> {sweep}")


def test_group_sweep_excludes_deactivated_from_both_figures(repo, framework):
    q = current_quarter()
    _earn(repo, "m-live", "g-a", q, 80, name="Live One")
    _earn(repo, "m-gone", "g-a", q, 60, name="Gone One")
    repo.upsert_member_profile("m-live", active=True)
    repo.upsert_member_profile("m-gone", active=False)      # B3: excluded

    _sweep(repo, framework)
    sweep = repo.get_sweep("group", "g-a", q)

    assert sweep["activeContributorCount"] == 1             # was 2 (len(rows))
    assert sum(sweep["tierCounts"].values()) == 1
    _assert_reconciles(sweep, "group")


def test_community_counts_a_two_group_member_once(repo, framework):
    """The distribution and the contributor count must agree on distinctness."""
    q = current_quarter()
    _earn(repo, "m-both", "g-a", q, 80, name="Both", ledger="l1")
    _earn(repo, "m-both", "g-b", q, 55, name="Both", ledger="l2")

    _sweep(repo, framework)
    community = repo.get_sweep("community", "all", q)

    assert community["activeContributorCount"] == 1
    # One member => exactly one tier slice, taken at their HIGHEST group total.
    assert sum(community["tierCounts"].values()) == 1
    assert community["tierCounts"] == {"Gold": 1}           # 80 pts, not 55
    _assert_reconciles(community, "community")


def test_negative_total_is_reported_as_unranked_not_dropped(repo, framework):
    q = current_quarter()
    _earn(repo, "m-neg", "g-a", q, -5, name="Negative")

    _sweep(repo, framework)
    group = repo.get_sweep("group", "g-a", q)
    community = repo.get_sweep("community", "all", q)

    assert group["activeContributorCount"] == 1
    assert sum(group["tierCounts"].values()) == 0           # no tier at -5
    assert group["unranked"] == 1                           # visible, not vanished
    _assert_reconciles(group, "group")
    _assert_reconciles(community, "community")


def test_reconciles_across_a_mixed_population(repo, framework):
    q = current_quarter()
    _earn(repo, "m-gold", "g-a", q, 90, name="Gold", ledger="a1")
    _earn(repo, "m-silver", "g-a", q, 55, name="Silver", ledger="a2")
    _earn(repo, "m-neg", "g-a", q, -3, name="Neg", ledger="a3")
    _earn(repo, "m-multi", "g-a", q, 30, name="Multi", ledger="a4")
    _earn(repo, "m-multi", "g-b", q, 80, name="Multi", ledger="b1")
    _earn(repo, "m-off", "g-b", q, 70, name="Off", ledger="b2")
    repo.upsert_member_profile("m-off", active=False)

    _sweep(repo, framework)

    _assert_reconciles(repo.get_sweep("group", "g-a", q), "group a")
    _assert_reconciles(repo.get_sweep("group", "g-b", q), "group b")
    community = repo.get_sweep("community", "all", q)
    _assert_reconciles(community, "community")
    # gold, silver, neg, multi — deactivated m-off excluded, multi counted once.
    assert community["activeContributorCount"] == 4
    assert community["tierCounts"] == {"Gold": 2, "Silver": 1}   # multi at 80 = Gold
    assert community["unranked"] == 1
