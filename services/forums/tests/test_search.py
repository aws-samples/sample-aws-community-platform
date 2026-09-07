"""Search tokenization + query tests (NFR-FO-MAINT-1 suite 6).

Tests: stop-word removal, case normalization, body cap at 50 terms,
multi-term intersection, access-scope filter, hidden/deleted excluded.
"""
import json

import pytest
from conftest import proxy_event

from app import dispatch
from models import STOP_WORDS, tokenize


class TestTokenization:
    """Unit tests for the tokenize() function."""

    def test_basic_tokenization(self):
        terms = tokenize("Hello World", "This is a test body")
        assert "hello" in terms
        assert "world" in terms
        assert "test" in terms
        assert "body" in terms
        # Stop words excluded
        assert "this" not in terms
        assert "is" not in terms
        assert "a" not in terms

    def test_case_normalization(self):
        terms = tokenize("UPPERCASE Title", "MixedCase Body")
        assert "uppercase" in terms
        assert "title" in terms
        assert "mixedcase" in terms

    def test_stop_words_excluded(self):
        terms = tokenize("The Quick Brown Fox", "jumps over the lazy dog")
        assert "the" not in terms
        assert "quick" in terms
        assert "brown" in terms
        assert "fox" in terms

    def test_body_capped_at_50_terms(self):
        # Body with 100 unique words
        body_words = [f"word{i}" for i in range(100)]
        body = " ".join(body_words)
        terms = tokenize("title", body)
        # Title contributes "title" (1 term), body capped at 50
        # Total should be <= 51
        assert len(terms) <= 51

    def test_short_tokens_excluded(self):
        """Tokens < 2 chars are excluded."""
        terms = tokenize("I am a x", "y z ok")
        assert "i" not in terms  # 1 char (also a stop word)
        assert "x" not in terms  # 1 char
        assert "ok" in terms  # 2 chars

    def test_deduplication(self):
        terms = tokenize("hello hello hello", "hello world world")
        assert terms.count("hello") == 1
        assert terms.count("world") == 1


