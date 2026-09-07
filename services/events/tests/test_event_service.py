"""Event lifecycle + the MANDATORY lifecycle-transition suite (NFR-EV-MAINT-1).

BR-L1 allows exactly two transitions: Upcoming -> Completed and
Upcoming -> Cancelled. Everything else is a 409, including any transition out of
a terminal state. The suite enumerates the illegal ones rather than sampling, so
a future refactor cannot quietly widen the state machine.
"""
from __future__ import annotations

import pytest
from _conventions.errors import ConflictError, ValidationError
from conftest import FUTURE, event_input, make_event, make_past_event

# ----------------------------------------------------------------- create

def test_create_sets_defaults_and_publishes(ctx, cl, events):
    created = make_event(ctx, cl)
    assert created["status"] == "Upcoming"
    assert created["rsvpYesCount"] == 0
    assert "EventCreated" in events.types()


def test_create_records_announcement_intent_without_calling_announcements(ctx, cl, events):
    """BR-X1 — the intent rides on the published event; Announcements acts on it
    when that service is real. No synchronous call, so event creation never
    depends on another service being up."""
    make_event(ctx, cl, announceOnCreate=True, announceByEmail=True)
    published = events.of_type("EventCreated")[0]["data"]
    assert published["announce"] is True
    assert published["announceByEmail"] is True


def test_create_rejects_unknown_type(ctx, cl):
    with pytest.raises(ValidationError):
        ctx.event_service.create(event_input(type="Party"), principal=cl)


def test_create_rejects_past_start(ctx, cl):
    with pytest.raises(ValidationError):
        ctx.event_service.create(event_input(startsAt="2020-01-01T10:00:00+00:00"), principal=cl)


def test_create_rejects_http_join_link_for_virtual(ctx, cl):
    """BR-V3 — a private community event's join link must not travel in
    cleartext, and silently upgrading the scheme would hide the mistake."""
    with pytest.raises(ValidationError):
        ctx.event_service.create(
            event_input(deliveryMode="Virtual", location="http://meet.example.com/x"),
            principal=cl)


def test_create_accepts_address_for_in_person(ctx, cl):
    created = ctx.event_service.create(
        event_input(deliveryMode="In-Person", location="12 Main St, Berlin"), principal=cl)
    assert created["deliveryMode"] == "In-Person"


def test_create_accepts_free_text_location_for_virtual_and_hybrid(ctx, cl):
    """Location is free text for EVERY delivery mode: a Virtual/Hybrid event may
    name a physical room rather than carry a join link."""
    for mode in ("Virtual", "Hybrid"):
        created = ctx.event_service.create(
            event_input(deliveryMode=mode, location="Boardroom 3B"), principal=cl)
        assert created["location"] == "Boardroom 3B"


def test_create_rejects_end_before_start(ctx, cl):
    with pytest.raises(ValidationError):
        ctx.event_service.create(
            event_input(startsAt="2027-06-12T14:00:00+00:00",
                        endsAt="2027-06-12T13:00:00+00:00"), principal=cl)


def test_create_rejects_span_over_cap(ctx, cl):
    """An event's span is capped (MAX_EVENT_SPAN_DAYS) so a mistyped end date
    cannot create an effectively open-ended event."""
    with pytest.raises(ValidationError):
        ctx.event_service.create(
            event_input(startsAt="2027-06-01T09:00:00+00:00",
                        endsAt="2027-08-01T09:00:00+00:00"), principal=cl)


def test_create_allows_multi_day_span(ctx, cl):
    """A hackathon runs across several days — one event, one span (US-2 gap)."""
    created = ctx.event_service.create(
        event_input(type="Hackathon", startsAt="2027-06-11T09:00:00+00:00",
                    endsAt="2027-06-13T18:00:00+00:00"), principal=cl)
    assert created["startsAt"] == "2027-06-11T09:00:00+00:00"
    assert created["endsAt"] == "2027-06-13T18:00:00+00:00"


def test_create_requires_end(ctx, cl):
    body = event_input()
    body.pop("endsAt")
    with pytest.raises(ValidationError):
        ctx.event_service.create(body, principal=cl)


