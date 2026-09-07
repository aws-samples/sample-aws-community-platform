"""ActivityService tests — US-3.10 leader-only detailed activity summary,
scoping (BR-4/13) and the degrade-path suite (NFR-MP-MAINT-1)."""
import pytest
from _conventions.errors import ForbiddenError, NotFoundError
from activity_service import ActivityService


def _seed_member(repo, member_id="u1", group_id="g1"):
    repo.put_profile({"id": member_id, "firstName": "A", "lastName": "B", "role": "Member",
                      "status": "active", "groups": [{"groupId": group_id, "joinedAt": "2026-01-01"}]})


def test_community_leader_can_view_any_member(repo, fan_out):
    _seed_member(repo)
    fan_out.responses = {"events": {"items": []}, "forums": {"items": []},
                         "certifications": {"items": []}, "contributions": {"points": 10, "lifetimePoints": 50}}
    svc = ActivityService(repo, fan_out)
    out = svc.get_activity("u1", principal_role="CommunityLeader", principal_led_group_id=None)
    assert out["points"]["currentQuarter"] == 10
    assert out["points"]["lifetime"] == 50


def test_administrator_forbidden(repo, fan_out):
    """BR-4."""
    _seed_member(repo)
    svc = ActivityService(repo, fan_out)
    with pytest.raises(ForbiddenError):
        svc.get_activity("u1", principal_role="Administrator", principal_led_group_id=None)


def test_member_forbidden_even_for_self(repo, fan_out):
    """BR-13 — a member's own basic counts come from getOwnProfile, not this endpoint."""
    _seed_member(repo)
    svc = ActivityService(repo, fan_out)
    with pytest.raises(ForbiddenError):
        svc.get_activity("u1", principal_role="Member", principal_led_group_id=None)


def test_ugl_scoped_to_own_led_group(repo, fan_out):
    """BR-13 — UGL may view only members of the group they lead."""
    _seed_member(repo, member_id="u1", group_id="g1")
    fan_out.responses = {"events": {"items": []}, "forums": {"items": []},
                         "certifications": {"items": []}, "contributions": {}}
    svc = ActivityService(repo, fan_out)
    # Same group as principal leads -> allowed.
    svc.get_activity("u1", principal_role="UserGroupLeader", principal_led_group_id="g1")
    # Different group -> forbidden.
    with pytest.raises(ForbiddenError):
        svc.get_activity("u1", principal_role="UserGroupLeader", principal_led_group_id="g2")


def test_not_found_for_missing_member(repo, fan_out):
    svc = ActivityService(repo, fan_out)
    with pytest.raises(NotFoundError):
        svc.get_activity("nope", principal_role="CommunityLeader", principal_led_group_id=None)


def test_degrades_gracefully_when_all_fan_out_fails(repo, fan_out):
    """NFR-MP-MAINT-1 — simulated downstream failure across all 4 targets ->
    still returns 200-equivalent (no exception), with empty/zeroed sections."""
    _seed_member(repo)
    fan_out.failing = {"events", "forums", "certifications", "contributions"}
    svc = ActivityService(repo, fan_out)
    out = svc.get_activity("u1", principal_role="CommunityLeader", principal_led_group_id=None)
    assert out["items"] == []
    assert out["points"] == {"currentQuarter": 0, "lifetime": 0}
