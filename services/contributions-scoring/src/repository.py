"""Single-table DynamoDB access for Contributions & Scoring (Unit 7).

Item layout (one main table; DL15 single-table design):

  Ledger (append-only, truth):
    MEMBER#<memberId> / LEDGER#<earnedDate>#<ledgerId>   -> immutable entry
        GSI3 (group points, US-7.9): pk=GLEDGER#<groupId>#<quarter>,
                                     sk=<earnedDate>#<ledgerId>
        (group-scoped paging; shares the sparse GSI3 with submissions, which use
         a MEMBERSUB# namespace, so no extra index is needed)
        (member-scoped history + reverse-entry browser; group/quarter as attrs)

  Rollups (derived cache, Stream-maintained — DL15):
    ROLLUP#<memberId> / Q#<quarter>#<groupId>   -> L1: total + pillar1..4 (+name/avatar)
        GSI1 (leaderboard): pk=gsi1pk=LB#<groupId>#<quarter>, sk=`total` (Number)
        -> sparse: ONLY L1 items carry gsi1pk, so ADD-ing `total` re-sorts the
           leaderboard automatically (BR-R3). No separate index write.
    ROLLUP#<memberId> / LIFE#<groupId>          -> L1-life: lifetimeTotal
    GROUP#<groupId>   / Q#<quarter>             -> L2: total + pillar1..4
    COMMUNITY         / Q#<quarter>             -> L3: total + pillar1..4

  Exactly-once guard (Q2=A′): GUARD#<ledgerId> / META, put conditionally IN THE
  SAME TransactWriteItems as the increments -> a redelivered Stream record fails
  the condition and the whole transaction is rejected (no drift, no crash window).

  Framework (single, community-wide):
    FRAMEWORK / ACT#<activityId>   -> activity type
    FRAMEWORK / EVTP#<eventType>   -> event points (attendance/delivery)
    FRAMEWORK / TIER#<tier>        -> tier threshold

  Submissions (evidence workflow):
    SUB#<submissionId> / META
        GSI2 (pending queue): pk=PENDINGQ (sparse, Pending only), sk=<submittedAt>#<id>
        GSI3 (my submissions): pk=MEMBERSUB#<memberId>, sk=<submittedAt>#<id>

  Reply award state (DL17 toggle): REPLY#<replyId> / META
  Membership projection (DL12/B3): MEMBERSHIP#<memberId> / GROUP#<groupId>  (+ /PROFILE)
  Sweep aggregates (DL14): SWEEP#<scope>#<scopeId> / Q#<quarter>

No Scans — every read is a Get or an index Query.
"""
from __future__ import annotations

import base64
import json

from _conventions.errors import ConflictError, ValidationError
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from models import PILLARS, epoch, now_iso

# Internal key attrs stripped from returned items. `total` is NOT here — it is
# the GSI1 sort key AND the real rollup value, so it must survive stripping.
_CURSOR_ATTRS = ("pk", "sk", "gsi1pk", "gsi2pk", "gsi2sk", "gsi3pk", "gsi3sk")
# The pending-approvals cursor is a GSI2 ExclusiveStartKey: base-table key + the
# GSI2 key ONLY. A submission row also carries gsi3pk/gsi3sk (my-submissions
# index, set in put_submission), and DynamoDB rejects a start key carrying stray
# attributes from another index. Mirrors the certifications verification queue.
_PENDING_CURSOR_ATTRS = ("pk", "sk", "gsi2pk", "gsi2sk")


def _strip(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in _CURSOR_ATTRS}


def encode_cursor(key: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(key, sort_keys=True).encode()).decode()


def decode_cursor(cursor: str) -> dict:
    """Opaque page cursor. Only index/table key attributes may appear, so a
    crafted cursor cannot name another field; malformed input is a client error
    (400) rather than an unhandled 500. Same contract as the other services."""
    try:
        key = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        if not isinstance(key, dict) or not key or not set(key) <= set(_CURSOR_ATTRS):
            raise ValueError("bad cursor shape")
        return key
    except (ValueError, TypeError, json.JSONDecodeError):
        raise ValidationError("Invalid pagination cursor.") from None


