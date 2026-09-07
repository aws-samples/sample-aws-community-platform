"""Unit tests for ContributionApprovedConsumer (US-2.24 / BR-LIB-P7/P12)."""
import pytest
from unittest.mock import MagicMock, call
from library_consumers import ContributionApprovedConsumer


def make_library_service():
    svc = MagicMock()
    svc.add_from_contribution = MagicMock()
    return svc


def make_envelope(contribution_id="con-1", add_to_library=True, **extra):
    payload = {
        "contributionId": contribution_id,
        "memberId": "usr-1",
        "memberName": "Alice",
        "addToLibrary": add_to_library,
        "libraryTitle": "Blog Post",
        "libraryDescription": "An AWS journey",
        "libraryFormat": "Link",
        "libraryTopics": ["aws"],
        "libraryUrl": "https://blog.example.com/post",
        **extra,
    }
    return {"id": f"evt-{contribution_id}", "detail-type": "ContributionApproved", "detail": payload}


class TestContributionApprovedConsumer:

    def test_add_to_library_true_creates_resource(self):
        svc = make_library_service()
        consumer = ContributionApprovedConsumer(svc)
        result = consumer.handle(make_envelope())
        svc.add_from_contribution.assert_called_once()
        assert result["added"] is True

    def test_add_to_library_false_is_ignored(self):
        svc = make_library_service()
        consumer = ContributionApprovedConsumer(svc)
        result = consumer.handle(make_envelope(add_to_library=False))
        svc.add_from_contribution.assert_not_called()
        assert result["ignored"] is True

    def test_missing_contribution_id_is_ignored(self):
        svc = make_library_service()
        consumer = ContributionApprovedConsumer(svc)
        result = consumer.handle({"detail": {"addToLibrary": True}})
        svc.add_from_contribution.assert_not_called()

    def test_idempotent_via_idempotency_store(self):
        svc = make_library_service()
        idem = MagicMock()
        called = []

        def run_once(key, fn):
            if key not in called:
                called.append(key)
                fn()

        idem.run_once = run_once
        consumer = ContributionApprovedConsumer(svc, idempotency=idem)
        envelope = make_envelope()
        consumer.handle(envelope)
        consumer.handle(envelope)  # redelivery
        # add_from_contribution called only once due to idempotency
        assert svc.add_from_contribution.call_count == 1

    def test_exception_in_service_does_not_propagate(self):
        svc = make_library_service()
        svc.add_from_contribution.side_effect = Exception("DynamoDB error")
        consumer = ContributionApprovedConsumer(svc)
        # Should not raise — fail silently (metric emitted instead)
        result = consumer.handle(make_envelope())
        assert result["added"] is False
