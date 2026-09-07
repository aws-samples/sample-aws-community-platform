"""BR-5 capability flags, and reply edit/delete.

WHY THIS SUITE EXISTS
---------------------
The server always enforced BR-5 correctly, but the UI hard-coded Edit and Delete
as unconditionally visible, so every member was offered both on everyone else's
posts and replies and only discovered otherwise from a 403 after clicking. The
post author was even offered Delete on other members' replies.

The fix makes the SERVER decide and publish `canEdit` / `canDelete`, so there is
one rule rather than a duplicated client-side guess. These tests pin the rule and
the published flags together — a flag that disagrees with the guard is the whole
failure mode being prevented.

Reply edit/delete were 501 stubs at the same time, so even the author of a reply
could not delete it. They are implemented here and tested.
"""
import pytest
from app import dispatch
from authz import can_delete, can_edit
from conftest import proxy_event
from models import serialize_post, serialize_reply


class _P:
    """Minimal Principal stand-in — the capability helpers read only these."""
    def __init__(self, user_id, role, led_group_id=None):
        self.user_id = user_id
        self.role = role
        self.led_group_id = led_group_id


ITEM = {"authorId": "author-1", "groupId": "group-A"}


class TestCanEdit:
    """BR-5 edit half: author ONLY."""

    def test_author_may_edit(self):
        assert can_edit(_P("author-1", "Member"), ITEM) is True

    def test_another_member_may_not_edit(self):
        # THE REPORTED BUG. This returning True is what the UI effectively assumed.
        assert can_edit(_P("member-2", "Member"), ITEM) is False

    @pytest.mark.parametrize("role,led", [
        ("CommunityLeader", None),
        ("UserGroupLeader", "group-A"),
    ])
    def test_leaders_may_not_edit_someone_elses_content(self, role, led):
        """Deliberate asymmetry with delete: moderating is removing, not rewording."""
        assert can_edit(_P("leader-1", role, led), ITEM) is False

    def test_administrator_never(self):
        # BR-1: Administrators have no forum access at all.
        assert can_edit(_P("author-1", "Administrator"), ITEM) is False


class TestCanDelete:
    """BR-5 delete half: author OR leader in scope."""

    def test_author_may_delete(self):
        assert can_delete(_P("author-1", "Member"), ITEM) is True

    def test_another_member_may_not_delete(self):
        assert can_delete(_P("member-2", "Member"), ITEM) is False

    def test_community_leader_may_delete_any_group(self):
        assert can_delete(_P("cl1", "CommunityLeader"), ITEM) is True

    def test_ugl_may_delete_in_own_group_only(self):
        assert can_delete(_P("ugl1", "UserGroupLeader", "group-A"), ITEM) is True
        assert can_delete(_P("ugl1", "UserGroupLeader", "group-B"), ITEM) is False

    def test_administrator_never(self):
        assert can_delete(_P("author-1", "Administrator"), ITEM) is False


class TestSerializersFailClosed:
    """A call site that forgets to pass the flags must HIDE the buttons.

    False is the safe direction to be wrong: a hidden button on content you own
    is a nuisance, a visible button on content you don't is the bug being fixed.
    """

    def test_post_defaults_to_no_capabilities(self):
        out = serialize_post({"postId": "p1"})
        assert out["canEdit"] is False
        assert out["canDelete"] is False

    def test_reply_defaults_to_no_capabilities(self):
        out = serialize_reply({"replyId": "r1"})
        assert out["canEdit"] is False
        assert out["canDelete"] is False


def _seed_thread(ctx, *, post_author="member-1", reply_author="member-2"):
    """CL creates a forum+channel in group-A; `post_author` posts; `reply_author`
    replies. Returns (post_id, reply_id)."""
    r = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                             body={"name": "F", "groupId": "group-A"}), ctx)
    forum_id = __import__("json").loads(r["body"])["id"]
    r = dispatch(proxy_event("POST", f"/forums/{forum_id}/channels", role="CommunityLeader",
                             sub="cl1", body={"name": "General"}), ctx)
    channel_id = __import__("json").loads(r["body"])["id"]
    r = dispatch(proxy_event("POST", f"/channels/{channel_id}/posts", role="Member",
                             sub=post_author, groups=["group-A"],
                             body={"title": "T", "body": "B"}), ctx)
    assert r["statusCode"] == 201, r["body"]
    post_id = __import__("json").loads(r["body"])["id"]
    r = dispatch(proxy_event("POST", f"/posts/{post_id}/replies", role="Member",
                             sub=reply_author, groups=["group-A"],
                             body={"body": "An answer."}), ctx)
    assert r["statusCode"] == 201, r["body"]
    reply_id = __import__("json").loads(r["body"])["id"]
    return post_id, reply_id


