"""Rate limiting tests (NFR-FO-MAINT-1 suite 3).

Tests per-user post/reply cap, mention cap (>25 → 400), report dedupe (→ 409).
"""
import json

import pytest
from conftest import proxy_event

from app import dispatch


class TestPostRateLimit:
    """Per-user post creation rate limit."""

    def _setup_channel(self, ctx):
        resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                                    body={"name": "Forum", "groupId": "g1"}), ctx)
        return json.loads(resp["body"])["channels"][0]["id"]

    def test_rate_limit_enforced(self, ctx):
        """After RATE_LIMIT_POST_PER_HOUR posts, next one returns 429."""
        ch_id = self._setup_channel(ctx)
        # Create 10 posts (the limit)
        for i in range(10):
            resp = dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                                        role="Member", sub="m1", groups=["g1"],
                                        body={"title": f"Post {i}", "body": "Body"}), ctx)
            assert resp["statusCode"] == 201, f"Post {i} failed: {resp['statusCode']}"

        # 11th post should be rate-limited
        resp = dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                                    role="Member", sub="m1", groups=["g1"],
                                    body={"title": "Over limit", "body": "Body"}), ctx)
        assert resp["statusCode"] == 429

    def test_different_user_not_affected(self, ctx):
        """Rate limit is per-user; another user is unaffected."""
        ch_id = self._setup_channel(ctx)
        # m1 exhausts their limit
        for i in range(10):
            dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                                 role="Member", sub="m1", groups=["g1"],
                                 body={"title": f"Post {i}", "body": "Body"}), ctx)
        # m2 can still post
        resp = dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                                    role="Member", sub="m2", groups=["g1"],
                                    body={"title": "m2 post", "body": "Body"}), ctx)
        assert resp["statusCode"] == 201


class TestMentionCap:
    """Mention cap: >25 mentions → 400."""

    def _setup_channel(self, ctx):
        resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                                    body={"name": "Forum", "groupId": "g1"}), ctx)
        return json.loads(resp["body"])["channels"][0]["id"]

    def test_over_25_mentions_rejected(self, ctx):
        ch_id = self._setup_channel(ctx)
        mentions = [f"user{i}" for i in range(26)]
        resp = dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                                    role="Member", sub="m1", groups=["g1"],
                                    body={"title": "Spam", "body": "Body", "mentions": mentions}), ctx)
        assert resp["statusCode"] == 400
        assert "25" in json.loads(resp["body"])["message"]

    def test_25_mentions_allowed(self, ctx):
        ch_id = self._setup_channel(ctx)
        mentions = [f"user{i}" for i in range(25)]
        resp = dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                                    role="Member", sub="m1", groups=["g1"],
                                    body={"title": "OK", "body": "Body", "mentions": mentions}), ctx)
        assert resp["statusCode"] == 201


class TestReportDedupe:
    """Report deduplication: same reporter + same target → 409."""

    def _setup_post(self, ctx):
        resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                                    body={"name": "Forum", "groupId": "g1"}), ctx)
        ch_id = json.loads(resp["body"])["channels"][0]["id"]
        resp = dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                                    role="Member", sub="m1", groups=["g1"],
                                    body={"title": "Post", "body": "Body"}), ctx)
        return json.loads(resp["body"])["id"]

    def test_first_report_succeeds(self, ctx):
        post_id = self._setup_post(ctx)
        resp = dispatch(proxy_event("POST", f"/posts/{post_id}/report",
                                    role="Member", sub="m2", groups=["g1"],
                                    body={"reason": "Spam"}), ctx)
        assert resp["statusCode"] == 200

    def test_duplicate_report_409(self, ctx):
        post_id = self._setup_post(ctx)
        dispatch(proxy_event("POST", f"/posts/{post_id}/report",
                             role="Member", sub="m2", groups=["g1"],
                             body={"reason": "Spam"}), ctx)
        # Second report from same user
        resp = dispatch(proxy_event("POST", f"/posts/{post_id}/report",
                                    role="Member", sub="m2", groups=["g1"],
                                    body={"reason": "Spam again"}), ctx)
        assert resp["statusCode"] == 409

    def test_different_reporter_allowed(self, ctx):
        post_id = self._setup_post(ctx)
        dispatch(proxy_event("POST", f"/posts/{post_id}/report",
                             role="Member", sub="m2", groups=["g1"],
                             body={"reason": "Spam"}), ctx)
        # Different user reports same post — allowed
        resp = dispatch(proxy_event("POST", f"/posts/{post_id}/report",
                                    role="Member", sub="m3", groups=["g1"],
                                    body={"reason": "Offensive"}), ctx)
        assert resp["statusCode"] == 200
