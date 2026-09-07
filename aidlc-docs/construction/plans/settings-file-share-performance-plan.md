# Settings — File Share listing: bug fix + performance rework (2026-08-04)

**Trigger**: user report — "File Share page for User Group leader shows *An unexpected error occurred.*"

**Root cause**: `list_links` routes non-CommunityLeader callers to
`list_file_share_links_by_creator`, which queries `IndexName="GSI1"`. The
`settings-${Stage}` table was never given that index (`service-settings-data.yaml`
defines `pk`/`sk` only), so DynamoDB raises `ValidationException`, which is not an
`AppError` and is flattened to a generic 500 by `to_response`. Unit tests passed
throughout because `tests/conftest.py` creates the table WITH `GSI1` under moto.
CommunityLeader was unaffected: that branch uses `Scan`.

**Scope approved by user (2026-08-04)**: all three phases, plus a `Created By`
column on the Community Leader view, plus replacing read-time S3 calls with a
table-backed `uploaded` flag maintained by an S3 event trigger.

---

## Phase A — unbreak the page

- [x] A1. Add `GSI1` (`gsi1pk` HASH / `gsi1sk` RANGE, `Projection: ALL`) to
      `infra/services/service-settings-data.yaml`. Sparse index — settings and
      template items carry no `gsi1pk`, so they are not projected.
- [x] A2. Add the missing `LastEvaluatedKey` loop to
      `list_file_share_links_by_creator` (silently truncated at 1MB).
- [x] A3. Add `_require_leader(role)` to `list_links` — Members currently fall
      through to the non-CL branch and would get an empty 200 instead of 403.

## Phase B — table-backed `uploaded` (no S3 on read) + Created By

- [x] B1. Pointer item `FILEKEY#<folder>/<fileName> / META -> {linkId}` in the
      repository: `put_file_key_pointer` (conditional, `attribute_not_exists`),
      `get_file_key_pointer`, `delete_file_key_pointer`.
- [x] B2. `create_link` uses the pointer's conditional put for uniqueness —
      replaces the full-table scan (O(total) per create) and closes the race
      where two concurrent creates both pass the scan check.
- [x] B3. Persist `uploaded` / `sizeBytes` / `uploadedAt` on the slot record;
      `set_upload_state` / `clear_upload_state` in the repository.
- [x] B4. `FileShareEventConsumer`: handles S3 `Object Created` / `Object Deleted`
      via the pointer lookup, idempotent on the EventBridge event id, ignores
      out-of-order events by comparing timestamps.
- [x] B5. `list_links` reads `uploaded` from the record — zero S3 calls. The
      per-slot "Open" folder view keeps its live listing (single user action).
- [x] B6. Foundation: `NotificationConfiguration.EventBridgeConfiguration` on
      `FileShareBucket`. Bucket-side only — names no consumer, so no circular
      dependency with the settings app stack.
- [x] B7. Settings app stack: `AWS::Events::Rule` on the DEFAULT bus (S3 events
      do not land on the custom platform bus) + `AWS::Lambda::Permission`.
- [x] B8. Denormalize `createdByEmail` from the `email` claim at create time and
      expose it; render a `Created By` column for CommunityLeader only.
- [x] B9. `providers.list_folder` — paginate `list_objects_v2` (was capped at
      1000 keys, silently wrong beyond that).
- [x] B10. One-time backfill script: stamp pointer items + upload state for
      pre-existing slots, otherwise already-uploaded files read as not uploaded
      once the S3 read path is gone.

## Phase C — cursor pagination end-to-end

- [x] C1. Contract: `limit`/`cursor` query params on `listFileShareLinks`,
      `cursor` on `FileShareLinkList`, new `FileShareLink` fields.
- [x] C2. Repository: `query_creator_page` (GSI1) and `scan_links_page` (CL),
      both returning `(rows, next_cursor)`, reusing the member-profiles
      `encode_cursor`/`decode_cursor` shape (invalid cursor -> 400).
- [x] C3. `app.py`: `_parse_limit` (1..200) + `cursor` passthrough.
- [x] C4. Frontend: `FileShareCard` -> `DataTable` server mode with the existing
      `ServerPaging` interface and cursor stack.

## Verification

- [x] V1. `python3 -m pytest services/settings -q`
- [x] V2. `make contract-tests SVC=settings`
- [x] V3. `ruff check .`
- [x] V4. `cfn-lint` on the three changed templates
- [x] V5. `cd frontend && npm run build`

---

## Outcome (2026-08-04)

All three phases executed. Gates: 74 settings tests pass (was 63), `make test`
green repo-wide, contract gate 12/12, ruff clean, cfn-lint clean on the three
changed templates, `npm run build` clean.

### Behavior change requiring notice
A **deactivated slot now keeps its claim on `folder/fileName`**. Previously a
revoked slot freed the name, which allowed two records to own one S3 key: an
upload to the newer slot would overwrite the file the deactivated slot still
serves through Open, and the S3 event consumer could not resolve the key to a
single slot. `Delete` is now the only way to free a name, which matches its
documented role as the kill switch and removes the file at the same time. The
409 message names the cause so the leader is not left guessing.
`test_create_allowed_when_only_a_revoked_slot_holds_the_name` was replaced by
`test_deactivated_slot_still_holds_the_name`.

### Deploy order (matters)
1. `service-settings-data` — creates GSI1. Only one index change is permitted
   per `UpdateTable`, and the sparse index backfills from attributes the
   repository has always written, so no item rewrite is needed.
2. `foundation` — enables EventBridge notifications on `FileShareBucket`.
3. `service-settings-app` — the rule, the permission, and the new code.
4. `python3 infra/tools/backfill_file_share_state.py --table settings-<stage>
   --bucket <name>` (dry run first, then `--apply`).

Step 4 is not optional: without it, pre-existing slots have no stored upload
state and no FILEKEY pointer, so already-uploaded files would read as "Awaiting
upload", future uploads to them could not be resolved to a slot, and their names
would not be protected by the new uniqueness guard.

### Not done (deliberately)
- Folder names are never reference-counted out of `FOLDERS/REGISTRY`. A stale
  suggestion in a pick-or-create selector is harmless; counting would add a
  query per delete.
- The per-slot "Open" view still lists S3 live. That is one deliberate user
  action, not the list path, and it needs fresh presigned download URLs anyway.
