"""Daily expiry sweep (US-5.1, BR-X1..X4) + scan watchdog (N4, J4).

Sweep work is a bounded query over the sparse EXPIRY window — proportional to
holdings expiring within 14 days, never a table walk. Both actions are
conditional writes claimed BEFORE any event is emitted (mark-before-emit,
BR-X2/X3): two concurrent sweeps cannot double-fire, and a crash between mark
and emit loses at most one notification, never a state change. The due-window
query naturally includes overdue items, so a missed daily run is fully caught
up by the next successful one (NFR-CT-AVAIL-3) — no backfill procedure needed.

`now` is injected so expiry math is testable without time travel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from _conventions.logger import get_logger, log
from models import STATUS_APPROVED, STATUS_EXPIRED, now_iso
from scan_reconcile import reconcile_badge, reconcile_evidence

_logger = get_logger("certifications.expiry")

NOTICE_DAYS = 14
_SCANWATCH_ALARM_MINUTES = 30  # N4 (user decision)


class ExpiryService:
    def __init__(self, repo, events, metrics=None):
        self._repo = repo
        self._events = events
        self._metrics = metrics

    def sweep(self, *, now: str | None = None, correlation_id: str | None = None) -> dict:
        now_dt = (datetime.fromisoformat(now.replace("Z", "+00:00")) if now
                  else datetime.now(timezone.utc))
        today = now_dt.date().isoformat()
        window_end = (now_dt + timedelta(days=NOTICE_DAYS)).date().isoformat()

        due = self._repo.query_expiry_window(until=window_end)
        expired = noticed = skipped = 0
        for claim in due:
            if claim.get("status") != STATUS_APPROVED:
                skipped += 1  # defensive: sparse key should only exist on Approved
                continue
            expires_at = claim.get("expiresAt") or ""
            if expires_at <= today:
                expired += self._expire(claim, correlation_id)
            elif not claim.get("expiringNoticeSent"):
                noticed += self._notice(claim, correlation_id)
        result = {"due": len(due), "expired": expired, "noticed": noticed,
                  "skipped": skipped}
        log(_logger, 20, "expiry sweep complete", **result)
        if self._metrics:
            # SweepRunOutcome=1 on ANY completed run — the SweepMissed alarm
            # fires on the ABSENCE of this datapoint for 26h.
            self._metrics.emit("SweepRunOutcome", 1)
        return result

    def _expire(self, claim: dict, correlation_id) -> int:
        try:
            # Conditional Approved->Expired: a concurrent revoke wins the race
            # and this becomes a no-op ConflictError.
            self._repo.transition_to_terminal(
                claim, new_status=STATUS_EXPIRED, expected_status=STATUS_APPROVED,
                extra_sets={"expiredAt": now_iso()})
        except Exception:  # noqa: BLE001 — race loser; the claim left Approved another way
            return 0
        self._events.publish("CertificationExpired", {
            "claimId": claim["id"], "certId": claim["certId"],
            "certName": claim.get("certName"), "memberId": claim["memberId"],
            "expiredAt": now_iso(), "pointsReversed": False,
        }, correlation_id=correlation_id)
        return 1

    def _notice(self, claim: dict, correlation_id) -> int:
        # Claim it FIRST (BR-X2). False = already claimed — do NOT emit.
        if not self._repo.mark_expiring_notice(claim["id"]):
            return 0
        self._events.publish("CertificationExpiringSoon", {
            "claimId": claim["id"], "certId": claim["certId"],
            "certName": claim.get("certName"), "memberId": claim["memberId"],
            "expiresAt": claim.get("expiresAt"),
        }, correlation_id=correlation_id)
        return 1


def _age_minutes(stamp: str | None, now_dt: datetime) -> float | None:
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return (now_dt - dt).total_seconds() / 60


class WatchdogService:
    """15-minute tick, and the BACKSTOP that makes 'stuck in scanning' impossible
    to persist. For every upload still awaiting a verdict — claim evidence AND
    definition badge images — it re-runs the idempotent reconcile against the
    authoritative pointer verdict, converging anything the fast paths missed (the
    two-writer race, a dropped event, a crash). Whatever genuinely remains
    pending (the scanner truly hasn't answered) drives PendingScanAgeMinutes /
    PendingBadgeAgeMinutes, whose alarms fire at 30 minutes (N4)."""

    def __init__(self, repo, metrics, storage=None):
        self._repo = repo
        self._metrics = metrics
        self._storage = storage

    def run(self, *, now: str | None = None) -> dict:
        now_dt = (datetime.fromisoformat(now.replace("Z", "+00:00")) if now
                  else datetime.now(timezone.utc))

        # --- claim evidence -------------------------------------------------
        stuck_claims = self._repo.query_scanwatch(older_than=now_dt.isoformat())
        oldest_claim = 0.0
        pending_claims = 0
        for claim in stuck_claims:
            if reconcile_evidence(self._repo, claim["id"]) == "pending":
                pending_claims += 1
                age = _age_minutes(claim.get("submittedAt"), now_dt)
                if age is not None:
                    oldest_claim = max(oldest_claim, age)
        self._metrics.emit("PendingScanAgeMinutes", round(oldest_claim, 1), unit="None")

        # --- definition badge images ---------------------------------------
        oldest_badge = 0.0
        pending_badges = 0
        for definition in self._repo.query_pending_badges():
            if reconcile_badge(self._repo, self._storage, definition["id"]) == "pending":
                pending_badges += 1
                age = _age_minutes(definition.get("updatedAt") or definition.get("createdAt"),
                                   now_dt)
                if age is not None:
                    oldest_badge = max(oldest_badge, age)
        self._metrics.emit("PendingBadgeAgeMinutes", round(oldest_badge, 1), unit="None")

        result = {"pendingScans": pending_claims, "oldestMinutes": round(oldest_claim, 1),
                  "pendingBadges": pending_badges, "oldestBadgeMinutes": round(oldest_badge, 1)}
        log(_logger, 20, "scan watchdog complete", **result)
        return result
