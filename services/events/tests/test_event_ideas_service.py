"""Event Ideas: decline-deletes and the all-groups backlog fan-out.

Both behaviours are new (2026-08-27) and neither was covered before — the feature
shipped with no tests at all, which is how the "All groups" filter could return
only community-wide ideas without anyone noticing.
"""
from __future__ import annotations

import pytest
from _conventions.errors import ForbiddenError, NotFoundError, ValidationError
from boto3.dynamodb.conditions import Key
from conftest import FakePrincipal


def submit(ctx, principal, *, title="Bedrock workshop", group_id="COMMUNITY", **extra):
    return ctx.ideas.submit(
        {"title": title, "groupId": group_id, "description": "desc", **extra},
        principal=principal)


def idea_items(ctx, idea_id: str) -> list[dict]:
    """Every item in the idea's partition — META plus one row per vote."""
    resp = ctx.ideas_repo._t.query(KeyConditionExpression=Key("pk").eq(f"IDEA#{idea_id}"))
    return resp.get("Items", [])


# ---------------------------------------------------------------- decline deletes

class TestDeclineDeletes:
    def test_decline_removes_the_idea_record(self, ctx, cl, member):
        idea = submit(ctx, member)
        out = ctx.ideas.decline(idea["id"], {"reason": "duplicate of Q4 session"},
                                principal=cl)

        assert out["deleted"] is True
        assert out["id"] == idea["id"]
        assert ctx.ideas_repo.get_idea(idea["id"]) is None
        with pytest.raises(NotFoundError):
            ctx.ideas.get(idea["id"], principal=member)

    def test_decline_also_removes_every_vote(self, ctx, cl, member, other_member):
        idea = submit(ctx, member)
        ctx.ideas.toggle_vote(idea["id"], principal=member)
        ctx.ideas.toggle_vote(idea["id"], principal=other_member)
        # META + 2 votes
        assert len(idea_items(ctx, idea["id"])) == 3

        ctx.ideas.decline(idea["id"], {"reason": "not this quarter"}, principal=cl)

        assert idea_items(ctx, idea["id"]) == [], "vote markers must not be orphaned"

    def test_declined_idea_leaves_the_feed(self, ctx, cl, member):
        idea = submit(ctx, member)
        assert ctx.ideas.browse(principal=member)["count"] == 1

        ctx.ideas.decline(idea["id"], {"reason": "no"}, principal=cl)

        assert ctx.ideas.browse(principal=member)["count"] == 0
        assert ctx.ideas.backlog(principal=cl)["count"] == 0

    def test_decline_publishes_the_reason_as_the_only_surviving_record(self, ctx, cl,
                                                                      member, events):
        idea = submit(ctx, member, title="Graviton deep dive")
        ctx.ideas.decline(idea["id"], {"reason": "covered last month"}, principal=cl)

        published = events.of_type("IdeaDeclined")
        assert len(published) == 1
        data = published[0]["data"]
        assert data["ideaId"] == idea["id"]
        assert data["reason"] == "covered last month"
        assert data["title"] == "Graviton deep dive"
        assert data["submitterId"] == member.user_id
        assert data["deleted"] is True

    def test_reason_is_still_required(self, ctx, cl, member):
        idea = submit(ctx, member)
        with pytest.raises(ValidationError):
            ctx.ideas.decline(idea["id"], {"reason": "  "}, principal=cl)
        # Nothing was deleted by the rejected call.
        assert ctx.ideas_repo.get_idea(idea["id"]) is not None

    def test_declining_twice_is_a_404_not_a_second_delete(self, ctx, cl, member):
        idea = submit(ctx, member)
        ctx.ideas.decline(idea["id"], {"reason": "no"}, principal=cl)
        with pytest.raises(NotFoundError):
            ctx.ideas.decline(idea["id"], {"reason": "no"}, principal=cl)

    def test_member_cannot_decline(self, ctx, member):
        idea = submit(ctx, member)
        with pytest.raises(ForbiddenError):
            ctx.ideas.decline(idea["id"], {"reason": "mine"}, principal=member)
        assert ctx.ideas_repo.get_idea(idea["id"]) is not None

    def test_ugl_cannot_decline_another_groups_idea(self, ctx, member, ugl):
        idea = submit(ctx, member, group_id="g-ml")   # ugl leads g-serverless
        with pytest.raises(ForbiddenError):
            ctx.ideas.decline(idea["id"], {"reason": "not mine"}, principal=ugl)
        assert ctx.ideas_repo.get_idea(idea["id"]) is not None

    def test_public_shape_no_longer_carries_declined_fields(self, ctx, member):
        idea = submit(ctx, member)
        assert "declinedBy" not in idea
        assert "declinedReason" not in idea


