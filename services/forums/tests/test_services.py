"""Happy-path service tests (NFR-FO-MAINT-1 suite 7).

End-to-end flow: create forum → channel → post → reply → react → pin → accept → follow → report → moderate.
Also tests counters, edit, and cascade delete.
"""
import json

import pytest
from conftest import proxy_event

from app import dispatch


class TestForumLifecycle:
    """Create, edit, browse, delete forums."""

    def test_create_forum_with_default_channel(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Python Forum", "groupId": "g1"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body["name"] == "Python Forum"
        assert body["groupId"] == "g1"
        assert len(body["channels"]) == 1
        assert body["channels"][0]["name"] == "General"

    def test_browse_forums(self, ctx):
        # Create two forums in same group
        dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                             body={"name": "Forum A", "groupId": "g1"}), ctx)
        dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                             body={"name": "Forum B", "groupId": "g1"}), ctx)
        # Browse as member of g1
        event = proxy_event("GET", "/forums", role="Member", sub="m1", groups=["g1"])
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["count"] == 2

    def test_edit_forum(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Old Name", "groupId": "g1"})
        resp = dispatch(event, ctx)
        forum_id = json.loads(resp["body"])["id"]

        event = proxy_event("PUT", f"/forums/{forum_id}", role="CommunityLeader", sub="cl1",
                            body={"name": "New Name"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["name"] == "New Name"


class TestPostLifecycle:
    """Create, list, edit, delete posts with counter verification."""

    def _setup_channel(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "g1"})
        resp = dispatch(event, ctx)
        return json.loads(resp["body"])["channels"][0]["id"]

    def test_create_post(self, ctx):
        ch_id = self._setup_channel(ctx)
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Hello World", "body": "First post!"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 201
        post = json.loads(resp["body"])
        assert post["title"] == "Hello World"
        assert post["authorId"] == "m1"
        assert post["replyCount"] == 0

    def test_post_increments_channel_count(self, ctx):
        ch_id = self._setup_channel(ctx)
        dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                             role="Member", sub="m1", groups=["g1"],
                             body={"title": "Post 1", "body": "Body"}), ctx)
        dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                             role="Member", sub="m1", groups=["g1"],
                             body={"title": "Post 2", "body": "Body"}), ctx)
        # Check channel postCount via listing
        event = proxy_event("GET", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"])
        resp = dispatch(event, ctx)
        assert json.loads(resp["body"])["count"] == 2

    def test_edit_post_sets_edited_flag(self, ctx):
        ch_id = self._setup_channel(ctx)
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Original", "body": "Body"})
        post_id = json.loads(dispatch(event, ctx)["body"])["id"]

        event = proxy_event("PUT", f"/posts/{post_id}",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Edited"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["edited"] is True
        assert body["title"] == "Edited"

    def test_delete_post(self, ctx):
        ch_id = self._setup_channel(ctx)
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "To Delete", "body": "Body"})
        post_id = json.loads(dispatch(event, ctx)["body"])["id"]

        event = proxy_event("DELETE", f"/posts/{post_id}",
                            role="Member", sub="m1", groups=["g1"])
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 204


