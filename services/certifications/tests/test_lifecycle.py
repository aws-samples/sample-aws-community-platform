"""Mandatory suite 2 (NFR-CT-MAINT-1): lifecycle transitions.

Every illegal transition -> 409; freeze-at-approval invariants (BR-V6/V7);
the duplicate rule across all six states (BR-C2 via the claim slot).
"""
from __future__ import annotations

import pytest
from _conventions.errors import ConflictError
from conftest import make_definition, raises_message, submit_claim
from models import STATUS_APPROVED, STATUS_EXPIRED


def _approve(ctx, cl, claim_id):
    return ctx.verifications.decide(claim_id, {"decision": "approve"},
                                    principal=cl, bearer_token=None)


def test_pending_to_approved_freezes_points_and_expiry(ctx, cl, member, aws):
    definition = make_definition(ctx, cl, points=25, expiryPeriodMonths=36)
    claim = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    approved = _approve(ctx, cl, claim["id"])
    assert approved["status"] == STATUS_APPROVED
    assert approved["pointsAwarded"] == 25
    assert approved["expiresAt"] == "2029-06-01"  # dateEarned + 36 months (D8)

    # BR-V6: re-pricing the definition NEVER touches the approved claim.
    ctx.definitions.edit(definition["id"], {"points": 99, "expiryPeriodMonths": 12},
                         principal=cl)
    stored = ctx.repo.get_claim(claim["id"])
    assert stored["pointsAwarded"] == 25
    assert stored["expiresAt"] == "2029-06-01"


def test_expiry_anchor_uses_date_earned_even_when_expiry_added_later(ctx, cl, member, aws):
    """D8 + BR-C5′: earned date is always supplied now, so expiry anchors on the
    member's dateEarned. Even if the definition had no expiry at submission and
    gains one before approval, the frozen expiresAt is dateEarned + period.
    (The legacy approval-date fallback remains in code for pre-BR-C5′ claims that
    never captured an earned date, but submission can no longer produce one.)"""
    definition = make_definition(ctx, cl, expiryPeriodMonths=None)
    claim = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    ctx.definitions.edit(definition["id"], {"expiryPeriodMonths": 24}, principal=cl)
    approved = _approve(ctx, cl, claim["id"])
    assert approved["expiresAt"] == "2028-06-01"  # dateEarned + 24 months


def test_approval_that_would_be_born_expired_is_409(ctx, cl, member, aws):
    """BR-V7: the definition's period shrank between submission and approval."""
    definition = make_definition(ctx, cl, expiryPeriodMonths=240)
    claim = submit_claim(ctx, member, definition["id"], dateEarned="2020-01-15")
    ctx.definitions.edit(definition["id"], {"expiryPeriodMonths": 12}, principal=cl)
    with raises_message(ConflictError, "already be expired"):
        _approve(ctx, cl, claim["id"])
    # Still Pending — the leader rejects it instead.
    assert ctx.repo.get_claim(claim["id"])["status"] == "Pending"


def test_double_decision_is_409(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    _approve(ctx, cl, claim["id"])
    with pytest.raises(ConflictError):
        ctx.verifications.decide(claim["id"], {"decision": "reject", "reason": "no"},
                                 principal=cl, bearer_token=None)


def test_withdraw_only_while_pending(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    _approve(ctx, cl, claim["id"])
    with raises_message(ConflictError, "pending"):
        ctx.claims.withdraw(claim["id"], principal=member)


def test_revoke_only_from_approved(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    with raises_message(ConflictError, "approved"):
        ctx.revocations.revoke(claim["id"], {"reason": "fake"}, principal=cl)
    _approve(ctx, cl, claim["id"])
    revoked = ctx.revocations.revoke(claim["id"], {"reason": "fake evidence"}, principal=cl)
    assert revoked["status"] == "Revoked"
    assert revoked["revokeReason"] == "fake evidence"
    # Revoking twice -> 409.
    with pytest.raises(ConflictError):
        ctx.revocations.revoke(claim["id"], {"reason": "again"}, principal=cl)


def test_reject_requires_reason(ctx, cl, member, aws):
    from _conventions.errors import ValidationError
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    with pytest.raises(ValidationError):
        ctx.verifications.decide(claim["id"], {"decision": "reject"},
                                 principal=cl, bearer_token=None)


# ------------------------------------------------------ duplicate rule (BR-C2)

def test_duplicate_blocked_while_pending_and_approved(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    submit_claim(ctx, member, definition["id"])
    with raises_message(ConflictError, "pending or approved"):
        submit_claim(ctx, member, definition["id"], group="g-ml")  # across ALL groups


def test_duplicate_allowed_after_each_terminal_state(ctx, cl, member, aws):
    """Rejected, Withdrawn, Revoked, Expired each free the slot (BR-W2)."""
    definition = make_definition(ctx, cl)

    # Rejected -> resubmit OK
    c1 = submit_claim(ctx, member, definition["id"])
    ctx.verifications.decide(c1["id"], {"decision": "reject", "reason": "blurry"},
                             principal=cl, bearer_token=None)
    # Withdrawn -> resubmit OK
    c2 = submit_claim(ctx, member, definition["id"])
    ctx.claims.withdraw(c2["id"], principal=member)
    # Revoked -> resubmit OK
    c3 = submit_claim(ctx, member, definition["id"])
    _approve(ctx, cl, c3["id"])
    ctx.revocations.revoke(c3["id"], {"reason": "invalid"}, principal=cl)
    # Expired -> resubmit OK (drive expiry via the repo transition)
    c4 = submit_claim(ctx, member, definition["id"])
    _approve(ctx, cl, c4["id"])
    stored = ctx.repo.get_claim(c4["id"])
    ctx.repo.transition_to_terminal(stored, new_status=STATUS_EXPIRED,
                                    expected_status=STATUS_APPROVED,
                                    extra_sets={"expiredAt": "2026-08-06T00:00:00Z"})
    c5 = submit_claim(ctx, member, definition["id"])
    assert c5["status"] == "Pending"
    # History retained: all five claims exist.
    assert len(ctx.repo.list_member_claims(member.user_id)) == 5


def test_concurrent_submit_race_cannot_double_claim(ctx, cl, member, aws):
    """The slot's conditional put IS the rule — no query-then-write window."""
    definition = make_definition(ctx, cl)
    submit_claim(ctx, member, definition["id"])
    with pytest.raises(ConflictError):
        # Direct repo-level second create simulating the race loser.
        from models import now_iso
        ctx.repo.create_claim({
            "id": "clm-race", "certId": definition["id"], "memberId": member.user_id,
            "creditedGroupId": "g-ml", "status": "Pending", "submittedAt": now_iso(),
        })


def test_slot_tracks_holder_status(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    claim = submit_claim(ctx, member, definition["id"])
    slot = ctx.repo.get_slot(definition["id"], member.user_id)
    assert slot["status"] == "Pending"
    _approve(ctx, cl, claim["id"])
    assert ctx.repo.get_slot(definition["id"], member.user_id)["status"] == "Approved"
    ctx.revocations.revoke(claim["id"], {"reason": "x"}, principal=cl)
    assert ctx.repo.get_slot(definition["id"], member.user_id) is None
