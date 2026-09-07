"""DynamoDB stream processor — indexes USER#*/PROFILE items into the shared
OpenSearch 'members' index (merged with member-profiles data).

identity-access writes PARTIAL updates (identity fields only) using
doc_as_upsert so member-profiles fields (bio, skills, groupIds) are never
overwritten. member-profiles owns the full document; identity-access only
updates the fields it owns.

Triggered by the identity-access DynamoDB stream on every write. Only USER#.../PROFILE
items are processed; all other item types are ignored.

Architecture notes:
  - Runs as a separate Lambda (UserIndexerFn) isolated from the API Lambda.
  - BatchSize=100, MaximumRetryAttempts=10, BisectBatchOnFunctionError=true.
  - Failed batches after 10 retries go to IndexerDLQ (alarm fires ops).
  - IndexerLagAlarm fires if the stream falls >5 min behind.
  - Nightly reindex (scheduled-reindex) provides the full consistency safety net.
"""
from __future__ import annotations

import json
import os
from decimal import Decimal

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from _conventions.logger import get_logger

_logger = get_logger("identity-access.indexer")

# Shared index — owned by member-profiles, partially updated by identity-access.
OPENSEARCH_INDEX = "members"

# Identity fields that identity-access owns in the merged index.
# member-profiles fields (bio, skills, groupIds, etc.) are NOT in this set —
# they must never be overwritten by this indexer.
_IDENTITY_FIELDS = frozenset({
    "id", "firstName", "lastName", "email",
    "role", "status", "roleSortOrder",
    "city", "country", "professionalRole", "awsProject", "timeZone",
})

# Role sort order for deterministic column sort in the admin table.
# Lower number = higher position when sorted ascending (Admin first).
_ROLE_SORT_ORDER: dict[str, int] = {
    "Administrator": 0,
    "CommunityLeader": 1,
    "UserGroupLeader": 2,
    "Member": 3,
}

# Module-level singleton — survives warm container reuse.
_os_client: OpenSearch | None = None


def _get_client() -> OpenSearch:
    global _os_client  # noqa: PLW0603 — intentional warm-container singleton
    if _os_client is None:
        endpoint = os.environ["OPENSEARCH_ENDPOINT"]
        region = os.environ.get("AWS_REGION", "us-east-1")
        creds = boto3.Session().get_credentials().get_frozen_credentials()
        auth = AWS4Auth(
            creds.access_key,
            creds.secret_key,
            region,
            "aoss",              # OpenSearch Serverless service name for SigV4
            session_token=creds.token,
        )
        # Strip leading https:// if present in the endpoint env var.
        host = endpoint.replace("https://", "").rstrip("/")
        _os_client = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=60,   # OpenSearch Serverless cold-start can take 10-30s
        )
    return _os_client


def handler(event: dict, context) -> None:  # noqa: ANN001
    """Process a batch of DynamoDB stream records."""
    client = _get_client()
    indexed = deleted = skipped = 0

    for record in event.get("Records", []):
        dynamodb = record.get("dynamodb", {})
        keys = dynamodb.get("Keys", {})
        pk = keys.get("pk", {}).get("S", "")
        sk = keys.get("sk", {}).get("S", "")

        # Only index user profile items — ignore groups, events, OTP records, etc.
        if not pk.startswith("USER#") or sk != "PROFILE":
            skipped += 1
            continue

        user_id = pk[len("USER#"):]
        event_name = record.get("eventName", "")

        if event_name == "REMOVE":
            try:
                client.delete(index=OPENSEARCH_INDEX, id=user_id, ignore=[404])
                deleted += 1
            except Exception:  # noqa: BLE001
                _logger.exception("Failed to delete user from OpenSearch", extra={"userId": user_id})
                raise  # re-raise so Lambda retries the batch
        else:
            # INSERT or MODIFY — partial update of identity-owned fields only.
            # doc_as_upsert=True creates the document if it doesn't exist yet
            # (e.g. identity-access event arrives before member-profiles event).
            # member-profiles fields (bio, skills, groupIds) are untouched.
            new_image = dynamodb.get("NewImage")
            if not new_image:
                skipped += 1
                continue
            doc = _deserialize(new_image)
            identity_doc = {k: v for k, v in doc.items() if k in _IDENTITY_FIELDS}
            try:
                client.update(
                    index=OPENSEARCH_INDEX,
                    id=user_id,
                    body={"doc": identity_doc, "doc_as_upsert": True},
                )
                indexed += 1
            except Exception:  # noqa: BLE001
                _logger.exception("Failed to update user in OpenSearch", extra={"userId": user_id})
                raise  # re-raise so Lambda retries the batch

    _logger.info(
        "Stream batch processed",
        extra={"indexed": indexed, "deleted": deleted, "skipped": skipped},
    )


def _deserialize(image: dict) -> dict:
    """Convert DynamoDB typed JSON to a plain dict suitable for OpenSearch.

    Strips all DynamoDB-internal projection keys (pk, sk, gsiNpk, gsiNsk, ttl)
    from the document. Adds roleSortOrder (integer) for deterministic admin sort.
    """
    out: dict = {}
    for k, v in image.items():
        if "S" in v:
            out[k] = v["S"]
        elif "N" in v:
            n = Decimal(v["N"])
            out[k] = int(n) if n == n.to_integral_value() else float(n)
        elif "BOOL" in v:
            out[k] = v["BOOL"]
        elif "NULL" in v:
            out[k] = None
        elif "SS" in v:
            out[k] = list(v["SS"])
        elif "NS" in v:
            out[k] = [float(x) for x in v["NS"]]
        elif "L" in v:
            out[k] = [_deserialize_value(i) for i in v["L"]]
        elif "M" in v:
            out[k] = _deserialize(v["M"])

    # Strip DynamoDB internal / GSI projection keys — these are index artefacts
    # that have no meaning in the search document.
    for key in ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk",
                "gsi3pk", "gsi3sk", "ttl"):
        out.pop(key, None)

    # Add numeric sort field for role column (0=Admin → 3=Member).
    role = out.get("role", "")
    out["roleSortOrder"] = _ROLE_SORT_ORDER.get(role, 99)

    # Normalise status to lowercase so it matches the member-profiles convention
    # and the frontend's `m.status === "active"` checks.
    # identity-access stores "Active"/"Inactive" (capital); member-profiles uses
    # "active"/"inactive". The merged index must be consistent.
    if out.get("status"):
        out["status"] = out["status"].lower()

    return out


def _deserialize_value(v: dict):  # noqa: ANN201
    """Deserialize a single DynamoDB typed value from a List element."""
    if "S" in v:
        return v["S"]
    if "N" in v:
        n = Decimal(v["N"])
        return int(n) if n == n.to_integral_value() else float(n)
    if "BOOL" in v:
        return v["BOOL"]
    if "NULL" in v:
        return None
    if "M" in v:
        return _deserialize(v["M"])
    if "L" in v:
        return [_deserialize_value(i) for i in v["L"]]
    return None
