"""Single-table DynamoDB access for Member Profiles & Directory (NFR-MP-SCALE-1).

Key design (see nfr-design/logical-components.md):
  MEMBER#<id>       / PROFILE              -> profile-extension record (E1)
  EXPORT#<jobId>    / JOB      (TTL=ttl)   -> async directory CSV export job
  EXPORTLOCK#<actor>/ LOCK     (TTL=ttl)   -> one-in-flight-export guard per leader

The ByName GSI (gsi_pk="DIRECTORY", gsi_sk="<lastName>#<firstName>#<id>") is
retained for put_profile writes (sort key still maintained) but the directory
listing read path now goes through OpenSearch exclusively — the DynamoDB scan
and GSI query methods have been removed.
"""
from __future__ import annotations

import base64
import json
import os
import unicodedata
from decimal import Decimal

from _conventions.errors import ValidationError
from _conventions.logger import get_logger, log

_logger = get_logger("member-profiles.repository")

GSI_NAME = "ByName"
GSI_PK_VALUE = "DIRECTORY"

# OpenSearch index name — must match indexer.py
OPENSEARCH_INDEX = "members"

# Role sort order for the directory table (ascending = CL first).
_ROLE_SORT: dict[str, int] = {
    "CommunityLeader": 0,
    "UserGroupLeader": 1,
    "Member": 2,
}


# DynamoDB page-cursor helpers for the shoutout queries.
#
# These were CALLED in three places (query_shoutout_feed_page,
# query_shoutouts_for_recipient_page, query_shoutouts_sent_page) but never
# defined or imported in this service, so every one raised NameError the moment
# pagination was actually needed. Settings, contributions-scoring, certifications
# and events each define the same pair locally; member-profiles was written
# against them and never got the copy. Same contract as those services,
# including the ValidationError message, so a malformed cursor is a 400 rather
# than an unhandled 500.
#
# Shoutout rows are keyed on pk/sk only — all three copies of a shoutout
# (SHOUTOUT_FEED, SHOUTOUT_RCPT#<id>, SHOUTOUT_SENT#<id>) share the same
# "<createdAt>#<id>" sort key — so the allow-list is just those two. Restricting
# it matters: a crafted cursor cannot name a different attribute.
_CURSOR_ATTRS = ("pk", "sk")


