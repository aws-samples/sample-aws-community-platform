"""Install-time seeder (custom resource, D7).

Runs on every deploy (a DeployNonce param forces the custom resource to fire
each time), but its Cognito side effects are only applied ONCE, at first
creation. Responsibilities:
  1. Create the bootstrap Administrator in the Cognito user pool with a
     locally generated random password, set as PERMANENT immediately (same
     mechanism as self-registration's `self_sign_up`, AdminCreateUser +
     AdminSetUserPassword). This lands the account in CONFIRMED, matching the
     status of every other user, rather than Cognito's own auto-generated
     temporary password which leaves the account in FORCE_CHANGE_PASSWORD
     until someone completes a NEW_PASSWORD_REQUIRED challenge the app does
     not implement.

     The password is DISCARDED — never logged, never returned, never
     persisted. The operator gets in via "Forgot password" (US-1.20/1.27),
     which works precisely because the account is CONFIRMED with
     email_verified=true; Cognito rejects ForgotPassword on a
     FORCE_CHANGE_PASSWORD user. This makes the bootstrap Administrator
     follow the same path as every admin-created and bulk-imported user
     (US-1.31), whose system-generated password is likewise never disclosed.

     There is deliberately no stored copy. It previously lived in Secrets
     Manager for operator retrieval, which went stale the first time anyone
     used the reset link (a scripted login probe returned 401 against the
     recorded value) — a long-lived admin password that no longer worked.
     Break-glass, if the reset email never arrives, is
     `aws cognito-idp admin-set-user-password --permanent`, available to
     anyone who can deploy this stack.

     On every re-run after the account already exists, the password is left
     untouched — see `_ensure_admin`.
  2. Write the bootstrap Administrator's portal record directly into the
     Identity & Access table with role=Administrator, mirroring how bulk
     import (US-1.31) creates portal records at creation time — this avoids
     relying on JIT provisioning (US-1.15), which always defaults new users
     to Member and would otherwise mis-provision the bootstrap account.
  3. Baseline reference data (scoring framework, email templates, certification
     catalog) — while every other service is `mock`, mocks serve bundled
     fixtures, so this is a logged no-op with a clear extension point for when
     services move mock -> real and expose seedable tables via this stack's
     parameters.

The handler always signals CloudFormation (success/failure) via cfn.send so the
stack never hangs; Delete is best-effort and never blocks stack teardown.
"""
from __future__ import annotations

import os
import secrets as _secrets
from datetime import datetime, timezone

import boto3
import cfn
from botocore.exceptions import ClientError

PHYSICAL_ID = "community-portal-seed"
ROLE_ADMIN = "Administrator"
STATUS_ACTIVE = "Active"

# Character pools for the throwaway bootstrap password. Deliberately the SAME
# sets as identity-access's generate_temp_password (providers.py) so both
# account-creation paths produce passwords of identical shape: ambiguous glyphs
# (I/l/1, O/0) excluded, and symbols restricted to "!@#$%^&*". That symbol set
# matters — a generated password once contained '<', which the request-body XSS
# input guard rejected with a 400 on login (see identity-access
# test_auth_service.py). Not reachable now that the value is never submitted
# through the API, but there is no reason to reintroduce the hazard.
_CHARSET_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # noqa: S105 — char pool, not a secret
_CHARSET_LOWER = "abcdefghijkmnopqrstuvwxyz"  # noqa: S105 — char pool, not a secret
_CHARSET_DIGITS = "23456789"  # noqa: S105 — char pool, not a secret
_CHARSET_SYMBOLS = "!@#$%^&*"  # noqa: S105 — char pool, not a secret

