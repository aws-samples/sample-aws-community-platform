"""Centralized Admin Settings (US-8.3/8.4/8.5/8.14 + self-registration toggle).

Administrator-only writes; any authenticated user may read the full settings
object (Settings pages for Member/leader roles display community name,
timezone, etc. per the mockup). Unauthenticated callers use the separate
`getPublicSettings` operation (pre-login gate for Self-Registration, US-1.30).

Every successful write publishes `SettingsChanged` so Identity & Access (which
enforces the allow-list / OTP interval / self-registration flag server-side)
and the frontend can react without polling on every request.
"""
from __future__ import annotations

from _conventions.validation import require, require_bool_like, require_int, require_str
from models import (
    DEFAULT_SETTINGS,
    settings_internal_subset,
    settings_public,
    settings_public_subset,
)


def normalize_domain(raw: str) -> str:
    """Normalise one allow-list entry to a bare, lowercase domain.

    Admins type these by hand, and the forms that look right to a human all fail
    the matcher: Identity & Access compares against `email.split("@")[-1].lower()`,
    so a stored "@amazon.com" or "https://amazon.com" can never match ANY address.
    Self-registration then rejects every applicant with "Email domain is not
    permitted" while the Settings screen displays a value that looks correct —
    one typo silently disables onboarding with nothing to diagnose it from.
    Normalise the recoverable shapes here; `validate_domain` rejects the rest.
    """
    d = (raw or "").strip().lower()
    if "://" in d:                      # https://amazon.com
        d = d.split("://", 1)[1]
    d = d.lstrip("@")                   # @amazon.com
    d = d.split("/", 1)[0]              # amazon.com/path
    return d.rstrip(".")                # amazon.com.


def validate_domain(raw: str) -> str:
    """Normalise then reject anything that cannot be an email domain, with a
    per-field message (rendered by the Settings screen, US-8.16) naming the entry
    at fault. Deliberately shape-only — no DNS lookup, no public-suffix list."""
    d = normalize_domain(raw)
    field = "allowedEmailDomains"
    require(bool(d), field, "contains an empty domain — remove the extra comma")
    require(" " not in d and "\t" not in d, field, f"'{raw.strip()}' contains a space")
    require("@" not in d, field, f"'{raw.strip()}' must be a domain only, not an email address")
    require("." in d, field, f"'{raw.strip()}' is not a domain (expected e.g. amazon.com)")
    require(not d.startswith(".") and ".." not in d, field, f"'{raw.strip()}' has a misplaced dot")
    require(len(d) <= 253, field, "domain is too long")
    return d


class SettingsService:
    def __init__(self, repo, events):
        self._repo = repo
        self._events = events

    def get_settings(self) -> dict:
        return settings_public(self._repo.get_settings())

    def get_public_settings(self) -> dict:
        return settings_public_subset(self._repo.get_settings())

    def get_internal_settings(self) -> dict:
        """Private-API-only projection (GET /internal/settings). Fields other
        services enforce server-side and that must stay off the public route."""
        return settings_internal_subset(self._repo.get_settings())

    def update_settings(self, body: dict, *, actor: str) -> dict:
        current = self._repo.get_settings()
        merged = {**DEFAULT_SETTINGS, **current}

        # Validate only the fields present in the request; unknown fields are
        # dropped rather than silently stored (avoids an ever-growing schema).
        if "communityName" in body:
            merged["communityName"] = require_str(body["communityName"], "communityName", max_len=100)
        if "logoUrl" in body:
            merged["logoUrl"] = require_str(body["logoUrl"], "logoUrl", max_len=500, min_len=0)
        if "defaultTimezone" in body:
            merged["defaultTimezone"] = require_str(body["defaultTimezone"], "defaultTimezone", max_len=64)
        if "enableSemanticSearch" in body:
            merged["enableSemanticSearch"] = require_bool_like(body["enableSemanticSearch"], "enableSemanticSearch")
        if "selfRegistrationEnabled" in body:
            merged["selfRegistrationEnabled"] = require_bool_like(body["selfRegistrationEnabled"], "selfRegistrationEnabled")
        if "allowedEmailDomains" in body:
            domains = body["allowedEmailDomains"]
            # Accept either a real array (what the SPA sends) or a raw
            # comma-separated string, so "amazon.com,cognizant.com" works from any
            # caller — including curl and the pre-SPA form shape.
            if not isinstance(domains, list):
                domains = str(domains).split(",")
            else:
                # An array element may itself hold commas if a caller pasted the
                # whole list into one slot; flatten so it cannot smuggle past
                # per-entry validation as a single "domain".
                domains = [part for d in domains for part in str(d).split(",")]
            cleaned = []
            for d in domains:
                # Blank-skip comes BEFORE require_str, whose min_len=1 would
                # otherwise reject the empty string a trailing comma produces.
                if not str(d).strip():
                    continue        # tolerate trailing/duplicate commas
                require_str(d, "allowedEmailDomains", max_len=253)
                cleaned.append(validate_domain(d))
            # De-duplicate (post-normalisation, so "Amazon.COM" and "amazon.com"
            # collapse) while preserving the order the Administrator typed.
            merged["allowedEmailDomains"] = list(dict.fromkeys(cleaned))
        if "otpIntervalDays" in body:
            merged["otpIntervalDays"] = require_int(
                body["otpIntervalDays"], "otpIntervalDays", minimum=1, maximum=365)
        if "teamsTenantId" in body:
            merged["teamsTenantId"] = require_str(
                body["teamsTenantId"], "teamsTenantId", max_len=200, min_len=0)
        # Platform-locked settings — always forced to their fixed values, ignoring
        # any client-supplied value (the Admin UI renders these controls disabled).
        # MS Teams integration OFF, LLM duplicate-post analysis OFF, and the
        # Bedrock model fixed to Claude 3.5 Sonnet.
        merged["teamsEnabled"] = False
        merged["llmDuplicateDetectionEnabled"] = False
        merged["bedrockModel"] = "anthropic.claude-3-5-sonnet"
        if "whatsNewEnabled" in body:
            merged["whatsNewEnabled"] = require_bool_like(body["whatsNewEnabled"], "whatsNewEnabled")
        if "whatsNewFeedUrl" in body:
            merged["whatsNewFeedUrl"] = require_str(
                body["whatsNewFeedUrl"], "whatsNewFeedUrl", max_len=500, min_len=0)
        if "senderName" in body:
            merged["senderName"] = require_str(body["senderName"], "senderName", max_len=100, min_len=0)
        if "senderEmail" in body:
            merged["senderEmail"] = require_str(
                body["senderEmail"], "senderEmail", max_len=200, min_len=0)
        if "shoutoutLimitMember" in body:
            merged["shoutoutLimitMember"] = require_int(
                body["shoutoutLimitMember"], "shoutoutLimitMember", minimum=0, maximum=100)
        if "shoutoutLimitUgl" in body:
            merged["shoutoutLimitUgl"] = require_int(
                body["shoutoutLimitUgl"], "shoutoutLimitUgl", minimum=0, maximum=100)
        if "shoutoutLimitCl" in body:
            merged["shoutoutLimitCl"] = require_int(
                body["shoutoutLimitCl"], "shoutoutLimitCl", minimum=0, maximum=100)

        self._repo.put_settings(merged)
        self._events.publish(
            "SettingsChanged", {"changedBy": actor, "settings": settings_public(merged)})
        return settings_public(merged)
