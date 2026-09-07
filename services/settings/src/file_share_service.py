"""External file-share slots (US-8.13, reworked 2026-08-04) — CL/UGL only.

Model: one link record = ONE FILE SLOT (folder + fileName -> S3 key
`<folder>/<fileName>` in the predefined community bucket, foundation
`FileShareBucket`). Leaders never choose buckets; they pick an existing
folder or create a new one. fileName is unique within its folder (409).

Upload side (curl-only, user decision 2026-08-04 — no upload page):
`get_upload_url` mints a FRESH short-lived (1h) presigned PUT at Copy-Link
time and returns a ready-to-run `curl -X PUT --upload-file ...` command.
Nothing long-lived is stored — the old model persisted a presigned URL at
creation time, which (a) was signed with the Lambda role's TEMPORARY
credentials and died within hours regardless of ExpiresIn, and (b) could not
be revoked. Minting at copy time bounds any issued URL to <=1h and lets
revocation take effect immediately for all future mints.

Approved US-8.13 deviations (audit 2026-08-04): no link expiry (Delete is the
kill switch), no max-file-size enforcement, curl instead of a link page,
revocation bounded by the <=1h life of an already-issued URL.

Owner side: `list_files` lists the slot's folder with fresh 5-min presigned
GET download URLs (never stored). CL: any slot; UGL: own slots only.

Performance rework (2026-08-04): the listing never touches S3. `uploaded` is a
stored field maintained by the S3 Object Created/Deleted consumer
(`file_share_event_consumer`), and listings are cursor-paginated — UGL by GSI1
Query on their own partition, CL by paged Scan. Uniqueness is a conditional put
on a FILEKEY pointer item instead of a full-table scan per create.
"""
from __future__ import annotations

import re

from _conventions.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from _conventions.validation import require_str
from models import file_share_link_public, listing, new_id, now_iso

_ROLES_ALLOWED = {"CommunityLeader", "UserGroupLeader"}
# Mockup hint: "Allowed: letters, numbers, hyphens."
_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,99}$")
# No path separators or control characters; must not be a dot-name.
_FILENAME_RE = re.compile(r"^[^/\\\x00-\x1f]{1,255}$")

UPLOAD_URL_SECONDS = 3600  # Option A — short-lived, Lambda-role signed
DOWNLOAD_URL_SECONDS = 300