def _thread(ctx, post_id, *, sub, role="Member", led=None):
    import json
    r = dispatch(proxy_event("GET", f"/posts/{post_id}", role=role, sub=sub,
                             groups=["group-A"], led=led), ctx)
    assert r["statusCode"] == 200, r["body"]
    return json.loads(r["body"])


class TestThreadPublishesPerViewerFlags:
    """The exact scenario from the bug report."""

    def test_post_author_gets_edit_and_delete_on_their_own_post(self, ctx):
        post_id, _ = _seed_thread(ctx)
        body = _thread(ctx, post_id, sub="member-1")
        assert body["post"]["canEdit"] is True
        assert body["post"]["canDelete"] is True

    def test_other_member_gets_neither_on_someone_elses_post(self, ctx):
        post_id, _ = _seed_thread(ctx)
        body = _thread(ctx, post_id, sub="member-9")
        assert body["post"]["canEdit"] is False
        assert body["post"]["canDelete"] is False

    def test_post_author_cannot_delete_another_members_reply(self, ctx):
        """THE REPORTED CASE. Member Two owns the post, Member One wrote the
        reply. Member Two was shown Delete on it."""
        post_id, _ = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        body = _thread(ctx, post_id, sub="member-2")
        reply = body["replies"]["items"][0]
        assert reply["canDelete"] is False
        assert reply["canEdit"] is False
        # ...while still being able to accept it, which is the post author's right.
        assert body["post"]["canAccept"] is True

    def test_reply_author_gets_delete_on_their_own_reply(self, ctx):
        post_id, _ = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        body = _thread(ctx, post_id, sub="member-1")
        reply = body["replies"]["items"][0]
        assert reply["canDelete"] is True
        assert reply["canEdit"] is True
        # ...but no rights over the post itself, which member-2 wrote.
        assert body["post"]["canDelete"] is False

    def test_flags_are_per_reply_not_per_thread(self, ctx):
        """Two replies by different authors must not share one verdict."""
        post_id, _ = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        dispatch(proxy_event("POST", f"/posts/{post_id}/replies", role="Member",
                             sub="member-3", groups=["group-A"],
                             body={"body": "Another."}), ctx)
        body = _thread(ctx, post_id, sub="member-1")
        by_author = {r["authorId"]: r["canDelete"] for r in body["replies"]["items"]}
        assert by_author == {"member-1": True, "member-3": False}

    def test_ugl_of_the_group_may_delete_but_not_edit(self, ctx):
        post_id, _ = _seed_thread(ctx)
        body = _thread(ctx, post_id, sub="ugl1", role="UserGroupLeader", led="group-A")
        assert body["post"]["canDelete"] is True
        assert body["post"]["canEdit"] is False


