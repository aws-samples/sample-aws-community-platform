"""RSVP + calendar invites (US-2.6/2.7/2.8).

Counters are written in the SAME transaction as the RSVP row (P-REL-6) so they
cannot drift. The alternative — counting on read — would cost a full RSVP query
for every row of every list page.

Invites are PUBLISHED, not sent: Events renders the .ics and Notifications
delivers it (D2/BR-N2). Until Notifications is real the events accumulate on the
bus; the state is correct and only delivery is pending.
"""
from __future__ import annotations

from _conventions.errors import ConflictError, ForbiddenError, NotFoundError
from _conventions.validation import require_enum
from ics import METHOD_CANCEL, METHOD_REQUEST, render
from models import (
    STATUS_UPCOMING,
    can_manage,
    can_view,
    listing,
    now_iso,
    rsvp_public,
)


class RsvpService:

    def __init__(self, repo, events):
        self._repo = repo
        self._events = events

    def _load_viewable(self, event_id: str, principal) -> dict:
        event = self._repo.get_event(event_id)
        if event is None or not can_view(event, principal):
            raise NotFoundError(message="Event not found.")
        return event

    def respond(self, event_id: str, body: dict, *, principal,
                correlation_id: str | None = None) -> dict:
        # BR-A6 — Administrators cannot RSVP. Checked before anything is loaded
        # so the denial does not depend on event state.
        if principal.role == "Administrator":
            raise ForbiddenError(message="Administrators cannot RSVP to events.")
        event = self._load_viewable(event_id, principal)
        if event.get("status") != STATUS_UPCOMING:
            raise ConflictError(message="RSVP is only possible for upcoming events.")

        response = require_enum(body.get("response"), "response", {"yes", "no"})
        existing = self._repo.get_rsvp(event_id, principal.user_id)
        previous = (existing or {}).get("response")

        if previous == response:
            # Idempotent: a repeated identical response must not double-count
            # (BR-C3). Return current state rather than an error — the UI may
            # legitimately re-send after a retry.
            return {
                "response": response,
                "rsvpYesCount": int(event.get("rsvpYesCount") or 0),
                "rsvpNoCount": int(event.get("rsvpNoCount") or 0),
                "icsAction": "none",
            }

        yes_delta = (1 if response == "yes" else 0) - (1 if previous == "yes" else 0)
        no_delta = (1 if response == "no" else 0) - (1 if previous == "no" else 0)

        rsvp = {
            "eventId": event_id, "userId": principal.user_id,
            "userEmail": getattr(principal, "email", "") or "",
            # Name and role are denormalised from claims at RSVP time — the same
            # precedent as userEmail (no per-row cross-service lookup on list).
            # A re-response overwrites the row, so they refresh themselves.
            "userName": getattr(principal, "name", "") or "",
            "userRole": principal.role,
            "response": response, "respondedAt": now_iso(),
            "attended": bool((existing or {}).get("attended", False)),
            "attendedSource": (existing or {}).get("attendedSource"),
            "pointsAwarded": (existing or {}).get("pointsAwarded"),
        }
        self._repo.put_rsvp_with_counters(
            rsvp, starts_at=event.get("startsAt") or "", yes_delta=yes_delta, no_delta=no_delta)

        # yes -> no must actively REMOVE the entry from the member's calendar,
        # not merely stop reminding them (BR-C4).
        ics_action = "none"
        if response == "yes":
            ics_action = "request"
        elif previous == "yes":
            ics_action = "cancel"
        if ics_action != "none":
            # A distinct event type rather than reusing EventUpdated: an invite
            # is addressed to ONE recipient and carries a rendered .ics, whereas
            # EventUpdated is a broadcast about the event itself. Conflating them
            # would force Notifications to inspect a `kind` field to decide who
            # to mail.
            method = METHOD_REQUEST if ics_action == "request" else METHOD_CANCEL
            self._events.publish("CalendarInviteDue", {
                "eventId": event_id,
                "recipientUserId": principal.user_id,
                "icsMethod": method,
                "ics": render(event, method=method,
                              sequence=int(event.get("icsSequence") or 0)),
            }, correlation_id=correlation_id)

        return {
            "response": response,
            "rsvpYesCount": int(event.get("rsvpYesCount") or 0) + yes_delta,
            "rsvpNoCount": int(event.get("rsvpNoCount") or 0) + no_delta,
            "icsAction": ics_action,
        }

    def list_for_event(self, event_id: str, *, principal) -> dict:
        """The per-member RSVP LIST is manager-only (BR-C5); the aggregate counts
        are on the event itself and visible to anyone who can see it."""
        event = self._load_viewable(event_id, principal)
        if not can_manage(event, principal):
            raise ForbiddenError(message="Only event managers can view the RSVP list.")
        rows = self._repo.list_rsvps(event_id)
        yes = sum(1 for r in rows if r.get("response") == "yes")
        no = sum(1 for r in rows if r.get("response") == "no")
        return listing(rows, rsvp_public, yesCount=yes, noCount=no)

    def ics_for(self, event_id: str, *, principal) -> str:
        """US-2.8 / BR-N6 — the mockup's Download .ics button. Subject to normal
        view authorization, so it cannot be used to read an out-of-scope event."""
        event = self._load_viewable(event_id, principal)
        return render(event, method=METHOD_REQUEST,
                      sequence=int(event.get("icsSequence") or 0))
