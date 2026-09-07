"""Event-scoped external upload slots (US-2.21, reworked 2026-08-13).

Redesigned to match the File Sharing pattern: one slot = one file. The CL/UGL
creates a slot by specifying a filename, then uses "Copy Link" to mint a fresh
presigned PUT URL (+ curl command) each time they need to share it. No token
exchange, no portal API endpoint — the external contributor PUTs directly to S3.

Upload side: `get_upload_url` mints a FRESH short-lived (60-min) presigned PUT
at Copy-Link time. Nothing long-lived is stored — the signature dies with the
Lambda role's session, so a leaked URL is bounded to <=60 min.

The S3 consumer (`consumers.py`) stamps `uploaded` when the object appears.
"""
from __future__ import annotations

import os

from _conventions.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from _conventions.logger import get_logger, log
from _conventions.validation import require_str
from models import (
    DOWNLOAD_URL_SECONDS,
    can_manage,
    listing,
    new_id,
    now_iso,
)

_logger = get_logger("events.upload_link_service")

UPLOAD_URL_SECONDS = 3600  # 60 minutes (matches File Sharing)


def material_prefix(event_id: str) -> str:
    return f"events/{event_id}/materials/"


def upload_slot_public(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "eventId": item.get("eventId"),
        "fileName": item.get("fileName"),
        "s3Key": item.get("s3Key"),
        "note": item.get("note"),
        "uploaded": bool(item.get("uploaded", False)),
        "sizeBytes": int(item["sizeBytes"]) if item.get("sizeBytes") is not None else None,
        "uploadedAt": item.get("uploadedAt"),
        "revoked": bool(item.get("revoked", False)),
        "createdBy": item.get("createdBy"),
        "createdAt": item.get("createdAt"),
    }


