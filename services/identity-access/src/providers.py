"""External adapters and the AuthProvider strategy.

- AuthProvider: CognitoAuthProvider — the single credential path for every user,
  including the bootstrap Administrator (US-1.27; deployment-seeded, no separate
  local credential store — see US-1.27/1.28 tombstone).
- SesAdapter: OTP delivery email.
- EventPublisher: domain events on the platform EventBridge bus (post-commit, BR-EV1).
- audit_log: US-1.13/1.14 audit records to CloudWatch (toggle-aware).

All external calls use bounded timeouts and fail closed (RESILIENCY-10, SECURITY-15).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets
import time
from urllib import error as urlerror
from urllib import request as urlrequest

from _conventions.envelope import build_event
from _conventions.errors import AppError, UnauthorizedError, ValidationError
from _conventions.logger import get_logger, log

_logger = get_logger("identity-access")
_audit = get_logger("identity-access.audit")

PBKDF2_ITERATIONS = 210_000

# Character pools for generated temporary passwords (bulk import, US-1.31). Meets
# the pool's password policy (min length 8, upper/lower/number/symbol) with a
# generous length so it's never the weak link; the user immediately replaces it
# via "Forgot password" — it is never emailed in plaintext (BR-P4).
_CHARSET_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # noqa: S105 — char pool, not a secret
_CHARSET_LOWER = "abcdefghijkmnopqrstuvwxyz"  # noqa: S105 — char pool, not a secret
_CHARSET_DIGITS = "23456789"  # noqa: S105 — char pool, not a secret
_CHARSET_SYMBOLS = "!@#$%^&*"  # noqa: S105 — char pool, not a secret


def generate_temp_password(length: int = 20) -> str:
    """Generate a random password satisfying the Cognito pool's password policy.
    Used only as a throwaway credential immediately superseded by the user's own
    password via the forgot-password flow (BR-P4) — never surfaced to the caller."""
    pools = [_CHARSET_UPPER, _CHARSET_LOWER, _CHARSET_DIGITS, _CHARSET_SYMBOLS]
    # Guarantee at least one char from each required class, then fill randomly.
    chars = [_secrets.choice(p) for p in pools]
    all_chars = "".join(pools)
    chars += [_secrets.choice(all_chars) for _ in range(length - len(chars))]
    _secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# ----------------- password hashing (SECURITY-12; used for OTP codes) -----------------

def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or _secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)  # constant-time
    except (ValueError, AttributeError):
        return False


# ----------------- SES -----------------

class SesAdapter:
    def __init__(self, client=None):
        self._c = client
        self.sender = os.environ.get("SES_SENDER", "no-reply@portal.local")

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("ses")
        return self._c

    def send(self, to: str, subject: str, body: str) -> None:
        try:
            self.client.send_email(
                Source=self.sender,
                Destination={"ToAddresses": [to]},
                Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
            )
        except Exception as err:  # noqa: BLE001 — email failure must fail closed for auth
            log(_logger, 40, "SES send failed", to=to, subject=subject)
            raise AppError(code="EMAIL_FAILED", message="Unable to send email. Please retry.", status=502) from err


# ----------------- CSV export storage (S3) -----------------

# The download link is deliberately short-lived. Matches certifications'
# _EVIDENCE_GET_TTL: the signature also dies with the Lambda role's session
# credentials, so a longer value would be illusory anyway. It is also the only
# thing bounding reachability of an export — cleanup is a 1-day S3 lifecycle
# rule (no delete-on-download, since a presigned GET is a direct
# browser-to-S3 transfer this service never observes completing).
EXPORT_GET_TTL_SECONDS = 300


class ExportStorage:
    """Writes generated CSV exports to the dedicated export bucket and mints
    short-lived presigned GETs for download.

    Its own bucket, not a prefix in FileShareBucket — see the rationale on
    UserExportBucket in infra/foundation.yaml. URLs are minted per request and
    NEVER stored (the Settings lesson: a stored URL outlives nothing useful and
    cannot be revoked).
    """

    def __init__(self, client=None, bucket: str | None = None):
        self._c = client
        self.bucket = bucket if bucket is not None else os.environ.get("USER_EXPORT_BUCKET", "")

    @property
    def client(self):
        if self._c is None:
            import boto3
            from botocore.config import Config
            # signature_version MUST be explicit. The default presign is legacy
            # and signs Content-Type into the string-to-sign, so any browser —
            # which always sends one — gets 403 SignatureDoesNotMatch. This bit
            # both Settings' file-share and Events' uploads before being fixed
            # there (2026-08-07); do not "simplify" this away.
            self._c = boto3.client("s3", config=Config(signature_version="s3v4"))
        return self._c

    def _require_bucket(self) -> None:
        if not self.bucket:
            raise AppError(code="NOT_CONFIGURED",
                           message="CSV export storage is not configured.", status=503)

    def put_csv(self, key: str, body: bytes) -> None:
        """Store the finished CSV. Fails loudly — the job must be marked failed
        rather than reporting a file the admin cannot download."""
        self._require_bucket()
        try:
            self.client.put_object(
                Bucket=self.bucket, Key=key, Body=body,
                ContentType="text/csv; charset=utf-8",
            )
        except Exception as err:  # noqa: BLE001 — surfaced as a failed job
            log(_logger, 40, "export upload failed", key=key)
            raise AppError(code="STORAGE_ERROR",
                           message="Unable to store the export file.", status=502) from err

    def download_url(self, key: str) -> dict:
        self._require_bucket()
        try:
            url = self.client.generate_presigned_url(
                "get_object", Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=EXPORT_GET_TTL_SECONDS,
            )
        except Exception as err:  # noqa: BLE001
            log(_logger, 40, "export presign failed", key=key)
            raise AppError(code="STORAGE_ERROR",
                           message="Unable to create the download link.", status=502) from err
        return {"url": url, "expiresInSeconds": EXPORT_GET_TTL_SECONDS}


# ----------------- Events (EventBridge) -----------------

class EventPublisher:
    def __init__(self, client=None):
        self._c = client
        self.bus = os.environ.get("EVENT_BUS_NAME", "")

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("events")
        return self._c

    def publish(self, event_type: str, data: dict, *, correlation_id: str | None = None) -> None:
        """Best-effort post-commit publish (BR-EV1). Never raises to the caller."""
        envelope = build_event(event_type, "identity-access", data, correlation_id=correlation_id)
        if not self.bus:
            log(_logger, 20, "event (no bus configured)", type=event_type)
            return
        try:
            self.client.put_events(Entries=[{
                "EventBusName": self.bus,
                "Source": "identity-access",
                "DetailType": event_type,
                "Detail": json.dumps(envelope, default=str),
            }])
        except Exception:  # noqa: BLE001 — publish failure must not fail the primary write
            log(_logger, 40, "event publish failed (will not block write)", type=event_type)


# ----------------- Audit (US-1.13/1.14) -----------------

def audit_log(action: str, *, actor: str, target: str | None = None, enabled: bool = True,
              always: bool = False, ip: str | None = None, **fields) -> None:
    """Write an audit record when enabled (or always for the toggle change itself)."""
    if not (enabled or always):
        return
    log(_audit, 20, "AUDIT", action=action, actor=actor, target=target, ip=ip, **fields)


# ----------------- AuthProvider strategy -----------------


class DuplicateUserError(ValidationError):
    """The email already has a Cognito account.

    A ValidationError subclass, so every caller that does not special-case it
    keeps its existing behaviour exactly: same code (VALIDATION_ERROR), same
    message, same 400 status. It exists so that `bulk_import` can tell an
    ordinary duplicate apart from genuinely bad data WITHOUT re-checking
    `user_exists` first — matching on a raw botocore exception type does not
    work, because `admin_create_user` maps UsernameExistsException to a domain
    error before the caller ever sees it.
    """

    def __init__(self, message: str = "A user with this email already exists."):
        super().__init__(message=message)


def cognito_username(email: str) -> str:
    """Normalize an email into the Cognito username form: stripped and LOWERCASED.

    The user pool is CASE-SENSITIVE. It is created by CloudFormation with no
    `UsernameConfiguration` block (infra/foundation.yaml), and AWS defaults
    `CaseSensitive` to true for pools created via API/CFN — only console-created
    pools default to insensitive. That cannot be changed after the fact: AWS
    requires migrating users to a new pool, so normalizing on our side is the
    only available fix.

    Without this, casing had to agree between the path that CREATED an account
    and the path that later authenticated it — and it did not. `create_user` and
    `bulk_import` lowercase before calling Cognito, while `login`, `forgot_password`
    and `confirm_forgot_password` passed through whatever the user typed
    (`require_email` returns its input unchanged and the SPA does not normalize).
    So an account added as "user+loadtestUgl@example.com" was stored as
    ...ugl@..., and a reset requested with the capital U raised
    UserNotFoundException, which `forgot_password` swallows for anti-enumeration:
    HTTP 200, "a verification code has been sent", no email, no log entry.
    Diagnosed live 2026-08-26 — a user could neither sign in nor reset, and every
    attempt reported success.

    Applied at THIS boundary, not in `require_email`: that validator is a shared
    `_conventions` file copied into eight services and used for addresses that are
    merely stored or displayed, where silently lowercasing would be a surprise.
    Cognito is the only case-sensitive consumer, so the normalization belongs here,
    where nothing can reach the pool without passing through it.

    Whitespace is stripped for the same class of reason: a pasted address with a
    trailing space is a mismatch the user cannot see.
    """
    return (email or "").strip().lower()


class CognitoAuthProvider:
    """Credential operations against the portal-owned Cognito user pool (US-1.2/1.4/1.30/1.31).

    Cognito is the system of record for community-user identity and credentials.
    The built-in local Administrator (US-1.27) does NOT use this path.

    EVERY method here that names a user normalizes the address through
    `cognito_username` first, so a caller's casing can never decide whether an
    account is found. See that function for the incident this prevents.
    """

    def __init__(self, client=None):
        self._c = client
        self.pool_id = os.environ.get("USER_POOL_ID", "")
        self.client_id = os.environ.get("USER_POOL_CLIENT_ID", "")

    @property
    def client(self):
        if self._c is None:
            import boto3
            self._c = boto3.client("cognito-idp")
        return self._c

    def initiate_auth(self, email: str, password: str) -> dict:
        email = cognito_username(email)
        try:
            resp = self.client.admin_initiate_auth(
                UserPoolId=self.pool_id,
                ClientId=self.client_id,
                AuthFlow="ADMIN_USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": email, "PASSWORD": password},
            )
            details = self.client.admin_get_user(UserPoolId=self.pool_id, Username=email)
            attrs = {a["Name"]: a["Value"] for a in details.get("UserAttributes", [])}
            return {
                "sub": attrs.get("sub", email),
                "email": attrs.get("email", email),
                "firstName": attrs.get("given_name", ""),
                "lastName": attrs.get("family_name", ""),
                "token": resp.get("AuthenticationResult", {}).get("IdToken", ""),
                # Captured so the SPA can re-mint an ID token mid-session without
                # the password (US-1.8 stale-claims fix). The pre-token-generation
                # trigger runs on refresh as well as login, so a refreshed ID token
                # carries the caller's CURRENT role/led_group_id/member_group_ids —
                # that is the whole mechanism behind refreshing after a group join.
                "refreshToken": resp.get("AuthenticationResult", {}).get("RefreshToken", ""),
                "enabled": details.get("Enabled", True),
            }
        # Identical message for both cases so the response never reveals whether
        # the account exists — bad password vs. unknown user are indistinguishable
        # to the caller (BR-A6, no enumeration).
        except self.client.exceptions.NotAuthorizedException:
            raise UnauthorizedError(
                message="The email or password you entered is incorrect."
            ) from None
        except self.client.exceptions.UserNotFoundException:
            raise UnauthorizedError(
                message="The email or password you entered is incorrect."
            ) from None

    def refresh_id_token(self, refresh_token: str) -> str:
        """Exchange a refresh token for a NEW ID token.

        REFRESH_TOKEN_AUTH re-runs the pre-token-generation trigger, so the new
        token carries freshly-resolved claims. That is the point: `member_group_ids`
        is stamped at issuance, so a member who joins a group mid-session keeps a
        token that says otherwise until one of these happens.

        `ALLOW_REFRESH_TOKEN_AUTH` is already on the app client
        (infra/foundation.yaml), so this needs no infrastructure change.

        Raises UnauthorizedError on an expired, revoked or malformed token — the
        SPA treats that as "keep the current token" rather than signing the user
        out, because a failed refresh is not a failed session.

        EVERY failure becomes a 401, not just the Cognito exceptions one would
        predict. This is a token exchange whose only meaningful outcomes are "here
        is a fresh token" and "carry on with the one you have", and a 500 here would
        raise an alarm about an operation the SPA is explicitly prepared to lose.
        The reason is logged at WARNING so a genuine misconfiguration (a pool client
        without ALLOW_REFRESH_TOKEN_AUTH, say) is still visible rather than
        silently degrading into "refresh never works". The caller learns nothing
        either way, matching how forgot_password reports its suppressed failures.
        """
        try:
            resp = self.client.admin_initiate_auth(
                UserPoolId=self.pool_id,
                ClientId=self.client_id,
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": refresh_token},
            )
        except Exception as err:  # noqa: BLE001 — see the docstring: all failures are 401
            log(_logger, 30, "token refresh failed", reason=type(err).__name__)
            raise UnauthorizedError(message="Your session could not be refreshed.") from None
        token = resp.get("AuthenticationResult", {}).get("IdToken", "")
        if not token:
            # Cognito answered without an ID token. Fail rather than hand back an
            # empty string the SPA would install as its bearer — that turns one
            # failed refresh into a 401 on the next call and a forced sign-out.
            log(_logger, 30, "token refresh returned no ID token")
            raise UnauthorizedError(message="Your session could not be refreshed.")
        return token

    def forgot_password(self, email: str) -> None:
        """Kick off the Cognito hosted forgot-password flow (US-1.20): Cognito
        emails a verification code to the account's registered address. Always
        succeeds from the caller's point of view — Cognito itself does not
        reveal whether the username exists (no enumeration, BR-A6), and any
        unexpected error is swallowed here for the same reason (the route
        always returns a generic message)."""
        email = cognito_username(email)
        try:
            self.client.forgot_password(ClientId=self.client_id, Username=email)
        except (self.client.exceptions.UserNotFoundException,
                self.client.exceptions.InvalidParameterException) as err:
            # Still swallowed — the RESPONSE must stay generic (BR-A6). But it is
            # now logged, because this branch is silent by design and that silence
            # cost a live investigation: a user reported no reset email, and with
            # no log line there was no way to tell "no such account" from "account
            # cannot receive mail" without probing the API from outside.
            #
            # UserNotFound      => nothing exists under that username.
            # InvalidParameter  => it exists but Cognito refuses to send, almost
            #                      always a missing/unverified email attribute.
            # The distinction picks the remedy, so record which one it was. Server
            # -side only, at WARNING; the caller learns nothing either way.
            log(_logger, 30, "forgot-password code not sent (suppressed for anti-enumeration)",
                reason=type(err).__name__, username=email)

    def confirm_forgot_password(self, email: str, code: str, new_password: str) -> None:
        """Complete the Cognito hosted forgot-password flow (US-1.20): verify the
        emailed code and set the new password. Cognito enforces the pool's
        password policy. Raises ValidationError on a bad/expired code or a
        password that fails policy, and UnauthorizedError if the account is
        unknown (mapped to the same generic message by the caller)."""
        email = cognito_username(email)
        try:
            self.client.confirm_forgot_password(
                ClientId=self.client_id, Username=email,
                ConfirmationCode=code, Password=new_password,
            )
        except (self.client.exceptions.CodeMismatchException,
                self.client.exceptions.ExpiredCodeException):
            raise ValidationError(message="That code is invalid or has expired.") from None
        except self.client.exceptions.InvalidPasswordException:
            raise ValidationError(message="Password does not meet the required policy.") from None
        except (self.client.exceptions.UserNotFoundException,
                self.client.exceptions.NotAuthorizedException):
            raise UnauthorizedError() from None  # generic (BR-A6)

    def admin_create_user(self, email, first_name, last_name):
        """THE single account-provisioning primitive — self-registration (US-1.30),
        Administrator-created users, and bulk import (US-1.31) all go through here
        (BR-P8). `self_sign_up` was removed 2026-08-11: it differed only by setting
        the CALLER's password as permanent, which meant a self-registering user
        never had to read anything sent to the address they claimed.

        Suppresses Cognito's own invitation email and sets a system-generated
        password as PERMANENT immediately — the same CONFIRMED outcome as the
        bootstrap Administrator (BR-P4), rather than Cognito's default
        FORCE_CHANGE_PASSWORD state, which the app's login flow does not handle.
        The generated password is never returned or emailed; the user sets their
        own via "Forgot password", and reading that code is what proves mailbox
        control on every path.

        `email_verified: "true"` is REQUIRED, not incidental: Cognito refuses to
        deliver a forgot-password code to a user with no verified email, and
        `forgot_password` below swallows that error for anti-enumeration reasons —
        so unsetting it would silently leave the account with no way in at all.
        It is a delivery precondition, not a claim of assurance (BR-P8)."""
        # Normalized here so the account is CREATED under the same username every
        # later sign-in and reset will look it up by. `create_user` and
        # `bulk_import` already lowercase, but `self_register` did not — so
        # self-registration was minting mixed-case usernames that only an
        # exactly-matching retype could authenticate.
        email = cognito_username(email)
        try:
            resp = self.client.admin_create_user(
                UserPoolId=self.pool_id, Username=email, MessageAction="SUPPRESS",
                UserAttributes=[
                    {"Name": "email", "Value": email},
                    {"Name": "given_name", "Value": first_name},
                    {"Name": "family_name", "Value": last_name},
                    {"Name": "email_verified", "Value": "true"},
                ],
            )
        except self.client.exceptions.UsernameExistsException:
            # The email already has an account. This is the PRIMARY duplicate
            # signal for bulk_import (which no longer pre-checks user_exists),
            # and also covers the race where a concurrent request created the
            # same user between a caller's own pre-check and this call.
            # DuplicateUserError is a ValidationError, so callers that do not
            # special-case it are unaffected (same code/message/status).
            raise DuplicateUserError() from None
        except self.client.exceptions.InvalidParameterException as err:
            raise ValidationError(message=f"Invalid user parameter: {err}") from err
        except self.client.exceptions.TooManyRequestsException:
            raise AppError(code="TOO_MANY_REQUESTS",
                           message="Too many requests. Please try again later.",
                           status=429) from None
        attrs = {a["Name"]: a["Value"] for a in resp.get("User", {}).get("Attributes", [])}
        self.client.admin_set_user_password(
            UserPoolId=self.pool_id, Username=email,
            Password=generate_temp_password(), Permanent=True,
        )
        return {"sub": attrs.get("sub", email), "email": email,
                "firstName": first_name, "lastName": last_name}

    def admin_set_enabled(self, username, enabled):
        # `username` is the Cognito username (email) — the pool's sign-in identifier.
        # Normalized because it arrives from a stored portal record, which for a
        # self-registered account could hold the mixed-case address the user typed.
        username = cognito_username(username)
        if enabled:
            self.client.admin_enable_user(UserPoolId=self.pool_id, Username=username)
        else:
            self.client.admin_disable_user(UserPoolId=self.pool_id, Username=username)

    def user_exists(self, email):
        # Normalized, or the duplicate check misses: "Foo@x.com" would report no
        # existing account and AdminCreateUser would then fail on the lowercased
        # username it actually collides with.
        try:
            self.client.admin_get_user(UserPoolId=self.pool_id, Username=cognito_username(email))
            return True
        except self.client.exceptions.UserNotFoundException:
            return False


# ----------------- Settings (live read of US-8.3 admin config) -----------------

_SETTINGS_CACHE_TTL_SECONDS = 30
_SETTINGS_TIMEOUT_SECONDS = 1.0


class SettingsClient:
    """Reads live admin config (allowedEmailDomains, otpIntervalDays,
    selfRegistrationEnabled) from the real Settings
    service via a same-account, unauthenticated call to `GET /internal/settings`
    (moved off `/public/settings` on 2026-08-28: allowedEmailDomains and
    otpIntervalDays were world-readable there and no pre-login caller used them.
    `/internal` is emitted only into the PRIVATE API, so this read requires the
    execute-api VPC endpoint — which is how every fan-out call already travels).
    Short-TTL, per-warm-container cache keeps this off the hot path's latency
    budget; falls back to CFN-Parameter env-var defaults (the pre-Settings
    stop-gap) if the call fails for any reason, so Identity & Access degrades
    to its previous behavior rather than failing closed on login (BR-P3 still
    applies to the fallback: no domains configured -> self-registration
    blocked)."""

    def __init__(self, base_url: str | None = None, opener=None, env_defaults: dict | None = None):
        self.base_url = (base_url or os.environ.get("API_BASE_URL", "")).rstrip("/")
        self._opener = opener or urlrequest.urlopen
        self._cache: dict | None = None
        self._fetched_at = 0.0
        self._env_defaults = env_defaults or {}

    def _fetch(self) -> dict | None:
        if not self.base_url or not self.base_url.startswith("https://"):
            return None  # only https:// same-account API Gateway endpoints (SECURITY-01/07)
        req = urlrequest.Request(f"{self.base_url}/internal/settings", method="GET")  # noqa: S310 — scheme validated above
        try:
            with self._opener(req, timeout=_SETTINGS_TIMEOUT_SECONDS) as resp:
                body = resp.read()
                return json.loads(body) if body else None
        except (urlerror.URLError, TimeoutError, ValueError, OSError) as err:
            log(_logger, 30, "settings fetch failed (falling back to env defaults)", error=str(err))
            return None

    def get(self) -> dict:
        now = time.monotonic()
        if self._cache is None or (now - self._fetched_at) > _SETTINGS_CACHE_TTL_SECONDS:
            fetched = self._fetch()
            self._cache = fetched if fetched is not None else dict(self._env_defaults)
            self._fetched_at = now
        return self._cache

    def allowed_email_domains(self) -> list[str]:
        return self.get().get("allowedEmailDomains") or self._env_defaults.get("allowedEmailDomains", [])

    def self_registration_enabled(self) -> bool:
        val = self.get().get("selfRegistrationEnabled")
        if val is None:
            # Fail CLOSED when neither the live read nor the env default says yes.
            return bool(self._env_defaults.get("selfRegistrationEnabled", False))
        return bool(val)

    def otp_interval_days(self) -> int:
        val = self.get().get("otpIntervalDays")
        if val is None:
            return int(self._env_defaults.get("otpIntervalDays", 30))
        return int(val)


class SettingsView:
    """dict-like `.get(key, default)` facade over SettingsClient + local
    env-only fields (auditEnabled has no Settings-service equivalent yet —
    kept as a local env default), so AuthService/app.py can keep using plain
    `self._settings.get(...)` calls whether the source is live or static."""

    def __init__(self, settings_client: SettingsClient, *, local_defaults: dict | None = None):
        self._client = settings_client
        self._local = local_defaults or {}

    def get(self, key: str, default=None):
        live = self._client.get()
        if key in live:
            return live[key]
        return self._local.get(key, default)