# --------------------------------------------------------- all-groups backlog

class TestBacklogAllGroups:
    def _spread(self, ctx, member):
        """One open idea in COMMUNITY and one in each of two groups."""
        return {
            "COMMUNITY": submit(ctx, member, title="Community idea", group_id="COMMUNITY"),
            "g-serverless": submit(ctx, member, title="Serverless idea",
                                   group_id="g-serverless"),
            "g-ml": submit(ctx, member, title="ML idea", group_id="g-ml"),
        }

    def test_all_groups_returns_group_ideas_not_just_community(self, ctx, cl, member):
        made = self._spread(ctx, member)

        out = ctx.ideas.backlog(principal=cl, group_ids="g-serverless,g-ml")

        ids = {i["id"] for i in out["items"]}
        assert ids == {made["COMMUNITY"]["id"], made["g-serverless"]["id"],
                       made["g-ml"]["id"]}, "the regression: group ideas went missing"
        assert out["count"] == 3

    def test_without_group_ids_it_still_returns_community_only(self, ctx, cl, member):
        """Old callers keep working — no groupIds means the COMMUNITY partition."""
        made = self._spread(ctx, member)
        out = ctx.ideas.backlog(principal=cl)
        assert [i["id"] for i in out["items"]] == [made["COMMUNITY"]["id"]]

    def test_an_explicit_group_is_still_scoped_to_that_group(self, ctx, cl, member):
        made = self._spread(ctx, member)
        out = ctx.ideas.backlog(principal=cl, group_id="g-ml",
                                group_ids="g-serverless,g-ml")
        assert [i["id"] for i in out["items"]] == [made["g-ml"]["id"]]

    def test_duplicate_group_ids_do_not_duplicate_rows(self, ctx, cl, member):
        made = self._spread(ctx, member)
        out = ctx.ideas.backlog(principal=cl, group_ids="g-ml,g-ml,g-ml")
        ids = [i["id"] for i in out["items"]]
        assert sorted(ids) == sorted([made["COMMUNITY"]["id"], made["g-ml"]["id"]])
        assert len(ids) == len(set(ids))

    def test_community_in_group_ids_is_not_walked_twice(self, ctx, cl, member):
        made = self._spread(ctx, member)
        out = ctx.ideas.backlog(principal=cl, group_ids="COMMUNITY,g-ml")
        ids = [i["id"] for i in out["items"]]
        assert ids.count(made["COMMUNITY"]["id"]) == 1

    def test_too_many_groups_is_rejected(self, ctx, cl):
        from event_ideas_service import MAX_IDEA_BACKLOG_GROUPS
        too_many = ",".join(f"g-{n}" for n in range(MAX_IDEA_BACKLOG_GROUPS + 1))
        with pytest.raises(ValidationError):
            ctx.ideas.backlog(principal=cl, group_ids=too_many)

    def test_pagination_across_groups_yields_every_idea_exactly_once(self, ctx, cl):
        """The cursor must remember which group partition it stopped in."""
        # Submitted as the CL — see the note in test_greenlit_is_found_across_all_groups:
        # g-a/g-b/g-c are arbitrary partition names, not groups anyone belongs to.
        expected = set()
        for gid in ("g-a", "g-b", "g-c"):
            for n in range(3):
                expected.add(submit(ctx, cl, title=f"{gid} idea {n}",
                                    group_id=gid)["id"])
        expected.add(submit(ctx, cl, title="community idea",
                            group_id="COMMUNITY")["id"])

        seen: list[str] = []
        cursor = None
        for _ in range(20):   # generous bound; asserts termination too
            page = ctx.ideas.backlog(principal=cl, group_ids="g-a,g-b,g-c",
                                     limit=2, cursor=cursor)
            seen.extend(i["id"] for i in page["items"])
            cursor = page.get("cursor")
            if not cursor:
                break
        assert cursor is None, "pagination did not terminate"
        assert len(seen) == len(set(seen)), "an idea was returned twice"
        assert set(seen) == expected

    def test_ugl_is_still_locked_to_their_led_group(self, ctx, ugl, member):
        made = self._spread(ctx, member)
        out = ctx.ideas.backlog(principal=ugl, group_ids="g-serverless,g-ml")
        assert [i["id"] for i in out["items"]] == [made["g-serverless"]["id"]]

    def test_member_cannot_read_the_backlog(self, ctx, member):
        with pytest.raises(ForbiddenError):
            ctx.ideas.backlog(principal=member)

    def test_greenlit_ideas_are_excluded_from_the_open_backlog(self, ctx, cl, member):
        idea = submit(ctx, member, group_id="g-ml")
        ctx.ideas.greenlight(idea["id"], {"note": "yes"}, principal=cl)
        out = ctx.ideas.backlog(principal=cl, group_ids="g-ml")
        assert out["count"] == 0

    def test_admin_cannot_read_the_backlog(self, ctx, admin):
        with pytest.raises(ForbiddenError):
            ctx.ideas.backlog(principal=admin, group_ids="g-ml")


