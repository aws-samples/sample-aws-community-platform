"""Claim-addressed revoke (US-5.8, D9).

CL (any group) + UGL (only certs credited to their led group, 404 outside it,
no self-revoke — change request 2026-08-07). Target must be Approved, reason
required. The badge disappears because
every badge read filters on Approved; the slot delete frees resubmission
(BR-C2); points are NEVER reversed — the event says so explicitly so a future
Contributions consumer cannot mis-infer (BR-R2).
"""
from __future__ import annotations

from _conventions.errors import ConflictError, ForbiddenError, NotFoundError
from _conventions.validation import require_str
from models import ROLE_UGL, STATUS_APPROVED, STATUS_REVOKED, now_iso, owner_claim


class RevocationService:
    def __init__(self, repo, events, identity=None):
        self._repo = repo
        self._events = events
        self._identity = identity

    def _led_group(self, principal, bearer_token: str | None) -> str:
        """UGL scope resolution (mirror of VerificationService): JWT claim first,
        Identity REST fallback, DENY when unresolvable — never 'all groups'."""
        led = principal.led_group_id
        if not led and self._identity is not None:
            led = self._identity.led_group_id(principal.user_id, bearer_token=bearer_token)
        if not led:
            raise ForbiddenError(message="Your led group could not be determined.")
        return led

    def revoke(self, claim_id: str, body: dict, *, principal,
               bearer_token: str | None = None,
               correlation_id: str | None = None) -> dict:
        reason = require_str(body.get("reason"), "reason", max_len=500)
        claim = self._repo.get_claim(claim_id)
        if not claim:
            raise NotFoundError()
        # Q1=A: a UGL may revoke ONLY certifications credited to the group they
        # lead — 404-not-403 outside it (don't reveal existence, BR-A5). A CL is
        # unscoped. Scope is checked before status so an out-of-scope claim's
        # state never leaks.
        if principal.role == ROLE_UGL:
            if claim.get("creditedGroupId") != self._led_group(principal, bearer_token):
                raise NotFoundError()
        # Q2=A: no self-revoke — a UGL cannot revoke their own certification
        # (mirrors no-self-approval, BR-V5). Harmless for a CL (never a holder).
        if claim.get("memberId") == principal.user_id:
            raise ForbiddenError(message="You cannot revoke your own certification.")
        if claim.get("status") != STATUS_APPROVED:
            raise ConflictError(message="Only an approved certification can be revoked.")
        revoked_at = now_iso()
        self._repo.transition_to_terminal(
            claim, new_status=STATUS_REVOKED, expected_status=STATUS_APPROVED,
            extra_sets={"revokeReason": reason, "revokedAt": revoked_at,
                        "revokedBy": principal.user_id})
        self._events.publish("CertificationRevoked", {
            "claimId": claim["id"], "certId": claim["certId"],
            "certName": claim.get("certName"),
            "memberId": claim["memberId"], "groupId": claim["creditedGroupId"],
            "reason": reason, "pointsReversed": False,
            "revokedAt": revoked_at, "revokedBy": principal.user_id,
        }, correlation_id=correlation_id)
        updated = self._repo.get_claim(claim["id"])
        return owner_claim(updated or claim)
