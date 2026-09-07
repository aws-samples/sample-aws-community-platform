"""Verification queue + decisions (US-5.6/5.7).

Routing is purely creditedGroupId-based (BR-V1), so leader-change reassignment
needs no code: a newly assigned UGL's queue query immediately returns the
group's pending claims, a removed UGL loses them, CLs always see everything —
nothing stored per leader, nothing orphaned.
"""
from __future__ import annotations

from _conventions.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from _conventions.validation import require_enum, require_str
from models import (
    ROLE_CL,
    ROLE_UGL,
    SCAN_CLEAN,
    SCAN_NONE,
    STATUS_PENDING,
    compute_expires_at,
    now_iso,
    owner_claim,
    parse_iso_date,
    queue_claim,
    today_iso,
)

REVIEWABLE_SCANS = {SCAN_NONE, SCAN_CLEAN}

_DEFAULT_PAGE = 25
_MAX_PAGE = 100


def _parse_limit(raw) -> int:
    """Queue page size: optional, integer, 1..100 (matches the DataTable Rows
    options). Malformed/out-of-range input is a client error, not a 500."""
    if raw is None or raw == "":
        return _DEFAULT_PAGE
    try:
        limit = int(raw)
    except (ValueError, TypeError):
        raise ValidationError("limit must be an integer.") from None
    if not 1 <= limit <= _MAX_PAGE:
        raise ValidationError(f"limit must be between 1 and {_MAX_PAGE}.")
    return limit