# ------------------------------------------------------------------ browse feed

class TestGreenlitTab:
    """The Greenlit tab returned nothing for any group, however many greenlit
    ideas existed: only Open ideas were indexed, and the status filter ran in
    memory over that Open-only index. Status is now part of the feed partition
    key, so each tab is an exact query.
    """

    def test_a_greenlit_idea_appears_in_the_greenlit_backlog(self, ctx, cl, member):
        idea = submit(ctx, member, title="Bedrock deep dive", group_id="g-ml")
        ctx.ideas.greenlight(idea["id"], {"note": "scheduling for Q4"}, principal=cl)

        out = ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Greenlit")

        assert out["count"] == 1, "the regression: Greenlit was always empty"
        row = out["items"][0]
        assert row["id"] == idea["id"]
        assert row["status"] == "Greenlit"
        assert row["greenlitNote"] == "scheduling for Q4"
        assert row["greenlitBy"] == cl.user_id

    def test_greenlighting_moves_an_idea_between_the_two_tabs(self, ctx, cl, member):
        idea = submit(ctx, member, group_id="g-ml")
        assert ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Open")["count"] == 1
        assert ctx.ideas.backlog(principal=cl, group_id="g-ml",
                                 status="Greenlit")["count"] == 0

        ctx.ideas.greenlight(idea["id"], {"note": ""}, principal=cl)

        assert ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Open")["count"] == 0
        assert ctx.ideas.backlog(principal=cl, group_id="g-ml",
                                 status="Greenlit")["count"] == 1

    def test_greenlit_is_found_across_all_groups(self, ctx, cl):
        # Submitted as the CL: this test is about the all-groups READ fan-out, and
        # the group ids are arbitrary placeholders. A Member may only submit into
        # their own groups now, so using `member` here would be asserting the
        # write rule by accident rather than the read rule on purpose.
        a = submit(ctx, cl, title="A", group_id="g-a")
        b = submit(ctx, cl, title="B", group_id="COMMUNITY")
        ctx.ideas.greenlight(a["id"], {"note": ""}, principal=cl)
        ctx.ideas.greenlight(b["id"], {"note": ""}, principal=cl)

        out = ctx.ideas.backlog(principal=cl, group_ids="g-a,g-b", status="Greenlit")
        assert {i["id"] for i in out["items"]} == {a["id"], b["id"]}

    def test_open_feed_is_highest_votes_first(self, ctx, cl, member, peer_member):
        """The documented contract is "sorted by vote count desc". The sort key is
        already descending-encoded (9999999999 - votes), so the query must read it
        ASCENDING — reading it descending inverted it a second time and put the
        least-voted idea at the top."""
        submit(ctx, member, title="Low", group_id="g-ml")
        high = submit(ctx, member, title="High", group_id="g-ml")
        ctx.ideas.toggle_vote(high["id"], principal=member)
        ctx.ideas.toggle_vote(high["id"], principal=peer_member)

        out = ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Open")
        assert [i["title"] for i in out["items"]] == ["High", "Low"]

    def test_greenlit_ideas_keep_their_vote_ordering(self, ctx, cl, member, peer_member):
        low = submit(ctx, member, title="Low", group_id="g-ml")
        high = submit(ctx, member, title="High", group_id="g-ml")
        # Two votes on `high`, none on `low`, then greenlight both.
        ctx.ideas.toggle_vote(high["id"], principal=member)
        ctx.ideas.toggle_vote(high["id"], principal=peer_member)
        ctx.ideas.greenlight(high["id"], {"note": ""}, principal=cl)
        ctx.ideas.greenlight(low["id"], {"note": ""}, principal=cl)

        out = ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Greenlit")
        assert [i["title"] for i in out["items"]] == ["High", "Low"]
        assert out["items"][0]["voteCount"] == 2

    def test_a_greenlit_idea_is_not_lost_behind_a_page_of_open_ideas(self, ctx, cl, member):
        """The old in-memory filter read one page of the Open-only index and then
        filtered — so even if Greenlit rows had been indexed, a group with a full
        page of Open ideas would have hidden them."""
        for n in range(30):
            submit(ctx, member, title=f"Open {n}", group_id="g-ml")
        target = submit(ctx, member, title="Greenlit one", group_id="g-ml")
        ctx.ideas.greenlight(target["id"], {"note": ""}, principal=cl)

        out = ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Greenlit", limit=25)
        assert [i["title"] for i in out["items"]] == ["Greenlit one"]

    def test_ugl_sees_greenlit_ideas_for_their_own_group_only(self, ctx, cl, member, ugl):
        mine = submit(ctx, member, title="Mine", group_id="g-serverless")
        theirs = submit(ctx, member, title="Theirs", group_id="g-ml")
        ctx.ideas.greenlight(mine["id"], {"note": ""}, principal=cl)
        ctx.ideas.greenlight(theirs["id"], {"note": ""}, principal=cl)

        out = ctx.ideas.backlog(principal=ugl, status="Greenlit")
        assert [i["title"] for i in out["items"]] == ["Mine"]

    def test_member_feed_shows_open_and_greenlit_by_default(self, ctx, cl, member):
        open_idea = submit(ctx, member, title="Still open", group_id="COMMUNITY")
        lit = submit(ctx, member, title="Approved", group_id="COMMUNITY")
        ctx.ideas.greenlight(lit["id"], {"note": ""}, principal=cl)

        ids = {i["id"] for i in ctx.ideas.browse(principal=member)["items"]}
        assert ids == {open_idea["id"], lit["id"]}

    def test_greenlit_pagination_terminates_and_is_complete(self, ctx, cl, member):
        made = set()
        for n in range(7):
            idea = submit(ctx, member, title=f"G{n}", group_id="g-ml")
            ctx.ideas.greenlight(idea["id"], {"note": ""}, principal=cl)
            made.add(idea["id"])

        seen: list[str] = []
        cursor = None
        for _ in range(20):
            page = ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Greenlit",
                                     limit=2, cursor=cursor)
            seen.extend(i["id"] for i in page["items"])
            cursor = page.get("cursor")
            if not cursor:
                break
        assert cursor is None
        assert len(seen) == len(set(seen))
        assert set(seen) == made

    def test_archived_ideas_remain_indexed_rather_than_disappearing(self, ctx, cl, member):
        """The sweep used to un-index the row. It now moves it to the Archived
        partition, so the data stays readable even though no tab offers it."""
        idea = submit(ctx, member, group_id="g-ml")
        # Force the idea stale, then sweep.
        ctx.ideas_repo._t.update_item(
            Key={"pk": f"IDEA#{idea['id']}", "sk": "META"},
            UpdateExpression="SET lastVoteAt = :old",
            ExpressionAttributeValues={":old": "2020-01-01T00:00:00+00:00"})
        assert ctx.ideas.sweep_stale()["archived"] == 1

        assert ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Open")["count"] == 0
        out = ctx.ideas.backlog(principal=cl, group_id="g-ml", status="Archived")
        assert [i["id"] for i in out["items"]] == [idea["id"]]


