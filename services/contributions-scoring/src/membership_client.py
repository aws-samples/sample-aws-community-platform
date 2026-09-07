"""Identity membership client (stale-JWT supplement).

Calls Identity's GET /groups/my-memberships endpoint to get the caller's
current group memberships freshly from the database, bypassing the stale JWT
claims that are only refreshed at login time.

Copied from the forums service — same pattern, same fail-soft contract.
1.5s timeout, returns None on any failure (falls back to JWT claims).
"""
from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

_TIMEOUT_MS = int(os.environ.get("MEMBERSHIP_TIMEOUT_MS", "1500"))
_TIMEOUT_S = _TIMEOUT_MS / 1000.0


class MembershipClient:
    """Lightweight HTTP client for Identity's fresh claims lookup."""

    def __init__(self, base_url: str | None = None):
        raw = (base_url or os.environ.get("API_BASE_URL", "")).rstrip("/")
        if raw and not raw.startswith("https://"):
            raise ValueError(
                f"API_BASE_URL must use the https:// scheme — got: {raw!r}. "
                "file:// and other schemes are not permitted."
            )
        self._base_url = raw

    def get_member_group_ids(self, bearer_token: str | None) -> list[str] | None:
        """Return the caller's current member_group_ids from Identity.

        Returns None on failure (timeout, error, missing config) so the caller
        can fall back to JWT claims gracefully.
        """
        if not self._base_url or not bearer_token:
            return None
        url = f"{self._base_url}/groups/my-memberships"
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {bearer_token}"},
                timeout=_TIMEOUT_S,
            )
            resp.raise_for_status()
            data = resp.json()
            groups = data.get("member_group_ids")
            if isinstance(groups, list):
                return groups
            return None
        except (requests.exceptions.RequestException, ValueError) as exc:
            logger.warning("membership lookup failed (fail-soft to JWT claims): %s", exc)
            return None
