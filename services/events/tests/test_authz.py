"""MANDATORY authorization-matrix suite (NFR-EV-MAINT-1).

Every operation x every role x ownership. Two rules here are counter-intuitive
enough that someone will eventually "fix" them into bugs, so they are pinned
explicitly with the reasoning attached:

* **BR-A1** — Administrators are denied on EVERY /events operation, *including
  plain reads*. The permission matrix contains zero event entries for them and no
  mockup shows Administrators an Events nav item. Read access would be an
  invention, not an oversight.
* **BR-A5** — a creator who has since been demoted to Member KEEPS edit/cancel
  rights on events they created. US-2.4 requires it, and it is the one case where
  a Member-role principal legitimately passes a leader-only check.
"""
from __future__ import annotations

import pytest
from _conventions.errors import ForbiddenError, NotFoundError
from conftest import FakePrincipal, event_input, make_event

# --------------------------------------------------------------- create rights

def test_community_leader_can_create_community_wide(ctx, cl):
    created = ctx.event_service.create(event_input(groupId=None), principal=cl)
    assert created["groupId"] is None


def test_community_leader_can_create_for_any_group(ctx, cl):
    created = ctx.event_service.create(event_input(groupId="g-ml"), principal=cl)
    assert created["groupId"] == "g-ml"


def test_ugl_can_create_for_own_group(ctx, ugl):
    created = ctx.event_service.create(event_input(groupId="g-serverless"), principal=ugl)
    assert created["groupId"] == "g-serverless"


def test_ugl_cannot_create_for_another_group(ctx, ugl):
    with pytest.raises(ForbiddenError):
        ctx.event_service.create(event_input(groupId="g-ml"), principal=ugl)


def test_ugl_cannot_create_community_wide(ctx, ugl):
    """Community-wide is a Community-Leader capability (BR-A3). `groupId=None`
    must not be a loophole."""
    with pytest.raises(ForbiddenError):
        ctx.event_service.create(event_input(groupId=None), principal=ugl)


def test_member_cannot_create(ctx, member):
    with pytest.raises(ForbiddenError):
        ctx.event_service.create(event_input(), principal=member)


def test_administrator_cannot_create(ctx, admin):
    with pytest.raises(ForbiddenError):
        ctx.event_service.create(event_input(), principal=admin)


# ------------------------------------------------------- BR-A1 admin lockout

def test_administrator_denied_on_list(ctx, admin):
    """Not a typo: reads too (BR-A1)."""
    with pytest.raises(ForbiddenError):
        ctx.event_service.list(principal=admin, filters={}, limit=25, cursor=None)


def test_administrator_denied_on_get(ctx, cl, admin):
    created = make_event(ctx, cl)
    # 404 rather than 403 for a read, because visibility is evaluated before
    # anything else and an Administrator can see no events at all (BR-A8).
    with pytest.raises(NotFoundError):
        ctx.event_service.get(created["id"], principal=admin)


def test_administrator_denied_on_rsvp(ctx, cl, admin):
    created = make_event(ctx, cl)
    with pytest.raises(ForbiddenError):
        ctx.rsvps.respond(created["id"], {"response": "yes"}, principal=admin)


# ------------------------------------------------ visibility: 404, never 403

def test_out_of_scope_member_gets_404_not_403(ctx, cl, other_member):
    """A member outside the event's group must not be able to tell the event
    exists (BR-A8) — the response is identical to a genuinely absent id."""
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(NotFoundError):
        ctx.event_service.get(created["id"], principal=other_member)


def test_community_wide_event_visible_to_any_member(ctx, cl, other_member):
    created = ctx.event_service.create(event_input(groupId=None), principal=cl)
    assert ctx.event_service.get(created["id"], principal=other_member)["id"] == created["id"]


def test_member_of_group_can_view(ctx, cl, member):
    created = make_event(ctx, cl, groupId="g-serverless")
    assert ctx.event_service.get(created["id"], principal=member)["id"] == created["id"]


# --------------------------------------------------------- manage rights

