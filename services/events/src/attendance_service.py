"""Attendance recording and point awards (US-2.12/2.16/2.17/2.19).

Three entry points, one commit path:
  * manual marking from the RSVP list
  * CSV import (CSV-ONLY — see below)
  * MS Teams review-then-apply

**A Teams fetch never awards anything** (BR-T4). It produces a reviewable batch;
points are committed only when a manager applies it, and a batch applies exactly
once (BR-T5). This is the single most important behaviour in this module: the
mockup states it twice and it is the difference between "we think these people
attended" and "these people have been paid".

**CSV only, no xlsx** (BR-T7). The SheetJS/`xlsx` package has unpatched
high-severity CVEs and was deliberately removed from this repo during the
Identity & Access bulk-import work; reintroducing it for one button here would
undo that decision. The mockup's "Upload Excel/CSV" label is narrowed to CSV.
"""
from __future__ import annotations

import csv
import io

from _conventions.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from models import (
    MAX_ATTENDEES_PER_APPLY,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    VIRTUAL_MODES,
    can_manage,
    can_view,
    new_id,
    now_iso,
    teams_batch_public,
)


def _require_teams_enabled(settings) -> None:
    """503 rather than 403: the caller is permitted, the capability is switched
    off (BR-T1). The SPA uses this to hide the MS Teams tab entirely."""
    if not settings.teams_enabled():
        raise AppError(code="NOT_CONFIGURED",
                       message="MS Teams integration is not enabled.", status=503)


