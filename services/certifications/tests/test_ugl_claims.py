"""UGL certification claims (change request 2026-08-07).

A User Group Leader may claim a certificate like a Member, with three behaviours
that differ from a Member and are the point of this suite:
- Q1=A: the claim is credited to the group the UGL LEADS, not a group they are a
  member of (a UGL need not be a member of any group).
- Q3=B: an approved UGL claim earns ZERO points, but still holds the badge.
- The UGL's own claim is NOT shown in (or counted by) their own Pending
  Verifications queue — it is verified only by a Community Leader (BR-V5 also
  blocks self-decision server-side).
"""
from __future__ import annotations

from _conventions.errors import ForbiddenError
from conftest import (
    FakePrincipal,
    call,
    make_definition,
    raises_message,
    submit_claim,
)

# ------------------------------------------------------------- credited group

def test_ugl_claim_is_credited_to_the_led_group_ignoring_body(ctx, cl, ugl, aws):
    """Q1=A: leadership, not membership, is the credit basis. The UGL leads
    g-serverless and is a member of nothing; a body creditedGroupId is ignored
    in favour of the led group."""
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, ugl, definition["id"], group="g-ml")  # not their led group
    assert claim["creditedGroupId"] == "g-serverless"
    assert claim["status"] == "Pending"


def test_ugl_led_group_resolved_via_identity_fallback(ctx, cl, aws):
    """JWT claim absent -> Identity REST fallback resolves the led group."""
    definition = make_definition(ctx, cl)
    clueless = FakePrincipal("u-ugl", "UserGroupLeader", led_group_id=None)
    claim = submit_claim(ctx, clueless, definition["id"])
    assert claim["creditedGroupId"] == "g-serverless"


def test_ugl_claim_fails_closed_when_led_group_unresolvable(ctx, cl, aws):
    """Fail-closed: a claim credited to an unverified group would corrupt
    routing, so an unresolvable led group is a 503, never a guess."""
    definition = make_definition(ctx, cl)
    ctx.fake_identity.led = {}
    lost = FakePrincipal("u-ugl", "UserGroupLeader", led_group_id=None)
    status, _ = call(ctx, "POST", "/certifications/claims", principal=lost,
                     body={"certId": definition["id"], "creditedGroupId": "g-serverless",
                           "evidenceUrl": "https://e.test/x", "dateEarned": "2026-06-01"})
    assert status == 503


# ------------------------------------------------------------- points (Q3=B)

def test_ugl_approved_claim_earns_zero_points_but_holds_the_badge(ctx, cl, ugl, aws):
    definition = make_definition(ctx, cl, points=40)
    claim = submit_claim(ctx, ugl, definition["id"])
    approved = ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                        principal=cl, bearer_token=None)
    assert approved["status"] == "Approved"        # badge holds (Q4=A)
    assert approved["pointsAwarded"] == 0          # but zero points (Q3=B)
    event = [e for e in ctx.events.published if e["type"] == "CertificationApproved"][-1]
    assert event["data"]["points"] == 0            # scoring credits nothing


def test_member_approved_claim_still_earns_definition_points(ctx, cl, member, aws):
    """Guard against a regression: the eligibility gate must not zero out
    Members. (pointsEligible defaults True for pre-change claims too.)"""
    definition = make_definition(ctx, cl, points=40)
    claim = submit_claim(ctx, member, definition["id"])
    approved = ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                        principal=cl, bearer_token=None)
    assert approved["pointsAwarded"] == 40


# ------------------------------------------- own claim excluded from own queue

def test_ugl_own_claim_is_not_in_their_own_queue(ctx, cl, ugl, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, ugl, definition["id"])

    # The UGL's own claim must NOT appear in — or be counted by — their queue.
    queue = ctx.verifications.queue({}, principal=ugl, bearer_token=None)
    assert all(r["id"] != claim["id"] for r in queue["items"])
    assert queue["count"] == 0
    count_only = ctx.verifications.queue({"countOnly": "true"}, principal=ugl,
                                         bearer_token=None)
    assert count_only["count"] == 0

    # And even if it somehow reached decide(), the UGL cannot self-decide (BR-V5).
    with raises_message(ForbiddenError, "own claim"):
        ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                 principal=ugl, bearer_token=None)


def test_ugl_own_claim_is_verified_by_a_community_leader(ctx, cl, ugl, aws):
    """It disappears from the UGL's queue but is fully present in the CL's, who
    verifies it."""
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, ugl, definition["id"])

    cl_queue = ctx.verifications.queue({}, principal=cl, bearer_token=None)
    assert any(r["id"] == claim["id"] for r in cl_queue["items"])
    approved = ctx.verifications.decide(claim["id"], {"decision": "approve"},
                                        principal=cl, bearer_token=None)
    assert approved["status"] == "Approved"
