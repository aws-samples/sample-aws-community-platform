"""Event consumers for Announcements (idempotent on the envelope id — BR-15).

- EventCreated (Events, Unit 4): when announce=true, auto-post an announcement
  targeting the event's audience (US-2.1, BR-17).
- GroupSoftDeleted / GroupRestored (Identity, Unit 2): hide / restore that group's
  group-targeted announcements (BR-13). Community-wide announcements are unaffected.
"""
from __future__ import annotations

from _conventions.logger import get_logger, log

_logger = get_logger("announcements.consumers")

CONSUMED_EVENT_TYPES = {"EventCreated", "GroupSoftDeleted", "GroupRestored"}


class EventConsumer:
    def __init__(self, service, repo, cache, idempotency=None):
        self._service = service
        self._repo = repo
        self._cache = cache
        self._idem = idempotency

    def handle(self, envelope: dict, *, correlation_id: str | None = None) -> dict:
        event_id = envelope.get("id", "")
        detail_type = envelope.get("type") or envelope.get("detail-type")
        data = envelope.get("data")
        payload = data if isinstance(data, dict) else envelope

        result = {"type": detail_type, "handled": False}

        def _apply():
            self._dispatch(detail_type, payload, correlation_id=correlation_id)
            result["handled"] = True

        if self._idem is not None and event_id:
            self._idem.run_once(event_id, _apply)
        else:
            _apply()
        return result

    def _dispatch(self, detail_type: str, data: dict, *, correlation_id: str | None) -> None:
        if detail_type == "EventCreated":
            self._service.auto_post_from_event(data, correlation_id=correlation_id)
        elif detail_type == "GroupSoftDeleted":
            self._set_group_hidden(data.get("groupId"), True)
        elif detail_type == "GroupRestored":
            self._set_group_hidden(data.get("groupId"), False)
        else:
            log(_logger, 20, "ignoring unrecognized event", detailType=detail_type)

    def _set_group_hidden(self, group_id: str | None, hidden: bool) -> None:
        if not group_id:
            log(_logger, 30, "group event without a groupId — ignoring")
            return
        affected = self._repo.targeting_group(group_id)
        for item in affected:
            self._repo.set_group_hidden(item["id"], hidden)
        if affected:
            self._cache.invalidate()
        log(_logger, 20, "group visibility updated", groupId=group_id,
            hidden=hidden, count=len(affected))
