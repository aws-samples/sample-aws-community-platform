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
        """Execute `action` only if event_id has not been processed. Returns True if executed.

        RELEASE-ON-FAILURE (live defect, 2026-08-06, certifications copy): the
        record is claimed BEFORE the action, so if the action raises, the
        source's redelivery/retry would hit "duplicate" and the event would be
        lost FOREVER — exactly how a badge got permanently stuck in PendingScan
        when its public-bucket copy was denied. On failure the claim is
        deleted (best-effort) and the exception re-raised, so EventBridge's
        Lambda retry genuinely retries. The claim-first order is kept: the
        failure direction for a crash BETWEEN delete and re-raise is a lost
        event (alarmed via Lambda Errors), never a double-processed one.
        """
        if self._seen(event_id):
            return False
        try:
            action()
        except Exception:
            try:
                self._ddb.delete_item(TableName=self._table,
                                      Key={"eventId": {"S": event_id}})
            except ClientError:
                pass  # best-effort; the re-raise below is what matters
            raise
        return True
