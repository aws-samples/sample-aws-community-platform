"""Idempotent, convergent promotion of scan-gated uploads (badge images and
claim evidence) to their terminal state.

THE single promotion step, reused by every trigger — the create/attach path,
the GuardDuty scan-verdict consumer, and the watchdog sweep. Because it is
idempotent and reads the AUTHORITATIVE verdict off the FILEKEY pointer each
time, the correct end state is reached regardless of the order the "owner
exists" and "scan is clean" facts arrive in, and regardless of whether any one
trigger misses (dropped event, crash, or the two-writer stale-snapshot race
that previously left a badge stuck in PendingScan forever).

Both functions return a short outcome string for logging/metrics:
  'promoted' | 'quarantined' | 'cleaned' | 'pending' | 'noop'
"""
from __future__ import annotations

from models import SCAN_CLEAN, SCAN_PENDING, SCAN_QUARANTINED


def reconcile_badge(repo, storage, cert_id: str) -> str:
    """Bring a definition's badge image to its terminal state from the verdict
    on its FILEKEY pointer. Safe to call any number of times, in any order."""
    definition = repo.get_definition(cert_id)
    if (not definition or not definition.get("badgeImageKey")
            or definition.get("badgeImagePromotedAt")):
        return "noop"  # nothing attached, or already terminal
    verdict = (repo.get_filekey_pointer(definition["badgeImageKey"]) or {}).get(
        "scanStatus", SCAN_PENDING)
    if verdict == SCAN_QUARANTINED:
        # purge_object, not delete_object: on the versioned bucket a keyed delete
        # would leave the infected image as a readable noncurrent version.
        storage.purge_object(definition["badgeImageKey"])
        repo.finalize_badge(cert_id, status=SCAN_QUARANTINED)
        return "quarantined"
    if verdict != SCAN_CLEAN:
        return "pending"  # scanner has not spoken yet — the watchdog will retry
    # Copy FIRST (idempotent — deterministic public key), flip Clean second; the
    # conditional finalize makes concurrent callers (consumer + watchdog) safe.
    public_url = storage.promote_badge(definition["badgeImageKey"])
    repo.finalize_badge(cert_id, status=SCAN_CLEAN, url=public_url)
    return "promoted"


def reconcile_evidence(repo, claim_id: str) -> str:
    """Bring a claim's evidence scan status to its terminal state from the
    verdict on its FILEKEY pointer. Quarantined objects are already deleted by
    the consumer; here we only stamp the claim so the review gate is correct."""
    claim = repo.get_claim(claim_id)
    if not claim:
        return "noop"
    if claim.get("scanStatus") in (SCAN_CLEAN, SCAN_QUARANTINED):
        return "noop"  # already terminal
    key = claim.get("evidenceFileKey")
    if not key:
        return "noop"  # link evidence — nothing to scan
    verdict = (repo.get_filekey_pointer(key) or {}).get("scanStatus", SCAN_PENDING)
    if verdict not in (SCAN_CLEAN, SCAN_QUARANTINED):
        return "pending"
    repo.set_claim_scan_status(claim_id, verdict)
    return "cleaned" if verdict == SCAN_CLEAN else "quarantined"
