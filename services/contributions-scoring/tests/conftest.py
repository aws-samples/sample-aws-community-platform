"""Test fixtures for Contributions & Scoring (Unit 7).

Exercises the REAL service against moto DynamoDB with the main table + 3 GSIs
(kept identical to service-contributions-scoring-data.yaml) and the idempotency
table. GSI1 (leaderboard) sort key is the `total` NUMBER attribute, so an ADD
re-sorts the index automatically.
"""
from __future__ import annotations

import os
import pathlib
import sys

import boto3
import pytest
from moto import mock_aws

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

TABLE_NAME = "contributions-scoring-test"
IDEM_TABLE_NAME = "contributions-scoring-idem-test"


@pytest.fixture()
def aws():
    with mock_aws():
        yield


@pytest.fixture()
def table(aws):
    ddb = boto3.resource("dynamodb")
    t = ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                   {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "gsi1pk", "AttributeType": "S"},
            {"AttributeName": "total", "AttributeType": "N"},
            {"AttributeName": "gsi2pk", "AttributeType": "S"},
            {"AttributeName": "gsi2sk", "AttributeType": "S"},
            {"AttributeName": "gsi3pk", "AttributeType": "S"},
            {"AttributeName": "gsi3sk", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {"IndexName": "GSI1",
             "KeySchema": [{"AttributeName": "gsi1pk", "KeyType": "HASH"},
                           {"AttributeName": "total", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "GSI2",
             "KeySchema": [{"AttributeName": "gsi2pk", "KeyType": "HASH"},
                           {"AttributeName": "gsi2sk", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
            {"IndexName": "GSI3",
             "KeySchema": [{"AttributeName": "gsi3pk", "KeyType": "HASH"},
                           {"AttributeName": "gsi3sk", "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}},
        ],
        BillingMode="PAY_PER_REQUEST")
    return t


@pytest.fixture()
def repo(table):
    from repository import ContributionsRepository
    return ContributionsRepository(table)


@pytest.fixture()
def framework(repo):
    """Seeded default framework (DL16 subset needed by tests)."""
    from framework_service import FrameworkService
    repo.put_framework_item("ACT#organize-event", {
        "activityId": "organize-event", "name": "Organize an event", "pillar": 1,
        "points": 20, "evidenceRequired": False, "active": True, "systemDefined": True})
    repo.put_framework_item("ACT#forum-post", {
        "activityId": "forum-post", "name": "Create a forum post", "pillar": 2,
        "points": 1, "evidenceRequired": False, "active": True, "systemDefined": True})
    repo.put_framework_item("ACT#forum-accepted-reply", {
        "activityId": "forum-accepted-reply", "name": "Accepted reply", "pillar": 2,
        "points": 2, "evidenceRequired": False, "active": True, "systemDefined": True})
    repo.put_framework_item("ACT#blog", {
        "activityId": "blog", "name": "Blog / article", "pillar": 4, "points": 15,
        "evidenceRequired": True, "active": True, "systemDefined": False})
    for et, a, d in [("Workshop", 10, 20), ("Meetup", 5, 10)]:
        repo.put_framework_item(f"EVTP#{et}", {"eventType": et, "attendancePoints": a,
                                               "deliveryPoints": d})
    for tier, m in [("Gold", 75), ("Silver", 50), ("Bronze", 25), ("Rising", 0)]:
        repo.put_framework_item(f"TIER#{tier}", {"tier": tier, "minPoints": m,
                                                 "recognitionLabel": tier})
    return FrameworkService(repo)


class P:
    """Test principal."""
    def __init__(self, role, user_id="u1", led=None, groups=None, name="Test User"):
        self.role = role
        self.user_id = user_id
        self.led_group_id = led
        self.member_group_ids = groups or []
        self.name = name


@pytest.fixture()
def member():
    return P("Member", user_id="m-alex", groups=["g-serverless", "g-ml"], name="Alex Morgan")


@pytest.fixture()
def cl():
    return P("CommunityLeader", user_id="cl-dana", name="Dana Cross")


@pytest.fixture()
def ugl():
    return P("UserGroupLeader", user_id="ugl-priya", led="g-serverless", name="Priya Nair")
