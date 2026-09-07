"""DynamoDB stream processor — indexes MEMBER#*/PROFILE items into OpenSearch.

Triggered by the member-profiles DynamoDB stream on every profile write.
Only MEMBER#.../PROFILE items are processed; shoutout records and other
item types are ignored.

Sort fields written per document:
  roleSortOrder    int  0=CommunityLeader, 1=UserGroupLeader, 2=Member (no Admin in directory)
  awsProjectSort   int  1=true first (ascending), 0=false
  firstNameNorm    str  lowercase accent-stripped — for firstName A-Z sort
"""
from __future__ import annotations

import json
import os
from decimal import Decimal

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from _conventions.logger import get_logger

_logger = get_logger("member-profiles.indexer")

OPENSEARCH_INDEX = "members"

_ROLE_SORT: dict[str, int] = {
    "CommunityLeader": 0,
    "UserGroupLeader": 1,
    "Member": 2,
}

_os_client: OpenSearch | None = None


def _get_client() -> OpenSearch:
    global _os_client  # noqa: PLW0603
    if _os_client is None:
        endpoint = os.environ["OPENSEARCH_ENDPOINT"]
        region = os.environ.get("AWS_REGION", "us-east-1")
        creds = boto3.Session().get_credentials().get_frozen_credentials()
        auth = AWS4Auth(creds.access_key, creds.secret_key, region, "aoss",
                        session_token=creds.token)
        host = endpoint.replace("https://", "").rstrip("/")
        _os_client = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=60,
        )
    return _os_client


def handler(event: dict, context) -> None:  # noqa: ANN001
    client = _get_client()
    indexed = deleted = skipped = 0

    for record in event.get("Records", []):
        dynamodb = record.get("dynamodb", {})
        keys = dynamodb.get("Keys", {})
        pk = keys.get("pk", {}).get("S", "")
        sk = keys.get("sk", {}).get("S", "")

        if not pk.startswith("MEMBER#") or sk != "PROFILE":
            skipped += 1
            continue

        member_id = pk[len("MEMBER#"):]
        event_name = record.get("eventName", "")

        if event_name == "REMOVE":
            try:
                client.delete(index=OPENSEARCH_INDEX, id=member_id, ignore=[404])
                deleted += 1
            except Exception:  # noqa: BLE001
                _logger.exception("Failed to delete member from OpenSearch",
                                  extra={"memberId": member_id})
                raise
        else:
            new_image = dynamodb.get("NewImage")
            if not new_image:
                skipped += 1
                continue
            doc = _deserialize(new_image)
            try:
                client.index(index=OPENSEARCH_INDEX, id=member_id, body=doc)
                indexed += 1
            except Exception:  # noqa: BLE001
                _logger.exception("Failed to index member in OpenSearch",
                                  extra={"memberId": member_id})
                raise

    _logger.info("Stream batch processed",
                 extra={"indexed": indexed, "deleted": deleted, "skipped": skipped})


def _deserialize(image: dict) -> dict:
    """Convert DynamoDB typed JSON to a plain dict for OpenSearch.

    Strips DynamoDB key fields. Adds sort-helper fields.
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
            out[k] = [_deser_val(i) for i in v["L"]]
        elif "M" in v:
            out[k] = _deserialize(v["M"])

    # Strip DynamoDB internal / GSI projection keys
    for key in ("pk", "sk", "gsi_pk", "gsi_sk", "ttl"):
        out.pop(key, None)

    # Flatten groups[] to groupIds[] for filter queries
    groups = out.get("groups", [])
    if isinstance(groups, list):
        out["groupIds"] = [
            g.get("groupId") for g in groups
            if isinstance(g, dict) and g.get("groupId")
        ]

    # Sort helper fields
    role = out.get("role", "Member")
    out["roleSortOrder"] = _ROLE_SORT.get(role, 99)
    out["awsProjectSort"] = 1 if out.get("awsProject") else 0

    import unicodedata  # noqa: PLC0415
    def _norm(s: str) -> str:
        nfkd = unicodedata.normalize("NFKD", s or "")
        return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()

    out["firstNameNorm"] = _norm(out.get("firstName") or "")
    out["lastNameNorm"] = _norm(out.get("lastName") or "")
    out["cityNorm"] = _norm(out.get("city") or "")
    out["countryNorm"] = _norm(out.get("country") or "")

    return out


def _deser_val(v: dict):  # noqa: ANN201
    if "S" in v: return v["S"]
    if "N" in v:
        n = Decimal(v["N"])
        return int(n) if n == n.to_integral_value() else float(n)
    if "BOOL" in v: return v["BOOL"]
    if "NULL" in v: return None
    if "M" in v: return _deserialize(v["M"])
    if "L" in v: return [_deser_val(i) for i in v["L"]]
    return None