class UploadLinkService:
    def __init__(self, repo, storage, events=None):
        self._repo = repo
        self._storage = storage
        self._events = events

    def _load_manageable(self, event_id: str, principal):
        event = self._repo.get_event(event_id)
        if event is None:
            raise NotFoundError(message="Event not found.")
        if not can_manage(event, principal):
            raise ForbiddenError(message="You cannot manage upload links for this event.")
        return event

    # ----------------------------------------------------------------- create

    def create(self, event_id: str, body: dict, *, principal,
               correlation_id: str | None = None) -> dict:
        self._load_manageable(event_id, principal)
        file_name = require_str(body.get("fileName"), "fileName", max_len=255)
        if "/" in file_name or "\\" in file_name or file_name in (".", ".."):
            raise ValidationError("fileName must not contain path separators.")
        note = require_str(body.get("note", ""), "note", max_len=500, min_len=0)

        # Uniqueness: reject if a material OR another upload slot with this name
        # already exists for this event.
        if any(m.get("name") == file_name for m in self._repo.list_materials(event_id)):
            raise ConflictError(
                message=f'A material named "{file_name}" already exists for this event.')
        if any(s.get("fileName") == file_name and not s.get("revoked")
               for s in self._repo.list_upload_links(event_id)):
            raise ConflictError(
                message=f'An upload slot for "{file_name}" already exists for this event.')

        s3_key = f"{material_prefix(event_id)}{file_name}"
        slot = {
            "id": new_id("evul"), "eventId": event_id,
            "fileName": file_name, "s3Key": s3_key,
            "folderPrefix": material_prefix(event_id),
            "note": note, "revoked": False, "uploaded": False,
            "createdBy": principal.user_id,
            "createdAt": now_iso(),
        }
        self._repo.put_upload_link(slot)

        if self._events:
            self._events.publish("EventUpdated", {
                "eventId": event_id, "kind": "upload-link-created",
                "linkId": slot["id"], "actor": principal.user_id, "audit": True,
            }, correlation_id=correlation_id)

        return upload_slot_public(slot)

    # -------------------------------------------------------------- copy link

    def get_upload_url(self, event_id: str, link_id: str, *, principal) -> dict:
        """Copy Link: mint a fresh presigned PUT + the full curl command.
        Revocation is checked HERE, at mint time — Delete/Deactivate is effective
        immediately for any future copy."""
        self._load_manageable(event_id, principal)
        link = self._repo.get_upload_link(event_id, link_id)
        if link is None:
            raise NotFoundError(message="Upload slot not found.")
        if link.get("revoked"):
            raise ForbiddenError(message="This upload slot is deactivated.")

        key = link["s3Key"]
        url = self._storage.presign_put(key, expires_in=UPLOAD_URL_SECONDS)
        return {
            "url": url, "key": key, "fileName": link["fileName"],
            "expiresInSeconds": UPLOAD_URL_SECONDS,
            "curl": f'curl -X PUT --upload-file "{link["fileName"]}" "{url}"',
        }

    # ----------------------------------------------------------------- list

    def list_for_event(self, event_id: str, *, principal) -> dict:
        self._load_manageable(event_id, principal)
        items = self._repo.list_upload_links(event_id)
        return listing(items, upload_slot_public)

    # -------------------------------------------------------------- delete

    def delete(self, event_id: str, link_id: str, *, principal,
               correlation_id: str | None = None) -> None:
        """Hard-delete: removes the slot record, the S3 file, and any uploaded-file
        records. Used when the material is no longer needed."""
        self._load_manageable(event_id, principal)
        link = self._repo.get_upload_link(event_id, link_id)
        if link is None:
            raise NotFoundError(message="Upload slot not found.")
        # Delete the S3 object (if it exists).
        if link.get("s3Key"):
            try:
                self._storage.delete_object(link["s3Key"])
            except Exception as exc:  # noqa: BLE001 — best-effort; slot is still removed
                log(_logger, 30, "S3 delete_object failed (best-effort; slot still removed)",
                    eventId=event_id, linkId=link_id, key=link["s3Key"], error=str(exc))
        # Delete any uploaded-file records for this link.
        for uf in self._repo.list_uploaded_files(event_id, link_id):
            self._repo._t.delete_item(Key={"pk": f"EVENT#{event_id}",
                                            "sk": f"UF#{link_id}#{uf.get('name','')}"})
        # Delete the slot itself.
        self._repo.delete_upload_link(event_id, link_id)
        if self._events:
            self._events.publish("EventUpdated", {
                "eventId": event_id, "kind": "upload-link-deleted",
                "linkId": link_id, "actor": principal.user_id, "audit": True,
            }, correlation_id=correlation_id)

    # -------------------------------------------------------------- revoke

    def revoke(self, event_id: str, link_id: str, *, principal,
               correlation_id: str | None = None) -> None:
        self._load_manageable(event_id, principal)
        link = self._repo.get_upload_link(event_id, link_id)
        if link is None:
            raise NotFoundError(message="Upload slot not found.")
        self._repo.set_upload_link_revoked(event_id, link_id)
        if self._events:
            self._events.publish("EventUpdated", {
                "eventId": event_id, "kind": "upload-link-revoked",
                "linkId": link_id, "actor": principal.user_id, "audit": True,
            }, correlation_id=correlation_id)

    # ---------------------------------------------------------- list files

    def list_files(self, event_id: str, link_id: str, *, principal) -> dict:
        """Show the uploaded file for this slot (at most one)."""
        self._load_manageable(event_id, principal)
        link = self._repo.get_upload_link(event_id, link_id)
        if link is None:
            raise NotFoundError(message="Upload slot not found.")
        rows = self._repo.list_uploaded_files(event_id, link_id)
        out = []
        for r in rows:
            url = self._storage.presign_get(
                f"{link['s3Key']}", expires_in=DOWNLOAD_URL_SECONDS)
            out.append({**r, "downloadUrl": url})
        return {"items": out, "count": len(out)}
