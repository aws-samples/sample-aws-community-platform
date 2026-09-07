"""Tests for mandatory event description on completion (US-2.19 / BR-LIB-V2)."""
import pytest
from unittest.mock import MagicMock, patch
from _conventions.errors import ValidationError


def _make_event_service(library=None):
    """Return a minimal EventService wired for complete() tests."""
    from event_service import EventService
    repo = MagicMock()
    events = MagicMock()
    contributions = MagicMock()
    contributions.points_for.return_value = {}
    designations = MagicMock()
    designations.award_on_completion = MagicMock()
    svc = EventService(repo, events, contributions, designations, library=library)
    return svc, repo


def _past_event(description="A great meetup about serverless"):
    from datetime import datetime, timezone, timedelta
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    return {
        "id": "ev-1", "title": "Serverless Meetup",
        "description": description,
        "status": "Upcoming", "startsAt": past,
        "groupId": "g-1", "type": "Meetup",
        "createdBy": "usr-cl", "attendedCount": 5,
    }


def _make_principal(role="CommunityLeader"):
    p = MagicMock()
    p.role = role
    p.user_id = "usr-cl"
    p.led_group_id = "g-1"
    p.member_group_ids = []
    return p


class TestMandatoryDescriptionOnComplete:

    def test_complete_with_description_succeeds(self):
        svc, repo = _make_event_service()
        event = _past_event(description="A great recap session")
        repo.get_event.return_value = event
        repo.put_event = MagicMock()
        # Should not raise
        result = svc.complete("ev-1", principal=_make_principal())
        assert result is not None

    def test_complete_without_description_raises_validation_error(self):
        svc, repo = _make_event_service()
        event = _past_event(description="")
        repo.get_event.return_value = event
        with pytest.raises(ValidationError) as exc_info:
            svc.complete("ev-1", principal=_make_principal())
        assert "description" in str(exc_info.value.message).lower()

    def test_complete_with_whitespace_only_description_raises(self):
        svc, repo = _make_event_service()
        event = _past_event(description="   ")
        repo.get_event.return_value = event
        with pytest.raises(ValidationError):
            svc.complete("ev-1", principal=_make_principal())

    def test_complete_triggers_path1_library_promotion(self):
        library = MagicMock()
        library.promote_event_materials = MagicMock(return_value=2)
        svc, repo = _make_event_service(library=library)
        event = _past_event()
        repo.get_event.return_value = event
        repo.put_event = MagicMock()
        svc.complete("ev-1", principal=_make_principal())
        library.promote_event_materials.assert_called_once()

    def test_complete_without_library_service_still_works(self):
        """Backward compatibility: if library is None, complete() works normally."""
        svc, repo = _make_event_service(library=None)
        event = _past_event()
        repo.get_event.return_value = event
        repo.put_event = MagicMock()
        result = svc.complete("ev-1", principal=_make_principal())
        assert result is not None
