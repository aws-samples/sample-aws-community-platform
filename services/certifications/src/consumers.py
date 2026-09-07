"""Event consumers: membership auto-reject (BR-S1..S3) and GuardDuty scan
verdicts (J5 — the single trust-promotion point).

Both are idempotent on the envelope/event id and read ONLY documented payload
fields — the Events unit once fell back to an envelope field and tried to
cancel events for a group named after an event id; malformed input here is
logged and dropped, never guessed at.
"""
from __future__ import annotations

from urllib.parse import unquote_plus

from _conventions.logger import get_logger, log
from models import (
    SCAN_CLEAN,
    SCAN_QUARANTINED,
    STATUS_PENDING,
    SYSTEM_REJECT_REASON,
    now_iso,
)
from scan_reconcile import reconcile_badge, reconcile_evidence

_logger = get_logger("certifications.consumers")

CERT_PREFIX = "certifications/"


class MembershipConsumer:
    """MemberLeftGroup | MemberRemoved -> auto-reject that member's Pending
    claims credited to that group (US-5.4). Approved claims are untouched —
    leaving a group does not un-earn a certification (BR-S3)."""

    def __init__(self, repo, events, idempotency=None):
        self._repo = repo
        self._events = events
        self._idem = idempotency

    def handle(self, envelope: dict, *, correlation_id: str | None = None) -> dict:
        data = envelope.get("data") or {}
        member_id = data.get("memberId")
        group_id = data.get("groupId")
        if not member_id or not group_id:
            log(_logger, 30, "membership event missing documented fields — dropped",
                keys=sorted(data.keys()))
            return {"ignored": True}

        result = {"rejected": 0}

        def run():
            # Bounded: one member's claims, filtered to Pending + this group.
            for claim in self._repo.list_member_claims(member_id):
                if (claim.get("status") == STATUS_PENDING
                        and claim.get("creditedGroupId") == group_id):
                    self._reject(claim, correlation_id)
                    result["rejected"] += 1

        event_id = envelope.get("id")
        if self._idem and event_id:
            executed = self._idem.run_once(event_id, run)
            if not executed:
                return {"duplicate": True}
        else:
            run()
        log(_logger, 20, "membership auto-reject processed",
            memberId=member_id, groupId=group_id, rejected=result["rejected"])
        return result

    def _reject(self, claim: dict, correlation_id) -> None:
        decided_at = now_iso()
        try:
            self._repo.transition_to_terminal(
                claim, new_status="Rejected", expected_status=STATUS_PENDING,
                extra_sets={"rejectReason": SYSTEM_REJECT_REASON,
                            "decidedAt": decided_at, "decidedBy": "system"})
        except Exception:  # noqa: BLE001 — a concurrent decision won; nothing to do
            return
        # The member must learn why their claim vanished (email + in-portal via
        # Notifications later) — one event per claim, system-flagged.
        self._events.publish("CertificationRejected", {
            "claimId": claim["id"], "certId": claim["certId"],
            "certName": claim.get("certName"),
            "memberId": claim["memberId"], "groupId": claim["creditedGroupId"],
            "reason": SYSTEM_REJECT_REASON, "system": True, "decidedAt": decided_at,
        }, correlation_id=correlation_id)


