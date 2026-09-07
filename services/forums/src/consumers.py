"""Event consumers for Forums (BR-27/28, NFR-FO-REL-3/6).

Handles group lifecycle events from Identity:
- GroupHardDeleted → mark forums PURGING (immediate hide)
- GroupSoftDeleted → set hidden=true
- GroupRestored → clear hidden

All idempotent on envelope id via the idempotency store.
"""
from __future__ import annotations

import logging

from _conventions.envelope import event_id
from _conventions.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)

CONSUMED_EVENT_TYPES = {"GroupHardDeleted", "GroupSoftDeleted", "GroupRestored", "GroupCreated"}


class EventConsumer:
    """Processes group lifecycle events for Forums."""

    def __init__(self, repo, idempotency: IdempotencyStore | None = None):
        self._repo = repo
        self._idempotency = idempotency

    def handle(self, envelope: dict) -> None:
        """Route an event envelope to the appropriate handler."""
        eid = event_id(envelope)
        detail_type = envelope.get("detail-type") or envelope.get("type", "")
        data = envelope.get("data")
        payload = data if isinstance(data, dict) else envelope

        if detail_type not in CONSUMED_EVENT_TYPES:
            logger.warning("Unknown event type: %s", detail_type)
            return

        if self._idempotency:
            def action():
                self._dispatch(detail_type, payload)
            if not self._idempotency.run_once(eid, action):
                logger.info("Duplicate event %s (idempotent skip)", eid)
        else:
            self._dispatch(detail_type, payload)

    def _dispatch(self, detail_type: str, data: dict) -> None:
        group_id = data.get("groupId", "")
        if not group_id:
            logger.error("Event %s missing groupId", detail_type)
            return

        if detail_type == "GroupHardDeleted":
            self._handle_hard_delete(group_id)
        elif detail_type == "GroupSoftDeleted":
            self._handle_soft_delete(group_id)
        elif detail_type == "GroupRestored":
            self._handle_restore(group_id)
        elif detail_type == "GroupCreated":
            self._handle_group_created(group_id, data)

    def _handle_hard_delete(self, group_id: str) -> None:
        """Mark all group's forums as PURGING. Content invisible immediately.

        Physical row deletion happens in the nightly sweep (Q6=C).
        """
        # Query GSI1 unfiltered (need to find ALL forums, including already-hidden ones)
        from boto3.dynamodb.conditions import Key
        resp = self._repo._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"GROUP#{group_id}") & Key("gsi1sk").begins_with("FORUM#"),
        )
        forums = resp.get("Items", [])
        for forum in forums:
            forum_id = forum.get("forumId", forum.get("pk", "").replace("FORUM#", ""))
            self._repo.mark_forum_purging(forum_id)
            logger.info("Marked forum %s as PURGING (group %s hard-deleted)", forum_id, group_id)

    def _handle_soft_delete(self, group_id: str) -> None:
        """Hide all group's forums (BR-28). Reversible on GroupRestored."""
        from boto3.dynamodb.conditions import Key
        resp = self._repo._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"GROUP#{group_id}") & Key("gsi1sk").begins_with("FORUM#"),
        )
        forums = resp.get("Items", [])
        for forum in forums:
            if not forum.get("hidden"):
                forum_id = forum.get("forumId", forum.get("pk", "").replace("FORUM#", ""))
                self._repo.update_forum(forum_id, {"hidden": True})
                logger.info("Hidden forum %s (group %s soft-deleted)", forum_id, group_id)

    def _handle_restore(self, group_id: str) -> None:
        """Un-hide group's forums (BR-28). Must also pick up hidden forums."""
        # Query GSI1 unfiltered to find hidden forums for this group
        from boto3.dynamodb.conditions import Key
        resp = self._repo._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"GROUP#{group_id}") & Key("gsi1sk").begins_with("FORUM#"),
        )
        for forum in resp.get("Items", []):
            if forum.get("hidden"):
                forum_id = forum.get("forumId", forum.get("pk", "").replace("FORUM#", ""))
                self._repo.update_forum(forum_id, {"hidden": False})
                logger.info("Restored forum %s (group %s restored)", forum_id, group_id)

    def _handle_group_created(self, group_id: str, data: dict) -> None:
        """Auto-create a forum for the new group with a default 'General' channel."""
        import uuid
        from models import gsi1_channel_keys, gsi1_forum_keys, now_iso

        group_name = data.get("name", data.get("groupName", group_id))
        forum_id = str(uuid.uuid4())
        ts = now_iso()

        # Check if forum already exists for this group (idempotent)
        from boto3.dynamodb.conditions import Key
        existing = self._repo._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("gsi1pk").eq(f"GROUP#{group_id}") & Key("gsi1sk").begins_with("FORUM#"),
            Limit=1,
        )
        if existing.get("Items"):
            logger.info("Forum already exists for group %s (idempotent skip)", group_id)
            return

        # Create forum
        forum = {
            "pk": f"FORUM#{forum_id}", "sk": "META",
            "forumId": forum_id, "groupId": group_id, "name": group_name,
            "description": "", "createdBy": "system", "createdAt": ts,
            "hidden": False, "channelCount": 1,
            **gsi1_forum_keys(group_id, forum_id),
        }
        from repository import _decimalize
        self._repo._table.put_item(Item=_decimalize(forum))

        # Create default "General" channel
        channel_id = str(uuid.uuid4())
        channel = {
            "pk": f"CHANNEL#{channel_id}", "sk": "META",
            "channelId": channel_id, "forumId": forum_id, "groupId": group_id,
            "name": "General", "description": "", "postCount": 0,
            "lastActivityAt": ts, "createdBy": "system", "createdAt": ts, "hidden": False,
            **gsi1_channel_keys(group_id, forum_id, channel_id),
        }
        self._repo._table.put_item(Item=_decimalize(channel))
        logger.info("Auto-created forum %s (%s) + General channel for group %s", forum_id, group_name, group_id)
