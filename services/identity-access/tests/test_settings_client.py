"""SettingsClient/SettingsView tests — live-read-with-fallback for US-8.3 config
consumed by Identity & Access (allowedEmailDomains, selfRegistrationEnabled,
otpIntervalDays)."""
from __future__ import annotations

import json

from providers import SettingsClient, SettingsView


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener_returning(payload: dict):
    def _opener(req, timeout=None):
        return _FakeResponse(json.dumps(payload).encode())
    return _opener


def _opener_raising():
    def _opener(req, timeout=None):
        raise OSError("connection refused")
    return _opener


def test_get_returns_live_payload_when_reachable():
    client = SettingsClient(base_url="https://api.example.com", opener=_opener_returning(
        {"selfRegistrationEnabled": False, "allowedEmailDomains": ["live.com"], "otpIntervalDays": 14}))
    assert client.self_registration_enabled() is False
    assert client.allowed_email_domains() == ["live.com"]
    assert client.otp_interval_days() == 14


def test_get_falls_back_to_env_defaults_on_failure():
    client = SettingsClient(base_url="https://api.example.com", opener=_opener_raising(),
                            env_defaults={"allowedEmailDomains": ["fallback.com"],
                                         "selfRegistrationEnabled": True, "otpIntervalDays": 30})
    assert client.allowed_email_domains() == ["fallback.com"]
    assert client.self_registration_enabled() is True
    assert client.otp_interval_days() == 30


def test_get_rejects_non_https_base_url():
    client = SettingsClient(base_url="http://insecure.example.com", opener=_opener_returning({}),
                            env_defaults={"allowedEmailDomains": ["fallback.com"]})
    assert client.allowed_email_domains() == ["fallback.com"]


def test_settings_view_prefers_live_value_over_local_default():
    client = SettingsClient(base_url="https://api.example.com",
                            opener=_opener_returning({"auditEnabled": False}))
    view = SettingsView(client, local_defaults={"auditEnabled": True})
    assert view.get("auditEnabled", True) is False


def test_settings_view_falls_back_to_local_default_when_key_absent():
    client = SettingsClient(base_url="https://api.example.com", opener=_opener_returning({}))
    view = SettingsView(client, local_defaults={"auditEnabled": True})
    assert view.get("auditEnabled", False) is True


# --- self-registration must fail CLOSED when settings are unreachable --------
# Regression for 2026-08-11: the env fallback defaulted to True, so a Settings
# outage silently re-enabled self-registration — the one provisioning path that
# emails nothing and asserts email_verified itself. The SPA keeps its tab hidden
# in that state, so the opening would have been invisible.

def test_self_registration_defaults_to_disabled_when_unreachable_and_unset():
    """No live read AND no env default => disabled, not enabled."""
    client = SettingsClient(base_url="https://api.example.com", opener=_opener_raising(),
                            env_defaults={"allowedEmailDomains": ["fallback.com"]})
    assert client.self_registration_enabled() is False


def test_self_registration_env_default_is_still_honoured_when_explicit():
    """An operator can still opt the fallback IN explicitly; only the absent case
    changed, so this is fail-closed rather than hard-coded-off."""
    client = SettingsClient(base_url="https://api.example.com", opener=_opener_raising(),
                            env_defaults={"selfRegistrationEnabled": True})
    assert client.self_registration_enabled() is True


def test_live_disabled_wins_over_an_enabled_env_default():
    """The admin's Settings value is authoritative whenever it is readable."""
    client = SettingsClient(base_url="https://api.example.com",
                            opener=_opener_returning({"selfRegistrationEnabled": False}),
                            env_defaults={"selfRegistrationEnabled": True})
    assert client.self_registration_enabled() is False


def _opener_capturing(sink: list, payload: dict | None = None):
    def _opener(req, timeout=None):
        sink.append(req.full_url)
        return _FakeResponse(json.dumps(payload or {}).encode())
    return _opener


def test_reads_the_private_only_internal_route_not_the_public_one():
    """allowedEmailDomains and otpIntervalDays must not come from an
    internet-reachable route: /public/settings has no authorizer, so anything it
    returns is world-readable. This read moved to /internal/settings, which is
    emitted only into the private API (gen_api_edge.PRIVATE_ONLY_BASES)."""
    seen: list[str] = []
    client = SettingsClient(base_url="https://api.example.com",
                            opener=_opener_capturing(seen, {"otpIntervalDays": 14}))
    client.get()
    assert seen == ["https://api.example.com/internal/settings"]
    assert "/public/settings" not in seen[0]