# Default scoring framework (Unit 7 DL16). Embedded here (not read from the
# service dir) so it is bundled with this Lambda. Kept in sync with
# services/contributions-scoring/seed_framework.json. Activities all Active;
# event points delivery = 2x attendance; tiers 75/50/25/0. Auto-award works
# day one before any Community Leader edit.
_FRAMEWORK_ACTIVITIES = [
    ("certification-approval", "Certification approval", 1, 0, False, True),
    ("organize-event", "Organize an event", 1, 20, False, True),
    ("mentor-member", "Mentor a member", 1, 15, True, False),
    ("forum-post", "Create a forum post", 2, 1, False, True),
    ("forum-accepted-reply", "Accepted reply", 2, 2, False, True),
    ("lessons-learned", "Lessons-learned writeup", 2, 10, True, False),
    ("open-source", "Open-source contribution", 3, 15, True, False),
    ("reusable-asset", "Reusable asset / demo", 3, 12, True, False),
    ("blog", "Blog / article", 4, 15, True, False),
    ("public-speaking", "Public speaking", 4, 20, True, False),
]
_FRAMEWORK_EVENT_POINTS = [
    ("Social", 3, 6), ("Meetup", 5, 10), ("Webinar", 8, 16), ("AMA", 8, 16),
    ("Presentation", 10, 20), ("Workshop", 10, 20), ("Conference", 15, 30),
    ("Hackathon", 25, 50),
]
_FRAMEWORK_TIERS = [
    ("Gold", 75, "Community Star"), ("Silver", 50, "Active Contributor"),
    ("Bronze", 25, "Engaged Member"), ("Rising", 0, "Rising Participant"),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()  # noqa: UP017 — local test runner is py3.10


def _generate_password(length: int = 20) -> str:
    """Generate a random password satisfying the pool's policy (MinimumLength 8,
    upper + lower + digits + symbols all required — foundation.yaml). Mirrors
    identity-access's generate_temp_password: a throwaway credential immediately
    superseded by the operator's own via the forgot-password flow, never
    surfaced to any caller and never stored."""
    pools = [_CHARSET_UPPER, _CHARSET_LOWER, _CHARSET_DIGITS, _CHARSET_SYMBOLS]
    # One char from each required class first, or the password can fail the
    # policy by chance and AdminSetUserPassword rejects it mid-deploy.
    chars = [_secrets.choice(p) for p in pools]
    all_chars = "".join(pools)
    chars += [_secrets.choice(all_chars) for _ in range(length - len(chars))]
    _secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _ensure_admin(user_pool_id: str, email: str) -> str:
    """Create the bootstrap admin with a PERMANENT password (no Cognito invite
    email, no temporary password) — same CONFIRMED outcome as self-registration,
    which is what keeps "Forgot password" usable: Cognito refuses
    ForgotPassword for a FORCE_CHANGE_PASSWORD user.

    The password is generated here and thrown away. Nothing reads it back, so
    there is no copy to go stale, and no caller can accidentally log it.

    Idempotent across stack updates: the password is set ONLY at first
    creation. On every later re-run (this Lambda fires on every deploy via
    DeployNonce), the account already exists and its password is left alone —
    otherwise a redeploy would silently overwrite any password the operator
    has since changed (e.g. via "Forgot password"), which is what happened
    before this fix. Returns the Cognito `sub`."""
    idp = boto3.client("cognito-idp")
    try:
        resp = idp.admin_create_user(
            UserPoolId=user_pool_id,
            Username=email,
            MessageAction="SUPPRESS",
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
            ],
        )
        attrs = {a["Name"]: a["Value"] for a in resp.get("User", {}).get("Attributes", [])}
        sub = attrs.get("sub", email)
        # Newly created — set the initial permanent password (first deploy only).
        # Generated inline and immediately out of scope: the operator is expected
        # to arrive via "Forgot password", not with this value.
        idp.admin_set_user_password(
            UserPoolId=user_pool_id, Username=email,
            Password=_generate_password(), Permanent=True,
        )
    except idp.exceptions.UsernameExistsException:
        details = idp.admin_get_user(UserPoolId=user_pool_id, Username=email)
        attrs = {a["Name"]: a["Value"] for a in details.get("UserAttributes", [])}
        sub = attrs.get("sub", email)  # idempotent on stack UPDATE / re-run
        # Account already exists: never touch the password here. The operator
        # may have changed it since (e.g. via "Forgot password") — re-running
        # the seeder on every deploy must not reset it back to the original
        # generated secret value.
    return sub


def _write_portal_record(table_name: str, user_id: str, email: str) -> None:
    """Write the Administrator's portal record directly (mirrors US-1.31 bulk
    import), so the account is role=Administrator from first login — no JIT
    dependency, no risk of defaulting to Member."""
    if not table_name:
        print("IDENTITY_ACCESS_TABLE not set; skipping portal record seed")
        return
    ddb = boto3.client("dynamodb")
    now = _now_iso()
    existing = ddb.get_item(
        TableName=table_name, Key={"pk": {"S": f"USER#{user_id}"}, "sk": {"S": "PROFILE"}},
    )
    if "Item" in existing:
        return  # idempotent — already seeded on a prior deploy
    ddb.put_item(
        TableName=table_name,
        Item={
            "pk": {"S": f"USER#{user_id}"},
            "sk": {"S": "PROFILE"},
            "id": {"S": user_id},
            "email": {"S": email},
            "firstName": {"S": ""},
            "lastName": {"S": ""},
            "role": {"S": ROLE_ADMIN},
            "status": {"S": STATUS_ACTIVE},
            "accountType": {"S": "cognito"},
            "createdAt": {"S": now},
            "updatedAt": {"S": now},
            "gsi1pk": {"S": f"EMAIL#{email.lower()}"},
            "gsi1sk": {"S": "USER"},
            "gsi2pk": {"S": f"ROLE#{ROLE_ADMIN}"},
            "gsi2sk": {"S": f"USER#{user_id}"},
        },
    )


