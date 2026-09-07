"""Keeps a file slot's upload state current from S3 bucket events (perf rework
2026-08-04).

Before this, `list_links` computed `uploaded` by calling S3 ListObjectsV2 once
per distinct folder in the result set, so page latency grew with the number of
folders a leader used and the listing could not be paginated cheaply. Upload
state is now STORED on the slot record and this consumer is its only writer.

Wiring: the community bucket has EventBridge notifications enabled (foundation
`FileShareBucket`), and an `AWS::Events::Rule` in the settings app stack routes
`Object Created` / `Object Deleted` for that bucket to this function. The rule
sits on the DEFAULT bus — S3 delivers to the default bus, not the platform's
custom bus. EventBridge (rather than a direct S3 -> Lambda notification) is what
keeps the bucket, which lives in the foundation stack, from having to name a
function that lives in a stack downstream of it.

Key -> slot resolution is an O(1) get_item on the FILEKEY pointer item written
at create time; no second index is needed.

Delivery is at-least-once and unordered, so:
  - idempotent on the EventBridge event id (IdempotencyStore), and
  - an Object Created older than the stored `uploadedAt` is dropped, so a
    delayed duplicate cannot resurrect a superseded state.
"""
from __future__ import annotations

from urllib.parse import unquote_plus

from _conventions.logger import get_logger, log
from botocore.exceptions import ClientError

_logger = get_logger("settings.file-share-events")

CREATED = "Object Created"
DELETED = "Object Deleted"
CONSUMED_S3_EVENTS = {CREATED, DELETED}


class FileShareEventConsumer:
    def __init__(self, repo, idempotency_store=None):
        self._repo = repo
        self._idem = idempotency_store

    def handle(self, event: dict) -> None:
        """`event` is the raw EventBridge envelope from the S3 notification."""
        event_id = event.get("id", "")

        def _apply():
            self._apply(event)

        if self._idem is not None and event_id:
            self._idem.run_once(event_id, _apply)
        else:
            _apply()

    def _apply(self, event: dict) -> None:
        detail_type = event.get("detail-type") or event.get("type")
        detail = event.get("detail") or {}
        # S3 URL-encodes object keys in notifications; a slot's fileName may
        # legitimately contain spaces or '+'.
        raw_key = ((detail.get("object") or {}).get("key")) or ""
        key = unquote_plus(raw_key)
        if not key:
            return

        pointer = self._repo.get_file_key_pointer(key)
        if pointer is None:
            # Object with no owning slot (pre-rework upload, or the slot was
            # deleted first). Nothing to stamp — not an error.
            log(_logger, 20, "s3 event for unclaimed key (ignored)", key=key)
            return
        link_id = pointer.get("linkId")
        if not link_id:
            return

        try:
            if detail_type == CREATED:
                self._on_created(link_id, detail, event)
            elif detail_type == DELETED:
                self._repo.clear_upload_state(link_id)
        except ClientError as err:
            if err.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Slot record already gone (delete raced this event). The pointer
                # is released after the record, so this window is expected.
                log(_logger, 20, "slot gone; upload state not applied", key=key)
                return
            raise

    def _on_created(self, link_id: str, detail: dict, event: dict) -> None:
        uploaded_at = event.get("time") or ""
        current = self._repo.get_file_share_link(link_id) or {}
        stored = current.get("uploadedAt")
        if stored and uploaded_at and uploaded_at < stored:
            log(_logger, 20, "stale Object Created dropped", linkId=link_id)
            return
        self._repo.set_upload_state(
            link_id,
            size_bytes=int((detail.get("object") or {}).get("size") or 0),
            uploaded_at=uploaded_at,
        )
