"""Test fixtures for settings."""
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

TABLE_NAME = "settings-test"
BUCKET_NAME = "settings-fileshare-test"


@pytest.fixture()
def aws():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
                {"AttributeName": "gsi1pk", "AttributeType": "S"},
                {"AttributeName": "gsi1sk", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {"IndexName": "GSI1",
                 "KeySchema": [{"AttributeName": "gsi1pk", "KeyType": "HASH"},
                               {"AttributeName": "gsi1sk", "KeyType": "RANGE"}],
                 "Projection": {"ProjectionType": "ALL"}},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET_NAME)

        os.environ["TABLE_NAME"] = TABLE_NAME
        os.environ["FILE_SHARE_BUCKET"] = BUCKET_NAME

        class NS:
            pass

        ns = NS()
        ns.table = table
        ns.s3 = s3
        yield ns


@pytest.fixture()
def ctx(aws):
    from app import Context

    class FakeEvents:
        def __init__(self):
            self.published = []

        def publish(self, event_type, data, correlation_id=None):
            self.published.append({"type": event_type, "data": data})

    return Context(table=aws.table, events=FakeEvents())


@pytest.fixture()
def repo(ctx):
    return ctx.repo
