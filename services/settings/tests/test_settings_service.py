"""SettingsService tests (US-8.3/8.4/8.14 + self-registration toggle)."""
import pytest
from _conventions.errors import ValidationError


def test_get_settings_returns_defaults_when_never_written(ctx):
    s = ctx.settings_service.get_settings()
    assert s["communityName"] == "AWS Community Portal"
    assert s["selfRegistrationEnabled"] is True
    assert s["otpIntervalDays"] == 30
    assert s["allowedEmailDomains"] == []


def test_update_settings_persists_and_merges(ctx):
    ctx.settings_service.update_settings({"communityName": "My Community"}, actor="admin-1")
    s = ctx.settings_service.get_settings()
    assert s["communityName"] == "My Community"
    # untouched fields keep defaults
    assert s["otpIntervalDays"] == 30


def test_update_settings_self_registration_toggle(ctx):
    out = ctx.settings_service.update_settings({"selfRegistrationEnabled": False}, actor="admin-1")
    assert out["selfRegistrationEnabled"] is False
    assert ctx.settings_service.get_settings()["selfRegistrationEnabled"] is False


def test_update_settings_allowed_domains_accepts_list(ctx):
    out = ctx.settings_service.update_settings({"allowedEmailDomains": ["company.com", "aws.org"]}, actor="admin-1")
    assert out["allowedEmailDomains"] == ["company.com", "aws.org"]


def test_update_settings_allowed_domains_accepts_csv_string(ctx):
    out = ctx.settings_service.update_settings({"allowedEmailDomains": "company.com, aws.org"}, actor="admin-1")
    assert out["allowedEmailDomains"] == ["company.com", "aws.org"]


def test_update_settings_publishes_event(ctx):
    ctx.settings_service.update_settings({"communityName": "X"}, actor="admin-1")
    assert ctx.events.published
    assert ctx.events.published[-1]["type"] == "SettingsChanged"


def test_update_settings_rejects_bad_otp_interval(ctx):
    with pytest.raises(ValidationError):
        ctx.settings_service.update_settings({"otpIntervalDays": 0}, actor="admin-1")


def test_session_lifetime_is_not_a_setting(ctx):
    """Removed 2026-08-11: session length is governed by the Cognito token
    lifetime, not by an admin knob. A client that still sends the old field
    must have it dropped rather than stored."""
    out = ctx.settings_service.update_settings({"sessionLifetimeHours": 12}, actor="admin-1")
    assert "sessionLifetimeHours" not in out
    assert "sessionLifetimeHours" not in ctx.settings_service.get_public_settings()


def test_get_public_settings_subset_only(ctx):
    ctx.settings_service.update_settings(
        {"communityName": "X", "bedrockModel": "secret-model", "teamsTenantId": "tenant-1"},
        actor="admin-1")
    pub = ctx.settings_service.get_public_settings()
    assert pub["communityName"] == "X"
    assert "bedrockModel" not in pub
    assert "teamsTenantId" not in pub


def test_get_public_settings_reflects_self_registration_flag(ctx):
    ctx.settings_service.update_settings({"selfRegistrationEnabled": False}, actor="admin-1")
    pub = ctx.settings_service.get_public_settings()
    assert pub["selfRegistrationEnabled"] is False


def test_read_edit_save_round_trip_preserves_int_types(ctx):
    """DynamoDB returns numbers as Decimal; the serializer must coerce them back
    to ints so a GET -> edit -> PUT round-trip re-validates (deploy regression:
    every save after the first returned 'Validation failed.')."""
    ctx.settings_service.update_settings({"communityName": "First"}, actor="admin-1")
    fetched = ctx.settings_service.get_settings()
    assert isinstance(fetched["otpIntervalDays"], int)
    assert isinstance(fetched["selfRegistrationEnabled"], bool)
    # PUT the whole fetched object back, exactly as the frontend does
    fetched["communityName"] = "Community Portal"
    out = ctx.settings_service.update_settings(fetched, actor="admin-1")
    assert out["communityName"] == "Community Portal"
    assert out["otpIntervalDays"] == 30