class VerificationService:
    def __init__(self, repo, storage, identity, events, metrics=None):
        self._repo = repo
        self._storage = storage
        self._identity = identity
        self._events = events
        self._metrics = metrics

    # ------------------------------------------------------------------ scope

    def _led_group(self, principal, bearer_token: str | None) -> str:
        """UGL scope resolution (D4): JWT claim first, Identity REST fallback,
        DENY when unresolvable — never 'all groups' (BR-A4, fail closed)."""
        led = principal.led_group_id
        if not led:
            led = self._identity.led_group_id(principal.user_id, bearer_token=bearer_token)
        if not led:
            raise ForbiddenError(message="Your led group could not be determined.")
        return led

    def _decision_scope_check(self, claim: dict, principal, bearer_token: str | None) -> None:
        if principal.role == ROLE_CL:
            return
        if principal.role == ROLE_UGL:
            if claim.get("creditedGroupId") != self._led_group(principal, bearer_token):
                # 404-not-403: an out-of-scope reviewer must not learn the
                # claim exists (BR-A5 discipline applied to group scope).
                raise NotFoundError()
            return
        raise ForbiddenError()

    # ------------------------------------------------------------------ queue

    def queue(self, filters: dict, *, principal, bearer_token: str | None) -> dict:
        cert_filter = filters.get("certId")
        group_filter = filters.get("groupId")
        count_only = str(filters.get("countOnly", "")).lower() == "true"

        led = None
        if principal.role == ROLE_UGL:
            led = self._led_group(principal, bearer_token)
            group_filter = None  # UGL scope IS the group filter (single group)

        def predicate(row: dict) -> bool:
            if row.get("status") != STATUS_PENDING:
                return False  # defensive; the sparse index should only hold Pending
            # A reviewer never verifies their OWN claim (BR-V5). A UGL's claim is
            # credited to their led group, but it must be decided ONLY by a
            # Community Leader — so it must not appear in, or be counted by, the
            # UGL's own Pending Verifications queue. It still surfaces in the CL's
            # queue (a CL cannot submit, so this never hides a CL's own claim).
            if row.get("memberId") == principal.user_id:
                return False
            if led and row.get("creditedGroupId") != led:
                return False
            if group_filter and row.get("creditedGroupId") != group_filter:
                return False
            if cert_filter and row.get("certId") != cert_filter:
                return False
            return True

        if count_only:
            # PendingScan claims are visible but not decidable (BR-V3); the nav
            # badge counts actionable work, so it counts ALL pending (they will
            # become decidable) — same number the queue table shows.
            return {"items": [], "count": self._repo.count_pending(predicate=predicate)}

        # Cursor pagination (2026-08-08, thousands-pending at CL scale — mirrors
        # the admin user list): oldest-first, opaque forward-only cursor.
        limit = _parse_limit(filters.get("limit"))
        claims, next_cursor = self._repo.query_pending_page(
            limit=limit, cursor=filters.get("cursor") or None, predicate=predicate)
        # A caller's own claim is never in their queue (excluded above), so every
        # row here is one the caller may actually decide.
        items = [queue_claim(c) for c in claims]
        out = {"items": items, "count": len(items)}
        if next_cursor:
            out["cursor"] = next_cursor
        return out

    # --------------------------------------------------------------- decision

    def decide(self, claim_id: str, body: dict, *, principal, bearer_token: str | None,
               correlation_id: str | None = None) -> dict:
        decision = require_enum(body.get("decision"), "decision", {"approve", "reject"})
        claim = self._repo.get_claim(claim_id)
        if not claim:
            raise NotFoundError()
        self._decision_scope_check(claim, principal, bearer_token)
        if claim.get("status") != STATUS_PENDING:
            raise ConflictError(message="The claim has already been decided.")
        if claim.get("scanStatus", SCAN_NONE) not in REVIEWABLE_SCANS:
            # BR-V3: not reviewable until the evidence scan is Clean.
            raise ConflictError(message="The evidence file has not finished scanning.")
        if claim.get("memberId") == principal.user_id:
            # BR-V5 defense-in-depth: leaders can't submit, but a role change
            # mid-flight must not allow self-approval.
            raise ForbiddenError(message="You cannot decide your own claim.")

        if decision == "approve":
            return self._approve(claim, principal, correlation_id)
        reason = require_str(body.get("reason"), "reason", max_len=500)
        return self._reject(claim, principal, reason, correlation_id)

    def _approve(self, claim: dict, principal, correlation_id) -> dict:
        definition = self._repo.get_definition(claim["certId"])
        if not definition:
            raise ConflictError(message="The certification definition no longer exists.")
        decided_at = now_iso()
        # Freeze at approval (BR-V6): the ledger-bound number and the expiry
        # date must not drift if the definition is re-priced/re-perioded later.
        # Points eligibility was frozen at submission (change request Q3=B): a
        # UGL's claim holds the badge but earns zero. Default True keeps
        # pre-change member claims (no field) awarding normally.
        eligible = claim.get("pointsEligible", True)
        points = int(definition.get("points", 0)) if eligible else 0
        expires_at = None
        months = definition.get("expiryPeriodMonths")
        if months:
            anchor = (parse_iso_date(claim["dateEarned"]) if claim.get("dateEarned")
                      else parse_iso_date(today_iso(), "today"))
            expires_at = compute_expires_at(anchor, int(months))
            if expires_at <= today_iso():
                # BR-V7: a badge must never be born expired (the definition's
                # period may have shrunk since submission passed BR-C6).
                raise ConflictError(
                    message="This certification would already be expired per its date "
                            "earned — reject the claim instead.")

        self._repo.transition_to_approved(
            claim, decided_by=principal.user_id, decided_at=decided_at,
            points=points, expires_at=expires_at)
        self._events.publish("CertificationApproved", {
            "idempotencyKey": f"{claim['certId']}#{claim['memberId']}#approved",
            "claimId": claim["id"], "certId": claim["certId"],
            "certName": definition.get("name"),
            "memberId": claim["memberId"], "groupId": claim["creditedGroupId"],
            # Denormalise the member name onto the award event so the point-ledger
            # row carries it directly (same pattern as contributions), instead of
            # relying on the scoring service's member projection — which is empty
            # for members that predate the identity→scoring projection wiring and
            # left cert rows reading "Unknown member".
            "memberName": claim.get("memberName"),
            "points": points,
            "dateEarned": claim.get("dateEarned"),
            # Unit 7 DL13: attribute cert points to the SUBMISSION quarter (US-6.12).
            "submittedAt": claim.get("submittedAt"),
            "expiresAt": expires_at,
            "decidedAt": decided_at, "decidedBy": principal.user_id,
        }, correlation_id=correlation_id)
        updated = self._repo.get_claim(claim["id"])
        return owner_claim(updated or claim)

    def _reject(self, claim: dict, principal, reason: str, correlation_id) -> dict:
        decided_at = now_iso()
        self._repo.transition_to_terminal(
            claim, new_status="Rejected", expected_status=STATUS_PENDING,
            extra_sets={"rejectReason": reason, "decidedAt": decided_at,
                        "decidedBy": principal.user_id})
        self._events.publish("CertificationRejected", {
            "claimId": claim["id"], "certId": claim["certId"],
            "certName": claim.get("certName"),
            "memberId": claim["memberId"], "groupId": claim["creditedGroupId"],
            "reason": reason, "system": False, "decidedAt": decided_at,
        }, correlation_id=correlation_id)
        updated = self._repo.get_claim(claim["id"])
        return owner_claim(updated or claim)

    # ------------------------------------------------------------ evidence url

    def evidence_url(self, claim_id: str, *, principal, bearer_token: str | None) -> dict:
        """Owner or in-scope reviewer, only while scan-Clean (BR-P2); minted per
        request, never stored."""
        claim = self._repo.get_claim(claim_id)
        if not claim:
            raise NotFoundError()
        if claim.get("memberId") != principal.user_id:
            try:
                self._decision_scope_check(claim, principal, bearer_token)
            except (ForbiddenError, NotFoundError):
                raise NotFoundError() from None
        if not claim.get("evidenceFileKey"):
            raise NotFoundError(message="This claim has no evidence file.")
        if claim.get("scanStatus") != SCAN_CLEAN:
            raise ConflictError(message="The evidence file has not passed the malware scan.")
        return self._storage.evidence_get_url(claim["evidenceFileKey"])
