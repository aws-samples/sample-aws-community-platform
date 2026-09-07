"""Bootstrap Administrator seeding tests (US-1.27).

Guards two things that a redeploy can silently break:

  1. The seed custom resource re-runs on every `./infra/deploy.sh` (via
     DeployNonce), but must only set the Cognito password at first creation. A
     prior bug reset it back to the originally generated value on every
     redeploy, discarding any password the operator had since chosen via
     "Forgot password".

  2. The account must land CONFIRMED, not FORCE_CHANGE_PASSWORD. This is now
     load-bearing rather than cosmetic: the generated password is discarded, so
     "Forgot password" is the ONLY way in — and Cognito refuses ForgotPassword
     for a FORCE_CHANGE_PASSWORD user. Anything that reintroduces a temporary
     password (e.g. dropping the AdminSetUserPassword call, or passing
     TemporaryPassword to AdminCreateUser) locks the operator out of a fresh
     stack with no recovery path short of the AWS CLI.
"""
from __future__ import annotations

import os
import pathlib
import sys

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

SRC = str(pathlib.Path(__file__).resolve().parents[1])
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import seed_handler  # noqa: E402


@pytest.fixture()
def pool():
    with mock_aws():
        idp = boto3.client("cognito-idp", region_name="us-east-1")
        created = idp.create_user_pool(PoolName="test-pool")
        yield idp, created["UserPool"]["Id"]


def test_first_run_creates_confirmed_user_so_forgot_password_works(pool):
    """CONFIRMED is the whole point — see this module's docstring. In
    FORCE_CHANGE_PASSWORD the operator could neither sign in (no
    NEW_PASSWORD_REQUIRED handling in the SPA) nor reset (Cognito rejects
    ForgotPassword in that state), and no stored copy of the password exists."""
    idp, pool_id = pool
    sub = seed_handler._ensure_admin(pool_id, "admin@company.com")
    assert sub

    details = idp.admin_get_user(UserPoolId=pool_id, Username="admin@company.com")
    assert details["UserStatus"] == "CONFIRMED"
    # email_verified must be asserted by the seeder: ForgotPassword needs a
    # verified delivery address or it fails with InvalidParameterException.
    attrs = {a["Name"]: a["Value"] for a in details["UserAttributes"]}
    assert attrs.get("email_verified") == "true"


def test_ensure_admin_does_not_return_or_expose_the_password(pool):
    """The password is generated and discarded. _ensure_admin returns only the
    Cognito sub — if it ever starts handing the password back, a caller can log
    it or (as before) persist it somewhere that goes stale."""
    idp, pool_id = pool
    result = seed_handler._ensure_admin(pool_id, "admin@company.com")
    assert isinstance(result, str)

    details = idp.admin_get_user(UserPoolId=pool_id, Username="admin@company.com")
    attrs = {a["Name"]: a["Value"] for a in details["UserAttributes"]}
    assert result == attrs.get("sub", "admin@company.com")


def test_generated_password_satisfies_the_pool_policy():
    """foundation.yaml requires upper + lower + digits + symbols. A password
    failing the policy would surface as a mid-deploy InvalidPasswordException
    from AdminSetUserPassword, so guarantee each class rather than trusting
    a random draw. Repeated because the failure would be intermittent."""
    for _ in range(200):
        pw = seed_handler._generate_password()
        assert len(pw) == 20
        assert any(c in seed_handler._CHARSET_UPPER for c in pw)
        assert any(c in seed_handler._CHARSET_LOWER for c in pw)
        assert any(c in seed_handler._CHARSET_DIGITS for c in pw)
        assert any(c in seed_handler._CHARSET_SYMBOLS for c in pw)


def test_generated_passwords_are_unique():
    """Distinct per invocation — a fixed value would be a shared credential
    across every stack this template ever deploys."""
    assert len({seed_handler._generate_password() for _ in range(50)}) == 50


