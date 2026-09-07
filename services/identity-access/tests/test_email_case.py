"""Cognito username case normalization (regression, diagnosed live 2026-08-26).

The user pool is CASE-SENSITIVE — created by CloudFormation with no
`UsernameConfiguration`, and AWS defaults `CaseSensitive` to true for pools made
via API/CFN. It cannot be switched afterwards (AWS requires migrating users to a
new pool), so `CognitoAuthProvider` normalizes on our side instead.

The bug these tests pin: `create_user`/`bulk_import` lowercased before calling
Cognito, but `login`, `forgot_password` and `confirm_forgot_password` forwarded
whatever the user typed. An account added as "user+loadtestUgl@example.com" was
stored as ...ugl@..., so a reset requested with the capital U raised
UserNotFoundException — which `forgot_password` swallows for anti-enumeration.
Result: HTTP 200, "a verification code has been sent", no email, and no log line.
The user could neither sign in nor reset, and every attempt reported success.

Most tests here drive a RECORDING fake client rather than moto, because the
invariant under test is "whatever reaches Cognito is lowercase". Asserting that
directly does not depend on how faithfully moto emulates pool case sensitivity.
"""
import pytest
from _conventions.errors import UnauthorizedError, ValidationError
from providers import CognitoAuthProvider, cognito_username


