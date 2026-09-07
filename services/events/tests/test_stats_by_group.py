"""Events per USER GROUP for one quarter (US-7.1) — CL dashboard ranked bars.

The invariant under test throughout: a Community Leader's per-group bar equals
what that group's own leader sees, and the bars plus the community-wide row
account for every event in the quarter.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ForbiddenError, ValidationError  # noqa: E402
from conftest import event_input  # noqa: E402
from models import (  # noqa: E402
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_UPCOMING,
    current_quarter,
    quarter_start_iso,
)


def _event_in(ctx, principal, *, quarter, event_type="Workshop", group="g-serverless",
              status=STATUS_COMPLETED):
    """Write an event sitting in `quarter`. Created then back-dated, since
    creation rightly refuses a past start (BR-V4)."""
    created = ctx.event_service.create(
        event_input(type=event_type, groupId=group), principal=principal)
    stored = ctx.repo.get_event(created["id"])
    stored["startsAt"] = quarter_start_iso(quarter).replace("-01T00:00:00", "-15T10:00:00")
    stored["status"] = status
    ctx.repo.put_event({k: v for k, v in stored.items()
                        if k not in ("pk", "sk", "gsi1pk", "gsi1sk")})
    return stored


def test_counts_events_per_named_group_ranked_largest_first(ctx, cl):
    q = current_quarter()
    _event_in(ctx, cl, quarter=q, group="g-serverless")
    _event_in(ctx, cl, quarter=q, group="g-ml")
    _event_in(ctx, cl, quarter=q, group="g-ml")

    out = ctx.event_service.stats_by_group(
        {"groupIds": "g-serverless,g-ml,g-empty"}, principal=cl)

    assert out["quarter"] == q
    assert [(i["groupId"], i["events"]) for i in out["items"]] == [
        ("g-ml", 2), ("g-serverless", 1), ("g-empty", 0)]


def test_community_wide_is_its_own_row_and_the_total_reconciles(ctx, cl):
    """Community-wide events belong to no group (BR-S1). Folding them into one
    would be wrong; dropping them would leave the bars summing to less than the
    quarter with nothing to explain the gap."""
    q = current_quarter()
    _event_in(ctx, cl, quarter=q, group="g-ml")
    _event_in(ctx, cl, quarter=q, group=None)          # community-wide
    _event_in(ctx, cl, quarter=q, group=None)

    out = ctx.event_service.stats_by_group({"groupIds": "g-ml"}, principal=cl)

    assert out["communityWide"] == 2
    assert out["total"] == 3
    assert out["total"] == out["communityWide"] + sum(i["events"] for i in out["items"])


def test_per_group_count_equals_what_that_groups_leader_sees(ctx, cl, ugl):
    """No discrepancy: the CL's bar for a group and the UGL's own by-type total
    for the same quarter are the same number, because both apply one rule."""
    q = current_quarter()
    _event_in(ctx, cl, quarter=q, group="g-serverless", event_type="Workshop")
    _event_in(ctx, cl, quarter=q, group="g-serverless", event_type="Meetup",
              status=STATUS_UPCOMING)
    _event_in(ctx, cl, quarter=q, group="g-serverless", status=STATUS_CANCELLED)

    by_group = ctx.event_service.stats_by_group(
        {"groupIds": "g-serverless"}, principal=cl)
    # The UGL's own view of the same group and quarter (their led group).
    by_type = ctx.event_service.stats_by_type({"quarters": "1"}, principal=ugl)

    assert by_group["items"][0]["events"] == by_type["items"][-1]["total"] == 2


def test_cancelled_events_are_excluded(ctx, cl):
    q = current_quarter()
    _event_in(ctx, cl, quarter=q, group="g-ml", status=STATUS_COMPLETED)
    _event_in(ctx, cl, quarter=q, group="g-ml", status=STATUS_CANCELLED)

    out = ctx.event_service.stats_by_group({"groupIds": "g-ml"}, principal=cl)

    assert out["items"][0]["events"] == 1


def test_events_in_another_quarter_are_excluded(ctx, cl):
    _event_in(ctx, cl, quarter="2019-Q1", group="g-ml")

    out = ctx.event_service.stats_by_group({"groupIds": "g-ml"}, principal=cl)

    assert out["items"][0]["events"] == 0
    assert out["total"] == 0


def test_a_past_quarter_can_be_selected(ctx, cl):
    _event_in(ctx, cl, quarter="2019-Q1", group="g-ml")

    out = ctx.event_service.stats_by_group(
        {"groupIds": "g-ml", "quarter": "2019-Q1"}, principal=cl)

    assert out["quarter"] == "2019-Q1"
    assert out["items"][0]["events"] == 1


def test_repeated_group_ids_are_collapsed(ctx, cl):
    """A repeated id would otherwise draw two bars for one group and inflate the
    total."""
    q = current_quarter()
    _event_in(ctx, cl, quarter=q, group="g-ml")

    out = ctx.event_service.stats_by_group({"groupIds": "g-ml,g-ml, g-ml"}, principal=cl)

    assert out["count"] == 1
    assert out["total"] == 1


def test_no_group_ids_still_reports_community_wide(ctx, cl):
    q = current_quarter()
    _event_in(ctx, cl, quarter=q, group=None)

    out = ctx.event_service.stats_by_group({}, principal=cl)

    assert out["items"] == []
    assert out["communityWide"] == 1 and out["total"] == 1


def test_group_count_is_capped(ctx, cl):
    """The ids arrive in the query string, so an unbounded list would turn one
    request into an unbounded fan-out."""
    with pytest.raises(ValidationError):
        ctx.event_service.stats_by_group(
            {"groupIds": ",".join(f"g-{n}" for n in range(101))}, principal=cl)


def test_only_a_community_leader_may_read_it(ctx, ugl, member):
    for principal in (ugl, member):
        with pytest.raises(ForbiddenError):
            ctx.event_service.stats_by_group({"groupIds": "g-ml"}, principal=principal)


# ---- route ordering (regression guard) -------------------------------------
# "/events/stats/by-group" collides with "/events/{id}": routes match in ORDER,
# so if the literal path ever sinks below the templated one, "stats" binds as an
# event id and the request 404s instead of returning statistics.

def test_stats_path_is_not_captured_by_the_event_id_route():
    from app import _match

    op, params = _match("GET", "/events/stats/by-group")

    assert op == "eventStatsByGroup"
    assert params == {}


def test_the_templated_event_route_still_works():
    from app import _match

    op, params = _match("GET", "/events/ev-123")

    assert op == "getEvent"
    assert params == {"id": "ev-123"}