def test_ugl_can_manage_cl_created_event_in_own_group(ctx, cl, ugl):
    """US-2.4 explicitly: a UGL may edit any event scoped to their led group even
    when a Community Leader created it."""
    created = make_event(ctx, cl, groupId="g-serverless")
    updated = ctx.event_service.edit(created["id"], event_input(title="Renamed"), principal=ugl)
    assert updated["title"] == "Renamed"


def test_ugl_cannot_manage_other_group_event(ctx, cl, ugl):
    created = make_event(ctx, cl, groupId="g-ml")
    with pytest.raises(NotFoundError):
        # The UGL cannot even see it, so 404 precedes any manage check.
        ctx.event_service.edit(created["id"], event_input(), principal=ugl)


def test_member_cannot_manage(ctx, cl, member):
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(ForbiddenError):
        ctx.event_service.edit(created["id"], event_input(), principal=member)


def test_member_cannot_view_rsvp_list(ctx, cl, member):
    """Aggregate counts are public to viewers; the per-member list is not
    (BR-C5)."""
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(ForbiddenError):
        ctx.rsvps.list_for_event(created["id"], principal=member)


def test_member_cannot_manage_materials(ctx, cl, member):
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(ForbiddenError):
        ctx.materials.add(created["id"], {"name": "x", "link": "https://e.test/x"},
                          principal=member)


def test_member_can_download_materials_without_rsvp(ctx, cl, member):
    """BR-A7 — viewing the event is enough; RSVP is not a precondition."""
    created = make_event(ctx, cl, groupId="g-serverless")
    ctx.materials.add(created["id"], {"name": "Slides", "link": "https://e.test/s"},
                      principal=cl)
    listed = ctx.materials.list_for_event(created["id"], principal=member)
    assert listed["count"] == 1


# ------------------------------------------- BR-A5 demoted creator keeps rights

def test_demoted_creator_retains_edit_rights(ctx, ugl):
    """The creator is a UGL at create time and a plain Member afterwards. Rights
    key on the immutable `createdBy`, so they survive the demotion (BR-A5,
    US-2.4). If this test ever fails because someone tightened the role check,
    the requirement is what broke, not the test."""
    created = ctx.event_service.create(event_input(groupId="g-serverless"), principal=ugl)

    demoted = FakePrincipal(ugl.user_id, "Member", member_group_ids=["g-serverless"])
    updated = ctx.event_service.edit(created["id"], event_input(title="Still mine"),
                                     principal=demoted)
    assert updated["title"] == "Still mine"


def test_demoted_creator_retains_cancel_rights(ctx, ugl):
    created = ctx.event_service.create(event_input(groupId="g-serverless"), principal=ugl)
    demoted = FakePrincipal(ugl.user_id, "Member", member_group_ids=["g-serverless"])
    ctx.event_service.cancel(created["id"], principal=demoted)
    assert ctx.repo.get_event(created["id"])["status"] == "Cancelled"


def test_demotion_does_not_grant_rights_over_others_events(ctx, cl, ugl):
    """The escape hatch is scoped to ownership only — a demoted leader does not
    keep blanket group powers."""
    created = make_event(ctx, cl, groupId="g-serverless")
    demoted = FakePrincipal(ugl.user_id, "Member", member_group_ids=["g-serverless"])
    with pytest.raises(ForbiddenError):
        ctx.event_service.edit(created["id"], event_input(), principal=demoted)


# --------------------------------------------------- upload links + attendance

def test_member_cannot_create_upload_link(ctx, cl, member):
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(ForbiddenError):
        ctx.upload_links.create(created["id"], {"expiryDays": 7}, principal=member)


def test_member_cannot_record_attendance(ctx, cl, member):
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(ForbiddenError):
        ctx.attendance.record(created["id"], {"userIds": ["u-mem-1"]}, principal=member)


def test_member_cannot_set_designations(ctx, cl, member):
    created = make_event(ctx, cl, groupId="g-serverless")
    with pytest.raises(ForbiddenError):
        ctx.designations.set(created["id"], {"presenters": ["u-mem-1"]}, principal=member)
