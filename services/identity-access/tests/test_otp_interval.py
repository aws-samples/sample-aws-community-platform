"""OTP re-verification interval (US-1.32) — the admin knob must actually decide.

`otpIntervalDays` is configured by an Administrator in Settings and read live by
Identity & Access. Existing tests cover the two ends (never verified -> due, just
verified -> not due) but nothing pinned the INTERVAL itself, so a regression that
ignored the setting and always used the 30-day default would have passed.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def _verified_days_ago(days: float) -> dict:
    stamp = datetime.now(timezone.utc) - timedelta(days=days)
    return {"id": "u-1", "lastVerifiedAt": stamp.isoformat()}


def _due(ctx, *, interval, days_ago):
    ctx.auth_service._settings = {"otpIntervalDays": interval}
    return ctx.auth_service._otp_due(_verified_days_ago(days_ago))


def test_interval_from_settings_decides_the_outcome(ctx):
    """Same user, same last-verified time — only the setting differs."""
    assert _due(ctx, interval=7, days_ago=3) is False
    assert _due(ctx, interval=2, days_ago=3) is True


def test_boundary_is_at_or_past_the_interval(ctx):
    assert _due(ctx, interval=7, days_ago=6.9) is False
    assert _due(ctx, interval=7, days_ago=7.1) is True


def test_a_one_day_interval_still_allows_a_same_day_signin(ctx):
    """The deployed value is 1, so this is the live behaviour: re-verify daily,
    but not twice in the same day."""
    assert _due(ctx, interval=1, days_ago=0.5) is False
    assert _due(ctx, interval=1, days_ago=1.2) is True


def test_a_long_interval_is_honoured(ctx):
    assert _due(ctx, interval=365, days_ago=200) is False


def test_never_verified_is_always_due(ctx):
    ctx.auth_service._settings = {"otpIntervalDays": 365}
    assert ctx.auth_service._otp_due({"id": "u-1"}) is True


def test_an_unparseable_timestamp_fails_towards_re_verification(ctx):
    """A record we cannot read must not be treated as recently verified —
    that would let a bad value switch OTP off entirely."""
    ctx.auth_service._settings = {"otpIntervalDays": 30}
    assert ctx.auth_service._otp_due({"id": "u-1", "lastVerifiedAt": "not-a-date"}) is True


def test_a_naive_timestamp_fails_towards_re_verification(ctx):
    """`now_iso()` always writes an offset, but an imported or hand-repaired row
    can be naive. Subtracting a naive datetime from an aware one raises
    TypeError, which must degrade to "re-verify" rather than escaping as a 500 on
    the login path."""
    ctx.auth_service._settings = {"otpIntervalDays": 30}
    assert ctx.auth_service._otp_due(
        {"id": "u-1", "lastVerifiedAt": "2026-08-01T00:00:00"}) is True
