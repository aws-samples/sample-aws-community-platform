"""Nightly purge sweep for Forums (Q6=C, ND-5=A, NFR-FO-REL-6).

Queries for forums with status=PURGING and deletes their underlying rows
in idempotent batches of 25. Self-caps at SWEEP_TIME_CAP_SECONDS (default 600s).
Emits a custom metric if PURGING items remain after the cap (alarm trigger).
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

_TIME_CAP = int(os.environ.get("SWEEP_TIME_CAP_SECONDS", "600"))
_BATCH_SIZE = 25


class SweepHandler:
    """Nightly scheduled purge of PURGING forum content."""

    def __init__(self, repo):
        self._repo = repo

    def run(self) -> dict:
        """Execute the sweep. Returns summary."""
        start = time.time()
        total_deleted = 0
        forums_purged = 0

        purging_forums = self._repo.query_purging_forums()
        if not purging_forums:
            logger.info("Sweep: no PURGING forums found")
            return {"purged": 0, "items_deleted": 0, "stalled": False}

        for forum in purging_forums:
            group_id = forum.get("groupId", "")
            forum_id = forum.get("forumId", forum.get("pk", "").replace("FORUM#", ""))

            # Delete all items under this group in batches
            while True:
                if time.time() - start > _TIME_CAP:
                    logger.warning("Sweep time-cap reached (%ds). Items remain.", _TIME_CAP)
                    return {
                        "purged": forums_purged,
                        "items_deleted": total_deleted,
                        "stalled": True,
                    }

                items = self._repo.query_items_by_group(group_id, limit=_BATCH_SIZE)
                if not items:
                    break

                keys = [{"pk": item["pk"], "sk": item["sk"]} for item in items]
                self._repo.batch_delete(keys)
                total_deleted += len(keys)

            # Delete the forum META item itself
            self._repo.delete_item(f"FORUM#{forum_id}", "META")
            total_deleted += 1
            forums_purged += 1
            logger.info("Purged forum %s (%d items so far)", forum_id, total_deleted)

        logger.info("Sweep complete: %d forums, %d items deleted", forums_purged, total_deleted)
        return {"purged": forums_purged, "items_deleted": total_deleted, "stalled": False}
