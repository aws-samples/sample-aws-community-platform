"""Completed events per quarter, by event type (US-7.2) — UGL dashboard column chart."""
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
    quarter_start_iso,
    trailing_quarters_asc,
)


def _event_in(ctx, principal, *, quarter, event_type, group="g-serverless",
              status=STATUS_COMPLETED):
    """Write an event that sits in `quarter` with the given status.

    Created then back-dated: creation rightly refuses a past start (BR-V4), so
    the stored timestamp is set directly — what time passing would have done.
    """
    created = ctx.event_service.create(
        event_input(type=event_type, groupId=group), principal=principal)
    stored = ctx.repo.get_event(created["id"])
    # Mid-quarter so the row cannot straddle a boundary.
    stored["startsAt"] = quarter_start_iso(quarter).replace("-01T00:00:00", "-15T10:00:00")
    stored["status"] = status
    ctx.repo.put_event({k: v for k, v in stored.items()
                        if k not in ("pk", "sk", "gsi1pk", "gsi1sk")})
    return stored


def test_counts_events_by_quarter_and_type(ctx, cl, ugl):
    qs = trailing_quarters_asc(4)
    _event_in(ctx, cl, quarter=qs[0], event_type="Workshop")
    _event_in(ctx, cl, quarter=qs[0], event_type="Workshop")
    _event_in(ctx, cl, quarter=qs[0], event_type="Meetup")
    _event_in(ctx, cl, quarter=qs[3], event_type="Webinar")

    out = ctx.event_service.stats_by_type({}, principal=ugl)

    assert out["quarters"] == qs                       # oldest first
    assert out["groupId"] == "g-serverless"
    by_q = {i["quarter"]: i for i in out["items"]}
    assert by_q[qs[0]]["counts"] == {"Workshop": 2, "Meetup": 1}
    assert by_q[qs[0]]["total"] == 3
    assert by_q[qs[3]]["counts"] == {"Webinar": 1}
    assert by_q[qs[1]]["counts"] == {} and by_q[qs[1]]["total"] == 0


def test_only_types_present_are_returned_in_canonical_order(ctx, cl, ugl):
    qs = trailing_quarters_asc(4)
    _event_in(ctx, cl, quarter=qs[0], event_type="Webinar")
    _event_in(ctx, cl, quarter=qs[1], event_type="Meetup")

    out = ctx.event_service.stats_by_type({}, principal=ugl)

    # Canonical EVENT_TYPES order is Meetup, Workshop, Hackathon, Webinar, ...
    assert out["types"] == ["Meetup", "Webinar"]


def test_counts_upcoming_and_completed_but_not_cancelled(ctx, cl, ugl):
    """Same rule as the dashboard's "Group Events" card: every status except
    Cancelled. The two must never disagree."""
    qs = trailing_quarters_asc(4)
    _event_in(ctx, cl, quarter=qs[0], event_type="Workshop", status=STATUS_COMPLETED)
    _event_in(ctx, cl, quarter=qs[0], event_type="Hackathon", status=STATUS_UPCOMING)
    _event_in(ctx, cl, quarter=qs[0], event_type="Meetup", status=STATUS_CANCELLED)

    out = ctx.event_service.stats_by_type({}, principal=ugl)

    assert out["types"] == ["Workshop", "Hackathon"]      # canonical order
    assert out["items"][0]["counts"] == {"Workshop": 1, "Hackathon": 1}
    assert out["items"][0]["total"] == 2


def test_other_groups_and_community_wide_do_not_leak_in(ctx, cl, ugl):
    qs = trailing_quarters_asc(4)
    _event_in(ctx, cl, quarter=qs[0], event_type="Workshop", group="g-ml")
    _event_in(ctx, cl, quarter=qs[0], event_type="Meetup", group=None)  # community-wide

    out = ctx.event_service.stats_by_type({}, principal=ugl)

    assert out["types"] == []
    assert all(i["total"] == 0 for i in out["items"])


def test_events_outside_the_window_are_excluded(ctx, cl, ugl):
    """Quarters are a trailing window; older events must not inflate it."""
    _event_in(ctx, cl, quarter="2019-Q1", event_type="Workshop")

    out = ctx.event_service.stats_by_type({"quarters": "4"}, principal=ugl)

    assert out["types"] == []


def test_ugl_scope_cannot_be_overridden_by_groupid(ctx, cl, ugl):
    qs = trailing_quarters_asc(4)
    _event_in(ctx, cl, quarter=qs[0], event_type="Workshop", group="g-ml")

    out = ctx.event_service.stats_by_type({"groupId": "g-ml"}, principal=ugl)

    assert out["groupId"] == "g-serverless"     # their led group, not the request
    assert out["types"] == []


def test_cl_may_select_a_group_and_defaults_to_community_wide(ctx, cl):
    qs = trailing_quarters_asc(4)
    _event_in(ctx, cl, quarter=qs[0], event_type="Workshop", group="g-ml")
    _event_in(ctx, cl, quarter=qs[0], event_type="Social", group=None)

    scoped = ctx.event_service.stats_by_type({"groupId": "g-ml"}, principal=cl)
    assert scoped["groupId"] == "g-ml"
    assert scoped["types"] == ["Workshop"]

    community = ctx.event_service.stats_by_type({}, principal=cl)
    assert community["groupId"] is None
    assert community["types"] == ["Social"]


def test_members_cannot_read_group_stats(ctx, member):
    with pytest.raises(ForbiddenError):
        ctx.event_service.stats_by_type({}, principal=member)


def test_quarters_window_is_validated(ctx, ugl):
    assert len(ctx.event_service.stats_by_type({"quarters": "8"}, principal=ugl)["items"]) == 8
    with pytest.raises(ValidationError):
        ctx.event_service.stats_by_type({"quarters": "99"}, principal=ugl)