class FileShareService:

    def __init__(self, repo, storage, events):
        self._repo = repo
        self._storage = storage
        self._events = events

    # ---------- helpers ----------

    def _require_leader(self, role: str) -> None:
        if role not in _ROLES_ALLOWED:
            raise ForbiddenError(message="Only Community Leaders and User Group Leaders can manage file-share links.")

    def _conflict_message(self, key: str, folder: str, file_name: str) -> str:
        """A DEACTIVATED slot keeps its claim on the name (behavior change
        2026-08-04). Previously a revoked slot freed it, which let two records
        own one S3 key: an upload to the new slot would overwrite the file the
        deactivated slot still serves through Open, and the S3 event consumer
        could not tell which slot to stamp. Delete is the way to free a name —
        it removes the file too, so nothing is left behind ambiguously owned.
        Say so explicitly, otherwise the 409 looks wrong to a leader who can see
        the blocking row is deactivated."""
        base = f'"{file_name}" already exists in folder "{folder}".'
        pointer = self._repo.get_file_key_pointer(key) or {}
        existing = self._repo.get_file_share_link(pointer.get("linkId") or "") or {}
        if existing.get("revoked"):
            return (base + " That slot is deactivated but still holds the name —"
                    " delete it to free the name, or choose a different file name.")
        return base

    def _load_owned(self, link_id: str, *, actor: str, role: str) -> dict:
        """Load a slot enforcing visibility: CL any, UGL own only (fail closed)."""
        self._require_leader(role)
        link = self._repo.get_file_share_link(link_id)
        if link is None:
            raise NotFoundError(message="Link not found.")
        if role == "UserGroupLeader" and link.get("createdBy") != actor:
            raise ForbiddenError(message="You can only use links you created.")
        return link

    # ---------- operations ----------

    def create_link(self, body: dict, *, actor: str, role: str, actor_email: str = "") -> dict:
        self._require_leader(role)
        folder = require_str(body.get("folder"), "folder", max_len=100)
        if not _FOLDER_RE.match(folder):
            raise ValidationError(message="Folder name may contain only letters, numbers, and hyphens.")
        file_name = require_str(body.get("fileName"), "fileName", max_len=255)
        if not _FILENAME_RE.match(file_name) or file_name in (".", ".."):
            raise ValidationError(message="File name must not contain slashes or control characters.")
        note = require_str(body.get("note", ""), "note", max_len=500, min_len=0)

        link = {
            "id": new_id("share"), "folder": folder, "fileName": file_name,
            "key": f"{folder}/{file_name}",
            "note": note, "createdBy": actor, "createdByEmail": actor_email,
            "createdByRole": role, "createdAt": now_iso(), "revoked": False,
            "uploaded": False,
        }
        # Uniqueness within the shared folder, across ALL leaders' slots: claim
        # the key with a conditional put on the FILEKEY pointer. O(1) and
        # race-free — the previous full-table scan was both O(total slots) per
        # create and lost to concurrent creates of the same name.
        if not self._repo.put_file_key_pointer(link["key"], link["id"]):
            raise ConflictError(message=self._conflict_message(link["key"], folder, file_name))
        # An object can predate its slot (legacy uploads, or a slot deleted while
        # its file lingered). Release the claim so the name stays free.
        if self._storage.object_exists(link["key"]):
            self._repo.delete_file_key_pointer(link["key"])
            raise ConflictError(message=f'"{file_name}" already exists in folder "{folder}".')

        self._repo.put_file_share_link(link)
        self._repo.add_folder(folder)
        self._events.publish("SettingsChanged", {"changedBy": actor, "fileShareLinkCreated": link["id"]})
        return file_share_link_public(link)

    def list_links(self, *, actor: str, role: str, limit: int | None = None,
                   cursor: str | None = None) -> dict:
        """CL sees every slot (owner-side visibility across the community);
        UGL sees only slots they created — fail closed for any other role.

        Zero S3 calls: `uploaded`/`sizeBytes`/`uploadedAt` are stored fields kept
        current by the S3 event consumer. Paginated when `limit`/`cursor` are
        supplied (the SPA always supplies them); the unpaged path is kept for
        callers that want everything.
        """
        self._require_leader(role)
        is_cl = role == "CommunityLeader"
        if limit or cursor:
            page = limit or 25
            items, next_cursor = self._repo.scan_links_page(limit=page, cursor=cursor) if is_cl \
                else self._repo.query_creator_page(actor, limit=page, cursor=cursor)
            return listing(items, file_share_link_public, cursor=next_cursor)
        items = self._repo.list_all_file_share_links() if is_cl \
            else self._repo.list_file_share_links_by_creator(actor)
        return listing(items, file_share_link_public)

    def list_folders(self, *, actor: str, role: str) -> dict:
        """Bucket (readonly in UI) + existing folders for the Create selector:
        union of the folder registry (one get_item — was a full-table scan on
        every dialog open) and bucket top-level prefixes.

        A folder name can outlive its last slot here. That is deliberate: this is
        a pick-or-create list, so a stale suggestion costs nothing, whereas
        reference-counting folders on delete would cost a query per delete.
        """
        self._require_leader(role)
        folders = set(self._repo.list_registered_folders())
        folders.update(self._storage.list_top_level_folders())
        return {"bucket": self._storage.bucket, "folders": sorted(f for f in folders if f)}

    def get_upload_url(self, link_id: str, *, actor: str, role: str) -> dict:
        """Copy Link: mint a fresh 1h presigned PUT + the full curl command.
        Revocation is checked HERE, at mint time — that is what makes Delete
        effective immediately for any future copy."""
        link = self._load_owned(link_id, actor=actor, role=role)
        if link.get("revoked"):
            raise ForbiddenError(message="This link is deactivated and can no longer be used for uploads.")
        key = link["key"]
        url = self._storage.presign_put(key, expires_in=UPLOAD_URL_SECONDS)
        file_name = link["fileName"]
        return {
            "url": url, "key": key, "fileName": file_name,
            "expiresInSeconds": UPLOAD_URL_SECONDS,
            "curl": f'curl -X PUT --upload-file "{file_name}" "{url}"',
        }

    def list_files(self, link_id: str, *, actor: str, role: str) -> dict:
        """Open: owner-side folder view (US-8.13 view/download) with fresh
        short-lived download URLs. Allowed for DEACTIVATED slots too (their
        files remain); hard-deleted slots are gone entirely."""
        link = self._load_owned(link_id, actor=actor, role=role)
        files = self._storage.list_folder(link["folder"])
        for f in files:
            f["downloadUrl"] = self._storage.presign_get(
                f"{link['folder']}/{f['name']}", expires_in=DOWNLOAD_URL_SECONDS)
        return {"items": files, "count": len(files)}

    def revoke_link(self, link_id: str, *, actor: str, role: str) -> dict:
        """Deactivate: stops all future upload-URL mints (Copy Link disabled).
        Record and any uploaded file remain — delete_link removes both."""
        link = self._load_owned(link_id, actor=actor, role=role)
        link["revoked"] = True
        self._repo.put_file_share_link(link)
        self._events.publish("SettingsChanged", {"changedBy": actor, "fileShareLinkRevoked": link_id})
        return file_share_link_public(link)

    def delete_link(self, link_id: str, *, actor: str, role: str) -> None:
        """Permanently delete the slot AND its uploaded file (user decision
        2026-08-04 — supersedes the earlier files-remain-after-delete behavior).
        S3 delete goes first and fails closed: if it errors, the record stays,
        so no file is ever orphaned without an owning slot.

        The FILEKEY pointer is released LAST, so a crash mid-delete leaves the
        name claimed rather than claimable while a record still exists — the
        fail-closed direction for a uniqueness guard.
        """
        link = self._load_owned(link_id, actor=actor, role=role)
        if link.get("key"):
            self._storage.delete_object(link["key"])
        self._repo.delete_file_share_link(link_id)
        if link.get("key"):
            self._repo.delete_file_key_pointer(link["key"])
        self._events.publish("SettingsChanged", {"changedBy": actor, "fileShareLinkDeleted": link_id})
