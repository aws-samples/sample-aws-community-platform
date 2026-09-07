"""Single-table DynamoDB access for Events.

Key design (one item collection per event, so the detail and manage screens read
one partition — P-PERF-2):

  EVENT#<id>        / META                      -> event
      GSI1  SCOPE#<scope>#<status> / <startsAt>       -> listings + calendar
  EVENT#<id>        / RSVP#<userId>             -> RSVP
      GSI2  USER#<userId> / RSVP#<startsAt>#<eventId> -> a member's own RSVPs
  EVENT#<id>        / MAT#<materialId>          -> material metadata
      GSI3  CONTENT#<scope> / <eventStartsAt>#<matId> -> Content Library (SPARSE)
  EVENT#<id>        / DESIG#<kind>#<userId>     -> presenter/organizer
  EVENT#<id>        / UL#<linkId>               -> upload link
  EVENT#<id>        / UF#<linkId>#<name>        -> uploaded file
  EVENT#<id>        / TEAMS#<fetchedAt>         -> reviewable Teams batch
  ULTOKEN#<sha256>  / META                      -> pointer -> {linkId, eventId}

**Sparse indexes (J2)**: GSI3 key attributes are written only while the item
qualifies and REMOVED when it stops. The index therefore stays proportional to
publishable content rather than to table size — a Content Library listing costs
the same at 100 events or 100,000.

**No Scans anywhere (P-SCALE-1)**. This is a hard rule for this unit, not a
preference: the Member Directory shipped on a Scan and had to be reworked under
load, and the File Share listing shipped a Query against an index that did not
exist and produced a live 500. Every listing here is an index Query.

All expressions are parameterized (SECURITY-05).
"""
from __future__ import annotations

from _conventions.logger import get_logger, log

_logger = get_logger("events.repository")

import base64
import json

from _conventions.errors import ValidationError
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from models import (
    COMMUNITY,
    SCAN_CLEAN,
    STATUS_COMPLETED,
    scope_key,
)

# Whitelisted cursor attributes. A GSI ExclusiveStartKey needs the index keys AND
# the table keys; whitelisting means a crafted cursor can never name another field.
_CURSOR_ATTRS = ("pk", "sk", "gsi1pk", "gsi1sk", "gsi2pk", "gsi2sk", "scopeIndex")