# ---------------------------------------------- lifecycle transitions (BR-L1)

def test_cancel_from_upcoming(ctx, cl):
    created = make_event(ctx, cl)
    ctx.event_service.cancel(created["id"], principal=cl)
    assert ctx.repo.get_event(created["id"])["status"] == "Cancelled"


def test_complete_from_upcoming_past_dated(ctx, cl):
    event = make_past_event(ctx, cl)
    result = ctx.event_service.complete(event["id"], principal=cl)
    assert result["status"] == "Completed"


def test_complete_rejects_future_event(ctx, cl):
    """BR-L2 — only past-dated events can be completed."""
    created = make_event(ctx, cl, startsAt=FUTURE)
    with pytest.raises(ValidationError):
        ctx.event_service.complete(created["id"], principal=cl)


def test_cancel_after_complete_is_conflict(ctx, cl):
    event = make_past_event(ctx, cl)
    ctx.event_service.complete(event["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.event_service.cancel(event["id"], principal=cl)


def test_complete_after_cancel_is_conflict(ctx, cl):
    event = make_past_event(ctx, cl)
    ctx.event_service.cancel(event["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.event_service.complete(event["id"], principal=cl)


def test_complete_twice_is_conflict(ctx, cl):
    event = make_past_event(ctx, cl)
    ctx.event_service.complete(event["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.event_service.complete(event["id"], principal=cl)


def test_cancel_twice_is_conflict(ctx, cl):
    created = make_event(ctx, cl)
    ctx.event_service.cancel(created["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.event_service.cancel(created["id"], principal=cl)


def test_edit_rejected_after_cancel(ctx, cl):
    created = make_event(ctx, cl)
    ctx.event_service.cancel(created["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.event_service.edit(created["id"], event_input(), principal=cl)


def test_edit_rejected_after_complete(ctx, cl):
    event = make_past_event(ctx, cl)
    ctx.event_service.complete(event["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.event_service.edit(event["id"], event_input(), principal=cl)


def test_cancelled_event_stays_visible(ctx, cl):
    """BR-L5 — cancellation is a state change, never a delete."""
    created = make_event(ctx, cl)
    ctx.event_service.cancel(created["id"], principal=cl)
    fetched = ctx.event_service.get(created["id"], principal=cl)
    assert fetched["status"] == "Cancelled"
    assert fetched["cancelledAt"]


def test_cancel_publishes_notification_intent(ctx, cl, events):
    created = make_event(ctx, cl)
    ctx.event_service.cancel(created["id"], principal=cl)
    payload = events.of_type("EventCancelled")[0]["data"]
    assert payload["notifyRsvps"] is True


def test_edit_bumps_ics_sequence(ctx, cl):
    """A stale SEQUENCE makes calendar clients ignore an updated invite, so it
    must increase on every edit (BR-N5)."""
    created = make_event(ctx, cl)
    before = ctx.repo.get_event(created["id"]).get("icsSequence") or 0
    ctx.event_service.edit(created["id"], event_input(title="New"), principal=cl)
    assert (ctx.repo.get_event(created["id"])["icsSequence"]) == before + 1


# ------------------------------------------------------------- group deletion

def test_group_soft_delete_cancels_only_upcoming(ctx, cl):
    upcoming = make_event(ctx, cl, groupId="g-serverless")
    past = make_past_event(ctx, cl, groupId="g-serverless", title="Done")
    ctx.event_service.complete(past["id"], principal=cl)

    cancelled = ctx.event_service.cancel_group_events("g-serverless")
    assert cancelled == 1
    assert ctx.repo.get_event(upcoming["id"])["status"] == "Cancelled"
    assert ctx.repo.get_event(past["id"])["status"] == "Completed"


def test_group_soft_delete_leaves_other_groups_alone(ctx, cl):
    mine = make_event(ctx, cl, groupId="g-serverless")
    theirs = make_event(ctx, cl, groupId="g-ml")
    ctx.event_service.cancel_group_events("g-serverless")
    assert ctx.repo.get_event(mine["id"])["status"] == "Cancelled"
    assert ctx.repo.get_event(theirs["id"])["status"] == "Upcoming"