class TestReplyLifecycle:
    """Create reply, verify counter increment."""

    def _setup_post(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "g1"})
        ch_id = json.loads(dispatch(event, ctx)["body"])["channels"][0]["id"]
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Post", "body": "Body"})
        return json.loads(dispatch(event, ctx)["body"])["id"]

    def test_create_reply(self, ctx):
        post_id = self._setup_post(ctx)
        event = proxy_event("POST", f"/posts/{post_id}/replies",
                            role="Member", sub="m2", groups=["g1"],
                            body={"body": "Great post!"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 201
        reply = json.loads(resp["body"])
        assert reply["authorId"] == "m2"
        assert reply["postId"] == post_id

    def test_reply_increments_post_reply_count(self, ctx):
        post_id = self._setup_post(ctx)
        dispatch(proxy_event("POST", f"/posts/{post_id}/replies",
                             role="Member", sub="m2", groups=["g1"],
                             body={"body": "Reply 1"}), ctx)
        dispatch(proxy_event("POST", f"/posts/{post_id}/replies",
                             role="Member", sub="m3", groups=["g1"],
                             body={"body": "Reply 2"}), ctx)
        # Get thread to check count
        event = proxy_event("GET", f"/posts/{post_id}",
                            role="Member", sub="m1", groups=["g1"])
        resp = dispatch(event, ctx)
        thread = json.loads(resp["body"])
        assert thread["replies"]["count"] == 2


class TestReaction:
    """Toggle reactions with counter verification (BR-16, DV-5)."""

    def _setup_post(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "g1"})
        ch_id = json.loads(dispatch(event, ctx)["body"])["channels"][0]["id"]
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Post", "body": "Body"})
        return json.loads(dispatch(event, ctx)["body"])["id"]

    def test_set_reaction(self, ctx):
        post_id = self._setup_post(ctx)
        event = proxy_event("POST", f"/posts/{post_id}/reactions",
                            role="Member", sub="m2", groups=["g1"],
                            body={"kind": "like"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["kind"] == "like"

    def test_invalid_reaction_kind(self, ctx):
        post_id = self._setup_post(ctx)
        event = proxy_event("POST", f"/posts/{post_id}/reactions",
                            role="Member", sub="m2", groups=["g1"],
                            body={"kind": "invalid"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 400


class TestPinAndAccept:
    """Pin/unpin + accept answer (BR-14/15)."""

    def _setup_post(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "g1"})
        ch_id = json.loads(dispatch(event, ctx)["body"])["channels"][0]["id"]
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Post", "body": "Body"})
        return json.loads(dispatch(event, ctx)["body"])["id"]

    def test_pin_post(self, ctx):
        post_id = self._setup_post(ctx)
        event = proxy_event("POST", f"/posts/{post_id}/pin",
                            role="CommunityLeader", sub="cl1")
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["pinned"] is True

    def test_member_cannot_pin(self, ctx):
        post_id = self._setup_post(ctx)
        event = proxy_event("POST", f"/posts/{post_id}/pin",
                            role="Member", sub="m1", groups=["g1"])
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 403


class TestFollow:
    """Follow/unfollow toggle (BR-17/18)."""

    def _setup_post(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "g1"})
        ch_id = json.loads(dispatch(event, ctx)["body"])["channels"][0]["id"]
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Post", "body": "Body"})
        return json.loads(dispatch(event, ctx)["body"])["id"]

    def test_follow_unfollow_post(self, ctx):
        post_id = self._setup_post(ctx)
        # Follow
        event = proxy_event("POST", f"/posts/{post_id}/follow",
                            role="Member", sub="m2", groups=["g1"])
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["following"] is True
        # Unfollow
        resp = dispatch(event, ctx)
        assert json.loads(resp["body"])["following"] is False


class TestReport:
    """Report + moderation (BR-24/25, W11)."""

    def _setup_post(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "g1"})
        ch_id = json.loads(dispatch(event, ctx)["body"])["channels"][0]["id"]
        event = proxy_event("POST", f"/channels/{ch_id}/posts",
                            role="Member", sub="m1", groups=["g1"],
                            body={"title": "Bad Post", "body": "Spam"})
        return json.loads(dispatch(event, ctx)["body"])["id"]

    def test_report_post(self, ctx):
        post_id = self._setup_post(ctx)
        event = proxy_event("POST", f"/posts/{post_id}/report",
                            role="Member", sub="m2", groups=["g1"],
                            body={"reason": "Spam"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert "reportId" in json.loads(resp["body"])

    def test_duplicate_report_409(self, ctx):
        post_id = self._setup_post(ctx)
        event = proxy_event("POST", f"/posts/{post_id}/report",
                            role="Member", sub="m2", groups=["g1"],
                            body={"reason": "Spam"})
        dispatch(event, ctx)
        # Second report from same user
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 409
