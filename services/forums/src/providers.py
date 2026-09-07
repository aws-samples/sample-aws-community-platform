"""Event publisher for Forums domain events.

Emits to EventBridge via the platform envelope pattern. Events:
- ForumPostCreated (+ followerIds for notification fan-out)
- ForumReplyCreated (+ followerIds)
- MemberMentioned (per mention)
- PostReported
- PostDeleted
- ForumChannelDeleted
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from _conventions.envelope import build_event

logger = logging.getLogger(__name__)

_SOURCE = "forums"


class EventPublisher:
    """Publishes domain events to EventBridge."""

    def __init__(self, bus_name: str | None = None, client=None):
        self._bus = bus_name or os.environ.get("EVENT_BUS_NAME", "default")
        self._client = client or boto3.client("events")

    def emit(self, event_type: str, data: dict) -> None:
        """Emit a single domain event."""
        envelope = build_event(event_type, _SOURCE, data)
        try:
            self._client.put_events(Entries=[{
                "Source": _SOURCE,
                "DetailType": event_type,
                "Detail": json.dumps(envelope),
                "EventBusName": self._bus,
            }])
        except Exception as exc:
            # Fail-soft: log but don't block the operation (NFR-FO-REL-2)
            logger.error("Failed to emit %s: %s", event_type, exc)

    def forum_post_created(self, post: dict, follower_ids: list[str]) -> None:
        self.emit("ForumPostCreated", {
            "postId": post["postId"],
            "authorId": post["authorId"],
            "authorName": post.get("authorName", ""),
            "authorRole": post.get("authorRoleLabel", "Member"),
            "groupId": post["groupId"],
            "channelId": post["channelId"],
            "title": post["title"],
            "postDate": post["createdAt"],
            "followerIds": follower_ids,
        })

    def forum_reply_created(self, reply: dict, post: dict, follower_ids: list[str]) -> None:
        self.emit("ForumReplyCreated", {
            "replyId": reply["replyId"],
            "postId": reply["postId"],
            "authorId": reply["authorId"],
            "authorName": reply.get("authorName", ""),
            "authorRole": reply.get("authorRoleLabel", "Member"),
            "groupId": reply["groupId"],
            "postDate": reply["createdAt"],
            "followerIds": follower_ids,
        })

    def member_mentioned(self, mentioned_user_id: str, author_id: str, author_name: str,
                         post_id: str, group_id: str, context_type: str) -> None:
        self.emit("MemberMentioned", {
            "mentionedUserId": mentioned_user_id,
            "authorId": author_id,
            "authorName": author_name,
            "postId": post_id,
            "groupId": group_id,
            "contextType": context_type,  # "post" or "reply"
        })

    def post_reported(self, report: dict) -> None:
        self.emit("PostReported", {
            "reportId": report["reportId"],
            "targetId": report["targetId"],
            "targetType": report["targetType"],
            "groupId": report["groupId"],
            "reporterId": report["reporterId"],
        })

    def post_deleted(self, post_id: str, group_id: str, deleted_by: str) -> None:
        self.emit("PostDeleted", {
            "postId": post_id,
            "groupId": group_id,
            "deletedBy": deleted_by,
        })

    def forum_channel_deleted(self, channel_id: str, forum_id: str, group_id: str, deleted_by: str) -> None:
        self.emit("ForumChannelDeleted", {
            "channelId": channel_id,
            "forumId": forum_id,
            "groupId": group_id,
            "deletedBy": deleted_by,
        })

    def reply_accepted(self, reply: dict, accepted: bool) -> None:
        """Emit ReplyAccepted for Contributions scoring (US-4.15, DL17)."""
        self.emit("ReplyAccepted", {
            "replyId": reply["replyId"],
            "authorId": reply["authorId"],
            "authorName": reply.get("authorName", ""),
            "authorRole": reply.get("authorRoleLabel", "Member"),
            "groupId": reply["groupId"],
            "postDate": reply["createdAt"],
            "accepted": accepted,
        })