def _seed_contributions_framework(table_name: str) -> None:
    """Seed the default scoring framework into the contributions-scoring table
    (Unit 7 DL16). Each row is an idempotent conditional put — a re-run (the
    seeder fires on every deploy) never overwrites a framework a Community
    Leader has since edited."""
    if not table_name:
        print("CONTRIBUTIONS_TABLE not set; skipping scoring framework seed")
        return
    ddb = boto3.client("dynamodb")
    rows: list[dict] = []
    for activity_id, name, pillar, points, evidence_required, system_defined in _FRAMEWORK_ACTIVITIES:
        rows.append({
            "pk": {"S": "FRAMEWORK"}, "sk": {"S": f"ACT#{activity_id}"},
            "activityId": {"S": activity_id}, "name": {"S": name},
            "pillar": {"N": str(pillar)}, "points": {"N": str(points)},
            "evidenceRequired": {"BOOL": evidence_required},
            "active": {"BOOL": True}, "systemDefined": {"BOOL": system_defined},
        })
    for event_type, attendance, delivery in _FRAMEWORK_EVENT_POINTS:
        rows.append({
            "pk": {"S": "FRAMEWORK"}, "sk": {"S": f"EVTP#{event_type}"},
            "eventType": {"S": event_type},
            "attendancePoints": {"N": str(attendance)}, "deliveryPoints": {"N": str(delivery)},
        })
    for tier, min_points, label in _FRAMEWORK_TIERS:
        rows.append({
            "pk": {"S": "FRAMEWORK"}, "sk": {"S": f"TIER#{tier}"},
            "tier": {"S": tier}, "minPoints": {"N": str(min_points)},
            "recognitionLabel": {"S": label},
        })
    seeded = 0
    for item in rows:
        try:
            ddb.put_item(TableName=table_name, Item=item,
                         ConditionExpression="attribute_not_exists(pk)")
            seeded += 1
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise  # real error; surface it
            # already present (prior deploy / CL edit) — leave untouched
    print(f"scoring framework seed: {seeded} new rows ({len(rows)} total defaults)")


def _delete_admin(user_pool_id: str, email: str) -> None:
    idp = boto3.client("cognito-idp")
    try:
        idp.admin_delete_user(UserPoolId=user_pool_id, Username=email)
    except ClientError as exc:  # best-effort; never block teardown
        print(f"admin_delete_user ignored: {exc}")


def handler(event, context):
    request_type = event.get("RequestType", "Create")
    email = os.environ["ADMIN_EMAIL"]
    user_pool_id = os.environ.get("USER_POOL_ID", "")
    table_name = os.environ.get("IDENTITY_ACCESS_TABLE", "")
    contributions_table = os.environ.get("CONTRIBUTIONS_TABLE", "")

    try:
        if request_type == "Delete":
            if user_pool_id:
                _delete_admin(user_pool_id, email)
            return cfn.send(event, context, cfn.SUCCESS, physical_id=PHYSICAL_ID)

        if user_pool_id:
            sub = _ensure_admin(user_pool_id, email)
            _write_portal_record(table_name, sub, email)
        else:
            print("USER_POOL_ID not set; skipping admin creation")

        # Baseline reference data for real services (mock services serve bundled
        # fixtures and need none). Unit 7 Contributions & Scoring: default
        # scoring framework so auto-award works day one (DL16).
        _seed_contributions_framework(contributions_table)

        return cfn.send(
            event, context, cfn.SUCCESS,
            data={"AdminEmail": email},
            physical_id=PHYSICAL_ID,
        )
    except Exception as exc:  # noqa: BLE001 — must report failure to CloudFormation
        print(f"seed failed: {exc}")
        return cfn.send(event, context, cfn.FAILED, physical_id=PHYSICAL_ID, reason=str(exc))
