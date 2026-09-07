"""Definitions + catalog (US-5.1/5.2/5.3/5.10)."""
from __future__ import annotations

import pytest
from _conventions.errors import ConflictError, ValidationError
from conftest import call, make_definition, raises_message, submit_claim


def test_create_publishes_immediately_with_full_fields(ctx, cl):
    definition = make_definition(ctx, cl)
    assert definition["active"] is True
    assert definition["category"] == "AWS Certification"
    assert definition["points"] == 25
    assert definition["expiryPeriodMonths"] == 36


def test_create_validates_fields(ctx, cl):
    with pytest.raises(ValidationError):
        ctx.definitions.create({"name": "X", "description": "d",
                                "category": "Nope", "points": 5}, principal=cl)
    with pytest.raises(ValidationError):
        ctx.definitions.create({"name": "X", "description": "d",
                                "category": "Community Badge", "points": -1},
                               principal=cl)


def test_catalog_shows_active_only_with_held_and_pending_flags(ctx, cl, member, aws):
    held_def = make_definition(ctx, cl, name="Held Cert")
    pending_def = make_definition(ctx, cl, name="Pending Cert")
    inactive = make_definition(ctx, cl, name="Old Cert")
    ctx.definitions.edit(inactive["id"], {"active": False}, principal=cl)

    held_claim = submit_claim(ctx, member, held_def["id"])
    ctx.verifications.decide(held_claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    submit_claim(ctx, member, pending_def["id"])

    catalog = ctx.definitions.catalog(principal=member)
    names = [i["name"] for i in catalog["items"]]
    assert "Old Cert" not in names  # US-5.3 hidden
    by_name = {i["name"]: i for i in catalog["items"]}
    assert by_name["Held Cert"]["held"] is True
    assert by_name["Held Cert"]["heldExpiresAt"]  # countdown source (mockup)
    assert by_name["Pending Cert"]["pendingClaim"] is True


def test_leaders_see_inactive_via_include_inactive(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    ctx.definitions.edit(definition["id"], {"active": False}, principal=cl)
    status, body = call(ctx, "GET", "/certifications", principal=cl,
                        qs={"includeInactive": "true"})
    assert body["count"] == 1
    # Members asking for includeInactive don't get it (leader-only param).
    status, body = call(ctx, "GET", "/certifications", principal=member,
                        qs={"includeInactive": "true"})
    assert body["count"] == 0


def test_deactivated_cert_rejects_new_claims_server_side(ctx, cl, member, aws):
    """BR-C1 — UI hiding is not enforcement."""
    definition = make_definition(ctx, cl)
    ctx.definitions.edit(definition["id"], {"active": False}, principal=cl)
    with raises_message(ConflictError, "not available"):
        submit_claim(ctx, member, definition["id"])


def test_deactivate_keeps_holder_badges_and_reactivates(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    ctx.definitions.edit(definition["id"], {"active": False}, principal=cl)
    # Badge still readable via listClaims (US-5.3: holders keep badges).
    result = ctx.claims.list_claims({"memberId": member.user_id}, principal=cl)
    assert result["count"] == 1
    # Reactivation any time.
    updated = ctx.definitions.edit(definition["id"], {"active": True}, principal=cl)
    assert updated["active"] is True


def test_pending_claims_remain_decidable_after_deactivation(ctx, cl, member, aws):
    """US-5.3 hides from NEW claims; an in-flight claim may still be honored."""
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    ctx.definitions.edit(definition["id"], {"active": False}, principal=cl)
    approved = ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                        principal=cl, bearer_token=None)
    assert approved["status"] == "Approved"


def test_edit_name_flows_into_badge_display(ctx, cl, member, aws):
    """US-5.2 reading: renaming a cert renames the badge everywhere (the claim
    read joins the definition)."""
    definition = make_definition(ctx, cl, name="Old Name")
    claim = submit_claim(ctx, member, definition["id"])
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    ctx.definitions.edit(definition["id"], {"name": "New Name"}, principal=cl)
    result = ctx.claims.list_claims({"memberId": member.user_id}, principal=cl)
    assert result["items"][0]["certName"] == "New Name"


def test_expiry_period_can_be_cleared_with_null(ctx, cl):
    definition = make_definition(ctx, cl, expiryPeriodMonths=36)
    updated = ctx.definitions.edit(definition["id"], {"expiryPeriodMonths": None},
                                   principal=cl)
    assert "expiryPeriodMonths" not in updated