class ScanVerdictConsumer:
    """GuardDuty Malware Protection scan results for this unit's prefixes (J5).

    THE single point where 'this file became trustworthy' is known, so trust
    promotion happens here and nowhere else:
      evidence + Clean       -> claim reviewable (scanStatus stamp)
      evidence + infected    -> claim Quarantined (flagged for re-upload) + object deleted
      badge    + Clean       -> copy to the public SPA bucket, THEN stamp Clean
      badge    + infected    -> definition image rejected + object deleted

    The FILEKEY pointer (written at grant time) resolves the verdict-before-
    owner race: a verdict landing before the claim/definition exists records
    itself on the pointer, and submission/create reads it (claim_service /
    definition_service handle that path inline).
    """

    def __init__(self, repo, storage, idempotency=None, metrics=None):
        self._repo = repo
        self._storage = storage
        self._idem = idempotency
        self._metrics = metrics

    def handle(self, envelope: dict, *, correlation_id: str | None = None) -> dict:
        detail = envelope.get("detail") or {}
        key = unquote_plus(str(
            ((detail.get("s3ObjectDetails") or {}).get("objectKey"))
            or ((detail.get("object") or {}).get("key")) or ""))
        status = str((detail.get("scanResultDetails") or {}).get("scanResultStatus")
                     or detail.get("scanStatus") or "").upper()
        if not key.startswith(CERT_PREFIX):
            # The EventBridge rule is prefix-filtered (F-B), so this is pure
            # defense-in-depth against a rule regression.
            return {"ignored": key}

        verdict = SCAN_CLEAN if status in ("NO_THREATS_FOUND", "CLEAN") else SCAN_QUARANTINED
        result: dict = {"key": key, "verdict": verdict}

        def run():
            pointer = self._repo.get_filekey_pointer(key)
            if pointer is None:
                # Verdict for a key we never granted — log loudly, touch nothing.
                log(_logger, 40, "scan verdict for unknown key — ignored", key=key)
                result["unknown"] = True
                return
            self._repo.update_filekey_pointer(key, scanStatus=verdict)
            owner_id = pointer.get("ownerId")
            if pointer.get("kind") == "evidence":
                self._handle_evidence(key, verdict, owner_id, result)
            elif pointer.get("kind") == "badge":
                self._handle_badge(key, verdict, owner_id, result)

        event_id = envelope.get("id") or f"scan#{key}#{status}"
        if self._idem:
            executed = self._idem.run_once(event_id, run)
            if not executed:
                return {"duplicate": True}
        else:
            run()
        return result

    def _handle_evidence(self, key: str, verdict: str, claim_id: str | None,
                         result: dict) -> None:
        if verdict == SCAN_QUARANTINED:
            # Never serve an infected byte — delete BEFORE any state that could
            # make it reachable. The claim row stays as the member's re-upload
            # prompt.
            # purge_object, NOT delete_object: the bucket is versioned, where a
            # keyed delete only writes a delete marker and leaves the infected
            # version readable via GetObjectVersion. See providers.purge_object.
            self._storage.purge_object(key)
        # Re-read the CURRENT pointer for the owner: the `claim_id` we were passed
        # came from a snapshot taken BEFORE this run wrote the verdict, so it can
        # be stale (the two-writer race). Deciding off the fresh pointer, then
        # delegating to the idempotent reconcile, is what closes that window.
        owner_id = (self._repo.get_filekey_pointer(key) or {}).get("ownerId")
        if not owner_id:
            # Verdict-before-claim: the pointer carries the verdict; submission
            # reconciles when it writes ownerId (and the watchdog is the backstop).
            result["deferred"] = True
            return
        result["outcome"] = reconcile_evidence(self._repo, owner_id)
        result["claimId"] = owner_id

    def _handle_badge(self, key: str, verdict: str, cert_id: str | None,
                      result: dict) -> None:
        if verdict == SCAN_QUARANTINED:
            # All versions, not just the current one (see _handle_evidence).
            self._storage.purge_object(key)
        # Fresh pointer read (see _handle_evidence): never trust the pre-verdict
        # snapshot's ownerId — that stale read was the stuck-badge deadlock.
        owner_id = (self._repo.get_filekey_pointer(key) or {}).get("ownerId")
        if not owner_id:
            result["deferred"] = True  # createCert/editCert reconciles inline
            return
        result["outcome"] = reconcile_badge(self._repo, self._storage, owner_id)
        result["certId"] = owner_id
        if result["outcome"] == "promoted":
            result["publicUrl"] = (self._repo.get_definition(owner_id) or {}).get("badgeImageUrl")