class TestBrowseDefaults:
    def test_default_feed_excludes_declined_because_none_can_exist(self, ctx, member, cl):
        keep = submit(ctx, member, title="Keeper")
        drop = submit(ctx, member, title="Doomed")
        ctx.ideas.decline(drop["id"], {"reason": "no"}, principal=cl)

        ids = [i["id"] for i in ctx.ideas.browse(principal=member)["items"]]
        assert ids == [keep["id"]]

    def test_route_returns_the_deletion_result(self, ctx, cl, member):
        """The dispatcher must not try to serialize a record that is gone."""
        from app import dispatch
        idea = submit(ctx, member)
        resp = dispatch({
            "httpMethod": "POST",
            "path": f"/events/ideas/{idea['id']}/decline",
            "headers": {"Authorization": "Bearer t"},
            "requestContext": {"authorizer": {"claims": {
                "sub": cl.user_id, "role": "CommunityLeader"}}},
            "queryStringParameters": None,
            "body": '{"reason": "not now"}',
        }, ctx)
        assert resp["statusCode"] == 200
        import json
        assert json.loads(resp["body"])["deleted"] is True
        assert ctx.ideas_repo.get_idea(idea["id"]) is None


def test_fake_principal_helper_is_used(ctx, member):
    """Guard: the ideas table must actually be wired into the test Context,
    otherwise every test above would hit the 503 branch instead of the service."""
    assert ctx.ideas is not None
    assert isinstance(member, FakePrincipal)


