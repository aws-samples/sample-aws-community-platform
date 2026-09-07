"""Event consumers (NFR-AN-MAINT-1 suite 4, BR-13/15/17): EventCreated auto-post
(idempotent), announce=false no-op, GroupSoftDeleted/GroupRestored hide/restore."""
from __future__ import annotations

from _conventions.authz import Principal
from conftest import bridge_event, claims


def _member(sub="um", groups=None):
    return Principal.from_claims(claims(sub, "Member", groups or []))


def test_event_created_announce_true_auto_posts_once(ctx):
    ev = bridge_event("EventCreated", {
        "eventId": "e-1", "title": "Serverless Deep Dive", "groupId": "g1",
        "announce": True, "announceByEmail": False, "createdBy": "ucl",
    }, event_id="evt-1")
    ctx.consumer.handle(ev["detail"])
    ctx.consumer.handle(ev["detail"])  # redelivery — idempotent on envelope id

    all_items = ctx.repo.scan_all()
    posted = [i for i in all_items if i.get("originEventId") == "e-1"]
    assert len(posted) == 1
    assert posted[0]["targetScope"] == "groups"
    assert posted[0]["targetGroupIds"] == ["g1"]


def test_event_created_announce_false_is_noop(ctx):
    ev = bridge_event("EventCreated", {"eventId": "e-2", "title": "Quiet", "announce": False},
                      event_id="evt-2")
    ctx.consumer.handle(ev["detail"])
    assert ctx.repo.scan_all() == []


def test_event_created_community_when_no_group(ctx):
    ev = bridge_event("EventCreated", {"eventId": "e-3", "title": "All hands",
                                       "announce": True, "createdBy": "ucl"}, event_id="evt-3")
    ctx.consumer.handle(ev["detail"])
    item = next(i for i in ctx.repo.scan_all() if i.get("originEventId") == "e-3")
    assert item["targetScope"] == "community"


def test_group_soft_deleted_hides_then_restored(ctx):
    cl = Principal.from_claims(claims("ucl", "CommunityLeader"))
    out = ctx.service.create({"title": "grp", "target": {"scope": "groups", "groupIds": ["g1"]}}, cl)
    member = _member(groups=["g1"])
    assert ctx.panel.panel(member)["count"] == 1

    ctx.consumer.handle(bridge_event("GroupSoftDeleted", {"groupId": "g1"},
                                     event_id="evt-sd", source="identity-access")["detail"])
    assert ctx.panel.panel(member)["count"] == 0  # hidden (BR-13)

    ctx.consumer.handle(bridge_event("GroupRestored", {"groupId": "g1"},
                                     event_id="evt-rs", source="identity-access")["detail"])
    assert ctx.panel.panel(member)["count"] == 1  # restored

    # sanity: the item's flag round-tripped
    assert ctx.repo.get(out["id"])["groupHidden"] is False


def test_group_event_without_group_id_ignored(ctx):
    ctx.consumer.handle(bridge_event("GroupSoftDeleted", {}, event_id="evt-x",
                                     source="identity-access")["detail"])
    # no crash, nothing to hide
    assert ctx.repo.scan_all() == []
