"""Who may shout out whom (US-13.1/13.2/13.11), and the canShoutout flag.

WHY THIS SUITE EXISTS
---------------------
Shoutouts had NO automated coverage at all — not even a route-table assertion —
while carrying a non-obvious authorisation rule. The UI guessed at that rule and
got it wrong in both directions:

  * the profile page keyed the button off the VIEWER's role being "Member", so a
    CL or UGL saw no button even though the backend explicitly allows them;
  * a Member viewing a LEADER's profile did get one, which always failed with
    "Shoutouts can only be sent to Members.";
  * the shoutouts-card button omitted the self check, so a member viewing their
    own profile was invited to shout themselves out.

The rule now lives in one place and is published as `canShoutout`. These tests
pin the predicate and the published flag together, because a flag that disagrees
with the enforcement is the whole failure mode.
"""
import pytest
from models import directory_row_public, profile_public
from shoutout_service import (
    can_send_shoutout,
    recipient_may_receive,
    sender_may_shout,
    ugl_in_scope,
)


class _P:
    def __init__(self, user_id, role, led_group_id=None):
        self.user_id = user_id
        self.role = role
        self.led_group_id = led_group_id


def _member(member_id="m1", role="Member", group_ids=("group-A",)):
    return {"id": member_id, "role": role,
            "groups": [{"groupId": g} for g in group_ids]}


class TestSenderMayShout:
    @pytest.mark.parametrize("role", ["CommunityLeader", "UserGroupLeader", "Member"])
    def test_allowed_roles(self, role):
        assert sender_may_shout(role) is True

    def test_administrator_cannot(self):
        # BR: Administrators do not participate in community recognition.
        assert sender_may_shout("Administrator") is False


class TestRecipientMayReceive:
    def test_members_can_receive(self):
        assert recipient_may_receive(_member(role="Member")) is True

    @pytest.mark.parametrize("role", ["CommunityLeader", "UserGroupLeader", "Administrator"])
    def test_leaders_and_admins_cannot_receive(self, role):
        """This is how "leaders recognise members, not each other" is actually
        implemented — as a property of the RECIPIENT, so it holds for every
        sender rather than only for leaders."""
        assert recipient_may_receive(_member(role=role)) is False

    def test_missing_role_defaults_to_member(self):
        # Older profile rows predate the role attribute.
        assert recipient_may_receive({"id": "m1"}) is True


class TestUglScope:
    def test_in_own_group(self):
        ugl = _P("ugl1", "UserGroupLeader", "group-A")
        assert ugl_in_scope(ugl, _member(group_ids=("group-A",))) is True

    def test_not_in_another_group(self):
        ugl = _P("ugl1", "UserGroupLeader", "group-A")
        assert ugl_in_scope(ugl, _member(group_ids=("group-B",))) is False

    def test_ugl_with_no_led_group_has_no_scope(self):
        # Fail closed rather than treating "no group" as "all groups".
        assert ugl_in_scope(_P("ugl1", "UserGroupLeader", None), _member()) is False

    def test_recipient_in_several_groups_one_of_which_matches(self):
        ugl = _P("ugl1", "UserGroupLeader", "group-B")
        assert ugl_in_scope(ugl, _member(group_ids=("group-A", "group-B"))) is True


class TestCanSendShoutout:
    """The combined verdict — what the UI actually renders from."""

    def test_member_to_another_member(self):
        assert can_send_shoutout(_P("m2", "Member"), _member("m1")) is True

    def test_community_leader_to_any_member_in_any_group(self):
        """THE REPORTED GAP: leaders were shown no button at all."""
        cl = _P("cl1", "CommunityLeader")
        assert can_send_shoutout(cl, _member("m1", group_ids=("group-Z",))) is True

    def test_ugl_only_within_led_group(self):
        ugl = _P("ugl1", "UserGroupLeader", "group-A")
        assert can_send_shoutout(ugl, _member("m1", group_ids=("group-A",))) is True
        assert can_send_shoutout(ugl, _member("m1", group_ids=("group-B",))) is False

    def test_nobody_may_shout_themselves_out(self):
        """The shoutouts-card button omitted this and offered it anyway."""
        assert can_send_shoutout(_P("m1", "Member"), _member("m1")) is False
        assert can_send_shoutout(_P("cl1", "CommunityLeader"), _member("cl1")) is False

    def test_no_one_may_shout_out_a_leader(self):
        cl_recipient = _member("cl9", role="CommunityLeader")
        assert can_send_shoutout(_P("m2", "Member"), cl_recipient) is False
        assert can_send_shoutout(_P("cl1", "CommunityLeader"), cl_recipient) is False

    def test_administrator_may_not_send(self):
        assert can_send_shoutout(_P("a1", "Administrator"), _member("m1")) is False

    def test_absent_recipient_is_false_not_an_exception(self):
        assert can_send_shoutout(_P("m2", "Member"), {}) is False
        assert can_send_shoutout(_P("m2", "Member"), None) is False


