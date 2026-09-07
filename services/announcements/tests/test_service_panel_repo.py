"""Service + panel targeting + repository (NFR-AN-MAINT-1 suite 5, part A)."""
from __future__ import annotations

import models
from _conventions.authz import Principal
from conftest import claims


def _cl(sub="ucl"):
    return Principal.from_claims(claims(sub, "CommunityLeader"))


def _ugl(sub="uugl", led="g1"):
    return Principal.from_claims(claims(sub, "UserGroupLeader", led=led))


def _member(sub="um", groups=None):
    return Principal.from_claims(claims(sub, "Member", groups or []))


def test_create_denormalizes_author_and_source(ctx, directory, events):
    directory.names["ucl"] = "Cleo Leader"
    directory.groups["g1"] = "Serverless Guild"
    out = ctx.service.create(
        {"title": "Hi", "target": {"scope": "groups", "groupIds": ["g1"]}}, _cl(), bearer_token="t")
    assert out["authorName"] == "Cleo Leader"
    assert out["authorRoleLabel"] == "Community Leader"
    assert out["source"] == "Serverless Guild"
    # publishes AnnouncementPublished (BR-10)
    assert events.published[-1]["type"] == "AnnouncementPublished"


def test_create_stores_markdown_body_verbatim(ctx):
    # Body is stored as inert Markdown (length-bounded); render-time sanitization
    # is a client concern (markdown-it html:false + DOMPurify).
    md = "**hi** and [link](https://aws.amazon.com)"
    out = ctx.service.create({"title": "t", "body": md, "target": {"scope": "community"}}, _cl())
    assert out["body"] == md


def test_community_visible_to_all(ctx):
    ctx.service.create({"title": "c", "target": {"scope": "community"}}, _cl())
    assert ctx.panel.panel(_member(groups=["gX"]))["count"] == 1
    assert ctx.panel.panel(_ugl())["count"] == 1


def test_group_targeting_only_members_see_it(ctx):
    ctx.service.create({"title": "g", "target": {"scope": "groups", "groupIds": ["g1"]}}, _cl())
    assert ctx.panel.panel(_member(groups=["g1"]))["count"] == 1   # in group
    assert ctx.panel.panel(_member(sub="u2", groups=["g2"]))["count"] == 0  # not in group


def test_ugl_sees_led_group_announcement(ctx):
    # another CL posts to g1; the UGL of g1 sees it
    ctx.service.create({"title": "g", "target": {"scope": "groups", "groupIds": ["g1"]}}, _cl())
    assert ctx.panel.panel(_ugl(led="g1"))["count"] == 1


def test_cl_sees_own_group_announcement_in_panel(ctx):
    # CL authors a group announcement; they see it in their own panel even without membership
    ctx.service.create({"title": "g", "target": {"scope": "groups", "groupIds": ["g9"]}}, _cl("ucl"))
    assert ctx.panel.panel(_cl("ucl"))["count"] == 1
    # a different CL who did not author it does not
    assert ctx.panel.panel(_cl("ucl-2"))["count"] == 0


def test_panel_newest_first(ctx):
    a = ctx.service.create({"title": "first", "target": {"scope": "community"}}, _cl())
    b = ctx.service.create({"title": "second", "target": {"scope": "community"}}, _cl())
    # force ordering by createdAt
    ia = ctx.repo.get(a["id"])
    ia["createdAt"] = "2026-01-01T00:00:00+00:00"
    ctx.repo.put(ia)
    ib = ctx.repo.get(b["id"])
    ib["createdAt"] = "2026-02-01T00:00:00+00:00"
    ctx.repo.put(ib)
    panel = ctx.panel.panel(_member())
    assert [i["title"] for i in panel["items"]] == ["second", "first"]


def test_edit_updates_and_delete_removes(ctx):
    out = ctx.service.create({"title": "t", "target": {"scope": "community"}}, _cl())
    edited = ctx.service.edit(out["id"], {"title": "New"}, _cl())
    assert edited["title"] == "New"
    ctx.service.delete(out["id"], _cl())
    assert ctx.repo.get(out["id"]) is None


def test_repository_by_author_and_targeting_group(ctx):
    ctx.service.create({"title": "a", "target": {"scope": "community"}}, _cl("ucl"))
    ctx.service.create({"title": "b", "target": {"scope": "groups", "groupIds": ["g1"]}}, _cl("ucl"))
    ctx.service.create({"title": "c", "target": {"scope": "community"}}, _cl("ucl-2"))
    assert len(ctx.repo.by_author("ucl")) == 2
    assert len(ctx.repo.targeting_group("g1")) == 1


def test_ttl_set_on_create(ctx):
    out = ctx.service.create({"title": "t", "target": {"scope": "community"}}, _cl())
    item = ctx.repo.get(out["id"])
    # DynamoDB numbers deserialize as Decimal via the resource client.
    assert int(item["ttl"]) == models.epoch(models.parse_iso(out["expiresAt"]))
