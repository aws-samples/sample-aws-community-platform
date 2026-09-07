# Plan — File Sharing rework (Unit 11 Settings, US-8.13 change request)

**Date**: 2026-08-04 · **Status**: EXECUTED (approved in chat — "a link record now represents one file slot")
**Trigger**: User-reported defect — "Copy link" produced a raw presigned PUT URL unusable in a browser; analysis then found the stored URL dies within hours (Lambda temp credentials), revoke did not stop uploads, single overwritable object, size unenforced, owner view/download missing.

## Approved direction (user decisions, 2026-08-04)
- **No separate upload UI** — external party uses **curl only**; "Copy Link" copies a **full ready-to-run curl command**.
- **Option A lifetime**: presigned PUT minted fresh at Copy-Link time, short-lived (1 hour); no new signing credentials.
- **Leader performs the mint** (authenticated endpoint) — uploader receives only the signed URL. No unauthenticated route.
- **Bucket predefined, readonly** in UI (foundation `FileShareBucket`, created at infra provisioning — already exists).
- **Folder**: create new OR select an existing folder in that bucket.
- **File name**: required, unique within the folder. One link record = one file slot.
- **Remove** "Link expires" and "Max file size" from the model and UI (**requirement deviation from US-8.13/mockup** — links live until deleted; size advisory dropped).
- **"Open" button** shows the folder containing the file (owner-side list + download — closes the missing US-8.13 view/download gap; modal, not a new page).
- Old links/fixtures are **legacy-dead** (schema incompatible); no migration.

## Requirement deviations recorded against US-8.13
1. No expiry on links (was 7/14/30/90 days) — revoke/Delete is the only kill switch.
2. No max-file-size enforcement (field removed).
3. Revocation stops **minting new upload URLs** immediately; an already-issued URL remains valid ≤1h (bounded exposure accepted with Option A).
4. Upload side is curl, not a link page.

## Steps

### Contract — `contracts/services/settings/openapi.yaml`
- [x] 1. Rework `FileShareLink` schema: required `{id, folder, fileName, revoked}`; add `key`; **remove** `url`, `expiresAt`, `maxFileSizeMb`.
- [x] 2. `createFileShareLink` body: required `{folder, fileName}`, optional `note`; add `409` response (duplicate fileName in folder).
- [x] 3. New `GET /settings/file-share/folders` → `{bucket, folders[]}` (union of link-record folders + S3 top-level prefixes).
- [x] 4. New `GET /settings/file-share/{id}/upload-url` → `{url, key, fileName, expiresInSeconds, curl}` (403 revoked-or-foreign-UGL, 404).
- [x] 5. New `GET /settings/file-share/{id}/files` → `{items: [{name, sizeBytes, lastModified, downloadUrl}], count}` (fresh 5-min presigned GETs).
- [x] 6. No api-edge change needed (all under existing `/settings` base path `{proxy+}`) — verify only.

### Backend — `services/settings/`
- [x] 7. `file_share_service.py`: `create_link(folder, fileName, note)` — folder regex `[a-z0-9-]`, fileName validation, uniqueness (link records + S3 `head_object`), key `=<folder>/<fileName>`; **no presign at creation, no URL stored**; keep CL/UGL authz + `SettingsChanged` event.
- [x] 8. New `get_upload_url(id)`: 404 unknown; 403 revoked or UGL-not-creator; mint presigned PUT (3600s) + compose curl string.
- [x] 9. New `list_folders()` and `list_files(id)` (CL any, UGL own; `ListObjectsV2` prefix-scoped; presigned GET 300s — finally uses `providers.presign_get`).
- [x] 10. `revoke_link`: unchanged semantics; status model becomes Active/Deleted (drop Expired).
- [x] 11. `providers.FileShareStorage`: add `head_object`, `list_objects`; drop the 7-day cap comment (1h constant); keep fail-closed.
- [x] 12. `app.py` routes + `models.file_share_link_public` updated; `fixtures.json` file-share entries reworked to new shape.
- [x] 13. Tests: rework existing file-share tests; add uniqueness (409), revoked-blocks-minting, UGL/CL authz on all new ops, folder union, curl composition. Target: settings suite green.

### Frontend — `frontend/src/features/singletons.tsx` (mirror mockup `leader/notifications-prefs.html` File Sharing tab)
- [x] 14. Create Share Link modal: **Bucket readonly** (from `/folders` response) with mockup hint text; **Folder** = select existing ∣ "New folder…" + text input; **File name** required; **Note** kept; **expiry + max-size fields removed**; keep mockup warning banner (reworded: "until you delete the link").
- [x] 15. Table per mockup: Folder (bold + `s3://bucket/folder/` faint path), File name, Created, Status (Active/Deleted), Actions = 📋 Copy Link ∣ Open ∣ Delete. Copy Link → `GET /upload-url` → copies the full curl command (button feedback "✓ Copied", disabled when Deleted).
- [x] 16. "Open" → modal listing the folder's files (name, size, date, Download via fresh presigned GET) — replaces mockup's `file-share.html` target per "no separate UI" decision.
- [x] 17. Info banner reworded (no expiry claim; write-only + revocable kept).

### Verification
- [x] 18. `pytest` settings suite; `ruff` clean; contract gate for settings passes; `npm run build` clean.
- [x] 19. Update `aidlc-state.md` (change-request row) + audit.md; note US-2.21 (Events, mock) must reuse this reworked model when built.
