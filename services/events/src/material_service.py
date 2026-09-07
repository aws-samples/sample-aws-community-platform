"""Event materials management (US-2.15).

Upload flow (D5/BR-M4): validate -> mint a short-lived presigned PUT -> the SPA
uploads DIRECTLY to S3 -> confirm the material row -> the S3 consumer stamps
`uploaded`/`sizeBytes`. Bytes never traverse Lambda, so a 500 MB file costs no
function duration and is not bound by the API Gateway payload limit.

Malware scanning (N1/J3) is modelled as three states, not a boolean:
`PendingScan` -> `Clean` | `Quarantined`. Only `Clean` is downloadable.
Three states rather than two because "not yet scanned" is transient and
shows the uploader a Scanning… state, while "failed scanning" is terminal and
needs an operator signal — a boolean would make a quarantined file look like a
permanently slow one.

Content Library has been extracted to library_service.py (US-2.20 rework).
"""
from __future__ import annotations

from _conventions.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from _conventions.validation import require_enum, require_int, require_str
from models import (
    ALLOWED_EXTENSIONS,
    COMMUNITY,
    CONTENT_TYPES,
    DOWNLOAD_URL_SECONDS,
    KIND_FILE,
    KIND_LINK,
    MAX_MATERIAL_BYTES,
    SCAN_CLEAN,
    SCAN_PENDING,
    STATUS_CANCELLED,
    UPLOAD_URL_SECONDS,
    can_manage,
    can_view,
    content_type_for,
    material_public,
    new_id,
    now_iso,
    visible_scopes,
)


def material_prefix(event_id: str) -> str:
    return f"events/{event_id}/materials/"


