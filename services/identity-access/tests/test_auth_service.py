"""AuthService tests (US-1.2/1.15/1.27/1.30/1.32) — real CognitoAuthProvider on moto."""
import pytest
from _conventions.errors import UnauthorizedError, ValidationError
from models import ROLE_ADMIN, ROLE_MEMBER, STATUS_ACTIVE, now_iso


def test_bootstrap_admin_login_via_cognito(ctx, aws, repo):
    """The bootstrap Administrator (US-1.27) is a regular Cognito user, seeded with
    role=Administrator (as Seed does). It signs in through the same Cognito path
    as every other user — no separate local credential store."""
    sub = aws.create_user("admin@company.com", "AdminPass!123")
    repo.put_user({"id": sub, "email": "admin@company.com", "firstName": "Admin", "lastName": "User",
                   "role": ROLE_ADMIN, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    out = ctx.auth_service.login({"email": "admin@company.com", "password": "AdminPass!123"})
    assert out["role"] == ROLE_ADMIN
    assert out["otpRequired"] is False
    assert out["token"]


def test_login_accepts_angle_bracket_password(ctx, aws, repo):
    """Passwords may legitimately contain '<'/'>' (e.g. Secrets Manager generated
    ones) — the XSS input guard must not apply to secret fields (deploy regression:
    the seeded bootstrap-admin password contained '<' and login returned 400)."""
    pw = "Adm<in>Pass!123"
    sub = aws.create_user("bracket@company.com", pw)
    repo.put_user({"id": sub, "email": "bracket@company.com", "firstName": "B", "lastName": "U",
                   "role": ROLE_ADMIN, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    out = ctx.auth_service.login({"email": "bracket@company.com", "password": pw})
    assert out["otpRequired"] is False
    assert out["token"]


def test_admin_login_bad_password_generic(ctx, aws, repo):
    sub = aws.create_user("admin2@company.com", "AdminPass!123")
    repo.put_user({"id": sub, "email": "admin2@company.com", "firstName": "Admin", "lastName": "User",
                   "role": ROLE_ADMIN, "status": STATUS_ACTIVE, "accountType": "cognito"})
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.login({"email": "admin2@company.com", "password": "wrong"})


def test_community_login_otp_due_when_never_verified(ctx, aws):
    aws.create_user("dev@company.com", "Secret!123")
    out = ctx.auth_service.login({"email": "dev@company.com", "password": "Secret!123"})
    assert out["otpRequired"] is True          # JIT record has no lastVerifiedAt → OTP due
    assert out["challengeId"]
    assert ctx.ses.sent                         # OTP emailed


def test_community_login_no_otp_when_recently_verified(ctx, aws, repo):
    sub = aws.create_user("dev@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "dev@company.com", "firstName": "Dev", "lastName": "User",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    out = ctx.auth_service.login({"email": "dev@company.com", "password": "Secret!123"})
    assert out["otpRequired"] is False
    assert out["token"]


def test_otp_verify_flow(ctx, aws, repo):
    aws.create_user("dev@company.com", "Secret!123")
    login = ctx.auth_service.login({"email": "dev@company.com", "password": "Secret!123"})
    code = ctx.ses.sent[-1]["body"].split("code is ")[1].split(".")[0].strip()
    out = ctx.auth_service.verify_otp({"code": code, "challengeId": login["challengeId"]})
    assert out["otpRequired"] is False
    # lastVerifiedAt stamped on the portal record.
    user = repo.get_user_by_email("dev@company.com")
    assert user["lastVerifiedAt"]


def test_otp_verify_returns_the_real_cognito_token(ctx, aws):
    """The token must be the JWT from the password step, NOT a fabricated one.
    Regression for 2026-08-11: verify_otp returned `session-<userId>`, which the
    API Gateway Cognito authorizer rejects, so every OTP-gated login (including
    every first login — JIT records have no lastVerifiedAt) looked successful and
    then 401'd on its first API call. `assert out["token"]` would NOT catch this:
    the placeholder is truthy. Assert its shape instead."""
    aws.create_user("dev@company.com", "Secret!123")
    login = ctx.auth_service.login({"email": "dev@company.com", "password": "Secret!123"})
    assert login["otpRequired"] is True
    code = ctx.ses.sent[-1]["body"].split("code is ")[1].split(".")[0].strip()
    out = ctx.auth_service.verify_otp({"code": code, "challengeId": login["challengeId"]})

    token = out["token"]
    assert not token.startswith("session-")
    assert token.count(".") == 2, "expected a three-segment JWT from Cognito"


def test_otp_verify_fails_closed_when_the_challenge_carries_no_token(ctx, aws, repo):
    """A challenge written by the PREVIOUS release has no idToken (deploy window).
    Reject it rather than falling back to a placeholder — an intermittently dead
    session is worse than being told to sign in again. lastVerifiedAt must NOT be
    stamped, or the failed attempt would reset the re-verification clock and skip
    OTP for a whole interval without ever having granted a session."""
    aws.create_user("dev@company.com", "Secret!123")
    login = ctx.auth_service.login({"email": "dev@company.com", "password": "Secret!123"})
    code = ctx.ses.sent[-1]["body"].split("code is ")[1].split(".")[0].strip()

    challenge = repo.get_otp(login["challengeId"])
    challenge["idToken"] = ""  # simulate a pre-fix challenge record
    repo.put_otp(challenge)

    with pytest.raises(UnauthorizedError):
        ctx.auth_service.verify_otp({"code": code, "challengeId": login["challengeId"]})
    assert not repo.get_user_by_email("dev@company.com").get("lastVerifiedAt")


def test_otp_verify_bad_code_generic_error(ctx, aws):
    aws.create_user("dev@company.com", "Secret!123")
    login = ctx.auth_service.login({"email": "dev@company.com", "password": "Secret!123"})
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.verify_otp({"code": "000000", "challengeId": login["challengeId"]})


def test_login_wrong_password_generic(ctx, aws):
    aws.create_user("dev@company.com", "Secret!123")
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.login({"email": "dev@company.com", "password": "WrongPass!1"})


def test_login_unknown_user_generic(ctx):
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.login({"email": "ghost@company.com", "password": "whatever"})


def test_self_register_rejects_disallowed_domain(ctx):
    with pytest.raises(ValidationError):
        ctx.auth_service.self_register({"email": "x@evil.com", "firstName": "A",
                                        "lastName": "B", "password": "Secret!123"})


def test_self_register_allows_permitted_domain(ctx, aws):
    """Reworked 2026-08-11 (BR-P8): no password is collected and the response is a
    bare acknowledgement, so it cannot echo the created account back."""
    out = ctx.auth_service.self_register({"email": "new@company.com", "firstName": "N",
                                          "lastName": "U"})
    assert "message" in out
    assert "email" not in out and "role" not in out
    # The Cognito account exists and is immediately usable for a password reset.
    assert ctx.auth_service._auth.user_exists("new@company.com")


def test_self_register_rejected_when_disabled(ctx):
    """Self-registration master switch (Settings addendum) — when off, register
    is rejected even for an otherwise-allowed domain."""
    ctx.settings["selfRegistrationEnabled"] = False
    with pytest.raises(ValidationError):
        ctx.auth_service.self_register({"email": "new@company.com", "firstName": "N",
                                        "lastName": "U", "password": "Secret!123"})


def test_reset_password_requests_code_generic_response(ctx, aws):
    aws.create_user("dev@company.com", "Secret!123")
    out = ctx.auth_service.reset_password({"email": "dev@company.com"})
    assert "message" in out


def test_reset_password_generic_response_for_unknown_email(ctx):
    # No user enumeration (BR-A6): same generic response either way.
    out = ctx.auth_service.reset_password({"email": "ghost@company.com"})
    assert "message" in out


def test_reset_password_rejects_malformed_email(ctx):
    with pytest.raises(ValidationError):
        ctx.auth_service.reset_password({"email": "not-an-email"})


def test_confirm_reset_password_success(ctx, aws):
    aws.create_user("dev@company.com", "Secret!123")
    ctx.auth_service.reset_password({"email": "dev@company.com"})
    # moto surfaces the generated code via a response header on forgot_password;
    # exercise confirm_forgot_password directly through the same provider path.
    code = aws.idp.forgot_password(ClientId=aws.client_id, Username="dev@company.com")[
        "ResponseMetadata"]["HTTPHeaders"]["x-moto-forgot-password-confirmation-code"]
    out = ctx.auth_service.confirm_reset_password(
        {"email": "dev@company.com", "code": code, "newPassword": "NewSecret!123"})
    assert "message" in out
    # New password now works for login.
    login = ctx.auth_service.login({"email": "dev@company.com", "password": "NewSecret!123"})
    assert login["otpRequired"] in (True, False)


@pytest.mark.parametrize("wrapper", [
    "{c} ",       # trailing space — the common case when copying from an email
    " {c}",       # leading space (see note below: not actually exercised by moto)
    "{c}\n",      # trailing newline
    "  {c}  \r\n",
])
def test_confirm_reset_password_tolerates_whitespace_around_the_code(ctx, aws, wrapper):
    """A pasted code routinely carries surrounding whitespace. Cognito compares
    the literal string, so " 123456" returns CodeMismatchException, which this
    service reports as "That code is invalid or has expired." — identical to a
    genuinely wrong code. A live admin reset failed repeatedly this way: the
    operator was submitting the CORRECT code and being told it was invalid, with
    no way to tell the difference. Strip server-side so every client benefits.

    Verified non-vacuous by removing the strip and re-running: the trailing-space,
    trailing-newline and mixed cases all FAIL without it. The LEADING-space case
    passes either way and is retained only for symmetry — moto validates a code
    only when it starts with its "moto-confirmation-code:" marker, so a leading
    space makes moto skip validation and accept anything. Real Cognito compares
    the whole string and would reject it, which is why the case belongs here even
    though this test double cannot demonstrate it."""
    aws.create_user("dev@company.com", "Secret!123")
    ctx.auth_service.reset_password({"email": "dev@company.com"})
    code = aws.idp.forgot_password(ClientId=aws.client_id, Username="dev@company.com")[
        "ResponseMetadata"]["HTTPHeaders"]["x-moto-forgot-password-confirmation-code"]

    out = ctx.auth_service.confirm_reset_password(
        {"email": "dev@company.com", "code": wrapper.format(c=code),
         "newPassword": "NewSecret!123"})
    assert "message" in out
    # Proves the reset actually took effect, not merely that no error was raised.
    assert ctx.auth_service.login(
        {"email": "dev@company.com", "password": "NewSecret!123"})["otpRequired"] in (True, False)


def test_confirm_reset_password_still_rejects_a_whitespace_only_code(ctx, aws):
    """Stripping must not turn an empty submission into a valid-looking one:
    require_str's min_len=1 has to fire AFTER the strip, not before."""
    aws.create_user("dev@company.com", "Secret!123")
    with pytest.raises(ValidationError):
        ctx.auth_service.confirm_reset_password(
            {"email": "dev@company.com", "code": "   ", "newPassword": "NewSecret!123"})


def test_confirm_reset_password_bad_code_generic_error(ctx, aws):
    aws.create_user("dev@company.com", "Secret!123")
    ctx.auth_service.reset_password({"email": "dev@company.com"})
    # moto only validates codes carrying its own "moto-confirmation-code:" prefix
    # (real Cognito validates any code against the one it issued) — use that
    # prefix with a wrong value to exercise the mismatch/expired path.
    with pytest.raises(ValidationError):
        ctx.auth_service.confirm_reset_password(
            {"email": "dev@company.com", "code": "moto-confirmation-code:000000",
             "newPassword": "NewSecret!123"})


def test_confirm_reset_password_rejects_short_password(ctx, aws):
    aws.create_user("dev@company.com", "Secret!123")
    with pytest.raises(ValidationError):
        ctx.auth_service.confirm_reset_password(
            {"email": "dev@company.com", "code": "123456", "newPassword": "short"})


# --- lastVerifiedAt stamped on proven mailbox control (2026-08-11) ------------
# Completing the Cognito forgot-password flow requires a code Cognito emailed to
# the registered address, so it proves the same thing the in-service OTP does.
# Without the stamp, an admin-created / bulk-imported user (invite mail
# suppressed, password never disclosed => "Forgot password" is the ONLY way in)
# hits a first-login OTP whose mail SES may be unable to deliver.

def _forgot_code(aws, email):
    """moto returns the generated code in a response header."""
    return aws.idp.forgot_password(ClientId=aws.client_id, Username=email)[
        "ResponseMetadata"]["HTTPHeaders"]["x-moto-forgot-password-confirmation-code"]


def test_confirm_reset_password_stamps_last_verified_at(ctx, aws, repo):
    sub = aws.create_user("dev@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "dev@company.com", "firstName": "Dev",
                   "lastName": "User", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    assert not repo.get_user_by_email("dev@company.com").get("lastVerifiedAt")

    ctx.auth_service.confirm_reset_password(
        {"email": "dev@company.com", "code": _forgot_code(aws, "dev@company.com"),
         "newPassword": "NewSecret!123"})

    assert repo.get_user_by_email("dev@company.com")["lastVerifiedAt"]


def test_login_after_reset_needs_no_otp(ctx, aws, repo):
    """The point of the stamp: the very next login yields a session directly
    instead of an OTP challenge that depends on SES being able to reach them."""
    sub = aws.create_user("dev@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "dev@company.com", "firstName": "Dev",
                   "lastName": "User", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    ctx.auth_service.confirm_reset_password(
        {"email": "dev@company.com", "code": _forgot_code(aws, "dev@company.com"),
         "newPassword": "NewSecret!123"})

    out = ctx.auth_service.login({"email": "dev@company.com", "password": "NewSecret!123"})
    assert out["otpRequired"] is False
    assert out["token"]
    assert not ctx.ses.sent, "no OTP email should be needed after a proven reset"


def test_confirm_reset_password_succeeds_with_no_portal_record(ctx, aws, repo):
    """No portal record yet (JIT creates it at first login, BR-P1). The stamp is a
    silent no-op — a bookkeeping gap must not turn a completed password reset into
    an error, and the response must not reveal whether the account exists."""
    aws.create_user("ghost@company.com", "Secret!123")
    assert repo.get_user_by_email("ghost@company.com") is None

    out = ctx.auth_service.confirm_reset_password(
        {"email": "ghost@company.com", "code": _forgot_code(aws, "ghost@company.com"),
         "newPassword": "NewSecret!123"})
    assert "message" in out


# --- US-1.30 unified provisioning (BR-P8, reworked 2026-08-11) ----------------
# Self-registration used to accept the caller's password and set it as permanent,
# so a registrant never had to read anything sent to the address they claimed —
# the LOWEST-trust path carried the WEAKEST verification. It now uses the same
# primitive as Administrator-created users and bulk import.

def test_self_register_does_not_accept_a_caller_password(ctx, aws):
    """`password` is tolerated for one release but must NEVER become the account
    credential — otherwise the whole point of the rework is lost. Proven by trying
    to log in with it."""
    ctx.auth_service.self_register({"email": "new@company.com", "firstName": "N",
                                   "lastName": "U", "password": "Attacker!123"})
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.login({"email": "new@company.com", "password": "Attacker!123"})


def test_self_register_is_indistinguishable_for_an_existing_address(ctx, aws, repo):
    """BR-A6. Previously a new address returned 201 and an existing one raised
    UsernameExistsException -> generic 500, letting an anonymous caller discover
    who holds an account."""
    first = ctx.auth_service.self_register({"email": "new@company.com", "firstName": "N",
                                           "lastName": "U"})
    again = ctx.auth_service.self_register({"email": "new@company.com", "firstName": "Someone",
                                           "lastName": "Else"})
    assert again == first


def test_re_registering_does_not_touch_the_existing_account(ctx, aws, repo):
    """The uniform response must not come at the cost of overwriting a real user —
    that would be an account takeover dressed as anti-enumeration."""
    sub = aws.create_user("victim@company.com", "TheirOwn!123")
    repo.put_user({"id": sub, "email": "victim@company.com", "firstName": "Real",
                   "lastName": "Owner", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})

    ctx.auth_service.self_register({"email": "victim@company.com", "firstName": "Imp",
                                   "lastName": "Ostor"})

    user = repo.get_user_by_email("victim@company.com")
    assert user["firstName"] == "Real" and user["lastName"] == "Owner"
    # And their existing password still works — nothing was reset.
    assert ctx.auth_service.login(
        {"email": "victim@company.com", "password": "TheirOwn!123"})["otpRequired"] in (True, False)


def test_self_register_sends_the_welcome_email(ctx, aws):
    """The generated password is never disclosed, so this mail is the ONLY thing
    telling the registrant to use "Forgot password"."""
    ctx.auth_service.self_register({"email": "new@company.com", "firstName": "N",
                                    "lastName": "U"})
    assert ctx.ses.sent, "a welcome email must be sent"
    assert "Forgot password" in ctx.ses.sent[-1]["body"]


def test_self_register_survives_a_failed_welcome_email(ctx, aws, monkeypatch):
    """SES is in sandbox on the dev stack, so delivery fails for most addresses.
    Registration must still succeed and still return the uniform acknowledgement —
    failing here would both contradict BR-A6 and make registration look broken."""
    def boom(*_a, **_k):
        raise RuntimeError("SES rejected: address not verified")
    monkeypatch.setattr(ctx.ses, "send", boom)

    out = ctx.auth_service.self_register({"email": "new@company.com", "firstName": "N",
                                         "lastName": "U"})
    assert "message" in out
    assert ctx.auth_service._auth.user_exists("new@company.com")


def test_self_register_still_enforces_the_domain_allow_list_before_creating(ctx, aws):
    """Gate order matters: a disallowed domain must be rejected BEFORE any Cognito
    account is created."""
    with pytest.raises(ValidationError):
        ctx.auth_service.self_register({"email": "x@evil.com", "firstName": "A", "lastName": "B"})
    assert not ctx.auth_service._auth.user_exists("x@evil.com")


def test_registered_user_can_set_a_password_and_then_log_in(ctx, aws, repo):
    """End-to-end: register -> Forgot password -> login. This is the flow that
    replaces the caller-chosen password, and it is what proves mailbox control."""
    ctx.auth_service.self_register({"email": "new@company.com", "firstName": "N",
                                    "lastName": "U"})
    ctx.auth_service.reset_password({"email": "new@company.com"})
    code = aws.idp.forgot_password(ClientId=aws.client_id, Username="new@company.com")[
        "ResponseMetadata"]["HTTPHeaders"]["x-moto-forgot-password-confirmation-code"]
    ctx.auth_service.confirm_reset_password(
        {"email": "new@company.com", "code": code, "newPassword": "MyOwn!123"})

    out = ctx.auth_service.login({"email": "new@company.com", "password": "MyOwn!123"})
    assert out["token"]
    # BR-A10: the reset proved the mailbox, so no first-login OTP is demanded.
    assert out["otpRequired"] is False


# --- Mid-session ID-token refresh (2026-08-27) --------------------------------
#
# Group membership travels in the ID token as the `member_group_ids` claim, stamped
# by the pre-token-generation trigger at issuance. The directory and the event ideas
# feed are scoped by that claim, so a member who joins a group mid-session was told
# they were not in it until they signed out and back in. REFRESH_TOKEN_AUTH re-runs
# the trigger, which is what makes an immediate fix possible.

def test_login_returns_a_refresh_token(ctx, aws, repo):
    """The credential the whole flow depends on. `initiate_auth` previously read
    only AuthenticationResult.IdToken and dropped the refresh token, so the SPA had
    nothing to refresh with."""
    sub = aws.create_user("ref@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "ref@company.com", "firstName": "R", "lastName": "T",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})

    out = ctx.auth_service.login({"email": "ref@company.com", "password": "Secret!123"})

    assert out["refreshToken"]


def test_refresh_session_returns_a_new_id_token(ctx, aws, repo):
    sub = aws.create_user("ref2@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "ref2@company.com", "firstName": "R", "lastName": "T",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    login = ctx.auth_service.login({"email": "ref2@company.com", "password": "Secret!123"})

    out = ctx.auth_service.refresh_session({"refreshToken": login["refreshToken"]})

    assert out["token"]


def test_refresh_session_rejects_a_bad_refresh_token(ctx):
    """Cognito's rejection must surface as 401, not leak as a 500."""
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.refresh_session({"refreshToken": "not-a-real-token"})


def test_refresh_session_requires_a_refresh_token(ctx):
    with pytest.raises(ValidationError):
        ctx.auth_service.refresh_session({})


def test_otp_path_returns_no_refresh_token(ctx, aws):
    """Deliberate omission (decision 2026-08-27), pinned so it cannot be "fixed"
    by accident. Supporting refresh here would mean parking a long-lived credential
    in the OTP challenge record — a DynamoDB row waiting on an emailed code. The
    accepted consequence is that OTP-gated users pick up membership changes only at
    their next sign-in."""
    aws.create_user("otp@company.com", "Secret!123")
    login = ctx.auth_service.login({"email": "otp@company.com", "password": "Secret!123"})
    assert login["otpRequired"] is True
    code = ctx.ses.sent[-1]["body"].split("code is ")[1].split(".")[0].strip()

    out = ctx.auth_service.verify_otp({"code": code, "challengeId": login["challengeId"]})

    assert out["token"]
    assert "refreshToken" not in out


def test_refreshed_token_is_reachable_over_http_without_a_bearer(ctx, aws, repo):
    """POST /auth/refresh must be PUBLIC. /auth/* carries no Cognito authorizer, so
    an authenticated-only op there would be unreachable rather than merely stricter
    — and the token being replaced may be the stale one the caller wants rid of."""
    import json

    from app import dispatch

    sub = aws.create_user("ref3@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "ref3@company.com", "firstName": "R", "lastName": "T",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    login = ctx.auth_service.login({"email": "ref3@company.com", "password": "Secret!123"})

    resp = dispatch({
        "httpMethod": "POST",
        "path": "/auth/refresh",
        "headers": {},
        # No authorizer claims at all — the refresh token IS the credential.
        "requestContext": {"authorizer": {"claims": {}}},
        "queryStringParameters": None,
        "body": json.dumps({"refreshToken": login["refreshToken"]}),
    }, ctx)

    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["token"]
