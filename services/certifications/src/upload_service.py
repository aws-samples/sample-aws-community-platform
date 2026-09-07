"""Upload grants (D5/D6, BR-C7, J1).

The system names the file: `certifications/<kind>/<userId>/<timestampMs>-<random>.<ext>`
— unique by construction, so the user's original filename is display metadata
only and (N3=B consequence) a badge re-upload is a NEW public URL, making CDN
invalidation structurally unnecessary.

The FILEKEY pointer is written AT GRANT TIME so a GuardDuty verdict that lands
before the owning claim/definition exists still has somewhere to record itself
(verdict-before-owner race). Orphaned grants (file never referenced) have no
ownerId and are invisible to every read path.
"""
from __future__ import annotations

import secrets
import time

from _conventions.validation import require, require_str
from models import MAX_UPLOAD_BYTES, SCAN_PENDING, now_iso


class UploadService:
    def __init__(self, repo, storage):
        self._repo = repo
        self._storage = storage

    def grant(self, body: dict, *, principal, kind: str, extensions: dict) -> dict:
        file_name = require_str(body.get("fileName"), "fileName", max_len=200)
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        require(ext in extensions, "fileName",
                f"file type must be one of: {', '.join(sorted(extensions))}")
        content_type = body.get("contentType") or extensions[ext]
        require(content_type == extensions[ext], "contentType",
                f"must be {extensions[ext]} for a .{ext} file")

        key = (f"certifications/{kind}/{principal.user_id}/"
               f"{int(time.time() * 1000)}-{secrets.token_hex(6)}.{ext}")
        grant = self._storage.grant_upload(key, content_type=content_type,
                                           max_bytes=MAX_UPLOAD_BYTES)
        self._repo.put_filekey_pointer(key, {
            "kind": kind,
            "grantedTo": principal.user_id,
            "fileName": file_name,
            "scanStatus": SCAN_PENDING,
            "grantedAt": now_iso(),
        })
        return grant
