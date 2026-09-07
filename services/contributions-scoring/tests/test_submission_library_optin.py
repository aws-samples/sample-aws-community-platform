"""Tests for Library opt-in at contribution approval (US-2.24 / BR-LIB-P7)."""
import pytest
from unittest.mock import MagicMock, call


def _make_service():
    from submission_service import SubmissionService
    repo = MagicMock()
    framework = MagicMock()
    framework.activity.return_value = {"points": 25}
    publisher = MagicMock()
    svc = SubmissionService(repo, framework, publisher=publisher)
    return svc, repo, framework, publisher


def _pending_sub(submission_id="sub-1"):
    from models import SUB_PENDING
    return {
        "submissionId": submission_id,
        "memberId": "usr-m1",
        "memberName": "Alice",
        "groupId": "g-1",
        "activity": "Blog Post",
        "activityId": "act-1",
        "pillar": 3,
        "status": SUB_PENDING,
        "submittedAt": "2026-08-01T10:00:00Z",
    }


def _cl():
    p = MagicMock()
    p.role = "CommunityLeader"
    p.user_id = "usr-cl"
    p.name = "CL Bob"
    p.led_group_id = None
    return p


class TestSubmissionLibraryOptIn:

    def test_approve_with_add_to_library_true_publishes_contribution_approved(self):
        svc, repo, _, publisher = _make_service()
        repo.get_submission.return_value = _pending_sub()
        repo.transition_submission = MagicMock()
        repo.append_ledger = MagicMock()

        svc.decide("sub-1", {
            "decision": "approve",
            "addToLibrary": True,
            "libraryTitle": "My Blog",
            "libraryDescription": "An AWS story",
            "libraryFormat": "Link",
            "libraryTopics": ["aws", "serverless"],
            "libraryUrl": "https://blog.example.com",
        }, principal=_cl())

        # Should publish both PointsAwarded and ContributionApproved
        calls = [c[0][0] for c in publisher.publish.call_args_list]
        assert "PointsAwarded" in calls
        assert "ContributionApproved" in calls

    def test_contribution_approved_payload_contains_library_fields(self):
        svc, repo, _, publisher = _make_service()
        repo.get_submission.return_value = _pending_sub()
        repo.transition_submission = MagicMock()
        repo.append_ledger = MagicMock()

        svc.decide("sub-1", {
            "decision": "approve",
            "addToLibrary": True,
            "libraryTitle": "My Blog",
            "libraryDescription": "An AWS story",
            "libraryFormat": "Link",
            "libraryTopics": ["aws"],
            "libraryUrl": "https://blog.example.com",
        }, principal=_cl())

        contrib_approved_call = next(
            c for c in publisher.publish.call_args_list
            if c[0][0] == "ContributionApproved"
        )
        payload = contrib_approved_call[0][1]
        assert payload["addToLibrary"] is True
        assert payload["libraryTitle"] == "My Blog"
        assert payload["libraryDescription"] == "An AWS story"
        assert payload["memberId"] == "usr-m1"
        assert payload["approverId"] == "usr-cl"

    def test_approve_without_opt_in_publishes_add_to_library_false(self):
        svc, repo, _, publisher = _make_service()
        repo.get_submission.return_value = _pending_sub()
        repo.transition_submission = MagicMock()
        repo.append_ledger = MagicMock()

        svc.decide("sub-1", {"decision": "approve"}, principal=_cl())

        contrib_approved_call = next(
            (c for c in publisher.publish.call_args_list
             if c[0][0] == "ContributionApproved"), None
        )
        assert contrib_approved_call is not None
        payload = contrib_approved_call[0][1]
        assert payload["addToLibrary"] is False

    def test_points_awarded_still_published_regardless_of_library_opt_in(self):
        svc, repo, _, publisher = _make_service()
        repo.get_submission.return_value = _pending_sub()
        repo.transition_submission = MagicMock()
        repo.append_ledger = MagicMock()

        svc.decide("sub-1", {
            "decision": "approve",
            "addToLibrary": True,
            "libraryTitle": "T", "libraryDescription": "D",
            "libraryFormat": "Link", "libraryUrl": "https://x.com",
        }, principal=_cl())

        calls = [c[0][0] for c in publisher.publish.call_args_list]
        assert "PointsAwarded" in calls

    def test_reject_does_not_publish_contribution_approved(self):
        svc, repo, _, publisher = _make_service()
        repo.get_submission.return_value = _pending_sub()
        repo.transition_submission = MagicMock()

        svc.decide("sub-1", {"decision": "reject", "reason": "Not relevant"}, principal=_cl())

        calls = [c[0][0] for c in publisher.publish.call_args_list]
        assert "ContributionApproved" not in calls
        assert "ContributionRejected" in calls