# ------------------------------------------------------- group scoping (2026-08-27)

class TestIdeaGroupScoping:
    """A Member must not see or touch ideas belonging to groups they are not in.

    The feature shipped with `browse` accepting `principal` and never reading it,
    `get` taking no principal at all, and `toggle_vote`/`submit` checking only the
    UGL case. So any authenticated caller could read every group's idea backlog by
    putting a group id in the query string, vote in it (reordering that group's
    priority list, since votes are the sort key), and post ideas into it.

    Fixture geography, relied on throughout: `member` is in g-serverless + g-ml,
    `other_member` is in g-other only, `ugl` leads g-serverless. COMMUNITY is
    visible to everyone.
    """

    # ---- browse ----

    def test_explicit_out_of_scope_group_is_refused(self, ctx, member, other_member):
        """The regression, stated directly: a group id in the query string used to
        be honoured verbatim."""
        submit(ctx, member, title="Serverless secret", group_id="g-serverless")

        with pytest.raises(ForbiddenError):
            ctx.ideas.browse(principal=other_member, group_id="g-serverless")

    def test_own_group_is_allowed_when_named_explicitly(self, ctx, member):
        idea = submit(ctx, member, title="Mine", group_id="g-ml")

        out = ctx.ideas.browse(principal=member, group_id="g-ml")

        assert [i["id"] for i in out["items"]] == [idea["id"]]

    def test_default_feed_spans_community_plus_own_groups_only(self, ctx, cl, member):
        """No groupId => the caller's whole visible surface, and nothing beyond it.
        Also pins the behaviour CHANGE: the default feed used to be COMMUNITY
        alone, so a member's own groups' ideas were missing from it."""
        community = submit(ctx, member, title="Community", group_id="COMMUNITY")
        mine_a = submit(ctx, member, title="Serverless", group_id="g-serverless")
        mine_b = submit(ctx, member, title="ML", group_id="g-ml")
        # Submitted by the CL, who may post anywhere — a Member could not create
        # this row, which is the point: it must be invisible, not merely absent.
        theirs = submit(ctx, cl, title="Someone else's", group_id="g-other")

        ids = {i["id"] for i in ctx.ideas.browse(principal=member, limit=50)["items"]}

        assert ids == {community["id"], mine_a["id"], mine_b["id"]}
        assert theirs["id"] not in ids

    def test_member_with_no_groups_still_sees_community_wide(self, ctx, cl):
        """Community-wide is not a group, so it survives having no memberships —
        a zero-group member gets an empty feed only if nothing is community-wide."""
        loner = FakePrincipal("u-loner", "Member", member_group_ids=[])
        community = submit(ctx, cl, title="Open to all", group_id="COMMUNITY")
        submit(ctx, cl, title="Group only", group_id="g-other")

        ids = [i["id"] for i in ctx.ideas.browse(principal=loner, limit=50)["items"]]

        assert ids == [community["id"]]

    def test_ugl_sees_community_plus_their_led_group(self, ctx, cl, ugl):
        community = submit(ctx, cl, title="Community", group_id="COMMUNITY")
        led = submit(ctx, cl, title="Led", group_id="g-serverless")
        other = submit(ctx, cl, title="Other", group_id="g-other")

        ids = {i["id"] for i in ctx.ideas.browse(principal=ugl, limit=50)["items"]}

        assert ids == {community["id"], led["id"]}
        assert other["id"] not in ids

    def test_community_leader_is_not_scoped(self, ctx, cl):
        """A CL may name any group. `visible_scopes` returns [] for a CL as an
        "unscoped" sentinel, so this pins that [] is not read as "deny"."""
        idea = submit(ctx, cl, title="Anywhere", group_id="g-nobody-is-in-this")

        out = ctx.ideas.browse(principal=cl, group_id="g-nobody-is-in-this")

        assert [i["id"] for i in out["items"]] == [idea["id"]]

    # ---- get: 404, never 403 ----

    def test_get_out_of_scope_is_404_not_403(self, ctx, member, other_member):
        """BR-A8 — a 403 would confirm the idea exists. Identical response to a
        genuinely unknown id."""
        idea = submit(ctx, member, title="Private", group_id="g-serverless")

        with pytest.raises(NotFoundError):
            ctx.ideas.get(idea["id"], principal=other_member)

    def test_get_unknown_id_is_also_404(self, ctx, other_member):
        """The other half of the pair above: both cases must raise the same thing,
        or the difference between them leaks existence."""
        with pytest.raises(NotFoundError):
            ctx.ideas.get("does-not-exist", principal=other_member)

    def test_get_in_scope_succeeds(self, ctx, member):
        idea = submit(ctx, member, title="Mine", group_id="g-ml")
        assert ctx.ideas.get(idea["id"], principal=member)["id"] == idea["id"]

    def test_get_community_wide_is_visible_to_any_member(self, ctx, cl, other_member):
        idea = submit(ctx, cl, title="Everyone", group_id="COMMUNITY")
        assert ctx.ideas.get(idea["id"], principal=other_member)["id"] == idea["id"]

    # ---- vote ----

    def test_vote_on_out_of_scope_idea_is_404(self, ctx, member, other_member):
        idea = submit(ctx, member, title="Mine", group_id="g-serverless")

        with pytest.raises(NotFoundError):
            ctx.ideas.toggle_vote(idea["id"], principal=other_member)

        assert int(ctx.ideas_repo.get_idea(idea["id"])["voteCount"]) == 0

    def test_vote_scope_is_checked_before_status(self, ctx, cl, member, other_member):
        """An Archived/Greenlit out-of-scope idea must raise NotFound, not the
        "voting is only available on Open ideas" ValidationError — that message
        would confirm the idea exists."""
        idea = submit(ctx, member, title="Mine", group_id="g-serverless")
        ctx.ideas.greenlight(idea["id"], {"note": ""}, principal=cl)

        with pytest.raises(NotFoundError):
            ctx.ideas.toggle_vote(idea["id"], principal=other_member)

    def test_vote_in_own_group_still_works(self, ctx, member):
        idea = submit(ctx, member, title="Mine", group_id="g-ml")
        out = ctx.ideas.toggle_vote(idea["id"], principal=member)
        assert out["voted"] is True
        assert out["voteCount"] == 1

    # ---- submit ----

    def test_member_cannot_submit_into_a_group_they_are_not_in(self, ctx, other_member):
        with pytest.raises(ForbiddenError):
            submit(ctx, other_member, title="Trespass", group_id="g-serverless")

    def test_member_cannot_submit_into_a_nonexistent_group(self, ctx, member):
        """This service holds no group registry, so an unknown id cannot be
        rejected as unknown — but it is not in the caller's claims either, and
        that is sufficient. Without this the table accrued ideas in partitions no
        feed would ever read."""
        with pytest.raises(ForbiddenError):
            submit(ctx, member, title="Ghost group", group_id="g-does-not-exist")

    def test_member_can_submit_into_own_group_and_community(self, ctx, member):
        assert submit(ctx, member, title="A", group_id="g-ml")["groupId"] == "g-ml"
        assert submit(ctx, member, title="B", group_id="COMMUNITY")["groupId"] == "COMMUNITY"

    def test_ugl_submit_scope_is_unchanged(self, ctx, ugl):
        assert submit(ctx, ugl, title="Led", group_id="g-serverless")["groupId"] == "g-serverless"
        with pytest.raises(ForbiddenError):
            submit(ctx, ugl, title="Not led", group_id="g-other")

    # ---- HTTP layer ----

    def test_route_passes_the_principal_to_get(self, ctx, member, other_member):
        """GET /events/ideas/{id} used to call `ideas.get(id)` with no principal at
        all — the scope check cannot fire if the router never supplies the caller.
        Asserted through dispatch so a future signature change cannot quietly drop
        it again."""
        import json

        from app import dispatch

        idea = submit(ctx, member, title="Private", group_id="g-serverless")

        def _get(principal):
            return dispatch({
                "httpMethod": "GET",
                "path": f"/events/ideas/{idea['id']}",
                "headers": {"Authorization": "Bearer t"},
                "requestContext": {"authorizer": {"claims": {
                    "sub": principal.user_id, "role": principal.role,
                    # The trigger stamps this as a comma-separated STRING.
                    "member_group_ids": ",".join(principal.member_group_ids),
                }}},
                "queryStringParameters": None,
                "body": None,
            }, ctx)

        assert _get(member)["statusCode"] == 200
        outsider = _get(other_member)
        assert outsider["statusCode"] == 404
        assert json.loads(outsider["body"])["code"] == "NOT_FOUND"

    def test_route_refuses_an_out_of_scope_browse(self, ctx, member, other_member):
        from app import dispatch

        submit(ctx, member, title="Private", group_id="g-serverless")
        resp = dispatch({
            "httpMethod": "GET",
            "path": "/events/ideas",
            "headers": {"Authorization": "Bearer t"},
            "requestContext": {"authorizer": {"claims": {
                "sub": other_member.user_id, "role": "Member",
                "member_group_ids": ",".join(other_member.member_group_ids),
            }}},
            "queryStringParameters": {"groupId": "g-serverless"},
            "body": None,
        }, ctx)
        assert resp["statusCode"] == 403
