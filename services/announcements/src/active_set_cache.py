"""ActiveSetCache — per-warm-container cache of the active-announcement set
(NFR-AN-PERF-1). The panel read is the hot path (every landing-page load for all
members); the active set is tiny (mandatory expiry keeps it to tens of items), so
we cache the whole set with a short TTL (default 30s) and filter it per-caller in
memory. A miss falls back to one bounded repository Scan.

State is per warm container and resets on cold start — an eventual-consistency
window of at most the TTL for a just-posted/edited/deleted announcement to appear
or disappear in another container's cached panel (Infra Design judgement call J1).
Delete/edit remain authoritative at the data layer immediately; only cached
READS lag. `invalidate()` clears the calling container's cache after a write.
"""
from __future__ import annotations

import os
import time


class ActiveSetCache:
    def __init__(self, repo, ttl_seconds: int | None = None):
        self._repo = repo
        self._ttl = ttl_seconds if ttl_seconds is not None else int(
            os.environ.get("ACTIVE_SET_CACHE_TTL_SECONDS", "30"))
        self._items: list[dict] | None = None
        self._fetched_at: float = 0.0

    def get(self) -> list[dict]:
        now = time.monotonic()
        if self._items is None or (now - self._fetched_at) > self._ttl:
            self._items = self._repo.scan_all()
            self._fetched_at = now
        return self._items

    def invalidate(self) -> None:
        self._items = None
        self._fetched_at = 0.0