class TestPayloadsFailClosed:
    """A serializer call that omits the flag must HIDE the button."""

    def test_profile_defaults_to_false(self):
        assert profile_public(_member())["canShoutout"] is False

    def test_directory_row_defaults_to_false(self):
        assert directory_row_public(_member())["canShoutout"] is False

    def test_flag_is_carried_when_passed(self):
        assert profile_public(_member(), can_shoutout=True)["canShoutout"] is True
        assert directory_row_public(_member(), can_shoutout=True)["canShoutout"] is True


# --- end to end through ProfileService.get_member -----------------------------
# The predicate being right is not enough: the flag has to reach the payload the
# profile page actually reads. This is the seam the bug lived in.

from profile_service import ProfileService  # noqa: E402


def _seed_member(repo, member_id="m1", role="Member", group_ids=("group-A",)):
    repo.put_profile({"id": member_id, "firstName": "Alex", "lastName": "Morgan",
                      "email": f"{member_id}@x.com", "role": role, "status": "active",
                      "groups": [{"groupId": g} for g in group_ids]})


class TestGetMemberPublishesTheFlag:

    def test_leader_viewing_a_member_gets_the_button(self, repo, fan_out, events):
        """THE REPORTED REQUEST. A CL opening a member's profile must be offered
        the shoutout — the page used to require the viewer to be a Member."""
        _seed_member(repo)
        out = ProfileService(repo, fan_out, events).get_member(
            "m1", principal_role="CommunityLeader",
            principal=_P("cl1", "CommunityLeader"))
        assert out["canShoutout"] is True

    def test_member_viewing_another_member_gets_the_button(self, repo, fan_out, events):
        _seed_member(repo)
        out = ProfileService(repo, fan_out, events).get_member(
            "m1", principal_role="Member", principal=_P("m2", "Member"))
        assert out["canShoutout"] is True

    def test_viewing_your_own_profile_does_not(self, repo, fan_out, events):
        _seed_member(repo, "m1")
        out = ProfileService(repo, fan_out, events).get_member(
            "m1", principal_role="Member", principal=_P("m1", "Member"))
        assert out["canShoutout"] is False

    def test_viewing_a_leaders_profile_does_not(self, repo, fan_out, events):
        """A member looking at a CL's profile was offered a button that always
        failed with "Shoutouts can only be sent to Members."."""
        _seed_member(repo, "cl9", role="CommunityLeader")
        out = ProfileService(repo, fan_out, events).get_member(
            "cl9", principal_role="Member", principal=_P("m2", "Member"))
        assert out["canShoutout"] is False

    def test_ugl_viewing_a_member_outside_their_group_does_not(self, repo, fan_out, events):
        _seed_member(repo, "m1", group_ids=("group-B",))
        out = ProfileService(repo, fan_out, events).get_member(
            "m1", principal_role="UserGroupLeader",
            principal=_P("ugl1", "UserGroupLeader", "group-A"))
        assert out["canShoutout"] is False

    def test_omitting_the_principal_fails_closed(self, repo, fan_out, events):
        """Older callers that pass only principal_role must not accidentally
        enable the button."""
        _seed_member(repo)
        out = ProfileService(repo, fan_out, events).get_member(
            "m1", principal_role="CommunityLeader")
        assert out["canShoutout"] is False
