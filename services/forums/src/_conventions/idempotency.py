"""Consumer idempotency on the event `id` (P-IDEMPOTENCY, Correctness Property 6).

Reference convention — copied per service by the scaffold generator (FQ1).
Backed by a per-service DynamoDB idempotency table (PK=eventId) with TTL.
Uses a conditional put: first writer proceeds, duplicates are skipped.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import boto3
from botocore.exceptions import ClientError

_DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7-day expiry (BR)


class IdempotencyStore:
    def __init__(self, table_name: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS, client=None):
        self._table = table_name
        self._ttl = ttl_seconds
        self._ddb = client or boto3.client("dynamodb")

    def _seen(self, event_id: str) -> bool:
        """Record event_id; return True if it was already processed (skip)."""
        try:
            self._ddb.put_item(
                TableName=self._table,
                Item={"eventId": {"S": event_id}, "ttl": {"N": str(int(time.time()) + self._ttl)}},
                ConditionExpression="attribute_not_exists(eventId)",
            )
            return False
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return True
            raise

    def run_once(self, event_id: str, action: Callable[[], None]) -> bool:
        """Execute `action` only if event_id has not been processed. Returns True if executed."""
        if self._seen(event_id):
            return False
        action()
        return True
