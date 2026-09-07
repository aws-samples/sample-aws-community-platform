"""Expiry sweep + watchdog (US-5.1, BR-X, N4) and revocation events."""
from __future__ import annotations

from conftest import make_definition, submit_claim, upload_evidence
from models import add_months, parse_iso_date


def _approved_claim(ctx, cl, member, *, date_earned="2026-06-01", months=36, **defn):
    definition = make_definition(ctx, cl, expiryPeriodMonths=months, **defn)
    claim = submit_claim(ctx, member, definition["id"], dateEarned=date_earned)
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    return ctx.repo.get_claim(claim["id"])


def test_add_months_clamps_month_end():
    assert add_months(parse_iso_date("2026-01-31"), 1).isoformat() == "2026-02-28"
    assert add_months(parse_iso_date("2024-01-31"), 1).isoformat() == "2024-02-29"
    assert add_months(parse_iso_date("2026-06-01"), 36).isoformat() == "2029-06-01"


def test_sweep_expires_at_the_frozen_date(ctx, cl, member, aws):
    claim = _approved_claim(ctx, cl, member)
    after = claim["expiresAt"] + "T06:00:00+00:00"
    result = ctx.expiry.sweep(now=after)
    assert result["expired"] == 1
    stored = ctx.repo.get_claim(claim["id"])
    assert stored["status"] == "Expired"
    events = [e for e in ctx.events.published if e["type"] == "CertificationExpired"]
    assert len(events) == 1
    assert events[0]["data"]["pointsReversed"] is False  # US-5.1: points retained
    # Badge gone from every read: slot deleted.
    assert ctx.repo.get_slot(claim["certId"], claim["memberId"]) is None


def test_sweep_notices_at_t14_exactly_once_then_expires(ctx, cl, member, aws):
    import datetime as dt
    claim = _approved_claim(ctx, cl, member)
    expiry_dt = dt.datetime.fromisoformat(claim["expiresAt"] + "T06:00:00+00:00")
    t_minus_10 = (expiry_dt - dt.timedelta(days=10)).isoformat()
    first = ctx.expiry.sweep(now=t_minus_10)
    assert first["noticed"] == 1 and first["expired"] == 0
    notices = [e for e in ctx.events.published
               if e["type"] == "CertificationExpiringSoon"]
    assert len(notices) == 1 and notices[0]["data"]["expiresAt"] == claim["expiresAt"]
    # Next daily run inside the window: no second notice.
    again = ctx.expiry.sweep(now=(expiry_dt - dt.timedelta(days=9)).isoformat())
    assert again["noticed"] == 0
    # And at expiry the same claim expires (missed-run self-healing also
    # covered: the window query includes overdue items).
    final = ctx.expiry.sweep(now=(expiry_dt + dt.timedelta(days=3)).isoformat())
    assert final["expired"] == 1


def test_sweep_outside_window_does_nothing(ctx, cl, member, aws):
    _approved_claim(ctx, cl, member)   # expires 2029
    result = ctx.expiry.sweep(now="2026-08-06T06:00:00+00:00")
    assert result == {"due": 0, "expired": 0, "noticed": 0, "skipped": 0}


def test_never_expiring_claim_is_not_in_the_window(ctx, cl, member, aws):
    definition = make_definition(ctx, cl, expiryPeriodMonths=None)
    claim = submit_claim(ctx, member, definition["id"], dateEarned="2026-06-01")
    ctx.verifications.decide(claim["id"], {"decision": "approve"},
                             principal=cl, bearer_token=None)
    result = ctx.expiry.sweep(now="2099-01-01T06:00:00+00:00")
    assert result["due"] == 0  # sparse index holds only expiring holdings


def test_revoked_claim_drops_out_of_the_expiry_window(ctx, cl, member, aws):
    claim = _approved_claim(ctx, cl, member)
    ctx.revocations.revoke(claim["id"], {"reason": "invalid"}, principal=cl)
    result = ctx.expiry.sweep(now=claim["expiresAt"] + "T06:00:00+00:00")
    assert result["due"] == 0  # terminal transition removed the sparse key


def test_sweep_emits_run_outcome_metric(ctx, cl, member, aws):
    ctx.expiry.sweep(now="2026-08-06T06:00:00+00:00")
    assert ctx.fake_metrics.of("SweepRunOutcome") == [1]


def test_watchdog_reports_oldest_pending_scan_age(ctx, cl, member, aws):
    import datetime as dt
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    claim = submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                         evidenceFileKey=file_key)
    submitted = ctx.repo.get_claim(claim["id"])["submittedAt"]
    later = (dt.datetime.fromisoformat(submitted) + dt.timedelta(minutes=45)).isoformat()
    result = ctx.watchdog.run(now=later)
    assert result["pendingScans"] == 1
    assert 44 <= result["oldestMinutes"] <= 46  # the N4 alarm threshold is 30
    assert ctx.fake_metrics.of("PendingScanAgeMinutes")


def test_watchdog_clears_after_verdict(ctx, cl, member, aws):
    definition = make_definition(ctx, cl)
    file_key = upload_evidence(ctx, member, aws)
    submit_claim(ctx, member, definition["id"], evidenceUrl=None,
                 evidenceFileKey=file_key)
    ctx.scan_consumer.handle({
        "id": "scan-w", "detail-type": "GuardDuty Malware Protection Object Scan Result",
        "detail": {"s3ObjectDetails": {"objectKey": file_key},
                   "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"}}})
    result = ctx.watchdog.run(now="2099-01-01T00:00:00+00:00")
    assert result["pendingScans"] == 0
