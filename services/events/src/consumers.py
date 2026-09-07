"""Event consumers: group soft-delete, S3 objects, and GuardDuty scan results.

All three are idempotent by event id via the shared idempotency store (BR-X4), so
a redelivery is acknowledged without re-processing.

The S3 rule is key-prefix filtered to `events/` and `library/` in the app stack.
That filter is not cosmetic: Foundation enables EventBridge notifications
bucket-wide, and Settings' own rule matched only on bucket name, so without
prefix filters on both rules each service would receive the other's object events
and burn an idempotency record per event — functionally tolerant, but it destroys
each service's logs as a signal for its own feature.
"""
from __future__ import annotations

from urllib.parse import unquote_plus

from _conventions.logger import get_logger, log
from models import SCAN_CLEAN, SCAN_QUARANTINED, now_iso

_logger = get_logger("events.consumers")

EVENTS_PREFIX = "events/"
LIBRARY_PREFIX = "library/"


def _event_id_from_key(key: str) -> str | None:
    """`events/<eventId>/materials/<name>` -> `<eventId>`. The key carries the
    event id, which is why no reverse-lookup index is needed for materials."""
    parts = key.split("/")
    if len(parts) >= 3 and parts[0] == "events":
        return parts[1]
    return None


class GroupEventConsumer:
    """`GroupSoftDeleted` -> cancel that group's UPCOMING events (BR-X3).

    Completed events are history and already-cancelled ones need nothing, which
    also makes the handler naturally idempotent beyond the event-id guard.
    """

    def __init__(self, event_service, idempotency=None):
        self._events = event_service
        self._idem = idempotency

    def handle(self, envelope: dict, *, correlation_id: str | None = None) -> dict:
        # Read `groupId` ONLY, and only from the payload. An earlier version fell
        # back to `detail.get("id")`, which silently picked up the ENVELOPE id
        # when the payload was empty and then tried to cancel events for a group
        # named after an event id. A malformed event is ignored, not guessed at.
        data = envelope.get("data")
        payload = data if isinstance(data, dict) else envelope
        group_id = payload.get("groupId")
        if not group_id:
            log(_logger, 30, "GroupSoftDeleted without a groupId — ignoring")
            return {"groupId": None, "cancelled": 0}

        cancelled = {"n": 0}

        def run():
            cancelled["n"] = self._events.cancel_group_events(
                group_id, correlation_id=correlation_id)
            log(_logger, 20, "cancelled group events", groupId=group_id,
                count=cancelled["n"])

        event_id = envelope.get("id")
        if self._idem and event_id:
            self._idem.run_once(event_id, run)
        else:
            run()
        return {"groupId": group_id, "cancelled": cancelled["n"]}


class S3ObjectConsumer:
    """Stamp material/uploaded-file state from S3 object events (BR-M6).

    Client-supplied sizes are never trusted; `uploaded`, `sizeBytes` and
    `uploadedAt` come either from here or from the confirm step's own HEAD
    against S3 (MaterialService.add/replace) — both are S3's server-side
    truth. The confirm-time stamp exists because this consumer can receive
    Object Created BEFORE the material row is confirmed (the browser PUT
    completes first); it drops the event, and someone must pick the state up.
    """

    def __init__(self, repo, idempotency=None, library=None):
        self._repo = repo
        self._idem = idempotency
        self._library = library  # LibraryService — wired in Context

    def handle(self, envelope: dict) -> dict:
        detail = envelope.get("detail") or {}
        detail_type = envelope.get("detail-type") or ""
        key = unquote_plus(str((detail.get("object") or {}).get("key") or ""))
        if not key.startswith(EVENTS_PREFIX):
            # Another consumer's prefix. Should be filtered at the rule, but a
            # rule can be mis-edited and this is one line of insurance.
            return {"ignored": key}

        event_id = _event_id_from_key(key)
        if not event_id:
            return {"ignored": key}

        def run():
            # 2026-08-12: external uploads now also land in /materials/ (merged folder).
            # Priority: if the key matches a known material row → stamp it as uploaded.
            # Otherwise, if it matches an upload-link's folderPrefix → record it as
            # an external upload file. This handles both direct and external uploads
            # landing in the same prefix.
            if "/materials/" in key:
                material = self._repo.find_material_by_key(event_id, key)
                if material is not None:
                    self._handle_material_found(event_id, key, detail, detail_type, material)
                else:
                    # Not a known material row — check if it's an external upload.
                    self._handle_upload(event_id, key, detail, detail_type)
            elif "/uploads/" in key:
                # Legacy prefix (pre-2026-08-12 links still use this).
                self._handle_upload(event_id, key, detail, detail_type)

        envelope_id = envelope.get("id")
        if self._idem and envelope_id:
            self._idem.run_once(envelope_id, run)
        else:
            run()
        return {"key": key, "eventId": event_id}

    def _handle_material_found(self, event_id: str, key: str, detail: dict,
                               detail_type: str, material: dict) -> None:
        if detail_type.endswith("Deleted"):
            self._repo.clear_material_upload_state(event_id, material["id"])
            return
        self._repo.set_material_upload_state(
            event_id, material["id"],
            size_bytes=int((detail.get("object") or {}).get("size") or 0),
            uploaded_at=now_iso())

        # A file just became uploaded. If its event is already Completed and it
        # has already scanned Clean, promote it to the Content Library now — the
        # scan verdict (Trigger B) may have arrived earlier while uploaded was
        # still False and no-opped. Idempotent inside promote_single_material.
        if self._library is not None:
            from models import STATUS_COMPLETED
            event = self._repo.get_event(event_id)
            if event and event.get("status") == STATUS_COMPLETED:
                updated = self._repo.get_material(event_id, material["id"])
                if updated:
                    self._library.promote_single_material(updated, event)

    def _handle_upload(self, event_id: str, key: str, detail: dict, detail_type: str) -> None:
        name = key.split("/")[-1]
        link_id = None
        for link in self._repo.list_upload_links(event_id):
            # Match by s3Key (exact file) or folderPrefix (legacy).
            if link.get("s3Key") == key or key.startswith(link.get("folderPrefix") or "\0"):
                link_id = link["id"]
                break
        if link_id is None:
            log(_logger, 30, "upload with no owning link", key=key)
            return
        if detail_type.endswith("Deleted"):
            return
        size_bytes = int((detail.get("object") or {}).get("size") or 0)
        # Stamp the slot as uploaded (the listing shows "Uploaded" status).
        self._repo.set_upload_link_uploaded(
            event_id, link_id, size_bytes=size_bytes, uploaded_at=now_iso())
        self._repo.put_uploaded_file({
            "id": f"uf-{name}", "eventId": event_id, "uploadLinkId": link_id,
            "name": name, "sizeBytes": size_bytes,
            "uploadedAt": now_iso(),
        })