def encode_cursor(key: dict) -> str:
    """Encode a DynamoDB LastEvaluatedKey-shaped dict as an opaque token.

    Takes a KEY, never a whole item. Passing an item would hand json.dumps the
    row's Decimal attributes (reactionCount) and raise TypeError — which is the
    second half of the bug this fixes.
    """
    return base64.urlsafe_b64encode(json.dumps(key, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Opaque page cursor. Only table key attributes may appear, so a crafted
    cursor cannot name another field; malformed input is a client error (400)
    rather than an unhandled 500."""
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(key, dict) or not key or not set(key) <= set(_CURSOR_ATTRS):
            raise ValueError("bad cursor shape")
        return key
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValidationError("Invalid pagination cursor.") from None


def _cursor_key(item: dict) -> dict:
    """The key attributes of a row, for resuming after it."""
    return {k: item[k] for k in _CURSOR_ATTRS if k in item}


def _norm(s: str) -> str:
    """Lowercase, accent-stripped normalisation for sort keys."""
    nfkd = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _name_key(first: str, last: str, member_id: str) -> str:
    return f"{_norm(last)}#{_norm(first)}#{member_id}"


def _member_to_doc(profile: dict) -> dict:
    """Convert a DynamoDB profile item to an OpenSearch document."""
    doc = {k: v for k, v in profile.items()
           if k not in ("pk", "sk", "gsi_pk", "gsi_sk", "ttl")}
    groups = doc.get("groups", [])
    doc["groupIds"] = [g.get("groupId") for g in groups
                       if isinstance(g, dict) and g.get("groupId")]
    doc["roleSortOrder"] = _ROLE_SORT.get(doc.get("role", "Member"), 99)
    doc["awsProjectSort"] = 1 if doc.get("awsProject") else 0
    doc["firstNameNorm"] = _norm(doc.get("firstName") or "")
    doc["lastNameNorm"] = _norm(doc.get("lastName") or "")
    doc["cityNorm"] = _norm(doc.get("city") or "")
    doc["countryNorm"] = _norm(doc.get("country") or "")
    return doc


def _member_query(*, q: str | None = None, role: str | None = None,
                  group_id: str | None = None, group_ids: list[str] | None = None,
                  id_filter: set[str] | None = None) -> dict:
    """The OpenSearch `bool` query for a directory listing.

    Shared by `search_members` (which fetches the rows) and `count_members`
    (which supplies the denominator for the CSV-export progress bar). They MUST
    build the query identically — if the count and the row walk disagree, the
    reported percentage is wrong and can stall short of 100% or overshoot it.

    `group_id` (one group) and `group_ids` (any of several) are separate
    parameters rather than one overloaded argument because they answer different
    questions and BOTH can apply at once: `group_id` is the user's chosen filter,
    `group_ids` is the set of groups a Member is allowed to see at all. Passing
    both ANDs them, which is what makes "filter to group X, but only if X is one
    of mine" a single query instead of a filter plus a post-check.
    """
    # Filter clauses (exact match, not scored).
    filters: list[dict] = []
    if role:
        filters.append({"term": {"role.keyword": role}})
    if group_id:
        # `.keyword` is required: groupIds is a dynamically-mapped string
        # array (analyzed `text`), so a bare term on a hyphenated group id
        # never matches its tokenized form — mirrors role.keyword/id.keyword.
        filters.append({"term": {"groupIds.keyword": group_id}})
    if group_ids is not None:
        # `terms` = OR within this clause, AND against the others. An empty list
        # is a real, meaningful value here: it matches nothing, which is exactly
        # what a Member who belongs to no groups should see. Callers short-circuit
        # before reaching OpenSearch, but the semantics hold if one does not.
        filters.append({"terms": {"groupIds.keyword": list(group_ids)}})
    if id_filter is not None:
        filters.append({"terms": {"id.keyword": list(id_filter)}})

    # Full-text query.
    must: list[dict] = []
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["firstName", "lastName", "email",
                           "professionalRole", "bio", "skills"],
                "type": "phrase_prefix",
            }
        })

    return {"bool": {"must": must if must else [{"match_all": {}}], "filter": filters}}


class ProfileRepository:
    def __init__(self, table):
        self._t = table

    def put_profile(self, profile: dict) -> dict:
        item = dict(profile)
        item["pk"] = f"MEMBER#{profile['id']}"
        item["sk"] = "PROFILE"
        item["gsi_pk"] = GSI_PK_VALUE
        item["gsi_sk"] = _name_key(
            profile.get("firstName", ""),
            profile.get("lastName", ""),
            profile["id"],
        )
        self._t.put_item(Item=item)
        return profile

    def get_profile(self, member_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"MEMBER#{member_id}", "sk": "PROFILE"})
        return resp.get("Item")

    # ------------------------------------------------------------------
    # OpenSearch directory search + reindex
    # ------------------------------------------------------------------

    def search_members(
        self,
        *,
        q: str | None = None,
        role: str | None = None,
        group_id: str | None = None,
        group_ids: list[str] | None = None,
        id_filter: set[str] | None = None,
        sort: str = "firstName",
        sort_dir: str = "asc",
        limit: int = 25,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:
        """Query the OpenSearch 'members' index.

        Returns (items, next_cursor). next_cursor is an opaque base64 string
        encoding the search_after values of the last hit — stable across
        concurrent writes. Returns ([], None) when OpenSearch is not configured.
        """
        client = self._os_client()
        if client is None:
            return [], None

        # Sort specification — all sort fields use .keyword or numeric sub-fields.
        _dir = "asc" if sort_dir == "asc" else "desc"
        _sort_map: dict[str, list[dict]] = {
            "firstName":   [{"firstNameNorm.keyword": _dir}, {"lastNameNorm.keyword": _dir},  {"id.keyword": "asc"}],
            "lastName":    [{"lastNameNorm.keyword": _dir},  {"firstNameNorm.keyword": _dir}, {"id.keyword": "asc"}],
            "email":       [{"email.keyword": _dir},                                           {"id.keyword": "asc"}],
            "role":        [{"roleSortOrder": _dir},                                           {"id.keyword": "asc"}],
            "city":        [{"cityNorm.keyword": _dir},                                        {"id.keyword": "asc"}],
            "country":     [{"countryNorm.keyword": _dir},                                     {"id.keyword": "asc"}],
            "status":      [{"status.keyword": _dir},                                          {"id.keyword": "asc"}],
            "awsProject":  [{"awsProjectSort": _dir},                                          {"id.keyword": "asc"}],
        }
        sort_spec = _sort_map.get(sort, _sort_map["firstName"])

        body: dict = {
            "query": _member_query(q=q, role=role, group_id=group_id,
                                   group_ids=group_ids, id_filter=id_filter),
            "sort": sort_spec,
            "size": limit + 1,  # fetch one extra to detect whether a next page exists
        }

        if cursor:
            try:
                body["search_after"] = json.loads(
                    base64.urlsafe_b64decode(cursor.encode())
                )
            except (ValueError, TypeError, json.JSONDecodeError):
                raise ValidationError("Invalid pagination cursor.") from None

        resp = client.search(index=OPENSEARCH_INDEX, body=body)
        hits = resp.get("hits", {}).get("hits", [])

        next_cursor: str | None = None
        if len(hits) > limit:
            # Extra item confirms a next page exists; exclude it from the response.
            hits = hits[:limit]
            last_sort = hits[-1].get("sort", [])
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(last_sort).encode()
            ).decode()

        items = [h["_source"] for h in hits]
        return items, next_cursor

    def count_members(self, *, q: str | None = None, role: str | None = None,
                      group_id: str | None = None, group_ids: list[str] | None = None,
                      id_filter: set[str] | None = None) -> int | None:
        """Exact count of members matching the same filters `search_members` would.

        Supplies the denominator for the CSV-export progress bar. Uses the
        OpenSearch `_count` API, which returns a total without materialising
        hits — so it stays cheap at 25k+ members, unlike counting via a
        DynamoDB scan of the whole table.

        Returns None when OpenSearch is not configured, so callers can fall back
        to an indeterminate progress display rather than reporting a fake total.
        """
        client = self._os_client()
        if client is None:
            return None
        resp = client.count(
            index=OPENSEARCH_INDEX,
            body={"query": _member_query(q=q, role=role, group_id=group_id,
                                         group_ids=group_ids, id_filter=id_filter)},
        )
        return int(resp.get("count", 0))

    # ---------- CSV export jobs (TTL) ----------
    # Short-lived job records for the async Member Directory CSV export. The
    # table has TTL enabled on `ttl` (see service-member-profiles-data.yaml), and
    # `expiresAt` is re-checked in application code because TTL deletion is
    # asynchronous and can lag by hours. First TTL-bearing item type in this
    # table; mirrors identity-access's EXPORT#<jobId>/JOB convention.

    def put_export_job(self, job: dict) -> dict:
        item = dict(job)
        item["pk"] = f"EXPORT#{job['jobId']}"
        item["sk"] = "JOB"
        self._t.put_item(Item=item)
        return job

    def get_export_job(self, job_id: str) -> dict | None:
        from models import epoch  # noqa: PLC0415 — avoids a circular import at module load
        resp = self._t.get_item(Key={"pk": f"EXPORT#{job_id}", "sk": "JOB"})
        item = resp.get("Item")
        if item and int(item.get("expiresAt", 0)) < epoch():
            return None
        return item

    def update_export_job(self, job_id: str, fields: dict) -> None:
        """Targeted attribute update.

        An UpdateExpression rather than read-merge-put: the worker writes
        `processed` repeatedly while the API may be reading the same row, and a
        whole-item put would race and could resurrect stale attributes.
        """
        if not fields:
            return
        names = {f"#f{i}": k for i, k in enumerate(fields)}
        values = {f":v{i}": v for i, v in enumerate(fields.values())}
        sets = ", ".join(f"{n} = {v}" for n, v in zip(names, values, strict=True))
        self._t.update_item(
            Key={"pk": f"EXPORT#{job_id}", "sk": "JOB"},
            UpdateExpression=f"SET {sets}",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def acquire_export_lock(self, actor: str, job_id: str, *, ttl_seconds: int) -> bool:
        """Atomically claim the one in-flight export slot for `actor`.

        Returns False if that leader already has an export running. A conditional
        write rather than read-then-write so two rapid clicks cannot both pass.
        Self-healing: the condition also succeeds once the existing lock is past
        `expiresAt`, so a worker that dies without releasing blocks retries for at
        most `ttl_seconds` instead of forever.
        """
        from botocore.exceptions import ClientError  # noqa: PLC0415 — lazy, file convention
        from models import epoch  # noqa: PLC0415
        now = epoch()
        try:
            self._t.put_item(
                Item={"pk": f"EXPORTLOCK#{actor}", "sk": "LOCK", "jobId": job_id,
                      "expiresAt": now + ttl_seconds, "ttl": now + ttl_seconds},
                ConditionExpression="attribute_not_exists(pk) OR expiresAt < :now",
                ExpressionAttributeValues={":now": now},
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def release_export_lock(self, actor: str) -> None:
        self._t.delete_item(Key={"pk": f"EXPORTLOCK#{actor}", "sk": "LOCK"})

    def reindex_all_members(self) -> int:
        """Bulk-index every PROFILE item from DynamoDB into OpenSearch.

        Called by the nightly reconciliation schedule and the on-demand
        POST /members/reindex endpoint. Returns the count of documents indexed.
        """
        client = self._os_client()
        if client is None:
            return 0

        # Full scan of PROFILE items.
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415
        items, kwargs = [], {}
        while True:
            resp = self._t.scan(FilterExpression=Attr("sk").eq("PROFILE"), **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break

        if not items:
            return 0

        bulk_lines: list[str] = []
        for item in items:
            member_id = item.get("id", "")
            doc = _member_to_doc(item)
            bulk_lines.append(
                json.dumps({"index": {"_index": OPENSEARCH_INDEX, "_id": member_id}})
            )
            bulk_lines.append(json.dumps(doc, default=str))

        client.bulk(body="\n".join(bulk_lines) + "\n")
        return len(items)

    def all_profiles(self) -> list[dict]:
        """Full profile scan — used by CSV export (unpaged path only)."""
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415
        items, kwargs = [], {}
        while True:
            resp = self._t.scan(FilterExpression=Attr("sk").eq("PROFILE"), **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def _os_client(self):  # noqa: ANN201
        """Lazy OpenSearch client — returns None if endpoint not configured."""
        endpoint = os.environ.get("OPENSEARCH_ENDPOINT", "")
        if not endpoint:
            return None
        try:
            import boto3 as _boto3  # noqa: PLC0415
            from opensearchpy import OpenSearch, RequestsHttpConnection  # noqa: PLC0415
            from requests_aws4auth import AWS4Auth  # noqa: PLC0415
        except ImportError:
            return None
        region = os.environ.get("AWS_REGION", "us-east-1")
        creds = _boto3.Session().get_credentials().get_frozen_credentials()
        auth = AWS4Auth(creds.access_key, creds.secret_key, region, "aoss",
                        session_token=creds.token)
        host = endpoint.replace("https://", "").rstrip("/")
        return OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            timeout=60,
        )
    # ============================================================== Shoutouts (US-13)
    #
    # Data layout (all in the same table, no GSIs needed):
    #   SHOUTOUT_FEED                / <createdAt>#<id>  → shoutout (home feed, Query desc limit 5)
    #   SHOUTOUT_RCPT#<recipientId>  / <createdAt>#<id>  → shoutout (profile view, Query desc)
    #   SHOUTOUT_SENT#<senderId>     / <createdAt>#<id>  → shoutout (weekly limit check, Query > weekStart)
    #   SHOUTOUT#<id>                / META              → canonical record
    #   SHOUTOUT#<id>                / REACTION#<userId> → reaction marker
    #
    # Three partition writes per shoutout (feed + recipient + sender) keep reads
    # as single-partition Queries. 13k member groups are never loaded.

    def put_shoutout(self, record: dict) -> None:
        """Write a shoutout to all access-pattern partitions."""
        sid = record["shoutoutId"]
        created = record["createdAt"]
        sk_suffix = f"{created}#{sid}"

        # Filter empty strings (DynamoDB rejects them)
        clean = {k: v for k, v in record.items() if v != "" and v is not None}

        # Write 4 items: canonical + feed + recipient + sender
        self._t.put_item(Item={**clean, "pk": f"SHOUTOUT#{sid}", "sk": "META"})
        self._t.put_item(Item={**clean, "pk": "SHOUTOUT_FEED", "sk": sk_suffix})
        self._t.put_item(Item={**clean, "pk": f"SHOUTOUT_RCPT#{record['recipientId']}", "sk": sk_suffix})
        self._t.put_item(Item={**clean, "pk": f"SHOUTOUT_SENT#{record['senderId']}", "sk": sk_suffix})

    def get_shoutout(self, shoutout_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"SHOUTOUT#{shoutout_id}", "sk": "META"})
        return resp.get("Item")

    def query_shoutout_feed(self, since_iso: str, *, limit: int = 5) -> list[dict]:
        """Home feed: recent shoutouts since cutoff, newest first."""
        from boto3.dynamodb.conditions import Key
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq("SHOUTOUT_FEED") & Key("sk").gt(since_iso),
            ScanIndexForward=False,
            Limit=limit,
        )
        return resp.get("Items", [])

    def query_shoutout_feed_page(self, since_iso: str, *, limit: int = 20,
                                  cursor: str | None = None) -> tuple[list[dict], str | None]:
        """Paginated feed for the 30-day detailed page."""
        from boto3.dynamodb.conditions import Key
        kwargs: dict = {
            "KeyConditionExpression": Key("pk").eq("SHOUTOUT_FEED") & Key("sk").gt(since_iso),
            "ScanIndexForward": False,
            "Limit": limit + 1,
        }
        if cursor:
            try:
                kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
            except ValidationError:
                raise
            except Exception as exc:  # noqa: BLE001
                log(_logger, 30, "unexpected cursor decode error — ignoring", error=str(exc))
        resp = self._t.query(**kwargs)
        items = resp.get("Items", [])
        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            # key only, not the whole row: the row carries Decimals
            next_cursor = encode_cursor(_cursor_key(items[-1]))
        return items, next_cursor

    def query_shoutouts_for_recipient(self, recipient_id: str, *, limit: int = 10) -> list[dict]:
        """All shoutouts received by a member, newest first."""
        from boto3.dynamodb.conditions import Key
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"SHOUTOUT_RCPT#{recipient_id}"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return resp.get("Items", [])

    def query_shoutouts_for_recipient_page(self, recipient_id: str, *, limit: int = 20,
                                            cursor: str | None = None) -> tuple[list[dict], str | None]:
        """Paginated shoutouts received by a member."""
        from boto3.dynamodb.conditions import Key
        kwargs: dict = {
            "KeyConditionExpression": Key("pk").eq(f"SHOUTOUT_RCPT#{recipient_id}"),
            "ScanIndexForward": False,
            "Limit": limit + 1,
        }
        if cursor:
            try:
                kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
            except ValidationError:
                raise
            except Exception as exc:  # noqa: BLE001
                log(_logger, 30, "unexpected cursor decode error — ignoring", error=str(exc))
        resp = self._t.query(**kwargs)
        items = resp.get("Items", [])
        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            # key only, not the whole row: the row carries Decimals
            next_cursor = encode_cursor(_cursor_key(items[-1]))
        return items, next_cursor

    def query_shoutouts_sent_page(self, sender_id: str, since_iso: str, *, limit: int = 20,
                                   cursor: str | None = None) -> tuple[list[dict], str | None]:
        """Paginated shoutouts sent by a user in the past 30 days."""
        from boto3.dynamodb.conditions import Key
        kwargs: dict = {
            "KeyConditionExpression": Key("pk").eq(f"SHOUTOUT_SENT#{sender_id}") & Key("sk").gt(since_iso),
            "ScanIndexForward": False,
            "Limit": limit + 1,
        }
        if cursor:
            try:
                kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
            except ValidationError:
                raise
            except Exception as exc:  # noqa: BLE001
                log(_logger, 30, "unexpected cursor decode error — ignoring", error=str(exc))
        resp = self._t.query(**kwargs)
        items = resp.get("Items", [])
        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            # key only, not the whole row: the row carries Decimals
            next_cursor = encode_cursor(_cursor_key(items[-1]))
        return items, next_cursor

    def list_shoutouts_sent_since(self, sender_id: str, since_iso: str) -> list[dict]:
        """Sender's shoutouts since a date (for weekly limit check). Max 3 items."""
        from boto3.dynamodb.conditions import Key
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"SHOUTOUT_SENT#{sender_id}") & Key("sk").gt(since_iso),
        )
        return resp.get("Items", [])

    def toggle_shoutout_reaction(self, shoutout_id: str, user_id: str) -> bool:
        """Toggle reaction. Returns True if reacted (added), False if unreacted (removed).
        Updates reactionCount on ALL 4 partition copies so feed queries see current count.
        """
        from botocore.exceptions import ClientError
        # Attr was used below (ConditionExpression) but imported only in two
        # SIBLING methods, so every reaction toggle raised NameError -> 500. Same
        # class of defect as the missing cursor helpers, and ruff had been
        # reporting it as F821 all along inside the accepted error baseline.
        from boto3.dynamodb.conditions import Attr  # noqa: PLC0415
        reaction_key = {"pk": f"SHOUTOUT#{shoutout_id}", "sk": f"REACTION#{user_id}"}

        # Get the canonical record to find the SK suffix used for feed copies
        canonical = self.get_shoutout(shoutout_id)
        if not canonical:
            return False
        created = canonical.get("createdAt", "")
        sk_suffix = f"{created}#{shoutout_id}"
        recipient_id = canonical.get("recipientId", "")
        sender_id = canonical.get("senderId", "")

        copy_keys = [
            {"pk": f"SHOUTOUT#{shoutout_id}", "sk": "META"},
            {"pk": "SHOUTOUT_FEED", "sk": sk_suffix},
            {"pk": f"SHOUTOUT_RCPT#{recipient_id}", "sk": sk_suffix},
            {"pk": f"SHOUTOUT_SENT#{sender_id}", "sk": sk_suffix},
        ]

        def _update_all(delta: int) -> None:
            for k in copy_keys:
                try:
                    self._t.update_item(
                        Key=k,
                        UpdateExpression="ADD reactionCount :d",
                        ExpressionAttributeValues={":d": delta},
                    )
                except Exception as exc:  # noqa: BLE001 — copy may not exist
                    log(_logger, 30, "reactionCount update failed on copy",
                        key=k, delta=delta, error=str(exc))

        # Try to ADD (condition: item must NOT exist)
        try:
            self._t.put_item(
                Item={**reaction_key, "reactedAt": _now_iso()},
                ConditionExpression=Attr("pk").not_exists(),
            )
            _update_all(1)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

        # Already exists — remove it and decrement
        self._t.delete_item(Key=reaction_key)
        _update_all(-1)
        return False

    def get_shoutout_reaction_count(self, shoutout_id: str) -> int:
        item = self.get_shoutout(shoutout_id)
        return int(item.get("reactionCount", 0)) if item else 0

    def delete_shoutout(self, record: dict) -> None:
        """Remove a shoutout from all partitions."""
        sid = record["shoutoutId"]
        created = record["createdAt"]
        sk_suffix = f"{created}#{sid}"

        keys = [
            {"pk": f"SHOUTOUT#{sid}", "sk": "META"},
            {"pk": "SHOUTOUT_FEED", "sk": sk_suffix},
            {"pk": f"SHOUTOUT_RCPT#{record['recipientId']}", "sk": sk_suffix},
            {"pk": f"SHOUTOUT_SENT#{record['senderId']}", "sk": sk_suffix},
        ]
        # Also delete all reactions (scan the SHOUTOUT#<id> partition for REACTION# items)
        from boto3.dynamodb.conditions import Key as K
        resp = self._t.query(
            KeyConditionExpression=K("pk").eq(f"SHOUTOUT#{sid}") & K("sk").begins_with("REACTION#"),
        )
        for r in resp.get("Items", []):
            keys.append({"pk": r["pk"], "sk": r["sk"]})

        # Individual deletes (no BatchWriteItem permission needed)
        for k in keys:
            self._t.delete_item(Key=k)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
