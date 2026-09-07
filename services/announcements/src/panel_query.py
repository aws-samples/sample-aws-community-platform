"""PanelQuery — the recipient panel (US-10.4), the hot path.

Resolves the caller's audience from JWT claims and filters the cached active set in
memory (no DynamoDB round trip on a cache hit). Excludes expired (BR-6) and
group-hidden (BR-13) items. Newest-first. Administrator is denied upstream (BR-3).

Audience rules (use case 10 / dashboard mockups):
- community-wide announcements -> everyone
- group-targeted -> a Member/UGL who is in (or leads) that group
- a Community Leader additionally sees group-targeted announcements THEY authored
  ("community-wide + announcements you authored" — leader dashboard subtitle)
"""
from __future__ import annotations

import models


def _audience_match(item: dict, principal) -> bool:
    scope = item.get("targetScope", models.SCOPE_COMMUNITY)
    if scope == models.SCOPE_COMMUNITY:
        return True
    group_ids = set(item.get("targetGroupIds") or [])
    if not group_ids:
        return False
    allowed = set(principal.member_group_ids or [])
    if principal.led_group_id:
        allowed.add(principal.led_group_id)
    if group_ids & allowed:
        return True
    # CL sees group-targeted announcements they authored (dashboard subtitle).
    if principal.role == "CommunityLeader" and item.get("authorId") == principal.user_id:
        return True
    return False


class PanelQuery:
    def __init__(self, cache):
        self._cache = cache

    def panel(self, principal) -> dict:
        at = models.now()
        items = [
            i for i in self._cache.get()
            if not models.is_expired(i, at=at)
            and not i.get("groupHidden", False)
            and _audience_match(i, principal)
        ]
        items.sort(key=lambda i: i.get("createdAt", ""), reverse=True)
        return models.listing(items, at=at)
