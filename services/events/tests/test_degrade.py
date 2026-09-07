"""MANDATORY degrade-path suite (NFR-EV-MAINT-1, BR-P1, RESILIENCY-10).

The contract with the rest of the portal is that a dependency outage degrades a
SECTION of a response, never the request. The specific promises tested here:

* Contributions unavailable -> 200 with the points fields ABSENT. Absence is the
  documented signal; returning 0 would render "+0 pts" in the UI, which is a lie.
* MS Teams disabled -> 503 on the Teams operations ONLY. Everything else,
  including manual attendance, keeps working.
* Settings unreachable -> Teams treated as disabled (fail closed), never enabled.
"""
from __future__ import annotations

import pytest
from _conventions.errors import AppError
from conftest import FakeSettings, FakeTeams, make_event, make_past_event


def test_points_omitted_when_contributions_fails(ctx, cl, contributions):
    contributions.failing = True
    created = make_event(ctx, cl)
    fetched = ctx.event_service.get(created["id"], principal=cl)
    assert "attendancePoints" not in fetched
    assert "deliveryPoints" not in fetched
    assert fetched["id"] == created["id"]  # the request still succeeded


def test_points_present_when_contributions_healthy(ctx, cl):
    created = make_event(ctx, cl)
    fetched = ctx.event_service.get(created["id"], principal=cl)
    assert fetched["attendancePoints"] == 10


def test_listing_still_renders_when_contributions_fails(ctx, cl, contributions):
    make_event(ctx, cl)
    make_event(ctx, cl, title="Second")
    contributions.failing = True
    page = ctx.event_service.list(principal=cl, filters={}, limit=25, cursor=None)
    assert page["count"] == 2
    assert all("attendancePoints" not in row for row in page["items"])


def test_attendance_records_without_points_when_contributions_fails(ctx, cl, contributions):
    """Attendance is a fact about the world; it must be recordable even when the
    scoring service is down. The award event still fires so Contributions can
    resolve the value when it recovers."""
    event = make_past_event(ctx, cl)
    ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=cl)
    contributions.failing = True

    result = ctx.attendance.record(event["id"], {"userIds": ["u-cl"]}, principal=cl)
    assert result["recorded"] == 1
    assert result["pointsPerAttendee"] is None


def test_teams_operations_503_when_disabled(ctx, cl):
    event = make_past_event(ctx, cl)
    with pytest.raises(AppError) as excinfo:
        ctx.attendance.teams_fetch(event["id"], principal=cl)
    assert excinfo.value.status == 503
    assert excinfo.value.code == "NOT_CONFIGURED"


def test_manual_attendance_unaffected_by_teams_being_disabled(ctx, cl):
    event = make_past_event(ctx, cl)
    ctx.rsvps.respond(event["id"], {"response": "yes"}, principal=cl)
    result = ctx.attendance.record(event["id"], {"userIds": ["u-cl"]}, principal=cl)
    assert result["recorded"] == 1


def test_teams_enabled_but_non_virtual_event_is_a_validation_error(aws, cl, events,
                                                                  contributions):
    """Enabled-but-inapplicable is a 400, distinct from disabled (503): the first
    is a request problem, the second a deployment one, and conflating them makes
    the UI unable to decide whether to hide the tab or show an error."""
    from _conventions.errors import ValidationError
    from app import Context
    from conftest import IDEM_TABLE_NAME
    from providers import S3Storage

    ctx = Context(table=aws.table, idempotency_table=IDEM_TABLE_NAME,
                  storage=S3Storage(bucket=aws.bucket), events=events,
                  contributions=contributions, teams=FakeTeams(),
                  settings=FakeSettings(teams=True))
    event = make_past_event(ctx, cl, deliveryMode="In-Person",
                            location="12 Main St")
    with pytest.raises(ValidationError):
        ctx.attendance.teams_fetch(event["id"], principal=cl)


def test_settings_unreachable_means_teams_disabled(monkeypatch):
    """Fail CLOSED: an unreachable Settings service must not be read as
    'enabled'. The opposite default would expose an integration nobody
    configured."""
    from providers import SettingsCache

    SettingsCache.reset_cache()
    monkeypatch.delenv("MS_TEAMS_ENABLED", raising=False)
    cache = SettingsCache(base_url="https://unused.invalid", opener=_boom)
    assert cache.teams_enabled() is False
    SettingsCache.reset_cache()


def _boom(*args, **kwargs):
    raise OSError("simulated outage")


def test_contributions_client_returns_none_on_failure(monkeypatch):
    from providers import ContributionsClient

    ContributionsClient.reset_cache()
    client = ContributionsClient(base_url="https://unused.invalid", opener=_boom)
    values = client.points_for("Workshop")
    assert values == {"attendance": None, "delivery": None}
    ContributionsClient.reset_cache()


def test_contributions_client_caches_within_ttl(monkeypatch):
    """N6 — a 25-row page must cost at most one downstream call."""
    from providers import ContributionsClient

    ContributionsClient.reset_cache()
    calls = {"n": 0}

    class FakeResponse:
        def read(self):
            return b'{"items": [{"activity": "Event attendance", "points": 10}]}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(req, timeout=None):
        calls["n"] += 1
        return FakeResponse()

    client = ContributionsClient(base_url="https://api.example.com", opener=opener)
    client.points_for("Workshop")
    client.points_for("Workshop")
    client.points_for("Workshop")
    assert calls["n"] == 1
    ContributionsClient.reset_cache()


def test_storage_failure_does_not_delete_metadata_row(ctx, cl, monkeypatch):
    """BR-M7 — S3 delete first and fail closed. An object with no owning record is
    invisible to the portal yet still billable and still reachable by an old URL,
    which is worse than a row whose object is already gone."""
    from _conventions.errors import AppError as Err

    event = make_event(ctx, cl)
    material = ctx.materials.add(
        event["id"], {"name": "Slides.pptx", "kind": "file",
                      "s3Key": f"events/{event['id']}/materials/Slides.pptx"},
        principal=cl)

    def failing_delete(key):
        raise Err(code="STORAGE_ERROR", message="nope", status=502)

    monkeypatch.setattr(ctx.storage, "delete_object", failing_delete)
    with pytest.raises(Err):
        ctx.materials.remove(event["id"], material["id"], principal=cl)
    assert ctx.repo.get_material(event["id"], material["id"]) is not None


def test_settings_cache_reads_internal_route_and_sees_the_flag(monkeypatch):
    """Two things at once. (1) The URL: teamsEnabled must be read from
    /internal/settings, which is private-API-only, not from the unauthenticated
    /public/settings. (2) The value: on /public the field was absent from the
    projection, so this always fell through to the False default. Feed a payload
    carrying True and prove the gate now follows the store."""
    import json as _json

    from providers import SettingsCache

    seen: list[str] = []

    class _Resp:
        def read(self):
            return _json.dumps({"teamsEnabled": True}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _opener(req, timeout=None):
        seen.append(req.full_url)
        return _Resp()

    SettingsCache.reset_cache()
    monkeypatch.delenv("MS_TEAMS_ENABLED", raising=False)
    cache = SettingsCache(base_url="https://api.example.com", opener=_opener)
    assert cache.teams_enabled() is True
    assert seen == ["https://api.example.com/internal/settings"]
    SettingsCache.reset_cache()
