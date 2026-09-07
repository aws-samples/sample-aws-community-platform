"""Attendance, point awards, and the Teams review-then-apply flow.

The behaviour worth guarding hardest: a Teams FETCH must award nothing, and an
APPLY must happen at most once. That is the difference between "we think these
people attended" and "these people have been paid".
"""
from __future__ import annotations

import pytest
from _conventions.errors import ConflictError, ValidationError
from conftest import FakeSettings, FakeTeams, make_past_event


def _rsvp_yes(ctx, event_id, *principals):
    for principal in principals:
        ctx.rsvps.respond(event_id, {"response": "yes"}, principal=principal)


# ------------------------------------------------------------------- manual

def test_manual_attendance_records_and_awards(ctx, cl, member, events):
    event = make_past_event(ctx, cl)
    _rsvp_yes(ctx, event["id"], member)
    result = ctx.attendance.record(event["id"], {"userIds": [member.user_id]}, principal=cl)
    assert result["recorded"] == 1
    assert result["pointsPerAttendee"] == 10
    awards = events.of_type("AttendanceRecorded")
    assert len(awards) == 1
    assert awards[0]["data"]["userId"] == member.user_id


def test_attendance_auto_completes_the_event(ctx, cl, member):
    """BR-L3 — any applied attendance transitions the event to Completed."""
    event = make_past_event(ctx, cl)
    _rsvp_yes(ctx, event["id"], member)
    result = ctx.attendance.record(event["id"], {"userIds": [member.user_id]}, principal=cl)
    assert result["status"] == "Completed"
    assert ctx.repo.get_event(event["id"])["status"] == "Completed"


def test_attendance_is_idempotent_per_member(ctx, cl, member, events):
    """BR-T8 — marking twice must not re-award."""
    event = make_past_event(ctx, cl)
    _rsvp_yes(ctx, event["id"], member)
    ctx.attendance.record(event["id"], {"userIds": [member.user_id]}, principal=cl)
    again = ctx.attendance.record(event["id"], {"userIds": [member.user_id]}, principal=cl)
    assert again["recorded"] == 0
    assert again["alreadyRecorded"] == 1
    assert len(events.of_type("AttendanceRecorded")) == 1


def test_award_events_carry_a_stable_idempotency_key(ctx, cl, member, events):
    """BR-P6 — a consumer retry must not double-award, which requires the key to
    be derived from identity rather than from time."""
    event = make_past_event(ctx, cl)
    _rsvp_yes(ctx, event["id"], member)
    ctx.attendance.record(event["id"], {"userIds": [member.user_id]}, principal=cl)
    key = events.of_type("AttendanceRecorded")[0]["data"]["idempotencyKey"]
    assert key == f"{event['id']}#{member.user_id}#attendance"


def test_attendance_rejected_above_the_ceiling(ctx, cl):
    """N4 — an explicit 400 beats an opaque Lambda timeout at an unpredictable
    size."""
    event = make_past_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.attendance.record(event["id"], {"userIds": [f"u-{i}" for i in range(1001)]},
                              principal=cl)