class TestDeleteReply:
    """Was a 501 stub for EVERYONE, so the author could not delete their own reply."""

    def test_author_can_delete_their_reply(self, ctx):
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        r = dispatch(proxy_event("DELETE", f"/replies/{reply_id}", role="Member",
                                 sub="member-1", groups=["group-A"],
                                 qs={"postId": post_id}), ctx)
        assert r["statusCode"] == 204, r["body"]
        # Gone from the thread, and the count went with it.
        body = _thread(ctx, post_id, sub="member-1")
        assert body["replies"]["items"] == []
        assert body["post"]["replyCount"] == 0

    def test_another_member_cannot(self, ctx):
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        r = dispatch(proxy_event("DELETE", f"/replies/{reply_id}", role="Member",
                                 sub="member-9", groups=["group-A"],
                                 qs={"postId": post_id}), ctx)
        assert r["statusCode"] == 403

    def test_post_author_cannot_delete_someone_elses_reply(self, ctx):
        """Server-side counterpart of the hidden button."""
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        r = dispatch(proxy_event("DELETE", f"/replies/{reply_id}", role="Member",
                                 sub="member-2", groups=["group-A"],
                                 qs={"postId": post_id}), ctx)
        assert r["statusCode"] == 403

    def test_ugl_of_the_group_can(self, ctx):
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        r = dispatch(proxy_event("DELETE", f"/replies/{reply_id}", role="UserGroupLeader",
                                 sub="ugl1", groups=["group-A"], led="group-A",
                                 qs={"postId": post_id}), ctx)
        assert r["statusCode"] == 204, r["body"]

    def test_missing_postid_is_a_400_not_a_501(self, ctx):
        post_id, reply_id = _seed_thread(ctx)
        r = dispatch(proxy_event("DELETE", f"/replies/{reply_id}", role="Member",
                                 sub="member-2", groups=["group-A"]), ctx)
        assert r["statusCode"] == 400

    def test_a_forged_postid_cannot_reach_the_reply(self, ctx):
        """postId comes from the caller, so this is the security-relevant case:
        the reply is read UNDER the supplied post, so a wrong parent finds
        nothing rather than deleting across a boundary."""
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        other_post_id, _ = _seed_thread(ctx, post_author="member-2", reply_author="member-3")
        r = dispatch(proxy_event("DELETE", f"/replies/{reply_id}", role="Member",
                                 sub="member-1", groups=["group-A"],
                                 qs={"postId": other_post_id}), ctx)
        assert r["statusCode"] == 404
        # And the real reply survived.
        body = _thread(ctx, post_id, sub="member-1")
        assert len(body["replies"]["items"]) == 1

    def test_deleting_the_accepted_answer_clears_the_badge(self, ctx):
        """Otherwise the post stays marked answered with no visible answer."""
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        r = dispatch(proxy_event("POST", f"/posts/{post_id}/accept", role="Member",
                                 sub="member-2", groups=["group-A"],
                                 body={"replyId": reply_id}), ctx)
        assert r["statusCode"] == 200, r["body"]
        assert _thread(ctx, post_id, sub="member-2")["post"]["acceptedReplyId"] == reply_id
        r = dispatch(proxy_event("DELETE", f"/replies/{reply_id}", role="Member",
                                 sub="member-1", groups=["group-A"],
                                 qs={"postId": post_id}), ctx)
        assert r["statusCode"] == 204, r["body"]
        assert _thread(ctx, post_id, sub="member-2")["post"]["acceptedReplyId"] is None

    def test_deleting_twice_is_a_404(self, ctx):
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        ev = proxy_event("DELETE", f"/replies/{reply_id}", role="Member", sub="member-1",
                        groups=["group-A"], qs={"postId": post_id})
        assert dispatch(ev, ctx)["statusCode"] == 204
        # Not another 204 — the second call must not decrement replyCount again.
        assert dispatch(ev, ctx)["statusCode"] == 404


class TestEditReply:
    """Also a 501 stub. Author only, per BR-5."""

    def test_author_can_edit_and_it_is_marked_edited(self, ctx):
        import json
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        r = dispatch(proxy_event("PUT", f"/replies/{reply_id}", role="Member",
                                 sub="member-1", groups=["group-A"],
                                 qs={"postId": post_id}, body={"body": "Reworded."}), ctx)
        assert r["statusCode"] == 200, r["body"]
        out = json.loads(r["body"])
        assert out["body"] == "Reworded."
        assert out["edited"] is True

    def test_a_leader_may_delete_but_not_edit(self, ctx):
        """The asymmetry, end to end."""
        post_id, reply_id = _seed_thread(ctx, post_author="member-2", reply_author="member-1")
        r = dispatch(proxy_event("PUT", f"/replies/{reply_id}", role="CommunityLeader",
                                 sub="cl1", qs={"postId": post_id},
                                 body={"body": "Rewritten by a leader."}), ctx)
        assert r["statusCode"] == 403