class AttendanceService:

    def __init__(self, repo, events, contributions, teams, settings, event_service):
        self._repo = repo
        self._events = events
        self._contrib = contributions
        self._teams = teams
        self._settings = settings
        self._event_service = event_service

    # ------------------------------------------------------------------ authz

    def _load_manageable(self, event_id: str, principal) -> dict:
        event = self._repo.get_event(event_id)
        if event is None or not can_view(event, principal):
            raise NotFoundError(message="Event not found.")
        if not can_manage(event, principal):
            raise ForbiddenError(message="You cannot record attendance for this event.")
        if event.get("status") == STATUS_CANCELLED:
            raise ConflictError(message="Attendance cannot be recorded for a cancelled event.")
        return event

    # ------------------------------------------------------------------ manual

    def record(self, event_id: str, body: dict, *, principal,
               correlation_id: str | None = None, bearer_token: str | None = None) -> dict:
        event = self._load_manageable(event_id, principal)
        user_ids = body.get("userIds") or []
        emails = body.get("emails")
        if isinstance(emails, str) and emails.strip():
            user_ids = user_ids + [e.strip() for e in emails.split(",") if e.strip()]
        if not user_ids:
            raise ValidationError("Provide at least one attendee.")
        if len(user_ids) > MAX_ATTENDEES_PER_APPLY:
            raise ValidationError(
                f"At most {MAX_ATTENDEES_PER_APPLY} attendees can be recorded in one request. "
                "Split the import.")
        return self._commit(event, user_ids, source="manual",
                            correlation_id=correlation_id, bearer_token=bearer_token,
                            principal=principal)

    # --------------------------------------------------------------------- CSV

    def import_csv(self, event_id: str, body: dict, *, principal,
                   correlation_id: str | None = None,
                   bearer_token: str | None = None) -> dict:
        """Returns a PER-ROW report (BR-T7). Unmatched rows are reported as
        errors, never silently skipped — a leader must be able to see which
        addresses failed and why."""
        event = self._load_manageable(event_id, principal)
        raw = body.get("csv")
        if not isinstance(raw, str) or not raw.strip():
            raise ValidationError("Provide CSV content.")

        reader = csv.DictReader(io.StringIO(raw))
        if not reader.fieldnames or not any(
                (name or "").strip().lower() == "email" for name in reader.fieldnames):
            raise ValidationError("The CSV must contain an 'email' column.")
        email_field = next(name for name in reader.fieldnames
                           if (name or "").strip().lower() == "email")

        rsvps = {(r.get("userEmail") or "").lower(): r for r in self._repo.list_rsvps(event_id)}
        rows: list[dict] = []
        matched_ids: list[str] = []
        for index, record in enumerate(reader, start=2):  # row 1 is the header
            email = (record.get(email_field) or "").strip().lower()
            if not email:
                rows.append({"row": index, "email": "", "result": "error",
                             "message": "Missing email."})
                continue
            hit = rsvps.get(email)
            if hit:
                matched_ids.append(hit["userId"])
                rows.append({"row": index, "email": email, "result": "matched", "message": ""})
            else:
                rows.append({"row": index, "email": email, "result": "unmatched",
                             "message": "No member with this email has an RSVP for this event."})
        if len(matched_ids) > MAX_ATTENDEES_PER_APPLY:
            raise ValidationError(
                f"At most {MAX_ATTENDEES_PER_APPLY} attendees can be recorded in one request.")

        if matched_ids:
            self._commit(event, matched_ids, source="csv", correlation_id=correlation_id,
                         bearer_token=bearer_token, principal=principal)
        return {
            "total": len(rows),
            "matched": sum(1 for r in rows if r["result"] == "matched"),
            "unmatched": sum(1 for r in rows if r["result"] != "matched"),
            "rows": rows,
        }

    # ------------------------------------------------------------------- Teams

    def teams_fetch(self, event_id: str, *, principal) -> dict:
        """Fetch + email-match for REVIEW. Awards nothing (BR-T4)."""
        event = self._load_manageable(event_id, principal)
        # Fails closed: an unreachable Settings service also lands here (BR-T1).
        _require_teams_enabled(self._settings)
        if event.get("deliveryMode") not in VIRTUAL_MODES or not event.get("teamsMeetingId"):
            raise ValidationError(
                "Teams attendance is only available for virtual or hybrid events "
                "linked to a Teams meeting.")

        participants = self._teams.fetch_participants(event["teamsMeetingId"])
        by_email = {(r.get("userEmail") or "").lower(): r
                    for r in self._repo.list_rsvps(event_id)}
        reviewed = []
        for participant in participants:
            email = (participant.get("email") or "").strip().lower()
            hit = by_email.get(email)
            reviewed.append({
                **participant,
                "matchedUserId": hit["userId"] if hit else None,
                "matchStatus": "matched" if hit else "unmatched",
                # Unmatched rows default to EXCLUDED, so a guest cannot be
                # awarded by a manager who simply clicks Apply (BR-T3).
                "include": bool(hit),
            })
        batch = self._repo.put_teams_batch({
            "id": new_id("tb"), "eventId": event_id, "fetchedAt": now_iso(),
            "appliedAt": None, "participants": reviewed,
        })
        return teams_batch_public(batch)

    def teams_apply(self, event_id: str, body: dict, *, principal,
                    correlation_id: str | None = None,
                    bearer_token: str | None = None) -> dict:
        event = self._load_manageable(event_id, principal)
        _require_teams_enabled(self._settings)
        batch = self._repo.latest_teams_batch(event_id)
        if batch is None:
            raise NotFoundError(message="Fetch Teams attendance before applying it.")

        # Apply-once, enforced by a conditional update rather than by reading
        # `appliedAt` first — two managers clicking Apply concurrently must not
        # both award (BR-T5).
        if not self._repo.mark_teams_batch_applied(
                event_id, batch["fetchedAt"], now_iso()):
            raise ConflictError(message="This attendance batch has already been applied.")

        supplied = {(p.get("email") or "").lower(): p for p in (body.get("participants") or [])}
        user_ids: list[str] = []
        for participant in batch.get("participants") or []:
            email = (participant.get("email") or "").lower()
            override = supplied.get(email, {})
            include = override.get("include", participant.get("include"))
            matched = override.get("matchedUserId") or participant.get("matchedUserId")
            if include and matched:
                user_ids.append(matched)
        if len(user_ids) > MAX_ATTENDEES_PER_APPLY:
            raise ValidationError(
                f"At most {MAX_ATTENDEES_PER_APPLY} attendees can be applied in one request.")
        return self._commit(event, user_ids, source="teams",
                            correlation_id=correlation_id, bearer_token=bearer_token,
                            principal=principal)

    # ------------------------------------------------------------------ commit

    def _commit(self, event: dict, user_ids: list[str], *, source: str,
                correlation_id: str | None, bearer_token: str | None, principal) -> dict:
        """The single commit path for all three entry points.

        Order is deliberate: mark attendance (idempotent, so a retry is safe),
        then publish awards, then transition to Completed. Publishing before the
        transition means a crash leaves the event Upcoming with awards already
        out — recoverable by completing it manually. The reverse would leave a
        Completed event whose attendees were never awarded, which nobody would
        notice.
        """
        points = self._contrib.points_for(event.get("type"), bearer_token=bearer_token)
        attendance_points = points.get("attendance")

        newly = 0
        already = 0
        batch: list[tuple[str, dict]] = []
        rsvp_ids = {r["userId"] for r in self._repo.list_rsvps(event["id"])}
        at = now_iso()

        for user_id in user_ids:
            if user_id in rsvp_ids:
                flipped = self._repo.mark_attended(
                    event["id"], user_id, source=source, points=attendance_points, at=at)
            else:
                # BR-T6 allows attendance without an RSVP for CSV/Teams matches.
                self._repo.put_attendance_only(
                    event["id"], user_id, source=source, points=attendance_points, at=at)
                flipped = True
            if not flipped:
                already += 1
                continue
            newly += 1
            batch.append(("AttendanceRecorded", {
                "idempotencyKey": f"{event['id']}#{user_id}#attendance",
                "eventId": event["id"], "userId": user_id,
                "groupId": event.get("groupId"), "eventType": event.get("type"),
                # eventDate lets Contributions attribute points to the correct
                # quarter (Unit 7 DL11/US-6.12); startsAt is the canonical date.
                "eventDate": event.get("startsAt"),
                "points": attendance_points, "source": source,
            }))

        if newly:
            self._repo.bump_event_counters(
                event["id"], attended_delta=newly,
                points_delta=(attendance_points or 0) * newly)
            self._events.publish_many(batch, correlation_id=correlation_id)

        # Any applied attendance completes the event (BR-L3). Already-completed
        # is fine — a second import must not fail because of it.
        status = event.get("status")
        if status != STATUS_COMPLETED:
            refreshed = self._repo.get_event(event["id"]) or event
            self._event_service.complete_internal(
                refreshed, correlation_id=correlation_id,
                bearer_token=bearer_token, principal=principal)
            status = STATUS_COMPLETED

        return {
            "recorded": newly, "alreadyRecorded": already, "status": status,
            "attendedCount": int((self._repo.get_event(event["id"]) or {}).get("attendedCount") or 0),
            "pointsPerAttendee": attendance_points,
        }