def test_attendance_rejected_on_cancelled_event(ctx, cl, member):
    event = make_past_event(ctx, cl)
    ctx.event_service.cancel(event["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.attendance.record(event["id"], {"userIds": [member.user_id]}, principal=cl)


def test_attendance_requires_at_least_one_attendee(ctx, cl):
    event = make_past_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.attendance.record(event["id"], {}, principal=cl)


# ---------------------------------------------------------------------- CSV

def test_csv_import_reports_matched_and_unmatched(ctx, cl, member):
    event = make_past_event(ctx, cl)
    _rsvp_yes(ctx, event["id"], member)
    csv_body = "email\nmem1@portal.test\nstranger@example.com\n"
    report = ctx.attendance.import_csv(event["id"], {"csv": csv_body}, principal=cl)
    assert report["total"] == 2
    assert report["matched"] == 1
    assert report["unmatched"] == 1
    unmatched = [r for r in report["rows"] if r["result"] == "unmatched"][0]
    assert unmatched["email"] == "stranger@example.com"
    assert unmatched["message"]


def test_csv_import_requires_an_email_column(ctx, cl):
    event = make_past_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.attendance.import_csv(event["id"], {"csv": "name\nAlex\n"}, principal=cl)


def test_csv_import_rejects_empty_body(ctx, cl):
    event = make_past_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.attendance.import_csv(event["id"], {"csv": "  "}, principal=cl)


def test_csv_import_reports_rows_with_a_missing_email_as_errors(ctx, cl, member):
    """Malformed rows are reported, never silently skipped — a leader must be
    able to see which rows failed. (Wholly blank lines are dropped by the CSV
    reader itself, so the case worth testing is a present-but-empty field.)"""
    event = make_past_event(ctx, cl)
    _rsvp_yes(ctx, event["id"], member)
    report = ctx.attendance.import_csv(
        event["id"], {"csv": "email,name\n,Nobody\nmem1@portal.test,Milo\n"}, principal=cl)
    assert any(r["result"] == "error" for r in report["rows"])
    assert report["matched"] == 1


def test_csv_import_is_case_insensitive_on_email(ctx, cl, member):
    event = make_past_event(ctx, cl)
    _rsvp_yes(ctx, event["id"], member)
    report = ctx.attendance.import_csv(
        event["id"], {"csv": "email\nMEM1@PORTAL.TEST\n"}, principal=cl)
    assert report["matched"] == 1


# -------------------------------------------------------------------- Teams

def _teams_ctx(aws, events, contributions, participants):
    from app import Context
    from conftest import IDEM_TABLE_NAME
    from providers import S3Storage

    return Context(table=aws.table, idempotency_table=IDEM_TABLE_NAME,
                   storage=S3Storage(bucket=aws.bucket), events=events,
                   contributions=contributions,
                   teams=FakeTeams(participants=participants),
                   settings=FakeSettings(teams=True))


PARTICIPANTS = [
    {"displayName": "Milo Member", "email": "mem1@portal.test", "joinTime": "14:01",
     "leaveTime": "15:28", "durationMinutes": 87},
    {"displayName": "a.guest@contoso.com (guest)", "email": "a.guest@contoso.com",
     "joinTime": "14:05", "leaveTime": "15:15", "durationMinutes": 70},
]


def test_teams_fetch_matches_by_email_and_awards_nothing(aws, cl, member, events,
                                                         contributions):
    """BR-T4 — the fetch is a review artefact only."""
    ctx = _teams_ctx(aws, events, contributions, PARTICIPANTS)
    event = make_past_event(ctx, cl, teamsMeetingId="meet-1")
    ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=member)

    batch = ctx.attendance.teams_fetch(event["id"], principal=cl)
    assert batch["matchedCount"] == 1
    assert batch["unmatchedCount"] == 1
    assert events.of_type("AttendanceRecorded") == []
    assert ctx.repo.get_event(event["id"])["status"] == "Upcoming"


def test_unmatched_participants_default_to_excluded(aws, cl, member, events, contributions):
    """BR-T3 — a guest must not be awarded by a manager who simply clicks Apply."""
    ctx = _teams_ctx(aws, events, contributions, PARTICIPANTS)
    event = make_past_event(ctx, cl, teamsMeetingId="meet-1")
    ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=member)
    batch = ctx.attendance.teams_fetch(event["id"], principal=cl)
    guest = [p for p in batch["participants"] if p["matchStatus"] == "unmatched"][0]
    assert guest["include"] is False


def test_teams_apply_awards_included_matches(aws, cl, member, events, contributions):
    ctx = _teams_ctx(aws, events, contributions, PARTICIPANTS)
    event = make_past_event(ctx, cl, teamsMeetingId="meet-1")
    ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=member)
    ctx.attendance.teams_fetch(event["id"], principal=cl)

    result = ctx.attendance.teams_apply(event["id"], {}, principal=cl)
    assert result["recorded"] == 1
    assert result["status"] == "Completed"
    assert len(events.of_type("AttendanceRecorded")) == 1


def test_teams_apply_twice_is_conflict(aws, cl, member, events, contributions):
    """BR-T5, enforced by a conditional update so two managers clicking Apply
    concurrently cannot both award."""
    ctx = _teams_ctx(aws, events, contributions, PARTICIPANTS)
    event = make_past_event(ctx, cl, teamsMeetingId="meet-1")
    ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=member)
    ctx.attendance.teams_fetch(event["id"], principal=cl)
    ctx.attendance.teams_apply(event["id"], {}, principal=cl)
    with pytest.raises(ConflictError):
        ctx.attendance.teams_apply(event["id"], {}, principal=cl)


def test_teams_apply_honours_manager_overrides(aws, cl, member, events, contributions):
    """The review screen lets a manager correct a match; the override must win
    over the fetched value."""
    ctx = _teams_ctx(aws, events, contributions, PARTICIPANTS)
    event = make_past_event(ctx, cl, teamsMeetingId="meet-1")
    ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=member)
    ctx.attendance.teams_fetch(event["id"], principal=cl)

    result = ctx.attendance.teams_apply(event["id"], {"participants": [
        {"email": "a.guest@contoso.com", "include": True, "matchedUserId": "u-mem-2"},
    ]}, principal=cl)
    assert result["recorded"] == 2


def test_teams_apply_without_a_fetch_is_not_found(aws, cl, events, contributions):
    from _conventions.errors import NotFoundError
    ctx = _teams_ctx(aws, events, contributions, PARTICIPANTS)
    event = make_past_event(ctx, cl, teamsMeetingId="meet-1")
    with pytest.raises(NotFoundError):
        ctx.attendance.teams_apply(event["id"], {}, principal=cl)


def test_teams_fetch_requires_a_meeting_id(aws, cl, events, contributions):
    ctx = _teams_ctx(aws, events, contributions, PARTICIPANTS)
    event = make_past_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.attendance.teams_fetch(event["id"], principal=cl)