class TestSearchEndpoint:
    """Integration tests for the /forums/search endpoint."""

    def _setup_posts(self, ctx):
        """Create a forum with posts containing specific keywords."""
        resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                                    body={"name": "Forum", "groupId": "g1"}), ctx)
        ch_id = json.loads(resp["body"])["channels"][0]["id"]

        # Post 1: contains "python" and "lambda"
        dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                             role="Member", sub="m1", groups=["g1"],
                             body={"title": "Python Lambda Functions", "body": "How to use python with lambda"}), ctx)
        # Post 2: contains "python" but not "lambda"
        dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                             role="Member", sub="m1", groups=["g1"],
                             body={"title": "Python Best Practices", "body": "Tips for writing clean python code"}), ctx)
        # Post 3: contains "javascript"
        dispatch(proxy_event("POST", f"/channels/{ch_id}/posts",
                             role="Member", sub="m1", groups=["g1"],
                             body={"title": "JavaScript Guide", "body": "Getting started with javascript"}), ctx)

    def test_single_term_search(self, ctx):
        self._setup_posts(ctx)
        event = proxy_event("GET", "/forums/search", role="Member", sub="m1",
                            groups=["g1"], qs={"q": "python"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["count"] == 2  # Both python posts

    def test_multi_term_intersection(self, ctx):
        self._setup_posts(ctx)
        event = proxy_event("GET", "/forums/search", role="Member", sub="m1",
                            groups=["g1"], qs={"q": "python lambda"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["count"] == 1  # Only the post with both terms

    def test_no_results(self, ctx):
        self._setup_posts(ctx)
        event = proxy_event("GET", "/forums/search", role="Member", sub="m1",
                            groups=["g1"], qs={"q": "nonexistent"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["count"] == 0

    def test_access_scoped(self, ctx):
        """Member in group-B cannot see group-A posts in search."""
        self._setup_posts(ctx)
        event = proxy_event("GET", "/forums/search", role="Member", sub="m2",
                            groups=["group-B"], qs={"q": "python"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["count"] == 0

    def test_short_query_returns_empty(self, ctx):
        event = proxy_event("GET", "/forums/search", role="Member", sub="m1",
                            groups=["g1"], qs={"q": "x"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["count"] == 0


class TestSearchScopeFilters:
    """channelId / forumId / groupId are declared in the OpenAPI contract. They
    were accepted and silently ignored, so "search this channel" searched every
    forum the caller could see."""

    def _two_channels(self, ctx):
        resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                                    body={"name": "Forum", "groupId": "g1"}), ctx)
        forum = json.loads(resp["body"])
        forum_id, ch_a = forum["id"], forum["channels"][0]["id"]
        resp = dispatch(proxy_event("POST", f"/forums/{forum_id}/channels",
                                    role="CommunityLeader", sub="cl1",
                                    body={"name": "Second"}), ctx)
        ch_b = json.loads(resp["body"])["id"]
        for ch, sub in ((ch_a, "m1"), (ch_b, "m2")):
            dispatch(proxy_event("POST", f"/channels/{ch}/posts", role="Member",
                                 sub=sub, groups=["g1"],
                                 body={"title": "Karpenter autoscaling notes",
                                       "body": "Notes about karpenter"}), ctx)
        return forum_id, ch_a, ch_b

    def test_unscoped_search_spans_channels(self, ctx):
        self._two_channels(ctx)
        resp = dispatch(proxy_event("GET", "/forums/search", role="Member", sub="m1",
                                    groups=["g1"], qs={"q": "karpenter"}), ctx)
        assert json.loads(resp["body"])["count"] == 2

    def test_channel_id_narrows_to_one_channel(self, ctx):
        _, ch_a, _ = self._two_channels(ctx)
        resp = dispatch(proxy_event("GET", "/forums/search", role="Member", sub="m1",
                                    groups=["g1"],
                                    qs={"q": "karpenter", "channelId": ch_a}), ctx)
        body = json.loads(resp["body"])
        assert body["count"] == 1
        assert body["items"][0]["channelId"] == ch_a

    def test_forum_id_and_group_id_narrow(self, ctx):
        forum_id, _, _ = self._two_channels(ctx)
        resp = dispatch(proxy_event("GET", "/forums/search", role="Member", sub="m1",
                                    groups=["g1"],
                                    qs={"q": "karpenter", "forumId": forum_id}), ctx)
        assert json.loads(resp["body"])["count"] == 2
        resp = dispatch(proxy_event("GET", "/forums/search", role="Member", sub="m1",
                                    groups=["g1"],
                                    qs={"q": "karpenter", "groupId": "other-group"}), ctx)
        assert json.loads(resp["body"])["count"] == 0

    def test_scope_filter_cannot_widen_access(self, ctx):
        """Asking for a group you cannot see must not reveal it."""
        _, ch_a, _ = self._two_channels(ctx)
        resp = dispatch(proxy_event("GET", "/forums/search", role="Member", sub="m9",
                                    groups=["group-B"],
                                    qs={"q": "karpenter", "groupId": "g1",
                                        "channelId": ch_a}), ctx)
        assert json.loads(resp["body"])["count"] == 0


class TestSearchRankingAndTruncation:
    """The match set used to be sliced to `limit` BEFORE the access and
    deleted/hidden filters, and sliced out of a `set` — so results were an
    arbitrary subset in arbitrary order, and visible matches could vanish."""

    def _posts_in_two_groups(self, ctx, per_group=3):
        made = {}
        for gid in ("g1", "g2"):
            resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader",
                                        sub="cl1",
                                        body={"name": f"Forum {gid}", "groupId": gid}), ctx)
            ch = json.loads(resp["body"])["channels"][0]["id"]
            ids = []
            for i in range(per_group):
                r = dispatch(proxy_event("POST", f"/channels/{ch}/posts", role="Member",
                                         sub=f"{gid}-m{i}", groups=[gid],
                                         body={"title": f"Graviton migration part {i}",
                                               "body": "notes on graviton"}), ctx)
                ids.append(json.loads(r["body"])["id"])
            made[gid] = ids
        return made

    def test_visible_matches_survive_a_small_limit(self, ctx):
        """A g1 member with limit=2 must get 2 g1 posts — never g2 posts, and
        never fewer than exist because g2 ids consumed the slice."""
        self._posts_in_two_groups(ctx, per_group=3)
        resp = dispatch(proxy_event("GET", "/forums/search", role="Member", sub="g1-m0",
                                    groups=["g1"],
                                    qs={"q": "graviton", "limit": "2"}), ctx)
        body = json.loads(resp["body"])
        assert body["count"] == 2, "page should be full — visible matches exist"
        assert body["total"] == 3, "total should report every visible match"
        assert all(p["groupId"] == "g1" for p in body["items"])

    def test_results_are_newest_first_and_stable(self, ctx):
        self._posts_in_two_groups(ctx, per_group=3)
        qs = {"q": "graviton"}
        first = json.loads(dispatch(proxy_event(
            "GET", "/forums/search", role="Member", sub="g1-m0",
            groups=["g1"], qs=qs), ctx)["body"])
        second = json.loads(dispatch(proxy_event(
            "GET", "/forums/search", role="Member", sub="g1-m0",
            groups=["g1"], qs=qs), ctx)["body"])
        order = [p["id"] for p in first["items"]]
        assert order == [p["id"] for p in second["items"]], "ordering must be stable"
        created = [p["createdAt"] for p in first["items"]]
        assert created == sorted(created, reverse=True), "newest first"

    def test_deleted_posts_do_not_consume_the_page(self, ctx):
        made = self._posts_in_two_groups(ctx, per_group=3)
        dispatch(proxy_event("DELETE", f"/posts/{made['g1'][0]}", role="Member",
                             sub="g1-m0", groups=["g1"]), ctx)
        resp = dispatch(proxy_event("GET", "/forums/search", role="Member", sub="g1-m1",
                                    groups=["g1"], qs={"q": "graviton"}), ctx)
        body = json.loads(resp["body"])
        assert body["count"] == 2
        assert body["total"] == 2
        assert made["g1"][0] not in [p["id"] for p in body["items"]]


class TestTermPagination:
    """repository.query_term read a single 100-item page. Any term used by more
    than 100 posts was silently truncated, and multi-term intersection then
    compared mismatched windows and dropped genuine hits."""

    def _seed_term_items(self, table, term, count):
        with table.batch_writer() as batch:
            for i in range(count):
                pid = f"p{i:05d}"
                batch.put_item(Item={"pk": f"TERM#{pid}#{term}", "sk": "SEARCHTERM",
                                     "gsi3pk": f"TERM#{term}", "gsi3sk": pid})

    def test_returns_matches_beyond_the_first_page(self, aws):
        from repository import ForumsRepository
        self._seed_term_items(aws.table, "karpenter", 250)
        repo = ForumsRepository(aws.table, aws.client)
        ids = repo.query_term("karpenter")
        assert len(ids) == 250, f"expected all 250 matches, got {len(ids)}"
        assert len(set(ids)) == 250

    def test_respects_an_explicit_cap(self, aws):
        from repository import ForumsRepository
        self._seed_term_items(aws.table, "lambda", 150)
        repo = ForumsRepository(aws.table, aws.client)
        assert len(repo.query_term("lambda", limit=120)) == 120

    def test_intersection_across_pages_keeps_shared_posts(self, aws):
        """Two terms on the same 250 posts must intersect to all 250, not to the
        overlap of two arbitrary 100-item windows."""
        from repository import ForumsRepository
        self._seed_term_items(aws.table, "graviton", 250)
        self._seed_term_items(aws.table, "migration", 250)
        repo = ForumsRepository(aws.table, aws.client)
        both = set(repo.query_term("graviton")) & set(repo.query_term("migration"))
        assert len(both) == 250