def test_rerun_does_not_reset_an_already_changed_password(pool):
    """Simulates: deploy #1 creates the admin with the generated password;
    the operator then changes it (e.g. via Forgot password); deploy #2 (the
    seed Lambda re-running due to DeployNonce) must NOT touch the password."""
    idp, pool_id = pool
    seed_handler._ensure_admin(pool_id, "admin@company.com")

    # Operator changes the password out-of-band (simulating "Forgot password").
    operator_password = "OperatorChosenPass!456"  # noqa: S105 — test fixture value, not a real secret
    idp.admin_set_user_password(
        UserPoolId=pool_id, Username="admin@company.com",
        Password=operator_password, Permanent=True,
    )

    # Second seeder run (redeploy) — must be a no-op on the password.
    sub2 = seed_handler._ensure_admin(pool_id, "admin@company.com")
    assert sub2

    # The operator's password must still authenticate; the seeder must not
    # have generated a fresh one and overwritten it.
    resp = idp.admin_initiate_auth(
        UserPoolId=pool_id,
        ClientId=_client_id(idp, pool_id),
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": "admin@company.com", "PASSWORD": operator_password},
    )
    assert "AuthenticationResult" in resp


def _client_id(idp, pool_id: str) -> str:
    client = idp.create_user_pool_client(
        UserPoolId=pool_id, ClientName="test-client",
        ExplicitAuthFlows=["ALLOW_ADMIN_USER_PASSWORD_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"],
    )
    return client["UserPoolClient"]["ClientId"]


# --- Scoring-framework seed (Unit 7 DL16) ------------------------------------

def _make_contributions_table(name: str = "contributions-scoring-test"):
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=name,
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return ddb, name


def test_framework_seed_writes_all_default_rows():
    with mock_aws():
        ddb, name = _make_contributions_table()
        seed_handler._seed_contributions_framework(name)

        items = ddb.scan(TableName=name)["Items"]
        expected = (
            len(seed_handler._FRAMEWORK_ACTIVITIES)
            + len(seed_handler._FRAMEWORK_EVENT_POINTS)
            + len(seed_handler._FRAMEWORK_TIERS)
        )
        assert len(items) == expected
        # Spot-check one activity row (accepted reply = 2 points, DL: forum).
        reply = ddb.get_item(
            TableName=name,
            Key={"pk": {"S": "FRAMEWORK"}, "sk": {"S": "ACT#forum-accepted-reply"}},
        )["Item"]
        assert reply["points"]["N"] == "2"


def test_framework_seed_is_idempotent_and_preserves_edits():
    """A redeploy re-runs the seeder; existing rows (e.g. a Community-Leader
    edit) must never be overwritten (conditional put on attribute_not_exists)."""
    with mock_aws():
        ddb, name = _make_contributions_table()
        # Simulate a CL having edited the accepted-reply points to 5.
        ddb.put_item(
            TableName=name,
            Item={
                "pk": {"S": "FRAMEWORK"}, "sk": {"S": "ACT#forum-accepted-reply"},
                "activityId": {"S": "forum-accepted-reply"}, "name": {"S": "Accepted reply"},
                "pillar": {"N": "2"}, "points": {"N": "5"},
                "evidenceRequired": {"BOOL": False}, "active": {"BOOL": True},
                "systemDefined": {"BOOL": True},
            },
        )

        seed_handler._seed_contributions_framework(name)  # redeploy
        seed_handler._seed_contributions_framework(name)  # again — still no-op

        reply = ddb.get_item(
            TableName=name,
            Key={"pk": {"S": "FRAMEWORK"}, "sk": {"S": "ACT#forum-accepted-reply"}},
        )["Item"]
        assert reply["points"]["N"] == "5"  # CL edit preserved, not reset to 2


def test_framework_seed_noop_when_table_unset(capsys):
    seed_handler._seed_contributions_framework("")
    assert "skipping scoring framework seed" in capsys.readouterr().out