class MaterialService:

    def __init__(self, repo, storage, events, library=None):
        self._repo = repo
        self._storage = storage
        self._events = events
        self._library = library  # LibraryService — optional, wired in Context

    # ------------------------------------------------------------------ authz

    def _load_viewable(self, event_id: str, principal) -> dict:
        event = self._repo.get_event(event_id)
        if event is None or not can_view(event, principal):
            raise NotFoundError(message="Event not found.")
        return event

    def _load_manageable(self, event_id: str, principal) -> dict:
        event = self._load_viewable(event_id, principal)
        if not can_manage(event, principal):
            raise ForbiddenError(message="You cannot manage this event's materials.")
        if event.get("status") == STATUS_CANCELLED:
            raise ConflictError(message="Materials cannot be changed on a cancelled event.")
        return event

    # ------------------------------------------------------------------- reads

    def list_for_event(self, event_id: str, *, principal) -> dict:
        """Anyone who can VIEW the event can download its materials — RSVP is not
        a precondition (BR-A7/US-2.14).

        Quarantined materials are hidden from non-managers entirely; managers see
        them so the problem is visible to somebody who can act on it.
        """
        event = self._load_viewable(event_id, principal)
        manager = can_manage(event, principal)
        rows = []
        for mat in self._repo.list_materials(event_id):
            state = mat.get("scanState", SCAN_CLEAN)
            if state != SCAN_CLEAN and not manager:
                continue
            url = None
            if state == SCAN_CLEAN and mat.get("kind") == KIND_FILE and mat.get("uploaded"):
                # Fresh, short-lived, never stored (P-SEC-4).
                url = self._storage.presign_get(mat["s3Key"], expires_in=DOWNLOAD_URL_SECONDS)
            rows.append((mat, url))
        return {
            "items": [material_public(m, download_url=u) for m, u in rows],
            "count": len(rows),
        }

    # ------------------------------------------------------------------ writes

    def upload_url(self, event_id: str, body: dict, *, principal) -> dict:
        """Validation happens BEFORE minting, so a disallowed type or an
        oversized file never receives an upload target at all (BR-M4)."""
        event = self._load_manageable(event_id, principal)
        file_name = require_str(body.get("fileName"), "fileName", max_len=255)
        if "/" in file_name or "\\" in file_name:
            raise ValidationError("fileName must not contain path separators.")
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if extension not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Files of type '.{extension}' are not allowed. Allowed: "
                f"{sorted(set(ALLOWED_EXTENSIONS))}.")
        size = require_int(int(body.get("sizeBytes") or 0), "sizeBytes", minimum=1)
        if size > MAX_MATERIAL_BYTES:
            raise ValidationError(
                f"Files must be {MAX_MATERIAL_BYTES // (1024 * 1024)} MB or smaller.")

        key = f"{material_prefix(event_id)}{file_name}"

        # RESERVE THE MATERIAL ROW NOW, before the browser PUTs (BR-M6 rework,
        # 2026-09-04). The row used to be created only by the confirm call
        # (add()) AFTER the upload, which left a window: GuardDuty scans on the
        # PUT, and for a small file the verdict — and the Object Created event —
        # can arrive before confirm runs. Both consumers look the row up by key
        # (find_material_by_key); with no row yet, the scan verdict was logged as
        # "unknown material" and DROPPED, stranding the file at PendingScan
        # forever with no re-delivery. Creating the row here means the row always
        # exists before any object or verdict event, so neither is ever dropped.
        # This mirrors certifications' FILEKEY-pointer-at-grant-time fix for the
        # same verdict-before-owner race.
        existing = next((m for m in self._repo.list_materials(event_id)
                         if m.get("name") == file_name), None)
        if existing is not None:
            # A link, or an already-uploaded file, genuinely owns this name.
            # An un-uploaded FILE row is a prior reserve for the same name (the
            # user re-picked the same file) — reuse it so a retry is idempotent
            # and does not orphan a second row.
            if existing.get("kind") == KIND_LINK or existing.get("uploaded"):
                raise ConflictError(message=f'A material named "{file_name}" already exists.')
            material_id = existing["id"]
        else:
            reserved = {
                "id": new_id("mat"), "eventId": event_id, "kind": KIND_FILE,
                "name": file_name, "contentType": content_type_for(file_name),
                "link": None, "s3Key": key,
                "scanState": SCAN_PENDING, "uploaded": False,
                "postEvent": bool(event.get("startsAt") and event["startsAt"] <= now_iso()),
                "addedBy": principal.user_id, "addedAt": now_iso(),
            }
            self._repo.put_material(reserved, event=event)
            material_id = reserved["id"]

        # The declared size is signed into the URL (exact-match Content-Length),
        # so the SPA must send exactly the bytes it declared — it does, both come
        # from the same File object.
        url = self._storage.presign_put(key, expires_in=UPLOAD_URL_SECONDS,
                                        content_length=size)
        return {"url": url, "key": key, "fileName": file_name,
                "materialId": material_id, "expiresInSeconds": UPLOAD_URL_SECONDS}

    def add(self, event_id: str, body: dict, *, principal,
            correlation_id: str | None = None) -> dict:
        event = self._load_manageable(event_id, principal)
        name = require_str(body.get("name"), "name", max_len=255)

        kind = body.get("kind") or (KIND_LINK if body.get("link") else KIND_FILE)
        require_enum(kind, "kind", {KIND_FILE, KIND_LINK})

        existing = next((m for m in self._repo.list_materials(event_id)
                         if m.get("name") == name), None)

        # CONFIRM PATH (files): the row was already created by upload_url() as a
        # reserve, so a fast Object Created / scan verdict had somewhere to land.
        # Here we only stamp `uploaded` — we MUST NOT re-create the row or reset
        # scanState, because a verdict may already have moved it to Clean or
        # Quarantined and clobbering that back to PendingScan would re-hide a
        # file that is actually ready (or un-quarantine an infected one).
        if kind == KIND_FILE and existing is not None and existing.get("kind") == KIND_FILE:
            return self._confirm_file_material(event, existing, correlation_id)

        # A name already taken by a link (or an uploaded file with no matching
        # reserve) is a genuine conflict.
        if existing is not None:
            raise ConflictError(message=f'A material named "{name}" already exists.')

        # CREATE PATH — links only in normal operation (a file always arrives via
        # the reserve above). Kept general so a direct add still works.
        link = body.get("link")
        if kind == KIND_LINK:
            if not link or not str(link).startswith("https://"):
                raise ValidationError("A link material requires an https:// URL.")
        s3_key = None
        if kind == KIND_FILE:
            # Server derives the key (2026-08-12 security fix): never trust a
            # client-supplied s3Key — prevents cross-event file access injection.
            s3_key = f"{material_prefix(event_id)}{name}"

        material = {
            "id": new_id("mat"), "eventId": event_id, "kind": kind, "name": name,
            "contentType": body.get("contentType") or (
                "Link" if kind == KIND_LINK else content_type_for(name)),
            "link": link, "s3Key": s3_key,
            # A link needs no scan; a file is unscanned until GuardDuty says
            # otherwise, and stays invisible to members until then (N1).
            "scanState": SCAN_CLEAN if kind == KIND_LINK else SCAN_PENDING,
            "uploaded": kind == KIND_LINK,
            "postEvent": bool(event.get("startsAt") and event["startsAt"] <= now_iso()),
            "addedBy": principal.user_id, "addedAt": now_iso(),
        }
        if kind == KIND_FILE:
            size_bytes = self._storage.head_object_size(s3_key)
            if size_bytes is not None:
                material["uploaded"] = True
                material["sizeBytes"] = size_bytes
                material["uploadedAt"] = now_iso()
        self._repo.put_material(material, event=event)
        self._maybe_promote_to_library(event, material)
        if material["postEvent"]:
            self._events.publish("MaterialsAdded", {
                "eventId": event_id, "materialId": material["id"], "name": name,
                "notifyRsvps": True,
            }, correlation_id=correlation_id)
        return material_public(material)

    def _confirm_file_material(self, event: dict, material: dict,
                               correlation_id: str | None) -> dict:
        """Confirm a reserved file material after the browser PUT completes.

        Idempotent and verdict-safe: stamps `uploaded`/`sizeBytes` from S3's own
        HEAD (never the client's claim) only if not already stamped by the
        Object Created consumer, and NEVER touches scanState. Then runs the same
        notify + completed-event Library promotion the create path does.
        """
        event_id = event["id"]
        if not material.get("uploaded"):
            # The browser PUT precedes this call, so the object is normally
            # present; if the Object Created event beat us here it has already
            # stamped uploaded and this HEAD is a harmless confirm.
            size_bytes = self._storage.head_object_size(material["s3Key"])
            if size_bytes is not None:
                self._repo.set_material_upload_state(
                    event_id, material["id"], size_bytes=size_bytes,
                    uploaded_at=now_iso())
        fresh = self._repo.get_material(event_id, material["id"]) or material
        # A file just became uploaded — same completed-event promotion the create
        # path runs (idempotent + qualification-gated inside).
        self._maybe_promote_to_library(event, fresh)
        if material.get("postEvent"):
            # Only POST-event materials notify (BR-M5) — pre-event uploads are
            # routine preparation and would spam RSVPs.
            self._events.publish("MaterialsAdded", {
                "eventId": event_id, "materialId": material["id"],
                "name": material.get("name"), "notifyRsvps": True,
            }, correlation_id=correlation_id)
        return material_public(fresh)

    def _maybe_promote_to_library(self, event: dict, material: dict) -> None:
        """Promote a material to the Content Library when its parent event is
        already Completed (BR-LIB-P1). Closes the 'complete first, then add
        materials' gap the completion-time pass (Trigger A) misses."""
        if self._library is None:
            return
        from models import STATUS_COMPLETED
        if event.get("status") == STATUS_COMPLETED:
            self._library.promote_single_material(material, event)

    def replace(self, event_id: str, material_id: str, body: dict, *, principal) -> dict:
        event = self._load_manageable(event_id, principal)
        existing = self._repo.get_material(event_id, material_id)
        if existing is None:
            raise NotFoundError(message="Material not found.")
        name = require_str(body.get("name") or existing.get("name"), "name", max_len=255)
        if name != existing.get("name") and any(
                m.get("name") == name for m in self._repo.list_materials(event_id)):
            raise ConflictError(message=f'A material named "{name}" already exists.')

        updated = {k: v for k, v in existing.items()
                   if k not in ("pk", "sk", "gsi3pk", "gsi3sk")}
        updated["name"] = name
        if body.get("link"):
            updated["link"] = body["link"]
        if body.get("s3Key") or body.get("newFile"):
            # 2026-08-12: derive key from the material name (security fix).
            updated["s3Key"] = f"{material_prefix(event_id)}{existing.get('name', '')}"
            updated["scanState"] = SCAN_PENDING
            updated["uploaded"] = False
            updated.pop("sizeBytes", None)
            updated.pop("uploadedAt", None)
            # Same confirm-time race handling as add(): the new object may have
            # landed (and its Object Created event been dropped) before this
            # confirm. Scan state stays PendingScan regardless — new bytes need
            # a new verdict.
            size_bytes = self._storage.head_object_size(updated["s3Key"])
            if size_bytes is not None:
                updated["uploaded"] = True
                updated["sizeBytes"] = size_bytes
                updated["uploadedAt"] = now_iso()
        if body.get("contentType"):
            updated["contentType"] = body["contentType"]
        self._repo.put_material(updated, event=event)
        # Same completed-event promotion as add() (e.g. a link edited onto a
        # material of an already-completed event).
        self._maybe_promote_to_library(event, updated)
        return material_public(updated)

    def remove(self, event_id: str, material_id: str, *, principal) -> None:
        """S3 object FIRST, metadata row second, and fail closed in between
        (BR-M7). An object with no owning record is invisible to the portal but
        still billable and still reachable by anyone holding an old URL — worse
        than a row whose object is already gone, which `uploaded=False` models
        safely."""
        self._load_manageable(event_id, principal)
        material = self._repo.get_material(event_id, material_id)
        if material is None:
            raise NotFoundError(message="Material not found.")
        if material.get("kind") == KIND_FILE and material.get("s3Key"):
            self._storage.delete_object(material["s3Key"])
        self._repo.delete_material(event_id, material_id)
        # BR-LIB-P5: auto-remove the corresponding Library resource if one exists.
        if self._library is not None:
            self._library.remove_by_material_id(material_id)