# --- allowed-email-domain entry: normalisation + validation (2026-08-11) -------
# Admins type these by hand. Identity & Access matches against
# email.split("@")[-1].lower(), so a stored "@amazon.com" matches NOTHING and
# self-registration then rejects every applicant while the Settings screen shows a
# value that looks correct. Normalise what is recoverable, reject the rest with a
# per-field message naming the offending entry.

def test_multiple_domains_comma_separated_string(ctx):
    out = ctx.settings_service.update_settings(
        {"allowedEmailDomains": "amazon.com,cognizant.com"}, actor="admin-1")
    assert out["allowedEmailDomains"] == ["amazon.com", "cognizant.com"]


def test_multiple_domains_as_array(ctx):
    out = ctx.settings_service.update_settings(
        {"allowedEmailDomains": ["amazon.com", " cognizant.com "]}, actor="admin-1")
    assert out["allowedEmailDomains"] == ["amazon.com", "cognizant.com"]


def test_array_element_containing_commas_is_flattened(ctx):
    """A pasted list in one slot must not slip past per-entry validation."""
    out = ctx.settings_service.update_settings(
        {"allowedEmailDomains": ["amazon.com,cognizant.com"]}, actor="admin-1")
    assert out["allowedEmailDomains"] == ["amazon.com", "cognizant.com"]


def test_recoverable_shapes_are_normalised(ctx):
    out = ctx.settings_service.update_settings(
        {"allowedEmailDomains": "@amazon.com, HTTPS://Cognizant.com, example.com."},
        actor="admin-1")
    assert out["allowedEmailDomains"] == ["amazon.com", "cognizant.com", "example.com"]


def test_duplicates_collapse_case_insensitively_preserving_order(ctx):
    out = ctx.settings_service.update_settings(
        {"allowedEmailDomains": "Amazon.COM, cognizant.com, amazon.com"}, actor="admin-1")
    assert out["allowedEmailDomains"] == ["amazon.com", "cognizant.com"]


def test_trailing_and_doubled_commas_are_tolerated(ctx):
    out = ctx.settings_service.update_settings(
        {"allowedEmailDomains": "amazon.com,,cognizant.com,"}, actor="admin-1")
    assert out["allowedEmailDomains"] == ["amazon.com", "cognizant.com"]


@pytest.mark.parametrize("bad", [
    "amazon",               # no dot
    "amazon com",           # space
    "user@amazon.com",      # an address, not a domain
    ".amazon.com",          # leading dot
    "amazon..com",          # doubled dot
])
def test_malformed_domains_are_rejected(ctx, bad):
    with pytest.raises(ValidationError):
        ctx.settings_service.update_settings({"allowedEmailDomains": bad}, actor="admin-1")


def test_rejection_names_the_offending_entry(ctx):
    """The Settings screen renders per-field details (US-8.16); a bare
    'Validation failed.' would leave the admin guessing which entry is wrong."""
    with pytest.raises(ValidationError) as err:
        ctx.settings_service.update_settings(
            {"allowedEmailDomains": "amazon.com, cognizant"}, actor="admin-1")
    details = err.value.details or []
    assert details and details[0]["field"] == "allowedEmailDomains"
    assert "cognizant" in details[0]["message"]


def test_one_bad_entry_rejects_the_whole_save(ctx):
    """Fail closed: never persist a partially-valid allow-list, or the admin would
    believe a domain is permitted when it was silently dropped."""
    ctx.settings_service.update_settings({"allowedEmailDomains": "amazon.com"}, actor="admin-1")
    with pytest.raises(ValidationError):
        ctx.settings_service.update_settings(
            {"allowedEmailDomains": "cognizant.com, bad domain"}, actor="admin-1")
    assert ctx.settings_service.get_settings()["allowedEmailDomains"] == ["amazon.com"]


def test_empty_list_still_means_blocked(ctx):
    """Empty allow-list keeps its BR-P3 meaning: self-registration blocked."""
    out = ctx.settings_service.update_settings({"allowedEmailDomains": []}, actor="admin-1")
    assert out["allowedEmailDomains"] == []
