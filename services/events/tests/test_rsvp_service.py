"""RSVP behaviour (US-2.6/2.7/2.8)."""
from __future__ import annotations

import pytest
from _conventions.errors import ConflictError, ForbiddenError
from conftest import make_event, make_past_event
from ics import METHOD_CANCEL, METHOD_REQUEST


def test_rsvp_yes_records_and_counts(ctx, cl, member):
    created = make_event(ctx, cl)
    result = ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    assert result["response"] == "yes"
    assert result["rsvpYesCount"] == 1
    assert result["icsAction"] == "request"


def test_rsvp_no_does_not_send_an_invite(ctx, cl, member):
    created = make_event(ctx, cl)
    result = ctx.rsvps.respond(created["id"], {"response": "no"}, principal=member)
    assert result["icsAction"] == "none"
    assert result["rsvpNoCount"] == 1


def test_repeated_identical_rsvp_is_idempotent(ctx, cl, member):
    """BR-C3 — a retry must not double-count. Returning current state rather than
    an error, because the SPA may legitimately re-send."""
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    again = ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    assert again["rsvpYesCount"] == 1
    assert again["icsAction"] == "none"


def test_changing_yes_to_no_sends_a_cancellation(ctx, cl, member, events):
    """BR-C4 — the entry must be actively REMOVED from the member's calendar, not
    merely left un-reminded."""
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    result = ctx.rsvps.respond(created["id"], {"response": "no"}, principal=member)
    assert result["icsAction"] == "cancel"
    invites = events.of_type("CalendarInviteDue")
    assert invites[-1]["data"]["icsMethod"] == METHOD_CANCEL


def test_changing_no_to_yes_sends_a_fresh_invite(ctx, cl, member, events):
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "no"}, principal=member)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    assert events.of_type("CalendarInviteDue")[-1]["data"]["icsMethod"] == METHOD_REQUEST


def test_invite_carries_a_rendered_ics(ctx, cl, member, events):
    """Events renders, Notifications delivers (D2) — so the .ics must be on the
    event, not left for the consumer to construct."""
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    payload = events.of_type("CalendarInviteDue")[0]["data"]
    assert payload["ics"].startswith("BEGIN:VCALENDAR")
    assert payload["recipientUserId"] == member.user_id


def test_counters_never_go_negative_across_flips(ctx, cl, member):
    created = make_event(ctx, cl)
    for response in ("yes", "no", "yes", "no", "no"):
        ctx.rsvps.respond(created["id"], {"response": response}, principal=member)
    stored = ctx.repo.get_event(created["id"])
    assert stored["rsvpYesCount"] == 0
    assert stored["rsvpNoCount"] == 1


def test_rsvp_rejected_once_event_is_not_upcoming(ctx, cl, member):
    event = make_past_event(ctx, cl)
    ctx.event_service.complete(event["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=member)


def test_rsvp_rejected_on_cancelled_event(ctx, cl, member):
    created = make_event(ctx, cl)
    ctx.event_service.cancel(created["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)


def test_invalid_response_rejected(ctx, cl, member):
    from _conventions.errors import ValidationError
    created = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.rsvps.respond(created["id"], {"response": "maybe"}, principal=member)


def test_leaders_can_rsvp(ctx, cl, ugl):
    """CL and UGL participate as attendees too (BR-A6)."""
    created = make_event(ctx, cl)
    assert ctx.rsvps.respond(created["id"], {"response": "yes"},
                             principal=ugl)["rsvpYesCount"] == 1


def test_rsvp_list_shows_counts_and_rows(ctx, cl, member, ugl):
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    ctx.rsvps.respond(created["id"], {"response": "no"}, principal=ugl)
    listed = ctx.rsvps.list_for_event(created["id"], principal=cl)
    assert listed["count"] == 2
    assert listed["yesCount"] == 1
    assert listed["noCount"] == 1


def test_rsvp_list_rows_carry_name_email_and_role(ctx, cl, member):
    """The manage screen's RSVP List renders Name / Email / Role columns —
    denormalised from the responder's claims at RSVP time, like userEmail."""
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    row = ctx.rsvps.list_for_event(created["id"], principal=cl)["items"][0]
    assert row["userName"] == "Mem One"
    assert row["userEmail"] == "mem1@portal.test"
    assert row["userRole"] == "Member"


def test_rsvp_list_denied_to_non_manager(ctx, cl, member):
    created = make_event(ctx, cl)
    with pytest.raises(ForbiddenError):
        ctx.rsvps.list_for_event(created["id"], principal=member)


def test_ics_download_available_to_viewers(ctx, cl, member):
    created = make_event(ctx, cl)
    body = ctx.rsvps.ics_for(created["id"], principal=member)
    assert body.startswith("BEGIN:VCALENDAR")


def test_ics_download_respects_visibility(ctx, cl, other_member):
    from _conventions.errors import NotFoundError
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(NotFoundError):
        ctx.rsvps.ics_for(created["id"], principal=other_member)


def test_own_rsvp_reflected_on_get(ctx, cl, member):
    created = make_event(ctx, cl)
    ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=member)
    fetched = ctx.event_service.get(created["id"], principal=member)
    assert fetched["myRsvp"] == "yes"
