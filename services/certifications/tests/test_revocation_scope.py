"""UGL revoke scope (change request 2026-08-07).

Revoke gained group scoping: a UGL may revoke ONLY certifications credited to
the group they lead (404 outside it, don't reveal existence) and never their
own certification (403). A CL remains unscoped.
"""
from __future__ import annotations

from _conventions.errors import ForbiddenError, NotFoundError
from conftest import (
    FakePrincipal,
    make_definition,
    raises_message,
    submit_claim,
)


def _approved(ctx, cl, member, *, group="g-serverless"):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"], group=group)
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    return claim


def test_ugl_revokes_a_claim_credited_to_its_led_group(ctx, cl, ugl, member, aws):
    claim = _approved(ctx, cl, member, group="g-serverless")  # ugl leads g-serverless
    revoked = ctx.revocations.revoke(claim["id"], {"reason": "invalid evidence"},
                                     principal=ugl, bearer_token="tok:u-ugl")
    assert revoked["status"] == "Revoked"


def test_ugl_cannot_revoke_a_claim_credited_to_another_group_404(ctx, cl, ugl, member, aws):
    """404-not-403: an out-of-scope reviewer must not learn the claim exists."""
    claim = _approved(ctx, cl, member, group="g-ml")  # not ugl's led group
    with raises_message(NotFoundError, ""):
        ctx.revocations.revoke(claim["id"], {"reason": "x"},
                               principal=ugl, bearer_token="tok:u-ugl")


def test_ugl_cannot_revoke_their_own_certification_403(ctx, cl, ugl, aws):
    """Q2=A: no self-revoke (mirrors no-self-approval). The UGL's own claim is
    credited to their led group, so it passes the scope check — the owner guard
    is what stops it."""
    definition = make_definition(ctx, cl)
    own = submit_claim(ctx, ugl, definition["id"])  # credited to the led group
    ctx.verifications.decide(own["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)  # CL approves it
    with raises_message(ForbiddenError, "your own certification"):
        ctx.revocations.revoke(own["id"], {"reason": "x"},
                               principal=ugl, bearer_token="tok:u-ugl")


def test_ugl_with_unresolvable_led_group_is_denied(ctx, cl, member, aws):
    claim = _approved(ctx, cl, member, group="g-serverless")
    ctx.fake_identity.led = {}
    lost = FakePrincipal("u-ugl", "UserGroupLeader", led_group_id=None)
    with raises_message(ForbiddenError, "led group"):
        ctx.revocations.revoke(claim["id"], {"reason": "x"},
                               principal=lost, bearer_token="tok:u-ugl")


def test_cl_revokes_any_group(ctx, cl, member, aws):
    claim = _approved(ctx, cl, member, group="g-ml")
    revoked = ctx.revocations.revoke(claim["id"], {"reason": "invalid"}, principal=cl)
    assert revoked["status"] == "Revoked"
