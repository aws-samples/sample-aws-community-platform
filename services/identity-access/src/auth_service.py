"""Authentication flows (US-1.2/1.3/1.15/1.20/1.27/1.30/1.32).

A single Cognito credential path for every user, including the bootstrap
Administrator (US-1.27, seeded at deployment — there is no separate portal-local
credential store or login path). Password reset (US-1.20) is the Cognito hosted
forgot-password flow, available to every user including the bootstrap
Administrator — there is no portal-local reset path. OTP re-verification is
in-service. Fail closed on every error (SECURITY-15). Generic errors, no user
enumeration (BR-A6).
"""
from __future__ import annotations

from _conventions.errors import UnauthorizedError, ValidationError
from _conventions.logger import get_logger, log
from _conventions.validation import require_email, require_secret_str, require_str
from models import (
    ACCOUNT_COGNITO,
    ROLE_MEMBER,
    ROLE_UGL,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
    now_iso,
)
from providers import audit_log

_logger = get_logger("identity-access")

DEFAULT_OTP_INTERVAL_DAYS = 30


class AuthService:
    def __init__(self, repo, auth_provider, otp_service, events, settings=None, ses=None):
        self._repo = repo
        self._auth = auth_provider
        self._otp = otp_service
        self._events = events
        self._settings = settings or {}
        # Needed since self-registration became responsible for its own welcome
        # mail (BR-P8): the generated password is never disclosed, so that email is
        # the only thing telling the registrant to use "Forgot password".
        self._ses = ses

    # ---------------- login (US-1.2/1.15/1.32) ----------------
    def login(self, body: dict, *, ip: str | None = None, audit_enabled: bool = True) -> dict:
        email = require_email(body.get("email"))
        password = require_secret_str(body.get("password"), "password", max_len=256)

        # Every user, including the bootstrap Administrator (US-1.27), authenticates
        # through Cognito. `initiate_auth` raises UnauthorizedError on bad credentials
        # (generic — BR-A6, no enumeration).
        result = self._auth.initiate_auth(email, password)
        user = self._resolve_or_jit(result)
        if user["status"] == STATUS_INACTIVE or not result.get("enabled", True):
            audit_log("login.denied", actor=email, enabled=audit_enabled, ip=ip)
            raise UnauthorizedError()

        if self._otp_due(user):
            # Hand the ID token to the challenge — it cannot be re-minted at
            # verify time (that needs the password), and returning a fabricated
            # one is what broke every OTP-gated login before 2026-08-11.
            challenge_id = self._otp.issue(user, result.get("token", ""))
            audit_log("login.otp_challenge", actor=user["id"], enabled=audit_enabled, ip=ip)
            return {"otpRequired": True, "challengeId": challenge_id, "role": user["role"]}

        audit_log("login.success", actor=user["id"], enabled=audit_enabled, ip=ip)
        return self._session(user, result.get("token", ""),
                             result.get("refreshToken", ""))

    # ---------------- verifyOtp (US-1.32) ----------------
    def verify_otp(self, body: dict, *, challenge_id: str | None = None,
                   ip: str | None = None, audit_enabled: bool = True) -> dict:
        # Stripped for the same reason as the reset code in
        # confirm_reset_password: a pasted code carrying whitespace is compared
        # literally and fails, and the generic BR-A6 response gives the user no
        # way to tell that from a wrong code.
        raw_code = body.get("code")
        code = require_str(raw_code.strip() if isinstance(raw_code, str) else raw_code,
                           "code", max_len=12)
        challenge_id = challenge_id or body.get("challengeId")
        if not challenge_id:
            raise ValidationError(message="Missing challenge.")
        challenge = self._otp.verify(challenge_id, code)
        if not challenge:
            audit_log("otp.failed", actor=challenge_id, enabled=audit_enabled, ip=ip)
            raise UnauthorizedError()  # generic (BR-A6)
        user_id = challenge["userId"]
        user = self._repo.get_user(user_id)
        if not user:
            raise UnauthorizedError()

        # Fail closed on a challenge with no token: one written by the previous
        # release (deploy window), or a login where Cognito returned none. The
        # old placeholder fallback is exactly the bug being fixed — an apparently
        # successful sign-in whose first API call 401s. Checked BEFORE stamping
        # lastVerifiedAt so a failed attempt doesn't reset the re-verification
        # clock (that would skip OTP for the next interval without ever having
        # granted a session); the user retries login and gets a fresh challenge.
        token = challenge.get("idToken") or ""
        if not token:
            audit_log("otp.no_session_token", actor=user_id, enabled=audit_enabled, ip=ip)
            raise UnauthorizedError()

        user["lastVerifiedAt"] = now_iso()
        self._repo.put_user(user)
        audit_log("otp.verified", actor=user_id, enabled=audit_enabled, ip=ip)
        # ~55 min of usable session, not a full hour: the ID token's clock starts
        # at the password step, before the code is emailed (5-minute OTP window).
        #
        # NO refresh token on this path, deliberately (decision 2026-08-27). The
        # OTP challenge record would have to carry it — the ID token already rides
        # there because it cannot be re-minted at verify time — and that means a
        # long-lived credential sitting in a DynamoDB row waiting on an emailed
        # code. Not worth it for the convenience being bought. The consequence is
        # real and accepted: an OTP-gated user's group membership stays as it was at
        # sign-in until they sign in again, so the SPA's refresh attempt is a no-op
        # for them and the "sign out and back in" hint in the empty states is the
        # actual remedy.
        return self._session(user, token)

    @staticmethod
    def _session(user: dict, token: str, refresh_token: str = "") -> dict:
        """Session payload. `ledGroupId` is included for a UserGroupLeader so the
        SPA can route straight to My Group (US-1.16 — a UGL manages exactly one
        group, BR-G7) without first having to discover which group that is.
        `firstName`/`lastName` are included so the SPA can show real initials
        in the avatar button without a separate /members/me fetch at startup.

        `refreshToken` is OMITTED when empty rather than sent as "", so a client
        can test for its presence and know whether mid-session refresh is
        available at all. It is absent on the OTP path by design — see verify_otp.
        """
        out = {
            "token": token, "role": user["role"], "otpRequired": False,
            "firstName": user.get("firstName", ""),
            "lastName": user.get("lastName", ""),
        }
        if refresh_token:
            out["refreshToken"] = refresh_token
        if user.get("role") == ROLE_UGL and user.get("ledGroupId"):
            out["ledGroupId"] = user["ledGroupId"]
        return out

    # ---------------- refreshSession (stale-claims fix) ----------------
    def refresh_session(self, body: dict) -> dict:
        """Exchange a refresh token for a new ID token with CURRENT claims.

        Why this exists: `member_group_ids` is baked into the ID token by the
        pre-token-generation trigger at issuance. Group membership decides what a
        Member can see in the directory and the event ideas feed, so a member who
        joins a group mid-session would otherwise keep being told they are not in
        it until they signed out and back in. The SPA calls this straight after a
        successful join or leave.

        Unauthenticated by design (it sits under the public /auth/* prefix, which
        has no Cognito authorizer): the refresh token IS the credential, and the
        caller's current ID token may be precisely the stale thing being replaced.
        """
        refresh_token = require_secret_str(body.get("refreshToken"), "refreshToken",
                                          max_len=4096)
        return {"token": self._auth.refresh_id_token(refresh_token)}

    # ---------------- selfRegister (US-1.30) ----------------
    #
    # Unified with Administrator-created users and bulk import (BR-P8, reworked
    # 2026-08-11). NO password is accepted: the account is created with a
    # system-generated permanent password that is never disclosed, and the
    # registrant sets their own via "Forgot password" (US-1.20). Reading that code
    # is what proves they control the address they claimed — previously they chose
    # a password outright and proved nothing, which meant the LOWEST-trust path
    # (anonymous caller) carried the WEAKEST verification.
    REGISTER_ACK = ("If that address is eligible, you'll receive an email with "
                    "instructions to set your password.")

    def self_register(self, body: dict, *, ip: str | None = None, audit_enabled: bool = True) -> dict:
        if not self._settings.get("selfRegistrationEnabled", False):
            raise ValidationError(message="Self-registration is currently disabled.")

        email = require_email(body.get("email"))
        first = require_str(body.get("firstName"), "firstName", max_len=100)
        last = require_str(body.get("lastName"), "lastName", max_len=100)
        # `password` is TOLERATED but ignored for one release (decision 2026-08-11)
        # so a cached older SPA bundle keeps working. It is never used to set a
        # credential. Remove from the contract's properties once no client sends it.

        allowed = self._allowed_domains()
        if not self._domain_allowed(email, allowed):
            # Not an enumeration leak: this reveals the configured domain policy,
            # which the sign-up form already states, and NOT whether an account
            # exists. Kept specific because it is the one rejection a registrant
            # can actually act on.
            raise ValidationError(message="Email domain is not permitted for registration.")

        # Already registered => return the SAME acknowledgement as success and
        # create/modify NOTHING (BR-A6). Previously this reached admin_create_user,
        # raised UsernameExistsException, and surfaced as a generic 500 while a new
        # address returned 201 — two distinguishable outcomes let an anonymous
        # caller discover who holds an account.
        if self._auth.user_exists(email) or self._repo.get_user_by_email(email):
            audit_log("user.self_register_existing", actor=email, enabled=audit_enabled, ip=ip)
            return {"message": self.REGISTER_ACK}

        res = self._auth.admin_create_user(email, first, last)  # BR-P8 — one primitive, all paths

        # Create the portal record NOW, exactly as create_user and bulk_import do,
        # rather than leaving it to first-login JIT. Unifying the Cognito call was
        # not enough: with no portal record, confirmResetPassword had nothing to
        # stamp (BR-A10), so JIT created a record with no lastVerifiedAt at first
        # login and the OTP fired anyway — defeating the point of the rework for
        # this path. JIT remains the no-op fallback it is meant to be (BR-P1).
        user = {
            "id": res["sub"], "email": email, "firstName": first, "lastName": last,
            "role": ROLE_MEMBER,          # self-registration can grant nothing else (BR-P3)
            "status": STATUS_ACTIVE, "accountType": ACCOUNT_COGNITO,
            "createdAt": now_iso(), "updatedAt": now_iso(),
        }
        self._repo.put_user(user)
        self._events.publish(
            "UserProvisioned",
            {"userId": res["sub"], "email": email, "firstName": first, "lastName": last,
             "role": ROLE_MEMBER, "source": "self-registration"},
        )
        self._send_welcome_email(email, first)
        audit_log("user.self_register", actor=email, enabled=audit_enabled, ip=ip)
        # Response carries no user data: echoing the created account back would
        # itself distinguish "created" from "already existed".
        return {"message": self.REGISTER_ACK}

    def _send_welcome_email(self, email: str, first_name: str) -> None:
        """Same welcome mail as bulk import (BR-P4): the generated password is never
        disclosed, so this is what tells the user to use "Forgot password".

        Best-effort — the account exists and works regardless, and failing the
        request would both contradict the uniform acknowledgement (BR-A6) and, while
        SES is in sandbox, make registration appear broken for every address SES
        cannot reach. Note the consequence: with SES unable to deliver, the user
        gets no instructions at all and must be told out of band.
        """
        if not self._ses:
            return
        try:
            self._ses.send(
                email,
                "Welcome to the community portal",
                f"Hi {first_name or ''},\n\n"
                "Your account on the community portal has been created. "
                "To set your password and sign in, use \"Forgot password\" on the "
                f"login page with your email address ({email}) to receive a "
                "verification code.\n\n"
                "If you weren't expecting this, you can ignore this email.",
            )
        except Exception:  # noqa: BLE001 — registration must still succeed
            log(_logger, 30, "welcome email failed (registration already succeeded)", to=email)

    # ---------------- resetPassword (US-1.20) ----------------
    def reset_password(self, body: dict, *, principal=None, ip: str | None = None,
                       audit_enabled: bool = True) -> dict:
        """Step 1 — request a reset code. Every user, including the bootstrap
        Administrator, resets via the Cognito hosted forgot-password flow
        (US-1.20/1.27). Always returns the same generic message regardless of
        whether the email exists, so the response can't be used to enumerate
        accounts (BR-A6); the email-format check below is the one exception —
        it's a client input error, not an account-existence signal."""
        email = require_email(body.get("email"))
        self._auth.forgot_password(email)
        audit_log("user.reset_requested", actor=email, enabled=audit_enabled, ip=ip)
        return {"message": "If the account exists, a verification code has been sent to its email."}

    # ---------------- confirmResetPassword (US-1.20) ----------------
    def confirm_reset_password(self, body: dict, *, principal=None, ip: str | None = None,
                               audit_enabled: bool = True) -> dict:
        """Step 2 — submit the emailed code plus a new password. Delegates
        policy enforcement (length/complexity) to Cognito (US-1.2/1.20)."""
        email = require_email(body.get("email"))
        # STRIP the code before Cognito sees it. Copying a 6-digit code out of an
        # email very often carries a trailing space or newline, and Cognito
        # compares the literal string: " 123456" comes back as
        # CodeMismatchException, which this service reports as "That code is
        # invalid or has expired." The user then retries the RIGHT code, gets the
        # same message, and concludes reset is broken — indistinguishable, from
        # the outside, from a genuinely bad code. Neither require_str (no
        # trimming, by design) nor the SPA input was normalizing it.
        # Whitespace is never significant in a verification code, so strip here,
        # server-side, where it covers the SPA and any other API client.
        raw_code = body.get("code")
        code = require_str(raw_code.strip() if isinstance(raw_code, str) else raw_code,
                           "code", max_len=32)
        new_password = require_secret_str(body.get("newPassword"), "newPassword", max_len=256, min_len=8)

        self._auth.confirm_forgot_password(email, code, new_password)
        # Completing this flow PROVES control of the registered mailbox: Cognito
        # only accepts a code it emailed there. That is exactly the assurance the
        # in-service OTP exists to obtain, so record it here (US-1.32).
        #
        # Without this, an admin-created or bulk-imported user (US-1.31 — invite
        # mail suppressed, system-generated password never disclosed, so "Forgot
        # password" is the ONLY way in) would immediately hit a first-login OTP,
        # because _otp_due treats a missing lastVerifiedAt as due. Self-registered
        # users are deliberately NOT covered: that path emails nothing and asserts
        # email_verified itself, so its first-login OTP is the only mailbox check
        # it has.
        self._mark_mailbox_verified(email)
        audit_log("user.reset_confirmed", actor=email, enabled=audit_enabled, ip=ip)
        return {"message": "Password has been reset. You can now sign in."}

    def _mark_mailbox_verified(self, email: str) -> None:
        """Stamp lastVerifiedAt after PROVEN mailbox control (valid emailed code).

        Best-effort by design: the password has already been changed in Cognito,
        so a bookkeeping failure here must not be reported as a failed reset.
        A missing portal record is a silent no-op — JIT creates it at first login
        (BR-P1). The response is identical either way, so this leaks nothing about
        whether the account exists (BR-A6).
        """
        try:
            user = self._repo.get_user_by_email(email)
            if not user:
                return
            user["lastVerifiedAt"] = now_iso()
            self._repo.put_user(user)
        except Exception:  # noqa: BLE001 — reset already succeeded; never fail it
            log(_logger, 30, "could not stamp lastVerifiedAt after password reset")

    # ---------------- logout (US-1.3) ----------------
    def logout(self, *, principal=None, audit_enabled: bool = True) -> dict:
        actor = getattr(principal, "user_id", "anonymous") if principal else "anonymous"
        audit_log("logout", actor=actor, enabled=audit_enabled)
        return {"message": "Logged out."}

    # ---------------- refreshClaims (stale-JWT supplement) ----------------
    def refresh_claims(self, *, principal=None) -> dict:
        """Return the caller's current claims (role, led_group_id, member_group_ids)
        freshly read from the database. This allows the frontend to discover updated
        group memberships mid-session without re-authenticating, solving the stale-JWT
        problem where joining a group is not reflected until re-login."""
        if not principal:
            from _conventions.errors import UnauthorizedError as _Unauth
            raise _Unauth()
        user = self._repo.get_user(principal.user_id)
        if not user:
            return {"role": ROLE_MEMBER, "led_group_id": "", "member_group_ids": []}
        role = user.get("role", ROLE_MEMBER)
        led_group_id = ""
        member_group_ids: list[str] = []
        if role == ROLE_UGL:
            led_group_id = user.get("ledGroupId") or ""
        elif role == ROLE_MEMBER:
            member_group_ids = sorted(self._repo.current_groups_for_member(user["id"]))
        return {
            "role": role,
            "led_group_id": led_group_id,
            "member_group_ids": member_group_ids,
        }

    # ---------------- helpers ----------------
    def _resolve_or_jit(self, result: dict) -> dict:
        """JIT provisioning (US-1.15): no-op if a portal record already exists (BR-P1)."""
        sub = result.get("sub") or result.get("email")
        user = self._repo.get_user(sub) or self._repo.get_user_by_email(result.get("email", ""))
        if user:
            return user
        user = {
            "id": sub,
            "email": result.get("email"),
            "firstName": result.get("firstName", ""),
            "lastName": result.get("lastName", ""),
            "role": ROLE_MEMBER,
            "status": STATUS_ACTIVE,
            "accountType": ACCOUNT_COGNITO,
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }
        self._repo.put_user(user)
        self._events.publish("UserProvisioned",
                             {"userId": sub, "email": user["email"],
                              "firstName": user["firstName"], "lastName": user["lastName"],
                              "role": ROLE_MEMBER, "source": "jit"})
        return user

    def _otp_due(self, user: dict) -> bool:
        from datetime import datetime, timezone
        last = user.get("lastVerifiedAt")
        interval_days = int(self._settings.get("otpIntervalDays", DEFAULT_OTP_INTERVAL_DAYS))
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            delta = datetime.now(timezone.utc) - last_dt
            return delta.days >= interval_days
        except (ValueError, TypeError):
            # ValueError: unparseable. TypeError: NAIVE timestamp — subtracting it
            # from an aware "now" raises, and this sits on the LOGIN path, so an
            # imported or hand-repaired row without an offset would lock that user
            # out entirely. Either way, degrade towards re-verification: a record
            # we cannot read must never be taken as recently verified.
            return True

    def _allowed_domains(self) -> list[str]:
        return self._settings.get("allowedEmailDomains", [])

    @staticmethod
    def _domain_allowed(email: str, allowed: list[str]) -> bool:
        if not allowed:
            return False  # empty allow-list ⇒ blocked (BR-P3 default)
        domain = email.split("@")[-1].lower()
        return domain in {d.lower() for d in allowed}
