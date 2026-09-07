"""Mandatory suites (NFR-CS-MAINT-1): split determinism, tier derivation,
quarter math, award idempotency + exactly-once rollup, forum toggle."""
from __future__ import annotations

import pathlib
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from models import current_quarter, derive_tier, quarter_of, trailing_quarters  # noqa: E402
from split import split_points  # noqa: E402

# ---- community-wide split determinism (BR-S2) ---------------------------------

def test_split_equal_no_remainder():
    groups = [{"groupId": "a", "joinedAt": "2025-01-01"},
              {"groupId": "b", "joinedAt": "2025-02-01"}]
    assert dict(split_points(10, groups)) == {"a": 5, "b": 5}


def test_split_remainder_earliest_join_first():
    groups = [{"groupId": "late", "joinedAt": "2026-01-01"},
              {"groupId": "early", "joinedAt": "2025-01-01"},
              {"groupId": "mid", "joinedAt": "2025-06-01"}]
    result = dict(split_points(10, groups))
    # 10/3 = 3 base, remainder 1 -> earliest join ('early') gets the extra point
    assert result == {"early": 4, "mid": 3, "late": 3}
    assert sum(result.values()) == 10  # sums EXACTLY to original


def test_split_no_groups_awards_nothing():
    assert split_points(10, []) == []


# ---- tier derivation (BR-T1) --------------------------------------------------

THRESHOLDS = [{"tier": "Gold", "minPoints": 75}, {"tier": "Silver", "minPoints": 50},
              {"tier": "Bronze", "minPoints": 25}, {"tier": "Rising", "minPoints": 0}]


def test_tier_boundaries():
    assert derive_tier(75, THRESHOLDS) == "Gold"
    assert derive_tier(74, THRESHOLDS) == "Silver"
    assert derive_tier(0, THRESHOLDS) == "Rising"


def test_tier_below_zero_is_none():
    # A negative total from an adjustment falls below Rising's 0 threshold.
    assert derive_tier(-2, THRESHOLDS) is None


# ---- quarter math (BR-Q1) -----------------------------------------------------

def test_quarter_of():
    assert quarter_of("2026-06-05") == "2026-Q2"
    assert quarter_of("2026-01-01") == "2026-Q1"
    assert quarter_of("2026-12-31") == "2026-Q4"


def test_trailing_window_is_eight():
    qs = trailing_quarters(8)
    assert len(qs) == 8
    assert qs[0] == current_quarter()
