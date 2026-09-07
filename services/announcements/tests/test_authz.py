"""Authorization matrix (NFR-AN-MAINT-1 suite 1): role x operation, incl.
Administrator-denied-on-reads (BR-3), UGL-target-forced (BR-2), author-only-edit
+ CL-moderation-delete + IDOR guard (BR-4)."""
from __future__ import annotations

import json

from conftest import proxy_event


def _call(ctx, **kw):
    from app import dispatch
    resp = dispatch(proxy_event(**kw), ctx)
    body = json.loads(resp["body"]) if resp.get("body") else {}
    return resp["statusCode"], body


def _create(ctx, *, role, sub, led=None, target=None, title="Hello"):
    body = {"title": title}
    if target is not None:
        body["target"] = target
    return _call(ctx, method="POST", path="/announcements", role=role, sub=sub, led=led, body=body)


# ---- create ----
def test_cl_can_create_community(ctx):
    status, body = _create(ctx, role="CommunityLeader", sub="ucl", target={"scope": "community"})
    assert status == 201
    assert body["target"]["scope"] == "community"


def test_ugl_create_forced_to_led_group(ctx):
    status, body = _create(ctx, role="UserGroupLeader", sub="uugl", led="g1",
                           target={"scope": "groups", "groupIds": ["g-other"]})
    assert status == 201
    # UGL-supplied target is ignored; forced to their led group (BR-2).
    assert body["target"] == {"scope": "groups", "groupIds": ["g1"]}


def test_member_cannot_create(ctx):
    status, _ = _create(ctx, role="Member", sub="um")
    assert status == 403


def test_administrator_cannot_create(ctx):
    status, _ = _create(ctx, role="Administrator", sub="ua")
    assert status == 403


# ---- edit (author-only) ----
def test_author_can_edit_others_cannot(ctx):
    status, created = _create(ctx, role="CommunityLeader", sub="ucl", target={"scope": "community"})
    ann_id = created["id"]
    ok, _ = _call(ctx, method="PUT", path=f"/announcements/{ann_id}", role="CommunityLeader",
                  sub="ucl", body={"title": "Edited"})
    assert ok == 200
    forbidden, _ = _call(ctx, method="PUT", path=f"/announcements/{ann_id}",
                         role="CommunityLeader", sub="ucl-2", body={"title": "Hijack"})
    assert forbidden == 403  # IDOR guard — not the author


# ---- delete (author or any CL; UGL only own) ----
def test_cl_moderation_delete_any(ctx):
    _, created = _create(ctx, role="UserGroupLeader", sub="uugl", led="g1")
    ann_id = created["id"]
    status, _ = _call(ctx, method="DELETE", path=f"/announcements/{ann_id}",
                      role="CommunityLeader", sub="ucl-mod")
    assert status == 204  # CL deletes another author's announcement for moderation


def test_ugl_cannot_delete_others(ctx):
    _, created = _create(ctx, role="CommunityLeader", sub="ucl", target={"scope": "community"})
    ann_id = created["id"]
    status, _ = _call(ctx, method="DELETE", path=f"/announcements/{ann_id}",
                      role="UserGroupLeader", sub="uugl-2", led="g9")
    assert status == 403


def test_member_cannot_delete(ctx):
    _, created = _create(ctx, role="CommunityLeader", sub="ucl", target={"scope": "community"})
    status, _ = _call(ctx, method="DELETE", path=f"/announcements/{created['id']}",
                      role="Member", sub="um")
    assert status == 403


# ---- panel / mine reads ----
def test_member_can_read_panel(ctx):
    status, _ = _call(ctx, method="GET", path="/announcements", role="Member", sub="um")
    assert status == 200


def test_administrator_denied_on_panel_read(ctx):
    status, _ = _call(ctx, method="GET", path="/announcements", role="Administrator", sub="ua")
    assert status == 403  # BR-3 — Administrator denied even on reads


def test_view_mine_requires_leader(ctx):
    cl, _ = _call(ctx, method="GET", path="/announcements", role="CommunityLeader", sub="ucl",
                  qs={"view": "mine"})
    assert cl == 200
    member, _ = _call(ctx, method="GET", path="/announcements", role="Member", sub="um",
                      qs={"view": "mine"})
    assert member == 403


def test_scope_all_is_cl_only(ctx):
    cl, _ = _call(ctx, method="GET", path="/announcements", role="CommunityLeader", sub="ucl",
                  qs={"view": "mine", "scope": "all"})
    assert cl == 200
    ugl, _ = _call(ctx, method="GET", path="/announcements", role="UserGroupLeader", sub="uugl",
                   led="g1", qs={"view": "mine", "scope": "all"})
    assert ugl == 403


def test_dismiss_route_removed(ctx):
    # Dismissal is client-side only (BR-11) — the server op was removed (v2.0.0).
    status, _ = _call(ctx, method="POST", path="/announcements/x/dismiss", role="Member", sub="um")
    assert status == 404