class ContributionsRepository:
    def __init__(self, table):
        self._t = table

    # ============================================================== ledger

    def append_ledger(self, entry: dict) -> dict:
        """Append one immutable ledger entry. Idempotency for auto awards is
        enforced upstream by the IdempotencyStore (award worker) / the rollup
        guard (maintainer); this is a plain put of an append-only row.

        The row is also placed on the GROUP-scoped index so a leader can page
        through one group's points for a quarter. The ledger's own partition is
        per MEMBER, so without this a group view would have to fan out over every
        member — 13,000+ queries for one screen.

        GSI3 is reused rather than a new index added: it is sparse and already
        carries submissions under `MEMBERSUB#...`, so a distinct `GLEDGER#...`
        namespace shares it without any table change or collision.
        """
        item = {k: v for k, v in entry.items() if v is not None}
        item["pk"] = f"MEMBER#{entry['memberId']}"
        item["sk"] = f"LEDGER#{entry['earnedDate']}#{entry['ledgerId']}"
        group_id, quarter = entry.get("groupId"), entry.get("quarter")
        if group_id and quarter:
            item["gsi3pk"] = f"GLEDGER#{group_id}#{quarter}"
            item["gsi3sk"] = f"{entry['earnedDate']}#{entry['ledgerId']}"
        self._t.put_item(Item=item)
        return entry

    def query_group_ledger_page(self, group_id: str, quarter: str, *,
                                limit: int = 25, cursor: str | None = None,
                                ) -> tuple[list[dict], str | None]:
        """One page of a group's ledger entries for a quarter, NEWEST FIRST.

        Cursor-paginated because this table is the 13k+ scale case: the screen
        never reads more than `limit` rows, and the opaque cursor is the index
        key of the last row returned.
        """
        kwargs: dict = {
            "IndexName": "GSI3",
            "KeyConditionExpression": Key("gsi3pk").eq(f"GLEDGER#{group_id}#{quarter}"),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if cursor:
            start = decode_cursor(cursor)
            if start:
                kwargs["ExclusiveStartKey"] = start
        resp = self._t.query(**kwargs)
        rows = [_strip(i) for i in resp.get("Items", [])]
        last = resp.get("LastEvaluatedKey")
        return rows, (encode_cursor(last) if last else None)

    def query_group_ledger_filtered_page(self, group_id: str, quarter: str, *,
                                         limit: int = 25, cursor: str | None = None,
                                         predicate=None,
                                         ) -> tuple[list[dict], str | None]:
        """One page of a group's ledger for a quarter (newest first) with an
        optional in-loop predicate (Point Ledger member/source/activity filters,
        US-7.9).

        Fetch-until-full: keep reading index pages within the SAME group+quarter
        partition, applying `predicate`, until `limit` MATCHING rows are gathered
        or the partition is exhausted — so a filtered page is still a full page
        and the returned cursor is the underlying index position, not the last
        matching row. Same pattern as the Member Directory / Admin Users tables.
        Still one bounded partition; never a Scan.
        """
        if predicate is None:
            return self.query_group_ledger_page(group_id, quarter, limit=limit, cursor=cursor)
        matched: list[dict] = []
        start = decode_cursor(cursor) if cursor else None
        while True:
            kwargs: dict = {
                "IndexName": "GSI3",
                "KeyConditionExpression": Key("gsi3pk").eq(f"GLEDGER#{group_id}#{quarter}"),
                "ScanIndexForward": False,
                # Read a little ahead so a highly-selective filter still fills a
                # page without one round-trip per row; never unbounded.
                "Limit": max(limit * 4, limit + 10),
            }
            if start:
                kwargs["ExclusiveStartKey"] = start
            resp = self._t.query(**kwargs)
            for item in resp.get("Items", []):
                if predicate(item):
                    matched.append(_strip(item))
                    if len(matched) >= limit:
                        # Cursor = this row's own index key, so the next page
                        # resumes right after it (not after the read-ahead block).
                        nxt = {k: item[k] for k in ("gsi3pk", "gsi3sk", "pk", "sk") if k in item}
                        return matched, encode_cursor(nxt)
            start = resp.get("LastEvaluatedKey")
            if not start:
                return matched, None

    def get_ledger_entry(self, member_id: str, earned_date: str, ledger_id: str) -> dict | None:
        resp = self._t.get_item(
            Key={"pk": f"MEMBER#{member_id}", "sk": f"LEDGER#{earned_date}#{ledger_id}"})
        item = resp.get("Item")
        return _strip(item) if item else None

    def list_member_ledger(self, member_id: str, *, group_id: str | None = None,
                           quarter: str | None = None) -> list[dict]:
        """Member-scoped ledger read (history + reverse browser). Bounded by one
        member's own entries; optional group/quarter filter in the loop."""
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq(f"MEMBER#{member_id}")
                & Key("sk").begins_with("LEDGER#"),
                ScanIndexForward=False, **kwargs)
            for row in resp.get("Items", []):
                if group_id and row.get("groupId") != group_id:
                    continue
                if quarter and row.get("quarter") != quarter:
                    continue
                items.append(_strip(row))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def reversal_exists(self, ledger_id: str) -> bool:
        """Single-use reverse guard (BR-J2): a reversal entry is keyed rev-<id>."""
        resp = self._t.get_item(Key={"pk": f"GUARD#reverse#{ledger_id}", "sk": "META"})
        return "Item" in resp

    def mark_reversed(self, ledger_id: str) -> bool:
        try:
            self._t.put_item(
                Item={"pk": f"GUARD#reverse#{ledger_id}", "sk": "META", "at": now_iso()},
                ConditionExpression="attribute_not_exists(pk)")
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    # ============================================================== rollups (Stream maintainer)

    def apply_to_rollups(self, entry: dict) -> bool:
        """Exactly-once rollup increment (Q2=A′). Guard + L1 + L1-life + L2 + L3
        in ONE TransactWriteItems. Returns False if the ledgerId was already
        applied (guard condition failed) — the maintainer treats that as a
        no-op skip. `total` is the GSI1 sort key, so the ADD re-sorts the
        leaderboard with no extra write."""
        member_id = entry["memberId"]
        group_id = entry["groupId"]
        quarter = entry["quarter"]
        delta = int(entry["points"])
        pillar = int(entry.get("pillar") or 0)
        ledger_id = entry["ledgerId"]
        pillar_attr = f"pillar{pillar}" if pillar in PILLARS else None
        name = entry.get("memberName") or ""
        avatar = entry.get("avatar") or ""

        tname = self._t.name
        pillar_add = f", {pillar_attr} :d" if pillar_attr else ""

        items = [
            {"Put": {"TableName": tname,
                     "Item": {"pk": f"GUARD#applied#{ledger_id}", "sk": "META"},
                     "ConditionExpression": "attribute_not_exists(pk)"}},
            # L1 — total is the GSI1 sort key (leaderboard); set gsi1pk + name/avatar
            {"Update": {"TableName": tname,
                        "Key": {"pk": f"ROLLUP#{member_id}", "sk": f"Q#{quarter}#{group_id}"},
                        "UpdateExpression": (f"ADD #total :d{pillar_add} "
                                             "SET gsi1pk = :lb, memberName = :n, avatar = :a, "
                                             "groupId = :g, quarter = :q, memberId = :m"),
                        "ExpressionAttributeNames": {"#total": "total"},
                        "ExpressionAttributeValues": {
                            ":d": delta, ":lb": f"LB#{group_id}#{quarter}",
                            ":n": name, ":a": avatar, ":g": group_id,
                            ":q": quarter, ":m": member_id}}},
            # L1-life
            {"Update": {"TableName": tname,
                        "Key": {"pk": f"ROLLUP#{member_id}", "sk": f"LIFE#{group_id}"},
                        "UpdateExpression": "ADD lifetimeTotal :d",
                        "ExpressionAttributeValues": {":d": delta}}},
            # L2 group
            {"Update": {"TableName": tname,
                        "Key": {"pk": f"GROUP#{group_id}", "sk": f"Q#{quarter}"},
                        "UpdateExpression": f"ADD #total :d{pillar_add}",
                        "ExpressionAttributeNames": {"#total": "total"},
                        "ExpressionAttributeValues": {":d": delta}}},
            # L3 community
            {"Update": {"TableName": tname,
                        "Key": {"pk": "COMMUNITY", "sk": f"Q#{quarter}"},
                        "UpdateExpression": f"ADD #total :d{pillar_add}",
                        "ExpressionAttributeNames": {"#total": "total"},
                        "ExpressionAttributeValues": {":d": delta}}},
        ]
        try:
            self._t.meta.client.transact_write_items(TransactItems=items)
            return True
        except ClientError as err:
            if "TransactionCanceled" in str(err.response["Error"].get("Code", "")):
                return False  # already applied (guard) — idempotent skip
            raise

    def get_l1(self, member_id: str, quarter: str, group_id: str) -> dict | None:
        resp = self._t.get_item(
            Key={"pk": f"ROLLUP#{member_id}", "sk": f"Q#{quarter}#{group_id}"})
        item = resp.get("Item")
        return _strip(item) if item else None

    def batch_get_l1(self, member_ids: list[str], quarter: str,
                     group_id: str) -> list[dict]:
        """L1 rollups for a SET of members in one group+quarter (BatchGetItem).

        Hydrates the visible page of a member table: O(page size) point/tier
        lookups regardless of group size — no top-N leaderboard scan. Members
        with no rollup (earned nothing this quarter) are simply absent from the
        result and render as '—'. DynamoDB caps a batch at 100 keys and may
        return UnprocessedKeys under throttling, so we chunk and retry those.
        """
        ids = [m for m in dict.fromkeys(member_ids) if m]  # de-dupe, drop blanks
        if not ids:
            return []
        client = self._t.meta.client
        tname = self._t.name
        out: list[dict] = []
        for i in range(0, len(ids), 100):
            keys = [{"pk": f"ROLLUP#{mid}", "sk": f"Q#{quarter}#{group_id}"}
                    for mid in ids[i:i + 100]]
            request = {tname: {"Keys": keys}}
            for _ in range(5):  # bounded UnprocessedKeys retries
                resp = client.batch_get_item(RequestItems=request)
                out.extend(resp.get("Responses", {}).get(tname, []))
                request = resp.get("UnprocessedKeys") or {}
                if not request:
                    break
        return [_strip(item) for item in out]

    def get_lifetime(self, member_id: str, group_id: str) -> int:
        resp = self._t.get_item(Key={"pk": f"ROLLUP#{member_id}", "sk": f"LIFE#{group_id}"})
        return int((resp.get("Item") or {}).get("lifetimeTotal", 0))

    def get_group_rollup(self, group_id: str, quarter: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"GROUP#{group_id}", "sk": f"Q#{quarter}"})
        item = resp.get("Item")
        return _strip(item) if item else None

    def get_community_rollup(self, quarter: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": "COMMUNITY", "sk": f"Q#{quarter}"})
        item = resp.get("Item")
        return _strip(item) if item else None

    def count_active_members(self, group_id: str, quarter: str) -> int:
        """How many members hold a rollup for this group+quarter, i.e. earned at
        least one point in it (US-7.3 "active members").

        `Select=COUNT` makes DynamoDB return the count WITHOUT transferring the
        item payloads, so a 4-quarter trend costs four cheap queries instead of
        reading every member's row. The trade-off is that the deactivated-member
        filter (B3) cannot be applied without item data — acceptable for a
        historical trend line, where a member who was active in a past quarter
        genuinely was active then.
        """
        total, kwargs = 0, {}
        while True:
            resp = self._t.query(
                IndexName="GSI1",
                KeyConditionExpression=Key("gsi1pk").eq(f"LB#{group_id}#{quarter}"),
                Select="COUNT", **kwargs)
            total += int(resp.get("Count", 0))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                return total

    def list_group_rollups(self, group_id: str, quarter: str) -> list[dict]:
        """Every member rollup for a group+quarter (tier distribution).

        ONE query per quarter. The leaderboard path deliberately is not reused
        here: it issues a profile GetItem PER ROW for the active-member filter,
        which turns a distribution over a 400-member group into 400 extra reads.
        """
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                IndexName="GSI1",
                KeyConditionExpression=Key("gsi1pk").eq(f"LB#{group_id}#{quarter}"),
                **kwargs)
            items.extend(_strip(i) for i in resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                return items

    def leaderboard_page(self, group_id: str, quarter: str, *, limit: int = 10,
                         buffer: int = 3) -> list[dict]:
        """Top-N by points via GSI1 (sort key = total, descending). Reads
        limit+buffer so the B3 filter (drop left/deactivated) can be applied at
        read without under-filling the page."""
        resp = self._t.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"LB#{group_id}#{quarter}"),
            ScanIndexForward=False, Limit=limit + buffer)
        return [_strip(i) for i in resp.get("Items", [])]

    # ============================================================== framework

    def put_framework_item(self, sk: str, item: dict) -> None:
        row = {k: v for k, v in item.items() if v is not None}
        row["pk"] = "FRAMEWORK"
        row["sk"] = sk
        self._t.put_item(Item=row)

    def get_framework_item(self, sk: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": "FRAMEWORK", "sk": sk})
        item = resp.get("Item")
        return _strip(item) if item else None

    def list_framework(self, prefix: str) -> list[dict]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq("FRAMEWORK") & Key("sk").begins_with(prefix),
                **kwargs)
            items.extend(_strip(i) for i in resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def update_framework_item(self, sk: str, sets: dict) -> None:
        parts, names, values = [], {}, {}
        for i, (field, value) in enumerate(sets.items()):
            parts.append(f"#f{i} = :v{i}")
            names[f"#f{i}"] = field
            values[f":v{i}"] = value
        self._t.update_item(
            Key={"pk": "FRAMEWORK", "sk": sk},
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeNames=names, ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(sk)")

    def delete_framework_item(self, sk: str) -> None:
        self._t.delete_item(Key={"pk": "FRAMEWORK", "sk": sk})

    # ============================================================== submissions

    def put_submission(self, sub: dict) -> dict:
        item = {k: v for k, v in sub.items() if v is not None}
        item["pk"] = f"SUB#{sub['submissionId']}"
        item["sk"] = "META"
        # pending queue (sparse) + my-submissions indexes
        item["gsi2pk"] = "PENDINGQ"
        item["gsi2sk"] = f"{sub['submittedAt']}#{sub['submissionId']}"
        item["gsi3pk"] = f"MEMBERSUB#{sub['memberId']}"
        item["gsi3sk"] = f"{sub['submittedAt']}#{sub['submissionId']}"
        self._t.put_item(Item=item)
        return sub

    def get_submission(self, submission_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"SUB#{submission_id}", "sk": "META"})
        item = resp.get("Item")
        return _strip(item) if item else None

    def list_member_submissions(self, member_id: str) -> list[dict]:
        resp = self._t.query(
            IndexName="GSI3",
            KeyConditionExpression=Key("gsi3pk").eq(f"MEMBERSUB#{member_id}"),
            ScanIndexForward=False)
        return [_strip(i) for i in resp.get("Items", [])]

    def query_pending(self, *, predicate=None, limit: int | None = None) -> list[dict]:
        """Pending queue as a query (BR-E6): one sparse partition, oldest-first
        by submittedAt. Leader-change reassignment is implicit — routing is by
        groupId in the predicate, nothing stored per-leader.

        UNBOUNDED by default. This used to default to `limit=500` and return the
        moment it had 500 matches, which silently truncated every caller: the
        leader approval queue could not reach submission 501+ at all (a real
        outage once a load test left >500 pending), and the US-6.1 activity
        cascade below would have skipped submissions it was supposed to sweep.
        The queue now uses `query_pending_page`; this method is for callers that
        genuinely need the whole set. Pass `limit` only to cap deliberately.
        """
        matched, kwargs = [], {}
        while True:
            resp = self._t.query(
                IndexName="GSI2", KeyConditionExpression=Key("gsi2pk").eq("PENDINGQ"),
                ScanIndexForward=True, **kwargs)
            for row in resp.get("Items", []):
                if predicate is None or predicate(row):
                    matched.append(_strip(row))
                    if limit is not None and len(matched) >= limit:
                        return matched
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return matched

    def query_pending_page(self, *, limit: int = 25, cursor: str | None = None,
                           predicate=None) -> tuple[list[dict], str | None]:
        """One page of the leader approval queue (US-6.8): the sparse PENDINGQ
        partition, submittedAt-ascending so oldest-first IS the index order and
        no sort step is needed. `predicate` applies scope/filters inside a
        fetch-until-full read loop, so a page never comes back short while more
        matches exist. Returns (rows, next_cursor); next_cursor is None on the
        last page.

        Replaces the old unpaginated read whose 500-row cap made anything past
        the 500th-oldest pending submission permanently unapprovable. Mirrors
        the certifications verification queue.
        """
        matched: list[dict] = []
        kwargs: dict = {}
        if cursor:
            kwargs["ExclusiveStartKey"] = decode_cursor(cursor)
        while True:
            resp = self._t.query(
                IndexName="GSI2", KeyConditionExpression=Key("gsi2pk").eq("PENDINGQ"),
                ScanIndexForward=True, **kwargs)
            for row in resp.get("Items", []):
                if predicate is None or predicate(row):
                    matched.append(row)
                    # One past the page proves there IS a next page; slice it off
                    # and build the cursor from the last row actually returned, so
                    # the next page resumes after what the reviewer saw rather
                    # than after the read-ahead block.
                    if len(matched) > limit:
                        page = matched[:limit]
                        nxt = encode_cursor(
                            {k: page[-1][k] for k in _PENDING_CURSOR_ATTRS if k in page[-1]})
                        return [_strip(i) for i in page], nxt
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break  # partition exhausted — last page
        return [_strip(i) for i in matched], None

    def count_pending(self, *, predicate=None) -> int:
        """TRUE total of pending matches, for the nav badge and the leader
        dashboard KPI (countOnly). Walks the sparse PENDINGQ partition counting
        only — no rows materialized, no page cap.

        Previously the count was `len()` of the capped 500-row read, so a backlog
        of any size reported exactly "500" and a leader could not see how much
        work was actually waiting.
        """
        total = 0
        kwargs: dict = {}
        while True:
            resp = self._t.query(
                IndexName="GSI2", KeyConditionExpression=Key("gsi2pk").eq("PENDINGQ"),
                ScanIndexForward=True, **kwargs)
            for row in resp.get("Items", []):
                if predicate is None or predicate(row):
                    total += 1
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return total

    def list_pending_for_activity(self, activity_id: str) -> list[dict]:
        """Pending submissions for one activity (US-6.1 deactivate/delete cascade).
        Rides the sparse PENDINGQ partition and filters by activityId in the loop.
        Deliberately unbounded — a cascade that stops after N rows leaves
        submissions pointing at a deleted activity."""
        return self.query_pending(predicate=lambda r: r.get("activityId") == activity_id)

    def transition_submission(self, submission_id: str, *, expected: str, new_status: str,
                              extra: dict | None = None) -> None:
        """Status change conditional on current state (409 on race). Leaves the
        pending queue (REMOVE gsi2*) on any terminal transition."""
        set_parts = ["#st = :new"]
        names = {"#st": "status"}
        values = {":new": new_status, ":expected": expected}
        for i, (field, value) in enumerate((extra or {}).items()):
            set_parts.append(f"#e{i} = :e{i}")
            names[f"#e{i}"] = field
            values[f":e{i}"] = value
        expr = "SET " + ", ".join(set_parts) + " REMOVE gsi2pk, gsi2sk"
        try:
            self._t.update_item(
                Key={"pk": f"SUB#{submission_id}", "sk": "META"},
                UpdateExpression=expr, ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression="attribute_exists(pk) AND #st = :expected")
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ConflictError(message="The submission is not in the required state.") from None
            raise

    # ============================================================== reply award state (DL17)

    def get_reply_state(self, reply_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"REPLY#{reply_id}", "sk": "META"})
        item = resp.get("Item")
        return _strip(item) if item else None

    def set_reply_awarded(self, reply_id: str, awarded: bool, meta: dict) -> bool:
        """Toggle guard: only flips when the awarded flag actually changes, so a
        redelivered accept/un-accept is a no-op (BR-P7)."""
        try:
            item = {k: v for k, v in meta.items() if v is not None}
            item.update({"pk": f"REPLY#{reply_id}", "sk": "META", "awarded": awarded})
            self._t.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) OR awarded <> :aw",
                ExpressionAttributeValues={":aw": awarded})
            return True
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    # ============================================================== membership projection (DL12/B3)

    def upsert_membership(self, member_id: str, group_id: str, *, joined_at: str,
                          active: bool = True) -> None:
        self._t.put_item(Item={
            "pk": f"MEMBERSHIP#{member_id}", "sk": f"GROUP#{group_id}",
            "groupId": group_id, "joinedAt": joined_at, "active": active})

    def remove_membership(self, member_id: str, group_id: str) -> None:
        self._t.delete_item(Key={"pk": f"MEMBERSHIP#{member_id}", "sk": f"GROUP#{group_id}"})

    def list_member_groups(self, member_id: str) -> list[dict]:
        """Current groups + join dates for the community-wide split (BR-S1/S2)."""
        resp = self._t.query(
            KeyConditionExpression=Key("pk").eq(f"MEMBERSHIP#{member_id}")
            & Key("sk").begins_with("GROUP#"))
        return [_strip(i) for i in resp.get("Items", [])]

    # ---- group registry (sweep + community export need the group set) --------

    def register_group(self, group_id: str) -> None:
        """Idempotent record that a group exists (populated from membership/group
        events). Lets the nightly sweep and the community export enumerate groups
        without a table scan."""
        if not group_id:
            return
        self._t.put_item(Item={"pk": "REGISTRY", "sk": f"GROUP#{group_id}", "groupId": group_id})

    def list_registered_groups(self) -> list[str]:
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                KeyConditionExpression=Key("pk").eq("REGISTRY") & Key("sk").begins_with("GROUP#"),
                **kwargs)
            items.extend(i["groupId"] for i in resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    def upsert_member_profile(self, member_id: str, *, name: str | None = None,
                              avatar: str | None = None, email: str | None = None,
                              active: bool | None = None, role: str | None = None) -> None:
        sets = {k: v for k, v in (("memberName", name), ("avatar", avatar),
                                  ("email", email), ("active", active),
                                  ("role", role)) if v is not None}
        if not sets:
            return
        parts, names, values = [], {}, {}
        for i, (field, value) in enumerate(sets.items()):
            parts.append(f"#f{i} = :v{i}")
            names[f"#f{i}"] = field
            values[f":v{i}"] = value
        self._t.update_item(
            Key={"pk": f"MEMBERSHIP#{member_id}", "sk": "PROFILE"},
            UpdateExpression="SET " + ", ".join(parts),
            ExpressionAttributeNames=names, ExpressionAttributeValues=values)

    def get_member_profile(self, member_id: str) -> dict:
        resp = self._t.get_item(Key={"pk": f"MEMBERSHIP#{member_id}", "sk": "PROFILE"})
        return _strip(resp.get("Item") or {})

    # ============================================================== sweep aggregates (DL14)

    def put_sweep(self, scope: str, scope_id: str, quarter: str, data: dict) -> None:
        item = {k: v for k, v in data.items() if v is not None}
        item.update({"pk": f"SWEEP#{scope}#{scope_id}", "sk": f"Q#{quarter}"})
        self._t.put_item(Item=item)

    def get_sweep(self, scope: str, scope_id: str, quarter: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"SWEEP#{scope}#{scope_id}", "sk": f"Q#{quarter}"})
        item = resp.get("Item")
        return _strip(item) if item else None

    def list_group_l1(self, group_id: str, quarter: str) -> list[dict]:
        """All members' L1 rollups for a group+quarter (nightly sweep input).
        Uses the leaderboard GSI partition — bounded to one group+quarter."""
        items, kwargs = [], {}
        while True:
            resp = self._t.query(
                IndexName="GSI1",
                KeyConditionExpression=Key("gsi1pk").eq(f"LB#{group_id}#{quarter}"), **kwargs)
            items.extend(_strip(i) for i in resp.get("Items", []))
            if "LastEvaluatedKey" in resp:
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            else:
                break
        return items

    # ---------- CSV export jobs (TTL) ----------
    # Short-lived job records for the async Point Ledger CSV export. Ported from
    # identity-access, which introduced this pattern for Admin > Users; the four
    # methods are table-agnostic and the two services must behave identically or
    # the shared frontend hook would need to know which one it is talking to.
    #
    # Dual expiry on purpose: `ttl` lets DynamoDB reclaim the row, and
    # `expiresAt` is re-checked in code because TTL deletion is asynchronous and
    # can lag by hours.

    def put_export_job(self, job: dict) -> dict:
        item = dict(job)
        item["pk"] = f"EXPORT#{job['jobId']}"
        item["sk"] = "JOB"
        self._t.put_item(Item=item)
        return job

    def get_export_job(self, job_id: str) -> dict | None:
        resp = self._t.get_item(Key={"pk": f"EXPORT#{job_id}", "sk": "JOB"})
        item = resp.get("Item")
        if item and int(item.get("expiresAt", 0)) < epoch():
            return None
        return item

    def acquire_export_lock(self, actor: str, job_id: str, *, ttl_seconds: int) -> bool:
        """Atomically claim the one in-flight export slot for `actor`.

        Returns False when that leader already has an export running. A
        conditional write rather than read-then-write so two rapid clicks cannot
        both pass.

        Self-healing: the condition also succeeds once the existing lock is past
        `expiresAt`, so a worker that dies without releasing blocks retries for at
        most `ttl_seconds` rather than forever.
        """
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

    def update_export_job(self, job_id: str, fields: dict) -> None:
        """Targeted attribute update.

        An UpdateExpression rather than read-merge-put: the worker writes
        `processed` repeatedly while the API may be reading the same row, and a
        full-item put would race and could resurrect stale attributes.
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