class RecordingIdp:
    """Minimal stand-in for a boto3 cognito-idp client that records the exact
    Username / USERNAME value it was asked to act on."""

    # Mirrors botocore's `client.exceptions` namespace, which the provider
    # catches by attribute (`self.client.exceptions.UserNotFoundException`).
    # Built dynamically only to avoid eight near-identical class bodies.
    exceptions = type("exceptions", (), {
        name: type(name, (Exception,), {})
        for name in ("UserNotFoundException", "InvalidParameterException",
                     "NotAuthorizedException", "UsernameExistsException",
                     "TooManyRequestsException", "CodeMismatchException",
                     "ExpiredCodeException", "InvalidPasswordException")
    })

    def __init__(self, raises: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self._raises = raises or {}

    def _record(self, op, kwargs):
        self.calls.append((op, kwargs))
        if op in self._raises:
            raise self._raises[op]

    def usernames(self) -> list[str]:
        """Every username this client was handed, across all operations."""
        out = []
        for _op, kw in self.calls:
            if "Username" in kw:
                out.append(kw["Username"])
            if "AuthParameters" in kw:
                out.append(kw["AuthParameters"]["USERNAME"])
        return out

    def admin_initiate_auth(self, **kw):
        self._record("admin_initiate_auth", kw)
        return {"AuthenticationResult": {"IdToken": "id-token"}}

    def admin_get_user(self, **kw):
        self._record("admin_get_user", kw)
        return {"Enabled": True, "UserAttributes": [
            {"Name": "sub", "Value": "sub-1"},
            {"Name": "email", "Value": kw.get("Username", "")},
            {"Name": "given_name", "Value": "Dev"},
            {"Name": "family_name", "Value": "User"},
        ]}

    def admin_create_user(self, **kw):
        self._record("admin_create_user", kw)
        return {"User": {"Attributes": [{"Name": "sub", "Value": "sub-1"}]}}

    def admin_set_user_password(self, **kw):
        self._record("admin_set_user_password", kw)

    def forgot_password(self, **kw):
        self._record("forgot_password", kw)

    def confirm_forgot_password(self, **kw):
        self._record("confirm_forgot_password", kw)

    def admin_enable_user(self, **kw):
        self._record("admin_enable_user", kw)

    def admin_disable_user(self, **kw):
        self._record("admin_disable_user", kw)


MIXED = "  User+LoadtestUgl@Example.COM "
NORMALIZED = "user+loadtestugl@example.com"


# ---------------------------------------------------------------- the normalizer

@pytest.mark.parametrize(("raw", "expected"), [
    ("user+loadtestUgl@example.com", "user+loadtestugl@example.com"),
    ("USER@EXAMPLE.COM", "user@example.com"),
    ("already@lower.com", "already@lower.com"),
    # Whitespace is stripped for the same reason case is folded: a pasted address
    # with a trailing space is a mismatch the user cannot see.
    ("  spaced@x.com  ", "spaced@x.com"),
    ("\tTabbed@X.com\n", "tabbed@x.com"),
    ("", ""),
    (None, ""),
])
def test_cognito_username_normalizes(raw, expected):
    assert cognito_username(raw) == expected


# ------------------------------------------- every call into Cognito is lowercase

def test_login_looks_up_the_lowercase_username():
    idp = RecordingIdp()
    CognitoAuthProvider(client=idp).initiate_auth(MIXED, "Secret!123")
    # Both the auth call and the follow-up profile read must agree, or login
    # succeeds and then fails to resolve the account.
    assert idp.usernames() == [NORMALIZED, NORMALIZED]


def test_forgot_password_sends_to_the_lowercase_username():
    """THE reported bug: this is the call that silently found nothing."""
    idp = RecordingIdp()
    CognitoAuthProvider(client=idp).forgot_password(MIXED)
    assert idp.usernames() == [NORMALIZED]


def test_confirm_forgot_password_uses_the_lowercase_username():
    idp = RecordingIdp()
    CognitoAuthProvider(client=idp).confirm_forgot_password(MIXED, "123456", "NewPass!123")
    assert idp.usernames() == [NORMALIZED]


def test_account_is_created_under_the_lowercase_username():
    """Normalized at creation too, so the username an account is CREATED under is
    the one every later sign-in and reset looks up. create_user/bulk_import
    already lowercased, but self_register did not — it was minting mixed-case
    usernames that only an exactly-matching retype could authenticate."""
    idp = RecordingIdp()
    out = CognitoAuthProvider(client=idp).admin_create_user(MIXED, "Dev", "User")

    # AdminCreateUser AND the immediately-following permanent-password set.
    assert idp.usernames() == [NORMALIZED, NORMALIZED]
    assert out["email"] == NORMALIZED
    # The email ATTRIBUTE matches the username; Cognito refuses to deliver a
    # reset code to an account whose email is not verified, and a mismatch here
    # is how that state arises.
    attrs = {a["Name"]: a["Value"] for a in idp.calls[0][1]["UserAttributes"]}
    assert attrs["email"] == NORMALIZED
    assert attrs["email_verified"] == "true"


def test_user_exists_checks_the_lowercase_username():
    """Otherwise the duplicate check misses: "Foo@x.com" reports no account and
    AdminCreateUser then fails on the lowercased username it collides with."""
    idp = RecordingIdp()
    assert CognitoAuthProvider(client=idp).user_exists(MIXED) is True
    assert idp.usernames() == [NORMALIZED]


def test_enable_disable_use_the_lowercase_username():
    """The username arrives from a stored portal record, which for a
    self-registered account could hold the mixed-case address the user typed."""
    idp = RecordingIdp()
    p = CognitoAuthProvider(client=idp)
    p.admin_set_enabled(MIXED, True)
    p.admin_set_enabled(MIXED, False)
    assert idp.usernames() == [NORMALIZED, NORMALIZED]
    assert [op for op, _ in idp.calls] == ["admin_enable_user", "admin_disable_user"]


# ------------------------------------------- the swallow stays, but is now logged

def test_forgot_password_still_swallows_unknown_user():
    """Must NOT raise — the route returns one generic message either way so the
    response cannot be used to enumerate accounts (BR-A6)."""
    idp = RecordingIdp(raises={"forgot_password": RecordingIdp.exceptions.UserNotFoundException()})
    CognitoAuthProvider(client=idp).forgot_password("ghost@x.com")   # no exception


def test_forgot_password_still_swallows_undeliverable_account():
    idp = RecordingIdp(
        raises={"forgot_password": RecordingIdp.exceptions.InvalidParameterException()})
    CognitoAuthProvider(client=idp).forgot_password("unverified@x.com")   # no exception


@pytest.mark.parametrize("exc_name", ["UserNotFoundException", "InvalidParameterException"])
def test_suppressed_send_is_logged_with_its_reason(caplog, exc_name):
    """The silence is what made the live bug expensive: with no log line there was
    no way to tell "no such account" from "account cannot receive mail" without
    probing the API from outside. The reason picks the remedy, so record it —
    server-side only, the caller still learns nothing."""
    exc = getattr(RecordingIdp.exceptions, exc_name)
    idp = RecordingIdp(raises={"forgot_password": exc()})
    with caplog.at_level(0):
        CognitoAuthProvider(client=idp).forgot_password("Someone@X.com")

    rec = next(r for r in caplog.records if "forgot-password code not sent" in r.getMessage())
    # The structured fields, not the message text — `extra_fields` is what the JSON
    # formatter emits and therefore what is greppable in CloudWatch.
    fields = rec.extra_fields
    assert fields["reason"] == exc_name       # which of the two, not just "something"
    # Logs the username actually sent to Cognito, so the log explains a casing
    # mismatch instead of echoing back what the user typed.
    assert fields["username"] == "someone@x.com"
    assert rec.levelno == 30


def test_unexpected_errors_are_not_swallowed():
    """Only the two anti-enumeration cases are suppressed. A throttle or outage
    must still surface rather than masquerading as a delivered code."""
    idp = RecordingIdp(
        raises={"forgot_password": RecordingIdp.exceptions.TooManyRequestsException()})
    with pytest.raises(RecordingIdp.exceptions.TooManyRequestsException):
        CognitoAuthProvider(client=idp).forgot_password("someone@x.com")


# ------------------------------------------- end-to-end against moto

def test_any_casing_can_log_in_and_reset(aws, ctx):
    """The reported scenario end to end: an account created from a mixed-case
    address is reachable by login and password reset typed in ANY casing."""
    ctx.user_service.create_user(
        {"email": "User+LoadtestUgl@Example.com", "firstName": "Load",
         "lastName": "Test", "role": "UserGroupLeader"},
        actor="admin", allowed_domains=[])

    for typed in ("user+loadtestugl@example.com",
                  "User+LoadtestUgl@Example.com",
                  "USER+LOADTESTUGL@EXAMPLE.COM"):
        # Reaches the real account: moto hands back the generated code, which only
        # exists because Cognito actually accepted the ForgotPassword call.
        ctx.auth_service.reset_password({"email": typed})
        code = aws.idp.forgot_password(
            ClientId=aws.client_id, Username="user+loadtestugl@example.com",
        )["ResponseMetadata"]["HTTPHeaders"]["x-moto-forgot-password-confirmation-code"]

        ctx.auth_service.confirm_reset_password(
            {"email": typed, "code": code, "newPassword": "BrandNew!123"})
        out = ctx.auth_service.login({"email": typed, "password": "BrandNew!123"})
        assert out.get("otpRequired") is False or "challengeId" in out


def test_duplicate_creation_is_caught_across_casings(aws, ctx):
    """Two spellings of one address must not become two accounts."""
    ctx.user_service.create_user(
        {"email": "dup@company.com", "firstName": "A", "lastName": "B"},
        actor="admin", allowed_domains=[])
    with pytest.raises(ValidationError):
        ctx.user_service.create_user(
            {"email": "DUP@Company.com", "firstName": "A", "lastName": "B"},
            actor="admin", allowed_domains=[])


def test_login_with_a_wrong_password_is_still_generic(aws, ctx):
    """Normalization must not change the anti-enumeration behaviour."""
    ctx.user_service.create_user(
        {"email": "real@company.com", "firstName": "A", "lastName": "B"},
        actor="admin", allowed_domains=[])
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.login({"email": "REAL@company.com", "password": "WrongPass!1"})
    with pytest.raises(UnauthorizedError):
        ctx.auth_service.login({"email": "NoSuchUser@company.com", "password": "WrongPass!1"})
