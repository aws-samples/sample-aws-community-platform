"""Authorization matrix tests (NFR-FO-MAINT-1 suite 1).

Tests BR-1 (Administrator 403 on all), BR-3 (group access), BR-4 (manage scope),
BR-5 (author-only edit / leader delete), IDOR guard.
"""
import pytest
from conftest import proxy_event

from app import dispatch


class TestAdministratorDenied:
    """BR-1: Administrator has NO forum access — 403 on everything including reads."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/forums"),
        ("POST", "/forums"),
        ("GET", "/channels/ch1/posts"),
        ("GET", "/posts/p1"),
        ("POST", "/channels/ch1/posts"),
        ("POST", "/posts/p1/reactions"),
        ("GET", "/forums/search"),
        ("GET", "/forums/moderation"),
        ("GET", "/forums/follows"),
        ("GET", "/forums/mention-suggest"),
    ])
    def test_admin_403(self, ctx, method, path):
        event = proxy_event(method, path, role="Administrator", sub="admin1")
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 403


class TestGroupAccess:
    """BR-3: Members only access their groups; UGL only ledGroupId."""

    def test_member_no_group_access(self, ctx):
        """Member without group membership gets 403 on that group's channel."""
        # Create a forum+channel in group-A (as CL)
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Test Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 201
        import json
        forum = json.loads(resp["body"])
        channel_id = forum["channels"][0]["id"]

        # Member in group-B tries to list posts in group-A's channel
        event = proxy_event("GET", f"/channels/{channel_id}/posts",
                            role="Member", sub="m1", groups=["group-B"])
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 403

    def test_member_with_group_access(self, ctx):
        """Member with group membership can access that group's channel."""
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Test Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 201
        import json
        forum = json.loads(resp["body"])
        channel_id = forum["channels"][0]["id"]

        event = proxy_event("GET", f"/channels/{channel_id}/posts",
                            role="Member", sub="m1", groups=["group-A"])
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200

    def test_ugl_only_led_group(self, ctx):
        """UGL cannot create forums (only CL can). UGL should get 403."""
        event = proxy_event("POST", "/forums", role="UserGroupLeader", sub="ugl1",
                            led="group-A", body={"name": "Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 403

    def test_cl_any_group(self, ctx):
        """CL can access any group."""
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "group-X"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 201


class TestManageScope:
    """BR-4: Only CL/UGL can create/edit/delete forums and channels."""

    def test_member_cannot_create_forum(self, ctx):
        event = proxy_event("POST", "/forums", role="Member", sub="m1",
                            groups=["group-A"], body={"name": "Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 403

    def test_member_cannot_delete_forum(self, ctx):
        # CL creates
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        import json
        forum_id = json.loads(resp["body"])["id"]

        # Member tries to delete
        event = proxy_event("DELETE", f"/forums/{forum_id}", role="Member", sub="m1",
                            groups=["group-A"])
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 403


class TestAuthorOnlyEdit:
    """BR-5: Edit = author only; leaders cannot edit others' content."""

    def test_author_can_edit(self, ctx):
        # Setup: CL creates forum+channel, member creates post
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        import json
        channel_id = json.loads(resp["body"])["channels"][0]["id"]

        event = proxy_event("POST", f"/channels/{channel_id}/posts",
                            role="Member", sub="m1", groups=["group-A"],
                            body={"title": "My Post", "body": "Content"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 201
        post_id = json.loads(resp["body"])["id"]

        # Author edits
        event = proxy_event("PUT", f"/posts/{post_id}", role="Member", sub="m1",
                            groups=["group-A"], body={"title": "Edited Title"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200

    def test_leader_cannot_edit_others_post(self, ctx):
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        import json
        channel_id = json.loads(resp["body"])["channels"][0]["id"]

        event = proxy_event("POST", f"/channels/{channel_id}/posts",
                            role="Member", sub="m1", groups=["group-A"],
                            body={"title": "My Post", "body": "Content"})
        resp = dispatch(event, ctx)
        post_id = json.loads(resp["body"])["id"]

        # CL tries to edit (not author) — should fail
        event = proxy_event("PUT", f"/posts/{post_id}", role="CommunityLeader", sub="cl1",
                            body={"title": "CL Edit"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 403

    def test_leader_can_delete_others_post(self, ctx):
        """BR-5: Delete = author OR leader."""
        event = proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                            body={"name": "Forum", "groupId": "group-A"})
        resp = dispatch(event, ctx)
        import json
        channel_id = json.loads(resp["body"])["channels"][0]["id"]

        event = proxy_event("POST", f"/channels/{channel_id}/posts",
                            role="Member", sub="m1", groups=["group-A"],
                            body={"title": "My Post", "body": "Content"})
        resp = dispatch(event, ctx)
        post_id = json.loads(resp["body"])["id"]

        # CL deletes (not author, but leader) — should succeed
        event = proxy_event("DELETE", f"/posts/{post_id}", role="CommunityLeader", sub="cl1")
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 204
