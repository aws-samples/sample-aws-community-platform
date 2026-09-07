"""Test fixtures for certifications.

Exercises the REAL service against moto DynamoDB **with all three GSIs** and
moto S3 (scanned bucket + SPA public bucket), plus a controllable fake for the
Identity read so tests can drive the fail-closed path.

The GSI definitions here are kept identical to
`infra/services/service-certifications-data.yaml`; if they ever diverge, tests
pass while production fails — the exact shape of the Settings file-share live
500 (test table had an index the deployed table did not).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from contextlib import contextmanager

import boto3
import pytest
from moto import mock_aws

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

TABLE_NAME = "certifications-test"
IDEM_TABLE_NAME = "certifications-idem-test"
BUCKET = "community-files-test"
SPA_BUCKET = "spa-bucket-test"

# Must mirror service-certifications-data.yaml exactly.
GSI_DEFS = [
    ("GSI1", "gsi1pk", "gsi1sk"),
    ("GSI2", "gsi2pk", "gsi2sk"),
    ("GSI3", "gsi3pk", "gsi3sk"),
    ("GSI4", "gsi4pk", "gsi4sk"),  # granted ledger (Certification Ledger enh.)
]


@pytest.fixture()
def aws():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        attrs = [{"AttributeName": "pk", "AttributeType": "S"},
                 {"AttributeName": "sk", "AttributeType": "S"}]
        indexes = []
        for name, hash_key, range_key in GSI_DEFS:
            attrs.append({"AttributeName": hash_key, "AttributeType": "S"})
            attrs.append({"AttributeName": range_key, "AttributeType": "S"})
            indexes.append({
                "IndexName": name,
                "KeySchema": [{"AttributeName": hash_key, "KeyType": "HASH"},
                              {"AttributeName": range_key, "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"},
            })
        table = ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=attrs,
            GlobalSecondaryIndexes=indexes,
            BillingMode="PAY_PER_REQUEST",
        )
        idem_table = ddb.create_table(
            TableName=IDEM_TABLE_NAME,
            KeySchema=[{"AttributeName": "eventId", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "eventId", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        s3.create_bucket(Bucket=SPA_BUCKET)
        # Mirror production: FileShareBucket is versioning-enabled (CKV_AWS_21).
        # This is not incidental test setup — on a versioned bucket a keyed delete
        # writes a delete marker instead of removing the object, so a quarantine
        # test against an UNVERSIONED bucket would pass while the real bucket
        # retained the infected bytes. The SPA bucket is left unversioned, which
        # also mirrors production.
        s3.put_bucket_versioning(
            Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})

        os.environ["TABLE_NAME"] = TABLE_NAME
        os.environ["IDEMPOTENCY_TABLE"] = IDEM_TABLE_NAME
        os.environ["FILE_SHARE_BUCKET"] = BUCKET
        os.environ["SPA_BUCKET"] = SPA_BUCKET

        class NS:
            pass

        ns = NS()
        ns.table = table
        ns.idem_table = idem_table
        ns.s3 = s3
        ns.bucket = BUCKET
        ns.spa_bucket = SPA_BUCKET
        yield ns


class FakePrincipal:
    """Mirrors _conventions.authz.Principal plus the `name` attribute the
    router attaches from claims."""

    def __init__(self, user_id, role, led_group_id=None, member_group_ids=None,
                 name=""):
        self.user_id = user_id
        self.role = role
        self.account_type = "cognito"
        self.led_group_id = led_group_id
        self.member_group_ids = member_group_ids or []
        self.name = name


@pytest.fixture()
def cl():
    return FakePrincipal("u-cl", "CommunityLeader", name="Dana CL")


@pytest.fixture()
def ugl():
    return FakePrincipal("u-ugl", "UserGroupLeader", led_group_id="g-serverless",
                         name="Priya UGL")


@pytest.fixture()
def member():
    return FakePrincipal("u-mem-1", "Member",
                         member_group_ids=["g-serverless", "g-ml"], name="Alex Morgan")


@pytest.fixture()
def other_member():
    return FakePrincipal("u-mem-2", "Member", member_group_ids=["g-serverless"],
                         name="Jordan Lee")


@pytest.fixture()
def admin():
    return FakePrincipal("u-admin", "Administrator")


class FakeIdentity:
    """Controllable Identity read. `unreachable=True` reproduces an Identity
    outage — the FAIL-CLOSED path (submission must 503, BR-C3)."""

    def __init__(self, groups=None, led=None, unreachable=False):
        self.groups = {"u-mem-1": ["g-serverless", "g-ml"],
                       "u-mem-2": ["g-serverless"]} if groups is None else groups
        self.led = led or {"u-ugl": "g-serverless"}
        self.unreachable = unreachable
        self.calls = 0

    def member_group_ids(self, *, bearer_token=None):
        self.calls += 1
        if self.unreachable:
            return None
        # bearer token identifies the caller in these tests: "tok:<userId>"
        user = (bearer_token or "").removeprefix("tok:")
        return self.groups.get(user, [])

    def led_group_id(self, user_id, *, bearer_token=None):
        self.calls += 1
        if self.unreachable:
            return None
        return self.led.get(user_id)


class FakeMetrics:
    def __init__(self):
        self.emitted = []

    def emit(self, name, value, unit="Count"):
        self.emitted.append((name, value))

    def of(self, name):
        return [v for n, v in self.emitted if n == name]


@pytest.fixture()
def ctx(aws):
    """Real Context on moto AWS with a controllable Identity fake and a real
    EventPublisher with no bus (publications captured in .published)."""
    import app as app_module
    from providers import EventPublisher, S3Broker

    identity = FakeIdentity()
    metrics = FakeMetrics()
    context = app_module.Context(
        table=aws.table,
        idempotency_table=IDEM_TABLE_NAME,
        storage=S3Broker(client=aws.s3, bucket=BUCKET, spa_bucket=SPA_BUCKET),
        events=EventPublisher(bus="", metrics=metrics),
        identity=identity,
        metrics=metrics,
    )
    context.fake_identity = identity
    context.fake_metrics = metrics
    return context


# ------------------------------------------------------------- HTTP helpers

def api_event(method, path, *, principal=None, body=None, qs=None):
    """Build an API GW proxy event carrying the given principal as Cognito
    authorizer claims (the shape token_claims_handler stamps)."""
    claims = {}
    if principal is not None:
        claims = {
            "sub": principal.user_id,
            "role": principal.role,
            "led_group_id": principal.led_group_id or "",
            "member_group_ids": ",".join(principal.member_group_ids),
            "given_name": (principal.name.split(" ")[0] if principal.name else ""),
            "family_name": (principal.name.split(" ")[-1] if principal.name
                            and " " in principal.name else ""),
        }
    return {
        "httpMethod": method,
        "path": path,
        "headers": {"Authorization": f"Bearer tok:{principal.user_id}"} if principal else {},
        "queryStringParameters": qs,
        "requestContext": {"authorizer": {"claims": claims}} if claims else {},
        "body": json.dumps(body) if body is not None else None,
    }


def call(ctx_obj, method, path, *, principal=None, body=None, qs=None):
    import app as app_module
    resp = app_module.dispatch(api_event(method, path, principal=principal,
                                         body=body, qs=qs), ctx_obj)
    parsed = json.loads(resp["body"]) if resp.get("body") else None
    return resp["statusCode"], parsed


# --------------------------------------------------------------- data helpers

def make_definition(ctx_obj, cl_principal, **overrides):
    body = {"name": "AWS Solutions Architect Pro", "description": "Pro-level cert",
            "category": "AWS Certification", "points": 25, "expiryPeriodMonths": 36}
    body.update(overrides)
    return ctx_obj.definitions.create(body, principal=cl_principal)


def upload_evidence(ctx_obj, member_principal, aws_ns, file_name="cert.pdf"):
    """Grant + actually PUT the object (HeadObject at submission requires it)."""
    grant = ctx_obj.claims.grant_evidence_upload({"fileName": file_name},
                                                 principal=member_principal)
    aws_ns.s3.put_object(Bucket=aws_ns.bucket, Key=grant["fileKey"], Body=b"%PDF-1.4 test")
    return grant["fileKey"]


def submit_claim(ctx_obj, member_principal, cert_id, *, group="g-serverless", **overrides):
    body = {"certId": cert_id, "creditedGroupId": group,
            "evidenceUrl": "https://credly.com/badges/x", "dateEarned": "2026-06-01"}
    body.update(overrides)
    return ctx_obj.claims.submit(body, principal=member_principal,
                                 bearer_token=f"tok:{member_principal.user_id}")


@contextmanager
def raises_message(exc_type, snippet):
    """pytest.raises(match=...) matches str(exc), but the dataclass-based
    AppErrors carry their text in .message/.details with empty Exception args —
    so match= silently compares against ''. This helper asserts on the real
    fields instead."""
    import pytest
    with pytest.raises(exc_type) as excinfo:
        yield
    err = excinfo.value
    text = getattr(err, "message", "") + " " + json.dumps(getattr(err, "details", None) or [])
    assert snippet.lower() in text.lower(), f"{snippet!r} not in {text!r}"
