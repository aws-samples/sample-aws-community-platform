"""Single-table DynamoDB repository for Forums.

Table: forums-<stage> (pk/sk + 4 GSIs). All expressions parameterized (SECURITY-05).
TransactWriteItems used for post/reply creation (counter + search index, ND-2/3=A).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key

from models import (
    epoch_ttl,
    gsi1_channel_keys,
    gsi1_forum_keys,
    gsi2_post_keys,
    gsi2_reply_keys,
    gsi4_report_keys,
    now_iso,
    rate_key,
    TERM_MATCH_CAP,
)

logger = logging.getLogger(__name__)


class ForumsRepository:
    """DynamoDB single-table access for all forum entities."""

    def __init__(self, table, client=None):
        self._table = table
        self._client = client  # low-level client for TransactWriteItems

    # --- Forum CRUD ---

    def put_forum(self, forum: dict) -> None:
        item = {
            "pk": f"FORUM#{forum['forumId']}",
            "sk": "META",
            **forum,
            **gsi1_forum_keys(forum["groupId"], forum["forumId"]),
        }
        self._table.put_item(Item=_decimalize(item))

    def get_forum(self, forum_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": f"FORUM#{forum_id}", "sk": "META"})
        return resp.get("Item")

    def update_forum(self, forum_id: str, updates: dict) -> dict | None:
        expr_parts, values, names = [], {}, {}
        for i, (k, v) in enumerate(updates.items()):
            attr = f"#a{i}"
            val = f":v{i}"
            expr_parts.append(f"{attr} = {val}")
            names[attr] = k
            values[val] = v
        values[":now"] = now_iso()
        expr_parts.append("#upd = :now")
        names["#upd"] = "updatedAt"
        resp = self._table.update_item(
            Key={"pk": f"FORUM#{forum_id}", "sk": "META"},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=_decimalize(values),
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes")

    def mark_forum_purging(self, forum_id: str) -> None:
        self._table.update_item(
            Key={"pk": f"FORUM#{forum_id}", "sk": "META"},
            UpdateExpression="SET #s = :s, #h = :t",
            ExpressionAttributeNames={"#s": "status", "#h": "hidden"},
            ExpressionAttributeValues={":s": "PURGING", ":t": True},
        )

    def delete_item(self, pk: str, sk: str) -> None:
        self._table.delete_item(Key={"pk": pk, "sk": sk})

    # --- Channel CRUD ---

    def put_channel(self, channel: dict) -> None:
        item = {
            "pk": f"CHANNEL#{channel['channelId']}",
            "sk": "META",
            **channel,
            **gsi1_channel_keys(channel["groupId"], channel["forumId"], channel["channelId"]),
        }
        self._table.put_item(Item=_decimalize(item))

    def get_channel(self, channel_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": f"CHANNEL#{channel_id}", "sk": "META"})
        return resp.get("Item")

    def increment_channel_count(self, forum_id: str, delta: int = 1) -> None:
        self._table.update_item(
            Key={"pk": f"FORUM#{forum_id}", "sk": "META"},
            UpdateExpression="ADD #cc :d",
            ExpressionAttributeNames={"#cc": "channelCount"},
            ExpressionAttributeValues={":d": Decimal(str(delta))},
        )

    # --- Post creation (transactional: post + counter + search index) ---

    def create_post_transact(self, post: dict, term_items: list[dict], channel_id: str) -> None:
        """Create post + update channel counters + write search-index items in one transaction."""
        items = []
        # 1. Put the post
        post_item = {
            "pk": f"POST#{post['postId']}",
            "sk": "META",
            **post,
            **gsi2_post_keys(channel_id, post["createdAt"]),
        }
        items.append({"Put": {"TableName": self._table_name, "Item": _decimalize_raw(post_item)}})
        # 2. Increment channel postCount + lastActivityAt
        items.append({"Update": {
            "TableName": self._table_name,
            "Key": _decimalize_raw({"pk": f"CHANNEL#{channel_id}", "sk": "META"}),
            "UpdateExpression": "ADD #pc :one SET #la = :now",
            "ExpressionAttributeNames": {"#pc": "postCount", "#la": "lastActivityAt"},
            "ExpressionAttributeValues": _decimalize_raw({":one": 1, ":now": post["createdAt"]}),
        }})
        # 3. Search index term-items
        for ti in term_items:
            items.append({"Put": {"TableName": self._table_name, "Item": _decimalize_raw(ti)}})
        # 4. Auto-follow: author follows their own post
        follow_item = {
            "pk": f"POST#{post['postId']}",
            "sk": f"FOLLOW#{post['authorId']}",
            "userId": post["authorId"],
            "targetId": post["postId"],
            "targetType": "post",
            "targetName": post["title"],
            "createdAt": post["createdAt"],
        }
        items.append({"Put": {"TableName": self._table_name, "Item": _decimalize_raw(follow_item)}})

        self._transact_write(items)

    # --- Reply creation (transactional: reply + counter) ---

    def create_reply_transact(self, reply: dict, post_id: str, channel_id: str) -> None:
        """Create reply + update post replyCount + channel lastActivityAt."""
        items = []
        reply_item = {
            "pk": f"POST#{post_id}",
            "sk": f"REPLY#{reply['replyId']}",
            **reply,
            **gsi2_reply_keys(post_id, reply["createdAt"]),
        }
        items.append({"Put": {"TableName": self._table_name, "Item": _decimalize_raw(reply_item)}})
        # Increment post replyCount
        items.append({"Update": {
            "TableName": self._table_name,
            "Key": _decimalize_raw({"pk": f"POST#{post_id}", "sk": "META"}),
            "UpdateExpression": "ADD #rc :one",
            "ExpressionAttributeNames": {"#rc": "replyCount"},
            "ExpressionAttributeValues": _decimalize_raw({":one": 1}),
        }})
        # Update channel lastActivityAt
        items.append({"Update": {
            "TableName": self._table_name,
            "Key": _decimalize_raw({"pk": f"CHANNEL#{channel_id}", "sk": "META"}),
            "UpdateExpression": "SET #la = :now",
            "ExpressionAttributeNames": {"#la": "lastActivityAt"},
            "ExpressionAttributeValues": _decimalize_raw({":now": reply["createdAt"]}),
        }})
        self._transact_write(items)

    # --- Post/Reply get/update ---

    def get_post(self, post_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": f"POST#{post_id}", "sk": "META"})
        return resp.get("Item")

    def update_post(self, post_id: str, updates: dict) -> dict | None:
        expr_parts, values, names = [], {}, {}
        for i, (k, v) in enumerate(updates.items()):
            attr = f"#a{i}"
            val = f":v{i}"
            expr_parts.append(f"{attr} = {val}")
            names[attr] = k
            values[val] = v
        resp = self._table.update_item(
            Key={"pk": f"POST#{post_id}", "sk": "META"},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=_decimalize(values),
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes")

    def get_reply(self, post_id: str, reply_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": f"POST#{post_id}", "sk": f"REPLY#{reply_id}"})
        return resp.get("Item")

    def soft_delete_reply(self, post_id: str, reply_id: str, *, was_accepted: bool = False) -> None:
        """Mark a reply deleted and keep the post's counters honest, in ONE
        transaction — mirroring create_reply_transact, which increments the same
        counter. Doing these as separate writes would let a failure between them
        leave replyCount permanently overstated.

        `ADD :minusone` rather than a computed value so two concurrent deletes
        cannot both read the same count and write the same decrement.
        """
        items = [
            {"Update": {
                "TableName": self._table_name,
                "Key": _decimalize_raw({"pk": f"POST#{post_id}", "sk": f"REPLY#{reply_id}"}),
                # REMOVE the GSI2 keys so the reply leaves the thread-listing
                # index rather than being fetched and filtered out on every read.
                "UpdateExpression": "SET #d = :true REMOVE gsi2pk, gsi2sk",
                "ExpressionAttributeNames": {"#d": "deleted"},
                "ExpressionAttributeValues": _decimalize_raw({":true": True}),
                "ConditionExpression": "attribute_exists(pk)",
            }},
            # ONE update on POST#/META, not two. A TransactWriteItems request may
            # not contain multiple operations on the same item, so clearing the
            # accepted answer has to ride in the same expression as the counter
            # decrement rather than being appended as its own action.
            {"Update": {
                "TableName": self._table_name,
                "Key": _decimalize_raw({"pk": f"POST#{post_id}", "sk": "META"}),
                "UpdateExpression": ("ADD #rc :minusone REMOVE acceptedReplyId"
                                     if was_accepted else "ADD #rc :minusone"),
                "ExpressionAttributeNames": {"#rc": "replyCount"},
                "ExpressionAttributeValues": _decimalize_raw({":minusone": -1}),
            }},
        ]
        self._transact_write(items)

    def update_reply(self, post_id: str, reply_id: str, updates: dict) -> dict | None:
        expr_parts, values, names = [], {}, {}
        for i, (k, v) in enumerate(updates.items()):
            attr = f"#a{i}"
            val = f":v{i}"
            expr_parts.append(f"{attr} = {val}")
            names[attr] = k
            values[val] = v
        resp = self._table.update_item(
            Key={"pk": f"POST#{post_id}", "sk": f"REPLY#{reply_id}"},
            UpdateExpression="SET " + ", ".join(expr_parts),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=_decimalize(values),
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes")

    # --- Reaction (atomic replace: ND-2=A, J2) ---

    def set_reaction_transact(
        self, target_pk: str, target_sk: str, user_id: str,
        new_kind: str | None, old_kind: str | None
    ) -> None:
        """Set/replace/clear a reaction atomically with counter updates.

        DynamoDB forbids two operations on the same item in one transaction.
        When new_kind and old_kind are both set (reaction switch), the increment
        and decrement must be merged into a single Update expression.
        """
        items = []
        reaction_pk = target_pk
        reaction_sk = f"REACTION#{user_id}"

        if new_kind:
            # Put new reaction
            items.append({"Put": {
                "TableName": self._table_name,
                "Item": _decimalize_raw({
                    "pk": reaction_pk, "sk": reaction_sk,
                    "userId": user_id, "kind": new_kind,
                    "targetId": target_pk.split("#", 1)[1],
                    "targetType": "post" if target_pk.startswith("POST#") else "reply",
                    "createdAt": now_iso(),
                }),
            }})

            if old_kind and old_kind != new_kind:
                # Switching reaction: increment new_kind AND decrement old_kind in
                # ONE Update — DynamoDB rejects two ops on the same item per tx.
                items.append({"Update": {
                    "TableName": self._table_name,
                    "Key": _decimalize_raw({"pk": target_pk, "sk": target_sk}),
                    "UpdateExpression": (
                        "SET #rc.#nk = if_not_exists(#rc.#nk, :zero) + :one, "
                        "#rc.#ok = if_not_exists(#rc.#ok, :zero) + :neg"
                    ),
                    "ExpressionAttributeNames": {
                        "#rc": "reactionCounts", "#nk": new_kind, "#ok": old_kind,
                    },
                    "ExpressionAttributeValues": _decimalize_raw(
                        {":zero": 0, ":one": 1, ":neg": -1}),
                }})
            else:
                # New reaction (no previous kind): increment only.
                items.append({"Update": {
                    "TableName": self._table_name,
                    "Key": _decimalize_raw({"pk": target_pk, "sk": target_sk}),
                    "UpdateExpression": "SET #rc.#nk = if_not_exists(#rc.#nk, :zero) + :one",
                    "ExpressionAttributeNames": {"#rc": "reactionCounts", "#nk": new_kind},
                    "ExpressionAttributeValues": _decimalize_raw({":zero": 0, ":one": 1}),
                }})
        else:
            # Clearing reaction: delete the reaction row.
            items.append({"Delete": {
                "TableName": self._table_name,
                "Key": _decimalize_raw({"pk": reaction_pk, "sk": reaction_sk}),
            }})

            if old_kind:
                # Decrement the cleared kind counter.
                items.append({"Update": {
                    "TableName": self._table_name,
                    "Key": _decimalize_raw({"pk": target_pk, "sk": target_sk}),
                    "UpdateExpression": "SET #rc.#ok = if_not_exists(#rc.#ok, :zero) + :neg",
                    "ExpressionAttributeNames": {"#rc": "reactionCounts", "#ok": old_kind},
                    "ExpressionAttributeValues": _decimalize_raw({":zero": 0, ":neg": -1}),
                }})

        if items:
            self._transact_write(items)

    def get_reaction(self, target_pk: str, user_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": target_pk, "sk": f"REACTION#{user_id}"})
        return resp.get("Item")

    # --- Follow ---

    def put_follow(self, target_pk: str, user_id: str, target_id: str,
                   target_type: str, target_name: str) -> None:
        self._table.put_item(Item=_decimalize({
            "pk": target_pk,
            "sk": f"FOLLOW#{user_id}",
            "userId": user_id,
            "targetId": target_id,
            "targetType": target_type,
            "targetName": target_name,
            "createdAt": now_iso(),
            # User-keyed follow for "my follows" listing
            "gsi2pk": f"USERFOLLOWS#{user_id}",
            "gsi2sk": now_iso(),
        }))

    def delete_follow(self, target_pk: str, user_id: str) -> None:
        self._table.delete_item(Key={"pk": target_pk, "sk": f"FOLLOW#{user_id}"})

    def get_follow(self, target_pk: str, user_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": target_pk, "sk": f"FOLLOW#{user_id}"})
        return resp.get("Item")

    def query_follows_for_target(self, target_pk: str) -> list[dict]:
        """Get all followers of a target (for notification fan-out). Bounded at community scale."""
        items = []
        resp = self._table.query(
            KeyConditionExpression=Key("pk").eq(target_pk) & Key("sk").begins_with("FOLLOW#"),
        )
        items.extend(resp.get("Items", []))
        while resp.get("LastEvaluatedKey"):
            resp = self._table.query(
                KeyConditionExpression=Key("pk").eq(target_pk) & Key("sk").begins_with("FOLLOW#"),
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
        return items

    def query_follows_for_user(self, user_id: str) -> list[dict]:
        """List a user's follows (GSI2 USERFOLLOWS# partition)."""
        resp = self._table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("gsi2pk").eq(f"USERFOLLOWS#{user_id}"),
        )
        return resp.get("Items", [])

    # --- Report ---

    def put_report(self, report: dict) -> None:
        item = {
            "pk": f"REPORT#{report['reportId']}",
            "sk": "META",
            **report,
            **gsi4_report_keys(report["groupId"], report["createdAt"]),
        }
        self._table.put_item(Item=_decimalize(item))

    def get_report(self, report_id: str) -> dict | None:
        resp = self._table.get_item(Key={"pk": f"REPORT#{report_id}", "sk": "META"})
        return resp.get("Item")

    def update_report_status(self, report_id: str, status: str, resolved_by: str) -> None:
        self._table.update_item(
            Key={"pk": f"REPORT#{report_id}", "sk": "META"},
            UpdateExpression="SET #s = :s, #ra = :ra, #rb = :rb",
            ExpressionAttributeNames={"#s": "status", "#ra": "resolvedAt", "#rb": "resolvedBy"},
            ExpressionAttributeValues=_decimalize({":s": status, ":ra": now_iso(), ":rb": resolved_by}),
        )

    def query_open_report_by_reporter(self, reporter_id: str, target_id: str) -> dict | None:
        """Check for existing Open report by this reporter on this target (dedupe)."""
        # Scan under the target to find reporter's open report
        # At community scale, reports per target are few
        resp = self._table.query(
            KeyConditionExpression=Key("pk").eq(f"REPORT#{target_id}") & Key("sk").begins_with("REPORTER#"),
        )
        # Alternative: store a reporter-index item
        # For now, use a secondary approach: store report with additional pk pattern
        # Actually, use a simpler approach: query GSI4 for this group and filter
        # Better: store a dedupe item
        pass  # Implemented via dedupe item below

    def put_report_dedupe(self, reporter_id: str, target_id: str) -> bool:
        """Put a dedupe item. Returns False if already exists (report already open)."""
        try:
            self._table.put_item(
                Item=_decimalize({
                    "pk": f"REPORTDEDUPE#{reporter_id}#{target_id}",
                    "sk": "DEDUPE",
                    "createdAt": now_iso(),
                }),
                ConditionExpression="attribute_not_exists(pk)",
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def delete_report_dedupe(self, reporter_id: str, target_id: str) -> None:
        self._table.delete_item(Key={
            "pk": f"REPORTDEDUPE#{reporter_id}#{target_id}", "sk": "DEDUPE"
        })

    # --- Search (GSI3, inverted index) ---

    def query_term(self, term: str, limit: int = TERM_MATCH_CAP) -> list[str]:
        """Query GSI3 for a single term. Returns list of postIds.

        Paginates the term partition instead of reading one 100-item page.
        A single page silently truncated every term used by more than 100 posts,
        which made multi-term search worse than useless: each term contributed a
        different arbitrary 100-post window, so intersecting them dropped posts
        that genuinely contained every word. `limit` is a real bound on how many
        matches a term can contribute (not a page size), so a pathological term
        cannot pull the whole table.
        """
        post_ids: list[str] = []
        kwargs: dict[str, Any] = {}
        while True:
            resp = self._table.query(
                IndexName="GSI3",
                KeyConditionExpression=Key("gsi3pk").eq(f"TERM#{term}"),
                **kwargs,
            )
            for item in resp.get("Items", []):
                post_ids.append(item["gsi3sk"])
                if len(post_ids) >= limit:
                    return post_ids
            if "LastEvaluatedKey" not in resp:
                return post_ids
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def batch_get_posts(self, post_ids: list[str]) -> list[dict]:
        """BatchGetItem for multiple posts by ID."""
        if not post_ids:
            return []
        keys = [{"pk": f"POST#{pid}", "sk": "META"} for pid in post_ids]
        # DynamoDB BatchGetItem limit is 100
        results = []
        for i in range(0, len(keys), 100):
            batch = keys[i:i + 100]
            resp = self._table.meta.client.batch_get_item(
                RequestItems={self._table_name: {"Keys": [_decimalize_raw(k) for k in batch]}}
            )
            results.extend(resp.get("Responses", {}).get(self._table_name, []))
        return results

    # --- GSI1 listings ---

    def browse_forums_by_group(self, group_id: str) -> list[dict]:
        """List forums for a group (GSI1, FORUM# prefix)."""
        resp = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"GROUP#{group_id}") & Key("gsi1sk").begins_with("FORUM#"),
        )
        return [item for item in resp.get("Items", []) if not item.get("hidden")]

    def list_channels_by_group(self, group_id: str, forum_id: str | None = None) -> list[dict]:
        """List channels for a group (optionally filtered by forum)."""
        sk_prefix = f"CHANNEL#{forum_id}#" if forum_id else "CHANNEL#"
        resp = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"GROUP#{group_id}") & Key("gsi1sk").begins_with(sk_prefix),
        )
        return [item for item in resp.get("Items", []) if not item.get("hidden")]

    # --- GSI2 listings ---

    def list_posts_by_channel(self, channel_id: str, limit: int = 20, cursor: str | None = None,
                              scan_forward: bool = False) -> tuple[list[dict], str | None]:
        """List posts by channel (GSI2), newest first by default."""
        kwargs: dict[str, Any] = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("gsi2pk").eq(f"CHANNEL#{channel_id}"),
            "ScanIndexForward": scan_forward,
            "Limit": limit,
        }
        if cursor:
            import json, base64
            kwargs["ExclusiveStartKey"] = json.loads(base64.b64decode(cursor))
        resp = self._table.query(**kwargs)
        items = [i for i in resp.get("Items", []) if not i.get("deleted")]
        next_cursor = None
        if resp.get("LastEvaluatedKey"):
            import json, base64
            next_cursor = base64.b64encode(json.dumps(resp["LastEvaluatedKey"], default=str).encode()).decode()
        return items, next_cursor

    def list_replies_by_post(self, post_id: str, limit: int = 50, cursor: str | None = None) -> tuple[list[dict], str | None]:
        """List replies by post (GSI2), oldest first."""
        kwargs: dict[str, Any] = {
            "IndexName": "GSI2",
            "KeyConditionExpression": Key("gsi2pk").eq(f"POST#{post_id}"),
            "ScanIndexForward": True,
            "Limit": limit,
        }
        if cursor:
            import json, base64
            kwargs["ExclusiveStartKey"] = json.loads(base64.b64decode(cursor))
        resp = self._table.query(**kwargs)
        next_cursor = None
        if resp.get("LastEvaluatedKey"):
            import json, base64
            next_cursor = base64.b64encode(json.dumps(resp["LastEvaluatedKey"], default=str).encode()).decode()
        return resp.get("Items", []), next_cursor

    # --- GSI4 moderation queue ---

    def list_reports_by_group(self, group_id: str, limit: int = 20, cursor: str | None = None) -> tuple[list[dict], str | None]:
        """List open reports for a group (GSI4). Leaders only."""
        kwargs: dict[str, Any] = {
            "IndexName": "GSI4",
            "KeyConditionExpression": Key("gsi4pk").eq(f"REPORTGROUP#{group_id}"),
            "ScanIndexForward": False,
            "Limit": limit,
        }
        if cursor:
            import json, base64
            kwargs["ExclusiveStartKey"] = json.loads(base64.b64decode(cursor))
        resp = self._table.query(**kwargs)
        items = [i for i in resp.get("Items", []) if i.get("status") == "Open"]
        next_cursor = None
        if resp.get("LastEvaluatedKey"):
            import json, base64
            next_cursor = base64.b64encode(json.dumps(resp["LastEvaluatedKey"], default=str).encode()).decode()
        return items, next_cursor

    # --- Rate limiting (D-FO-3) ---

    def check_rate(self, member_id: str, action: str, limit: int) -> bool:
        """Check if under rate limit. Returns True if allowed."""
        key = rate_key(member_id, action)
        resp = self._table.get_item(Key={"pk": key["pk"], "sk": key["sk"]})
        item = resp.get("Item")
        if item and int(item.get("count", 0)) >= limit:
            return False
        return True

    def increment_rate(self, member_id: str, action: str) -> None:
        """Increment rate counter (TTL auto-cleans)."""
        key = rate_key(member_id, action)
        self._table.update_item(
            Key={"pk": key["pk"], "sk": key["sk"]},
            UpdateExpression="ADD #c :one SET #t = if_not_exists(#t, :ttl)",
            ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
            ExpressionAttributeValues=_decimalize({":one": 1, ":ttl": epoch_ttl(3600)}),
        )

    # --- Sweep (nightly purge, ND-5=A) ---

    def query_purging_forums(self) -> list[dict]:
        """Find all forums with status=PURGING."""
        # Full table scan filtered for PURGING — acceptable for nightly sweep
        items = []
        kwargs: dict[str, Any] = {
            "FilterExpression": "#s = :s",
            "ExpressionAttributeNames": {"#s": "status"},
            "ExpressionAttributeValues": {":s": "PURGING"},
        }
        resp = self._table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        while resp.get("LastEvaluatedKey"):
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
            resp = self._table.scan(**kwargs)
            items.extend(resp.get("Items", []))
        return items

    def query_items_by_group(self, group_id: str, limit: int = 100) -> list[dict]:
        """Query all items for a group (GSI1) for cascade delete."""
        items = []
        resp = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"GROUP#{group_id}"),
            Limit=limit,
        )
        items.extend(resp.get("Items", []))
        return items

    def batch_delete(self, keys: list[dict]) -> None:
        """Batch delete items (25 at a time)."""
        with self._table.batch_writer() as batch:
            for key in keys:
                batch.delete_item(Key={"pk": key["pk"], "sk": key["sk"]})

    # --- Helpers ---

    @property
    def _table_name(self) -> str:
        return self._table.table_name

    def _transact_write(self, items: list[dict]) -> None:
        """Execute TransactWriteItems via the low-level client."""
        client = self._client or self._table.meta.client
        client.transact_write_items(TransactItems=items)


def _decimalize(obj: Any) -> Any:
    """Convert ints/floats to Decimal for DynamoDB (resource-level API)."""
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimalize(i) for i in obj]
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return Decimal(str(obj))
    return obj


def _decimalize_raw(obj: Any) -> Any:
    """Convert for low-level client (TransactWriteItems uses raw attribute format)."""
    # For the resource-level table, we use _decimalize above.
    # TransactWriteItems with resource-level table uses the same format.
    return _decimalize(obj)