def encode_cursor(key: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(key, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Malformed input is a client error (400), never an unhandled 500."""
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(key, dict) or not key or not set(key) <= set(_CURSOR_ATTRS):
            raise ValueError("bad cursor shape")
        return key
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValidationError("Invalid pagination cursor.") from None


class EventRepository:
    def __init__(self, table):
        self._t = table

    # ------------------------------------------------------------------ events

    def put_event(self, event: dict) -> dict:
        item = dict(event)
        item["pk"] = f"EVENT#{event['id']}"
        item["sk"] = "META"
        item["gsi1pk"] = f"SCOPE#{scope_key(event.get('groupId'))}#{event['status']}"
        item["gsi1sk"] = event.get("startsAt") or ""
        self._t.put_item(Item=item)
        return event

    def get_event(self, event_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"EVENT#{event_id}", "sk": "META"})
        return resp.get("Item")

    def scan_scope_status_range(self, scope: str, status: str, *,
                                date_from: str, date_to: str) -> list[dict]:
        """Every event of ONE scope + status whose date falls in a range, as
        minimal `{startsAt, type}` rows.

        Aggregation-only read (US-7.2 "events by type"). Three properties make it
        cheap enough to run on a dashboard load:

        * It hits a SINGLE partition (`SCOPE#<scope>#<status>`) instead of the
          listing walk, which visits community-wide as well and then post-filters
          — so counting one group's events no longer reads every other scope.
        * The date range is a sort-key condition, so out-of-window events are
          never read at all.
        * `ProjectionExpression` fetches only the attributes the aggregate needs,
          so a busy quarter transfers a few hundred bytes rather than full event
          records. ("type" is a DynamoDB reserved word, hence the alias.)
        """
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                IndexName="GSI1",
                KeyConditionExpression=self._scope_condition(
                    f"SCOPE#{scope}#{status}", date_from, date_to),
                ProjectionExpression="gsi1sk, #t",
                ExpressionAttributeNames={"#t": "type"},
                **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                return items

    def query_scope_page(self, scopes: list[str], *, statuses: list[str],
                         limit: int, cursor: str | None = None,
                         date_from: str | None = None, date_to: str | None = None,
                         predicate=None) -> tuple[list[dict], str | None]:
        """Scope partition walk with fetch-until-full pagination (P-SCALE-2).

        A caller's visible events span several partitions (community-wide plus
        each of their groups, times each requested status), so the walk visits
        them in a FIXED order and the cursor carries which partition it stopped
        in. Same shape as the role walk already shipped for Admin Users.

        `predicate` applies post-filters (keyword, type, delivery mode) INSIDE
        the loop, so a selective filter still returns a full page instead of a
        near-empty one.
        """
        partitions = [f"SCOPE#{s}#{st}" for st in statuses for s in scopes]
        start_index = 0
        start_key: dict | None = None
        if cursor:
            decoded = decode_cursor(cursor)
            start_index = int(decoded.pop("scopeIndex", 0))
            start_key = decoded or None

        matched: list[dict] = []
        for index in range(start_index, len(partitions)):
            exclusive = start_key if index == start_index else None
            while True:
                kwargs: dict = {
                    "IndexName": "GSI1",
                    "KeyConditionExpression": self._scope_condition(partitions[index], date_from, date_to),
                    "Limit": limit + 1,
                }
                if exclusive:
                    kwargs["ExclusiveStartKey"] = exclusive
                resp = self._t.query(**kwargs)
                for row in resp.get("Items", []):
                    if predicate is None or predicate(row):
                        matched.append(row)
                    if len(matched) > limit:
                        page = matched[:limit]
                        last = page[-1]
                        return page, encode_cursor(self._cursor_from(last, index, ("pk", "sk", "gsi1pk", "gsi1sk")))
                exclusive = resp.get("LastEvaluatedKey")
                if not exclusive:
                    break
        return matched, None

    @staticmethod
    def _scope_condition(partition: str, date_from: str | None, date_to: str | None):
        cond = Key("gsi1pk").eq(partition)
        if date_from and date_to:
            return cond & Key("gsi1sk").between(date_from, date_to)
        if date_from:
            return cond & Key("gsi1sk").gte(date_from)
        if date_to:
            return cond & Key("gsi1sk").lte(date_to)
        return cond

    @staticmethod
    def _cursor_from(item: dict, scope_index: int, attrs: tuple[str, ...]) -> dict:
        key = {a: item[a] for a in attrs if a in item}
        key["scopeIndex"] = str(scope_index)
        return key

    def query_all_scopes_page(self, *, statuses: list[str], limit: int,
                              cursor: str | None = None, date_from: str | None = None,
                              date_to: str | None = None, predicate=None,
                              known_scopes: list[str] | None = None):
        """Community-Leader listing: every scope. CL visibility is unbounded, so
        the partition set is community-wide plus every group that actually has
        events. `known_scopes` is supplied by the caller (from the scope
        registry) — deriving it with a Scan would reintroduce exactly the
        pattern this unit forbids."""
        scopes = [COMMUNITY] + [s for s in (known_scopes or []) if s != COMMUNITY]
        return self.query_scope_page(
            scopes, statuses=statuses, limit=limit, cursor=cursor,
            date_from=date_from, date_to=date_to, predicate=predicate)

    # A tiny registry of scopes that have ever had an event, so the CL walk and
    # the Content Library walk know which partitions exist without scanning.
    def register_scope(self, group_id: str | None) -> None:
        self._t.update_item(
            Key={"pk": "SCOPES", "sk": "REGISTRY"},
            UpdateExpression="ADD #s :v",
            ExpressionAttributeNames={"#s": "scopes"},
            ExpressionAttributeValues={":v": {scope_key(group_id)}},
        )

    def list_scopes(self) -> list[str]:
        resp = self._t.get_item(Key={"pk": "SCOPES", "sk": "REGISTRY"})
        item = resp.get("Item") or {}
        return sorted(item.get("scopes") or set())

    # -------------------------------------------------------------------- rsvp

    def get_rsvp(self, event_id: str, user_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"EVENT#{event_id}", "sk": f"RSVP#{user_id}"})
        return resp.get("Item")

    def put_rsvp_with_counters(self, rsvp: dict, *, starts_at: str,
                               yes_delta: int, no_delta: int) -> None:
        """RSVP row and the event's counters in ONE transaction (P-REL-6), so
        they cannot drift. Recomputing counts on read would cost a full RSVP
        query per list row."""
        item = dict(rsvp)
        item["pk"] = f"EVENT#{rsvp['eventId']}"
        item["sk"] = f"RSVP#{rsvp['userId']}"
        item["gsi2pk"] = f"USER#{rsvp['userId']}"
        item["gsi2sk"] = f"RSVP#{starts_at}#{rsvp['eventId']}"
        # Plain Python values, NOT low-level AttributeValue dicts: a client
        # obtained from a boto3 *resource* carries the document transformer, so
        # it serializes on the way out. Hand-serializing here double-encodes
        # (`{"S": "x"}` becomes `{"M": {"S": {"S": "x"}}}`), which surfaces from
        # DynamoDB as an opaque type error rather than a validation message.
        self._t.meta.client.transact_write_items(TransactItems=[
            {"Put": {"TableName": self._t.name, "Item": item}},
            {"Update": {
                "TableName": self._t.name,
                "Key": {"pk": f"EVENT#{rsvp['eventId']}", "sk": "META"},
                "UpdateExpression": "SET rsvpYesCount = if_not_exists(rsvpYesCount, :z) + :y, "
                                    "rsvpNoCount = if_not_exists(rsvpNoCount, :z) + :n",
                "ExpressionAttributeValues": {":y": yes_delta, ":n": no_delta, ":z": 0},
                "ConditionExpression": "attribute_exists(pk)",
            }},
        ])

    def list_rsvps(self, event_id: str) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
                & Key("sk").begins_with("RSVP#"),
                **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def list_user_rsvps(self, user_id: str) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                IndexName="GSI2",
                KeyConditionExpression=Key("gsi2pk").eq(f"USER#{user_id}"),
                **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def mark_attended(self, event_id: str, user_id: str, *, source: str,
                      points: int | None, at: str) -> bool:
        """Idempotent (BR-T8): the condition makes a second call a no-op, so a
        retry cannot re-award points. Returns True only if this call flipped it."""
        try:
            self._t.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": f"RSVP#{user_id}"},
                UpdateExpression="SET attended = :t, attendedSource = :s, attendedAt = :a, "
                                 "pointsAwarded = :p",
                ExpressionAttributeValues={":t": True, ":s": source, ":a": at, ":p": points,
                                           ":f": True},
                ConditionExpression="attribute_exists(sk) AND attended <> :f",
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def put_attendance_only(self, event_id: str, user_id: str, *, source: str,
                            points: int | None, at: str, email: str = "") -> None:
        """Attendance for someone with no RSVP row (CSV import, Teams match)."""
        self._t.put_item(Item={
            "pk": f"EVENT#{event_id}", "sk": f"RSVP#{user_id}",
            "eventId": event_id, "userId": user_id, "userEmail": email,
            "response": "no", "attended": True, "attendedSource": source,
            "attendedAt": at, "pointsAwarded": points,
            "gsi2pk": f"USER#{user_id}", "gsi2sk": f"RSVP#{at}#{event_id}",
        })

    def bump_event_counters(self, event_id: str, *, attended_delta: int = 0,
                            points_delta: int = 0) -> None:
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": "META"},
            UpdateExpression="SET attendedCount = if_not_exists(attendedCount, :z) + :a, "
                             "pointsAwarded = if_not_exists(pointsAwarded, :z) + :p",
            ExpressionAttributeValues={":a": attended_delta, ":p": points_delta, ":z": 0},
            ConditionExpression="attribute_exists(pk)",
        )

    # --------------------------------------------------------------- materials

    def put_material(self, material: dict, *, event: dict | None = None) -> dict:
        item = dict(material)
        item["pk"] = f"EVENT#{material['eventId']}"
        item["sk"] = f"MAT#{material['id']}"
        self._apply_content_index(item, event)
        self._t.put_item(Item=item)
        return material

    @staticmethod
    def _apply_content_index(item: dict, event: dict | None) -> None:
        """REMOVED — GSI3 sparse index removed as part of Content Library rework.
        The Content Library is now served by the library-${Stage} table via
        LibraryRepository. This stub is kept temporarily to avoid import errors
        from any test that still calls it; remove after full test suite update."""
        # No-op: remove gsi3 keys if somehow present
        item.pop("gsi3pk", None)
        item.pop("gsi3sk", None)

    def refresh_content_index(self, event: dict) -> int:
        """REMOVED — no longer used. Kept as a no-op stub for safe removal."""
        return 0

    def get_material(self, event_id: str, material_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"EVENT#{event_id}", "sk": f"MAT#{material_id}"})
        return resp.get("Item")

    def delete_material(self, event_id: str, material_id: str) -> None:
        self._t.delete_item(Key={"pk": f"EVENT#{event_id}", "sk": f"MAT#{material_id}"})

    def list_materials(self, event_id: str) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
                & Key("sk").begins_with("MAT#"),
                **kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def find_material_by_key(self, event_id: str, s3_key: str) -> dict | None:
        """Used by the S3 consumer. Bounded to one event's partition because the
        key itself carries the event id, so no reverse-lookup index is needed."""
        for mat in self.list_materials(event_id):
            if mat.get("s3Key") == s3_key:
                return mat
        return None

    def set_material_upload_state(self, event_id: str, material_id: str, *,
                                  size_bytes: int, uploaded_at: str) -> None:
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"MAT#{material_id}"},
            UpdateExpression="SET uploaded = :t, sizeBytes = :s, uploadedAt = :a",
            ExpressionAttributeValues={":t": True, ":s": size_bytes, ":a": uploaded_at},
            ConditionExpression="attribute_exists(sk)",
        )

    def set_material_scan_state(self, event_id: str, material_id: str, state: str) -> None:
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"MAT#{material_id}"},
            UpdateExpression="SET scanState = :s",
            ExpressionAttributeValues={":s": state},
            ConditionExpression="attribute_exists(sk)",
        )

    def clear_material_upload_state(self, event_id: str, material_id: str) -> None:
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"MAT#{material_id}"},
            UpdateExpression="SET uploaded = :f REMOVE sizeBytes, uploadedAt",
            ExpressionAttributeValues={":f": False},
            ConditionExpression="attribute_exists(sk)",
        )

    # ------------------------------------------------------------ designations

    def put_designation(self, designation: dict) -> None:
        item = dict(designation)
        item["pk"] = f"EVENT#{designation['eventId']}"
        item["sk"] = f"DESIG#{designation['kind']}#{designation['userId']}"
        self._t.put_item(Item=item)

    def list_designations(self, event_id: str) -> list[dict]:
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with("DESIG#"))
        return resp.get("Items", [])

    def clear_designations(self, event_id: str, kind: str) -> None:
        for row in self.list_designations(event_id):
            if row.get("kind") == kind:
                self._t.delete_item(Key={"pk": row["pk"], "sk": row["sk"]})

    def set_designation_counts(self, event_id: str, *, presenters: int, organizers: int) -> None:
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": "META"},
            UpdateExpression="SET presenterCount = :p, organizerCount = :o",
            ExpressionAttributeValues={":p": presenters, ":o": organizers},
            ConditionExpression="attribute_exists(pk)",
        )

    # ------------------------------------------------------------ upload links

    def put_upload_link(self, link: dict) -> dict:
        item = dict(link)
        item["pk"] = f"EVENT#{link['eventId']}"
        item["sk"] = f"UL#{link['id']}"
        self._t.put_item(Item=item)
        return link

    def get_upload_link(self, event_id: str, link_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"EVENT#{event_id}", "sk": f"UL#{link_id}"})
        return resp.get("Item")

    def list_upload_links(self, event_id: str) -> list[dict]:
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with("UL#"))
        return resp.get("Items", [])

    def find_upload_link_by_key(self, event_id: str, key: str) -> dict | None:
        """Locate the external-upload link slot for a scanned S3 object key.
        Matches on the slot's own s3Key, else its folderPrefix (legacy)."""
        for link in self.list_upload_links(event_id):
            if link.get("s3Key") == key:
                return link
            prefix = link.get("folderPrefix")
            if prefix and key.startswith(prefix):
                return link
        return None

    def set_upload_link_revoked(self, event_id: str, link_id: str) -> None:
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"UL#{link_id}"},
            UpdateExpression="SET revoked = :t",
            ExpressionAttributeValues={":t": True},
            ConditionExpression="attribute_exists(sk)",
        )

    def set_upload_link_uploaded(self, event_id: str, link_id: str, *,
                                 size_bytes: int = 0, uploaded_at: str = "") -> None:
        """Stamp the slot as uploaded (S3 Object Created consumer)."""
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"UL#{link_id}"},
            UpdateExpression="SET uploaded = :t, sizeBytes = :s, uploadedAt = :at",
            ExpressionAttributeValues={":t": True, ":s": size_bytes, ":at": uploaded_at},
            ConditionExpression="attribute_exists(sk)",
        )

    def set_upload_link_scan_state(self, event_id: str, link_id: str, scan_state: str) -> None:
        """Record the GuardDuty verdict on an external-upload slot — the scan
        gate for promoting external uploads to the Content Library."""
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"UL#{link_id}"},
            UpdateExpression="SET scanState = :s",
            ExpressionAttributeValues={":s": scan_state},
            ConditionExpression="attribute_exists(sk)",
        )

    def delete_upload_link(self, event_id: str, link_id: str) -> None:
        """Hard-delete the upload-link slot."""
        self._t.delete_item(Key={"pk": f"EVENT#{event_id}", "sk": f"UL#{link_id}"})

    def bump_upload_count(self, event_id: str, link_id: str) -> None:
        self._t.update_item(
            Key={"pk": f"EVENT#{event_id}", "sk": f"UL#{link_id}"},
            UpdateExpression="SET uploadCount = if_not_exists(uploadCount, :z) + :one",
            ExpressionAttributeValues={":one": 1, ":z": 0},
            ConditionExpression="attribute_exists(sk)",
        )

    def put_token_pointer(self, token_hash: str, *, link_id: str, event_id: str) -> None:
        """O(1) token -> link lookup. A pointer item rather than a fifth index:
        DynamoDB allows one index change per UpdateTable, and a token must never
        be found by scanning."""
        self._t.put_item(Item={
            "pk": f"ULTOKEN#{token_hash}", "sk": "META",
            "linkId": link_id, "eventId": event_id,
        })

    def get_token_pointer(self, token_hash: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"ULTOKEN#{token_hash}", "sk": "META"})
        return resp.get("Item")

    # ---------------------------------------------------------- uploaded files

    def put_uploaded_file(self, record: dict) -> None:
        item = dict(record)
        item["pk"] = f"EVENT#{record['eventId']}"
        item["sk"] = f"UF#{record['uploadLinkId']}#{record['name']}"
        self._t.put_item(Item=item)

    def list_uploaded_files(self, event_id: str, link_id: str) -> list[dict]:
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with(f"UF#{link_id}#"))
        return resp.get("Items", [])

    # ------------------------------------------------------------ teams batch

    def put_teams_batch(self, batch: dict) -> dict:
        item = {k: v for k, v in batch.items() if v is not None}
        item["pk"] = f"EVENT#{batch['eventId']}"
        item["sk"] = f"TEAMS#{batch['fetchedAt']}"
        # `appliedAt` must be ABSENT, not null. DynamoDB stores None as the NULL
        # type, and `attribute_exists(appliedAt)` is TRUE for a NULL attribute —
        # so writing appliedAt=None would make the apply-once guard reject the
        # FIRST apply. Dropping None keys is what keeps that guard meaningful.
        self._t.put_item(Item=item)
        return batch

    def latest_teams_batch(self, event_id: str) -> dict | None:
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"EVENT#{event_id}")
            & Key("sk").begins_with("TEAMS#"),
            ScanIndexForward=False, Limit=1)
        items = resp.get("Items", [])
        return items[0] if items else None

    def mark_teams_batch_applied(self, event_id: str, fetched_at: str, at: str) -> bool:
        """Apply-once guard (BR-T5). False means it was already applied."""
        try:
            self._t.update_item(
                Key={"pk": f"EVENT#{event_id}", "sk": f"TEAMS#{fetched_at}"},
                UpdateExpression="SET appliedAt = :a",
                ExpressionAttributeValues={":a": at},
                ConditionExpression="attribute_exists(sk) AND attribute_not_exists(appliedAt)",
            )
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise


class EventIdeasRepository:
    """Separate DynamoDB table for event ideas (ideas table, not the events table).

    Key design:
      IDEA#<ideaId>          / META           -> idea record
      IDEA#<ideaId>          / VOTE#<userId>  -> vote marker

    GSI1 (feed by group AND status, most-voted first):
      gsi1pk = GROUP#<groupId>#<status>
      gsi1sk = <10-digit-padded-voteCount-desc>#<ideaId>
      The sort key is pre-inverted (9999999999 - voteCount), so the feed reads it
      ASCENDING to get most-voted-first. Reading it descending as well inverts
      twice and yields least-voted-first, which is what it used to do.

    STATUS IS PART OF THE PARTITION KEY (2026-08-27). It previously was not: the
    key was GROUP#<groupId>, only Open ideas carried it at all, and every other
    status had its keys REMOVEd on transition. The status filter was then applied
    in memory to rows read from that Open-only index — so the Greenlit, Declined
    and Archived tabs could never return a single row no matter how many such
    ideas existed. Folding status into the partition makes each tab an exact
    Query with no over-read, and matches the shape the events table in this same
    file already uses for its own listings (SCOPE#<scope>#<status>).

    The index is no longer sparse: every idea is indexed under its current
    status. Rows written under the old scheme needed a one-off backfill, which
    has been retired — every deployment from this point starts with an empty
    table, so all ideas are written with the status-qualified key from creation.
    """

    def __init__(self, table):
        self._t = table

    @staticmethod
    def _gsi1pk(group_id: str, status: str) -> str:
        return f"GROUP#{group_id}#{status}"

    def put_idea(self, record: dict) -> None:
        """Write a new idea (always Open)."""
        sid = record["ideaId"]
        item = {k: v for k, v in record.items() if v is not None and v != ""}
        item["pk"] = f"IDEA#{sid}"
        item["sk"] = "META"
        # Indexed under its status, so the per-status tabs are exact queries.
        item["gsi1pk"] = self._gsi1pk(record["groupId"], item.get("status", "Open"))
        item["gsi1sk"] = self._gsi1sk(0, sid)
        self._t.put_item(Item=item)

    def get_idea(self, idea_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"IDEA#{idea_id}", "sk": "META"})
        return resp.get("Item")

    def delete_idea(self, idea_id: str) -> int:
        """Hard-delete an idea and every vote cast on it.

        Everything belonging to one idea shares the partition `IDEA#<id>` — the
        META record plus one VOTE#<userId> per voter — so the whole thing is a
        single Query and a batch delete. Deleting only META would orphan the vote
        markers: nothing else references them, so they would sit in the table
        forever and a re-used idea id (not generated today, but nothing prevents
        it) would inherit stale votes.

        The sparse GSI1 keys live on the META item, so they disappear with it —
        no separate index cleanup.
        """
        keys: list[dict] = []
        kwargs: dict = {"ProjectionExpression": "pk, sk"}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq(f"IDEA#{idea_id}"), **kwargs)
            keys.extend({"pk": i["pk"], "sk": i["sk"]} for i in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        if not keys:
            return 0
        with self._t.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key=key)
        return len(keys)

    def update_idea_status(self, idea_id: str, new_status: str, extra: dict) -> None:
        """Change status and MOVE the idea to that status's feed partition.

        Used to REMOVE the GSI keys instead, which is what made every non-Open tab
        permanently empty. Now the row is re-pointed at GROUP#<groupId>#<status>,
        so a greenlit idea is still readable — just under a different partition.

        The group is read from the item rather than passed in because callers only
        have the idea id; a status change never moves an idea between groups.
        """
        current = self.get_idea(idea_id)
        if not current:
            return
        group_id = current.get("groupId") or ""

        sets = {f"#{k}": v for k, v in extra.items() if v is not None}
        sets["#status"] = new_status

        names: dict = {}
        values: dict = {}
        set_parts: list[str] = []
        for i, (alias, val) in enumerate(sets.items()):
            names[alias] = alias[1:]
            values[f":v{i}"] = val
            set_parts.append(f"{alias} = :v{i}")

        # Re-point the feed key at the new status's partition. gsi1sk (the
        # vote-count sort key) is left alone — the vote count has not changed.
        names["#gsi1pk"] = "gsi1pk"
        values[":newpk"] = self._gsi1pk(group_id, new_status)
        set_parts.append("#gsi1pk = :newpk")

        self._t.update_item(
            Key={"pk": f"IDEA#{idea_id}", "sk": "META"},
            UpdateExpression="SET " + ", ".join(set_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def query_ideas_by_group(self, group_id: str, *, statuses: list[str],
                              limit: int = 20, cursor: str | None = None
                              ) -> tuple[list[dict], str | None]:
        """One group's feed, highest votes first.

        Status is in the partition key, so each requested status is its own exact
        Query — no reading Open rows and discarding them to find the Greenlit
        ones, which is what the previous in-memory filter did (and why it always
        found nothing).
        """
        return self._walk_partitions(
            [self._gsi1pk(group_id, s) for s in statuses], limit=limit, cursor=cursor)

    def query_ideas_by_groups(self, group_ids: list[str], *, statuses: list[str],
                              limit: int = 20, cursor: str | None = None
                              ) -> tuple[list[dict], str | None]:
        """Feed across SEVERAL groups (the Community Leader's "All groups" view).

        GSI1 is partitioned by group and status, so there is no single query that
        spans groups. Partitions are walked in a FIXED order and the cursor
        records which one it stopped in — the same shape as this file's
        `query_scope_page`, and the reason a Scan is not used here: this is an
        interactive read.

        ORDERING CAVEAT, stated plainly because it is visible in the UI: results
        are vote-sorted WITHIN each partition, which appear in sequence. This is
        not a global vote ranking across groups — producing one would mean reading
        every idea in every group before returning the first page.
        """
        partitions = [self._gsi1pk(gid, s) for s in statuses for gid in group_ids]
        return self._walk_partitions(partitions, limit=limit, cursor=cursor)

    def _walk_partitions(self, partitions: list[str], *, limit: int,
                         cursor: str | None) -> tuple[list[dict], str | None]:
        """Fetch-until-full walk over an ordered list of GSI1 partitions.

        Shared by the single-group and all-groups feeds: both are now
        multi-partition (one partition per status, times one per group), so a
        single walker keeps the cursor logic in one place instead of two that
        drift.
        """
        start_index = 0
        start_key: dict | None = None
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                start_index = int(decoded.pop("partitionIndex", 0))
                start_key = decoded or None
            except Exception as exc:  # noqa: BLE001
                log(_logger, 30, "malformed idea feed cursor — ignoring", error=str(exc))

        # Each match is carried with the partition it came from. The cursor pairs
        # a start key with a partition index, so those two must describe the SAME
        # row — using the loop's current index would be wrong whenever a page
        # boundary falls exactly on a partition transition (the last row of the
        # page belongs to the previous partition, and resuming the next partition
        # from that row's key silently skips it).
        matched: list[tuple[int, dict]] = []
        for index in range(start_index, len(partitions)):
            exclusive = start_key if index == start_index else None
            while True:
                kwargs: dict = {
                    "IndexName": "GSI1",
                    "KeyConditionExpression": Key("gsi1pk").eq(partitions[index]),
                    # ASCENDING, because gsi1sk is ALREADY descending-encoded
                    # (9999999999 - voteCount). Reading it descending inverted it
                    # a second time, so the feed documented as "highest votes
                    # first" was actually returning the least-voted idea at the
                    # top. Two inversions cancelling out is easy to miss because
                    # both halves look individually correct.
                    "ScanIndexForward": True,
                    "Limit": limit + 1,
                }
                if exclusive:
                    kwargs["ExclusiveStartKey"] = exclusive
                resp = self._t.query(**kwargs)
                for row in resp.get("Items", []):
                    # No status filter: the partition key IS the status, so every
                    # row here already matches.
                    matched.append((index, row))
                    if len(matched) > limit:
                        page = matched[:limit]
                        last_index, last_row = page[-1]
                        key = {a: last_row[a] for a in ("pk", "sk", "gsi1pk", "gsi1sk")
                               if a in last_row}
                        key["partitionIndex"] = str(last_index)
                        return [r for _, r in page], base64.urlsafe_b64encode(
                            json.dumps(key, sort_keys=True).encode()).decode()
                exclusive = resp.get("LastEvaluatedKey")
                if not exclusive:
                    break
        return [r for _, r in matched], None

    def toggle_idea_vote(self, idea_id: str, user_id: str) -> tuple[bool, int]:
        """Toggle vote. Returns (voted, new_count)."""
        from botocore.exceptions import ClientError
        from boto3.dynamodb.conditions import Attr as _Attr
        vote_key = {"pk": f"IDEA#{idea_id}", "sk": f"VOTE#{user_id}"}

        # Try to add (conditional: item must not exist)
        try:
            self._t.put_item(
                Item={**vote_key, "votedAt": _now_iso()},
                ConditionExpression=_Attr("pk").not_exists(),
            )
            # Increment and update GSI sort key
            resp = self._t.update_item(
                Key={"pk": f"IDEA#{idea_id}", "sk": "META"},
                UpdateExpression="ADD voteCount :d SET lastVoteAt = :now",
                ExpressionAttributeValues={":d": 1, ":now": _now_iso()},
                ReturnValues="ALL_NEW",
            )
            new_count = int(resp.get("Attributes", {}).get("voteCount", 1))
            self._update_gsi1_sort_key(idea_id, new_count)
            return True, new_count
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

        # Already voted — remove
        self._t.delete_item(Key=vote_key)
        resp = self._t.update_item(
            Key={"pk": f"IDEA#{idea_id}", "sk": "META"},
            UpdateExpression="ADD voteCount :d SET lastVoteAt = :now",
            ExpressionAttributeValues={":d": -1, ":now": _now_iso()},
            ReturnValues="ALL_NEW",
        )
        new_count = max(0, int(resp.get("Attributes", {}).get("voteCount", 0)))
        self._update_gsi1_sort_key(idea_id, new_count)
        return False, new_count

    def _update_gsi1_sort_key(self, idea_id: str, vote_count: int) -> None:
        """Keep the feed sort key in sync with the current vote count. Only the
        sort key moves — a vote never changes an idea's status, so its partition
        is unaffected."""
        self._t.update_item(
            Key={"pk": f"IDEA#{idea_id}", "sk": "META"},
            UpdateExpression="SET gsi1sk = :sk",
            ExpressionAttributeValues={":sk": self._gsi1sk(vote_count, idea_id)},
        )

    def archive_stale_ideas(self, cutoff_iso: str) -> int:
        """Nightly sweep: archive Open ideas with lastVoteAt < cutoff."""
        # Scan the entire GSI1 across all groups looking for stale items.
        # This is acceptable for nightly batch — not on the hot path.
        from boto3.dynamodb.conditions import Attr as _Attr
        kwargs: dict = {
            "IndexName": "GSI1",
            "FilterExpression": _Attr("lastVoteAt").lt(cutoff_iso) &
                                _Attr("status").eq("Open"),
        }
        archived = 0
        while True:
            resp = self._t.scan(**kwargs)
            for item in resp.get("Items", []):
                sid = item.get("ideaId")
                if not sid:
                    continue
                try:
                    # Move to the Archived partition rather than un-indexing the
                    # row. Removing the keys is what made archived ideas
                    # unreachable; they are now readable under
                    # GROUP#<groupId>#Archived even though no tab offers it today.
                    self._t.update_item(
                        Key={"pk": f"IDEA#{sid}", "sk": "META"},
                        UpdateExpression="SET #s = :a, gsi1pk = :pk",
                        ExpressionAttributeNames={"#s": "status"},
                        ExpressionAttributeValues={
                            ":a": "Archived",
                            ":pk": self._gsi1pk(item.get("groupId") or "", "Archived"),
                        },
                    )
                    archived += 1
                except Exception as exc:  # noqa: BLE001
                    log(_logger, 30, "idea archive update failed — skipping", ideaId=sid, error=str(exc))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return archived

    @staticmethod
    def _gsi1sk(vote_count: int, idea_id: str) -> str:
        """Descending sort key: 9999999999 - voteCount padded to 10 digits."""
        desc = 9_999_999_999 - max(0, vote_count)
        return f"{desc:010d}#{idea_id}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