class MalwareScanConsumer:
    """GuardDuty Malware Protection for S3 scan results (N1/J3).

    Handles both events/ and library/ key prefixes:
    - events/: updates material scanState; triggers Path 1 Library promotion
      if the event is Completed.
    - library/: updates Library resource scanState directly.
    """

    def __init__(self, repo, events, idempotency=None, library=None):
        self._repo = repo
        self._events = events
        self._idem = idempotency
        self._library = library  # LibraryService — wired in Context

    def handle(self, envelope: dict, *, correlation_id: str | None = None) -> dict:
        detail = envelope.get("detail") or {}
        key = unquote_plus(str(
            ((detail.get("s3ObjectDetails") or {}).get("objectKey"))
             or ((detail.get("object") or {}).get("key")) or ""))
        status = str((detail.get("scanResultDetails") or {}).get("scanResultStatus")
                     or detail.get("scanStatus") or "").upper()
        if not key.startswith(EVENTS_PREFIX) and not key.startswith(LIBRARY_PREFIX):
            return {"ignored": key}

        # Derive the verdict BEFORE any routing — the library branch below uses
        # it, and computing it later left `state` unbound on that path (a
        # NameError that stopped library uploads from ever leaving PendingScan).
        state = SCAN_CLEAN if status in ("NO_THREATS_FOUND", "CLEAN") else SCAN_QUARANTINED

        # Route library/ prefix to Library scan-state update.
        if key.startswith(LIBRARY_PREFIX):
            resource_id = key.split("/")[1] if len(key.split("/")) > 1 else None
            if resource_id and self._library is not None:
                self._library.update_scan_state(resource_id, state)
            return {"key": key, "scanState": state}

        event_id = _event_id_from_key(key)
        if not event_id:
            return {"ignored": key}

        def run():
            material = self._repo.find_material_by_key(event_id, key)
            if material is None:
                # Not an organizer Material — it may be an EXTERNAL UPLOAD
                # (upload-link file) landing in the shared materials prefix.
                # Promote it to the Content Library on a Clean verdict for a
                # Completed event (same scan gate materials use).
                link = self._repo.find_upload_link_by_key(event_id, key)
                if link is None:
                    log(_logger, 20, "scan result for an unknown material", key=key)
                    return
                # Record the verdict on the slot (scan gate + audit).
                self._repo.set_upload_link_scan_state(event_id, link["id"], state)
                if state == SCAN_CLEAN and self._library is not None:
                    from models import STATUS_COMPLETED
                    event = self._repo.get_event(event_id)
                    if event and event.get("status") == STATUS_COMPLETED:
                        link["scanState"] = state
                        self._library.promote_external_upload(link, event)
                elif state == SCAN_QUARANTINED:
                    log(_logger, 40, "MALWARE DETECTED — external upload quarantined",
                        key=key, eventId=event_id)
                return
            self._repo.set_material_scan_state(event_id, material["id"], state)
            event = self._repo.get_event(event_id)
            if event:
                # Path 1: if the material is now Clean and the event is Completed,
                # promote to the Content Library (BR-LIB-P1 Trigger B).
                if state == SCAN_CLEAN and self._library is not None:
                    from models import STATUS_COMPLETED
                    if event.get("status") == STATUS_COMPLETED:
                        updated_material = self._repo.get_material(event_id, material["id"])
                        if updated_material:
                            self._library.promote_single_material(updated_material, event)
            if state == SCAN_QUARANTINED:
                # Surfaced as a metric/alarm — a threat reaching the community
                # bucket is an operator concern, not just a hidden row.
                log(_logger, 40, "MALWARE DETECTED — material quarantined",
                    key=key, eventId=event_id)
                self._events.publish("EventUpdated", {
                    "eventId": event_id, "kind": "material-quarantined",
                    "materialId": material["id"], "audit": True,
                }, correlation_id=correlation_id)

        envelope_id = envelope.get("id")
        if self._idem and envelope_id:
            self._idem.run_once(envelope_id, run)
        else:
            run()
        return {"key": key, "scanState": state}
