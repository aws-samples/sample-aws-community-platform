# Code Generation Plan — Content Library Rework

## Unit: content-library-rework
## Stories: US-2.19 (updated), US-2.20, US-2.22, US-2.23, US-2.24, US-2.25, US-2.26

---

## Unit Context

**Primary service**: Events (`services/events/`)
**Secondary service**: Contributions-scoring (`services/contributions-scoring/`)
**Frontend**: `frontend/src/`
**Infrastructure**: `infra/services/service-events-data.yaml`, `infra/services/service-events-app.yaml`, `infra/api-edge.yaml`
**Contract**: `contracts/services/events/openapi.yaml`, `contracts/services/contributions-scoring/openapi.yaml`

**Dependencies**: Unit 4 Events (complete), Unit 7 Contributions & Scoring (complete)

---

## Step-by-Step Plan

---

### Step 1 — New file: `services/events/src/library_repository.py`
[x] Create new file.
DynamoDB access layer for the `library-${Stage}` table.

Implement `LibraryRepository` class with:
- `__init__(self, table, tags_table=None)` — accepts DynamoDB Table resource; tags stored in same table
- `put_resource(resource: dict) -> None` — write `RESOURCE#<id>` / `META` item; maintain GSI1 sparse key (present only for Clean resources), GSI2 key (`MAT#<materialId>` when materialId present), GSI3 key (`CON#<contributionId>` when contributionId present)
- `get_resource(resource_id: str) -> dict | None` — `GetItem` by pk/sk
- `delete_resource(resource_id: str) -> None` — `DeleteItem`
- `delete_by_material_id(material_id: str) -> None` — `Query GSI2` on `gsi2pk=MAT#<materialId>`, delete matching item (at most one)
- `get_by_contribution_id(contribution_id: str) -> dict | None` — `Query GSI3` on `gsi3pk=CON#<contributionId>`, return first match
- `query_page(*, limit: int, cursor: str | None, predicate=None) -> tuple[list[dict], str | None]` — `Query GSI1` on `gsi1pk=COMMUNITY`, `ScanIndexForward=False`, apply predicate in-memory, cursor-paginated
- `get_all_tags() -> set[str]` — `GetItem` on `pk=TAGS#ALL`, `sk=META`; return `tags` string set or empty set
- `add_tags(new_tags: list[str]) -> None` — `UpdateItem` ADD on `tags` SS attribute for `TAGS#ALL`/`META`; no-op on empty list
- Cursor encode/decode helpers (reuse pattern from `repository.py`)

**Stories**: US-2.20, US-2.22–2.26 (data layer for all)

---

### Step 2 — New file: `services/events/src/library_service.py`
[x] Create new file.
Business logic for all three entry paths, search, tags, and curation.

Implement `LibraryService` class with:
- `__init__(self, repo: LibraryRepository, storage, events=None)`
- `_assert_curator(principal)` — raise `ForbiddenError` if role not CL or UGL
- `promote_event_materials(event: dict) -> int` — Path 1 bulk promotion on completion; iterate `events_repo.list_materials(event_id)`; call `_create_from_material` for each clean+uploaded (or link); return count promoted
- `promote_single_material(material: dict, event: dict) -> None` — Path 1 single promotion (called by scan consumer); idempotent via `get_by_material_id` check
- `remove_by_material_id(material_id: str) -> None` — Path 1 auto-removal; calls `repo.delete_by_material_id`; no-op if not found
- `add_from_contribution(payload: dict) -> None` — Path 2 consumer handler; idempotency via `get_by_contribution_id`; validate fields; create resource
- `add(body: dict, *, principal) -> dict` — Path 3 direct add by curator; full validation; return `resource_public` with `presignedUploadUrl` for file formats
- `search(*, principal, filters: dict, limit: int, cursor: str | None) -> dict` — search-first gate; build predicate; call `repo.query_page`; generate presigned GET URLs for clean files; return paginated result
- `get_tags(*, principal, prefix: str) -> dict` — fetch `TAGS#ALL`; filter by prefix; return sorted list capped at 100
- `edit(resource_id: str, body: dict, *, principal) -> dict` — curator edit; validate; rewrite item; `add_tags` for new topics
- `remove(resource_id: str, *, principal) -> None` — curator delete; S3 object NOT deleted
- `_create_from_material(material: dict, event: dict) -> None` — internal helper; builds resource dict; writes via `repo.put_resource`; calls `repo.add_tags([])`
- `_validate_resource_fields(body: dict) -> None` — shared validation for add + edit (title, description, format, topics, url)
- `resource_public(resource: dict, download_url: str | None = None) -> dict` — serialiser

Include module-level constants: `LIBRARY_CONTENT_TYPES`, `LIBRARY_SOURCES`, `LIBRARY_DOWNLOAD_URL_SECONDS`, `LIBRARY_UPLOAD_URL_SECONDS`

**Stories**: US-2.20 (search), US-2.22 (Path 1), US-2.23 (Path 3), US-2.24 (Path 2), US-2.25 (edit/delete), US-2.26 (tags)

---

### Step 3 — New file: `services/events/src/library_consumers.py`
[x] Create new file.
EventBridge consumer for `ContributionApproved` (Path 2).

Implement `ContributionApprovedConsumer` class:
- `__init__(self, library_service: LibraryService, idempotency=None)`
- `handle(self, envelope: dict) -> dict`
  - Extract `contributionId`, `addToLibrary`, library fields from `envelope.get('detail') or envelope`
  - If `addToLibrary` is False or missing: return `{"ignored": True}`
  - Idempotency gate on `contributionId`
  - Call `self._library.add_from_contribution(payload)`
  - Emit `LibraryContributionConsumerFailures` CloudWatch metric on exception (fail silently — does not propagate to EventBridge)
  - Return `{"contributionId": contributionId, "added": True}`

**Stories**: US-2.24

---

### Step 4 — Modify: `services/events/src/app.py`
[x] Modify existing file.

Changes:
1. Add imports: `from library_service import LibraryService`, `from library_repository import LibraryRepository`, `from library_consumers import ContributionApprovedConsumer`
2. Add `LIBRARY_TABLE_NAME` env var read in `Context.__init__`
3. Add `library_repo`, `library` (LibraryService), `contribution_consumer` (ContributionApprovedConsumer) to `Context.__init__`
4. Add library routes to `OPERATIONS` list (before the `{id}` catch-all):
   - `("GET", "/library")`, `("GET", "/library/tags")`, `("POST", "/library")`, `("PUT", "/library/{id}")`, `("DELETE", "/library/{id}")`
5. Add to `OPERATION_IDS`: `searchLibrary`, `listLibraryTags`, `addLibraryResource`, `updateLibraryResource`, `deleteLibraryResource`
6. Add `ContributionApproved` to `CONSUMED_EVENT_TYPES`
7. In `dispatch()`: add handler for `detail_type == "ContributionApproved"` → `ctx.contribution_consumer.handle(event)`
8. Remove `("GET", "/events/content-library")` from `OPERATIONS` and `"contentLibrary"` from `OPERATION_IDS`
9. In `_execute()`: remove `contentLibrary` branch; add 5 new library operation branches
10. In `_execute()`: update Administrator check note to include Library

**Stories**: US-2.20, US-2.22–2.26

---

### Step 5 — Modify: `services/events/src/event_service.py`
[x] Modify existing file.

Changes to `complete()` method:
1. Add mandatory description validation: if `event.get('description', '').strip() == ''`: raise `ValidationError("Event description is required before marking an event as completed.")`
2. After status write, call `self._library.promote_event_materials(event)` (inject `LibraryService` into `EventService.__init__`)

**Stories**: US-2.19 (mandatory description), US-2.22 (Path 1 trigger)

---

### Step 6 — Modify: `services/events/src/material_service.py`
[x] Modify existing file.

Changes:
1. Inject `LibraryService` into `MaterialService.__init__` (optional dependency, default `None`)
2. In `remove()`: after `self._repo.delete_material(event_id, material_id)`, call `self._library.remove_by_material_id(material_id)` if `self._library`
3. Remove `content_library()` method entirely
4. Remove all `gsi3pk`/`gsi3sk` references from any helpers that still reference them

**Stories**: US-2.22 (auto-removal on material delete)

---

### Step 7 — Modify: `services/events/src/consumers.py`
[x] Modify existing file.

Changes to `MalwareScanConsumer.handle()`:
1. Extend key prefix check to also handle `library/` prefix (alongside existing `events/`)
2. After setting `scanState = Clean` on a material: if event is Completed, call `self._library.promote_single_material(material, event)` if `self._library`
3. For `library/` prefix keys: call `self._library.update_scan_state(resource_id, state)` to update Library resource scan state directly

**Stories**: US-2.22, US-2.23 (scan gate for Path 3 files)

---

### Step 8 — Modify: `services/events/src/repository.py`
[x] Modify existing file.

Removals:
1. Remove `_apply_content_index()` method
2. Remove `refresh_content_index()` method
3. Remove all `gsi3pk`/`gsi3sk` writes from `put_material()` and any other methods

**Stories**: US-2.22 (GSI3 removal)

---

### Step 9 — Modify: `services/contributions-scoring/src/submission_service.py`
[x] Modify existing file.

Changes to `decide()` and `_notify_decision()`:
1. `decide()` — when `decision == "approve"`:
   - Read optional Library opt-in fields from `body`: `addToLibrary` (bool), `libraryTitle`, `libraryDescription`, `libraryFormat`, `libraryTopics`, `libraryUrl`, `libraryS3Key`
   - Pass these as `library_data` to `_notify_decision()`
2. `_notify_decision()`:
   - Keep existing `PointsAwarded` publish unchanged
   - When `outcome == "approved"`: also publish new `ContributionApproved` event with full payload including `addToLibrary` flag and library fields
   - Include `approverId` (principal.user_id) and `approverName` (principal.name) in payload

**Stories**: US-2.24 (Path 2 — Contributions side)

---

### Step 10 — Update infrastructure: `infra/services/service-events-data.yaml`
[x] Modify existing file.

Changes:
1. Add `LibraryTable` resource (new DynamoDB table `library-${Stage}`) with all attributes, keys, 3 GSIs, PITR, SSE — per infrastructure design
2. Remove GSI3 (`gsi3pk`/`gsi3sk`) from events `Table` resource:
   - Remove from `AttributeDefinitions`
   - Remove from `GlobalSecondaryIndexes`
3. Add `LibraryTableName` and `LibraryTableArn` outputs

**Stories**: US-2.20 (new table), US-2.22 (GSI3 removal)

---

### Step 11 — Update infrastructure: `infra/services/service-events-app.yaml`
[x] Modify existing file.

Changes:
1. Add `LibraryTableName` and `LibraryTableArn` parameters
2. Add `HasLibraryTable` condition
3. Add `LIBRARY_TABLE_NAME` env var to Lambda
4. Add Library IAM statements (table CRUD + index query + `library/*` S3 prefix)
5. Add `ContributionApprovedRule` EventBridge rule + `ContributionApprovedRulePermission`
6. Extend `ObjectRule` EventPattern to add `library/` prefix alongside `events/`
7. Extend `MalwareScanRule` EventPattern to add `library/` prefix alongside `events/`
8. Add `LibraryContributionConsumerFailureAlarm` CloudWatch alarm

**Stories**: US-2.22–2.24 (infra wiring)

---

### Step 12 — Update infrastructure: `infra/root-template.yaml`
[x] Modify existing file.

Pass `LibraryTableName` + `LibraryTableArn` from events data stack outputs to events app stack parameters.

**Stories**: US-2.20 (root wiring)

---

### Step 13 — Update API contract: `contracts/services/events/openapi.yaml`
[x] Modify existing file.

Changes:
1. Remove `GET /events/content-library` path and `contentLibrary` operationId
2. Remove `MaterialList` schema reference for content library (keep for event materials)
3. Add 5 new paths under `/library`: `searchLibrary`, `listLibraryTags`, `addLibraryResource`, `updateLibraryResource`, `deleteLibraryResource`
4. Add `LibraryResource` schema and `LibraryList` schema
5. Version bump: `2.0.0` → `2.1.0`

**Stories**: US-2.20, US-2.22–2.26

---

### Step 14 — Update API contract: `contracts/services/contributions-scoring/openapi.yaml`
[x] Modify existing file.

Changes:
1. Add `ContributionApproved` event schema (published event, not an HTTP endpoint)
2. Extend `POST /contributions/{id}/decide` request body to include optional Library opt-in fields (`addToLibrary`, `libraryTitle`, `libraryDescription`, `libraryFormat`, `libraryTopics`, `libraryUrl`, `libraryS3Key`)
3. Version bump

**Stories**: US-2.24

---

### Step 15 — Regenerate API edge: `infra/api-edge.yaml`
[x] Run `gen_api_edge.py` or manually add `/library` base path routing.

Add `library` to base-path routing: `GET /library`, `GET /library/{proxy+}`, `POST /library`, `PUT /library/{id}`, `DELETE /library/{id}` → `events-${Stage}` Lambda with Cognito authorizer.

**Stories**: US-2.20 (routing)

---

### Step 16 — New frontend file: `frontend/src/features/ContentLibraryPage.tsx`
[x] Create new file.

Implement `ContentLibraryPage` component per `frontend-components.md`:
- `LibrarySearchBar` (keyword, format select, source select, topic `TopicTagInput` in single mode)
- `LibraryResultsList` with `LibraryResourceCard` per item
- Search-first state: `submitted = null` → show empty prompt; `submitted !== null` → show results or "no matches"
- Cursor-stack pagination (Prev/Next)
- "Add to Library" button for CL/UGL → opens `LibraryAddResourceModal`
- All interactive elements: `data-testid` attributes (`library-search-input`, `library-search-btn`, `library-format-select`, `library-source-select`, `library-topic-input`, `library-add-btn`, `resource-card-{id}`, `resource-download-{id}`, `resource-open-{id}`, `resource-edit-{id}`, `resource-delete-{id}`, `library-prev`, `library-next`, `library-count`)

**Stories**: US-2.20 (browse/search UI)

---

### Step 17 — New frontend file: `frontend/src/components/TopicTagInput.tsx`
[x] Create new file.

Shared component:
- `mode='multi'`: autocomplete tag input with chips; `GET /library/tags?prefix=` on keystroke (debounced 300ms, min 2 chars); add on Enter/click; removable chips; lowercase on add; max 20 tags
- `mode='single'`: single-value filter; same autocomplete; displays current tag with clear button
- `data-testid='topic-tag-input'`, `data-testid='topic-suggestion-{tag}'`, `data-testid='topic-chip-{tag}'`, `data-testid='topic-chip-remove-{tag}'`

**Stories**: US-2.26 (topic tag input)

---

### Step 18 — New frontend file: `frontend/src/components/LibraryAddResourceModal.tsx`
[x] Create new file.

Modal for Path 3 (curator direct add):
- Fields: title, description, format select, TopicTagInput (multi), conditional URL input (Link format) or file picker (other formats)
- On submit: `POST /library`; for file formats, use response `presignedUploadUrl` to upload file directly to S3 (same fetch pattern as event materials)
- Validation mirrors backend (title required, description required, format required, url https:// for Link)
- `data-testid`: `library-add-modal`, `add-title`, `add-description`, `add-format`, `add-url`, `add-file`, `add-submit`, `add-cancel`

**Stories**: US-2.23 (Path 3 UI)

---

### Step 19 — New frontend file: `frontend/src/components/EditResourceModal.tsx`
[x] Create new file.

Modal for curator edit:
- Pre-filled fields: title, description, format, topics (TopicTagInput multi), url (Link only)
- No file upload (note displayed: "To replace the file, delete and re-add")
- On submit: `PUT /library/{id}`
- `data-testid`: `edit-resource-modal`, `edit-title`, `edit-description`, `edit-format`, `edit-url`, `edit-submit`, `edit-cancel`

**Stories**: US-2.25 (edit UI)

---

### Step 20 — Modify: `frontend/src/features/EventsPage.tsx`
[x] Modify existing file.

Removals:
1. Remove `ContentLibraryTab` component and its export
2. Remove `tab === "library"` branch from tab switcher
3. Remove `📚 Content Library` tab from tab strip
4. Remove library-specific state (`libGroups`, `gname`, `term`, `contentType`, `group`, `submitted`, `cursorStack`, `cursor`, `path` for library, `runSearch` for library)
5. Remove `useApi` call for `/events/content-library`
6. Remove all CSS classes only used by Content Library tab (`.cl-*` usage in JSX)

**Stories**: US-2.20 (tab removal)

---

### Step 21 — Modify: `frontend/src/App.tsx`
[x] Modify existing file.

Changes:
1. Add import for `ContentLibraryPage`
2. Add route: `<Route path="/content-library" element={<ContentLibraryPage role={role} />} />`
3. Add `📚 Content Library` to sidebar navigation (visible to Member, UGL, CL; hidden for Administrator)

**Stories**: US-2.20 (standalone page routing)

---

### Step 22 — Modify: `frontend/src/styles/portal.css`
[x] Modify existing file.

Remove dead `.cl-*` CSS classes (`.cl-list`, `.cl-row`, `.cl-row-head`, etc.) that were used by the Events page Content Library tab. These will be replaced with styles inside `ContentLibraryPage.tsx` using inline styles or new class names.

**Stories**: US-2.20 (CSS cleanup)

---

### Step 23 — Write tests: `services/events/tests/test_library_service.py`
[x] Create new file. Unit tests for `LibraryService`.

Test suites:
- **Search**: search-first gate (no filters → empty), keyword matches title, keyword matches description, format filter, source filter, topic filter, combined filters, Administrator denied (403), pagination cursor
- **Path 1**: `promote_event_materials` promotes all clean materials on completion; skips PendingScan; skips Quarantined; `promote_single_material` idempotent (no duplicate on re-call)
- **Path 1 auto-removal**: `remove_by_material_id` deletes resource; no-op if not in Library
- **Path 2**: `add_from_contribution` creates resource when `addToLibrary=True`; idempotent on contributionId; no-op when `addToLibrary=False`
- **Path 3**: curator add succeeds (CL); curator add succeeds (UGL); Member denied (403); missing description → 400; invalid format → 400; Link without https:// → 400
- **Edit**: CL can edit any resource; UGL can edit any resource; Member denied; immutable fields unchanged
- **Delete**: CL deletes; UGL deletes; Member denied; S3 object not touched
- **Tags**: prefix filters correctly; empty prefix returns all (capped 100); TAGS#ALL updated on add

**Stories**: US-2.20, US-2.22–2.26

---

### Step 24 — Write tests: `services/events/tests/test_library_consumers.py`
[x] Create new file. Unit tests for `ContributionApprovedConsumer`.

Tests:
- `addToLibrary=True` creates resource
- `addToLibrary=False` is ignored (no resource created)
- Redelivered event (same contributionId) is idempotent
- Missing `contributionId` handled gracefully

**Stories**: US-2.24

---

### Step 25 — Write tests: `services/events/tests/test_event_complete_description.py`
[x] Create new file (or add to existing `test_event_service.py`). Tests for mandatory description on completion.

Tests:
- Complete without description → 400 ValidationError
- Complete with description → succeeds
- Complete triggers Path 1 promotion for clean materials

**Stories**: US-2.19, US-2.22

---

### Step 26 — Write tests: `services/contributions-scoring/tests/test_submission_library_optin.py`
[x] Create new file. Tests for Library opt-in at contribution approval.

Tests:
- Approve with `addToLibrary=True` publishes `ContributionApproved` with library fields
- Approve with `addToLibrary=False` publishes `ContributionApproved` with `addToLibrary=False`
- Approve without opt-in fields defaults to `addToLibrary=False`
- Existing `PointsAwarded` still published (unchanged)

**Stories**: US-2.24

---

### Step 27 — Update mock: `services/events/src/mock_handler.py` (if exists)
[x] Check if mock handler exists and update.

- Remove `contentLibrary` mock response
- Add mock responses for 5 library operations (returning empty lists / 501 as appropriate)
- Add `ContributionApproved` to consumed event types

**Stories**: US-2.20

---

### Step 28 — Documentation: `aidlc-docs/construction/content-library-rework/code/code-summary.md`
[x] Create summary document.

Record:
- Files created (7 new)
- Files modified (11 existing)
- Tests created (4 new test files)
- Story coverage: US-2.19 ✅, US-2.20 ✅, US-2.22 ✅, US-2.23 ✅, US-2.24 ✅, US-2.25 ✅, US-2.26 ✅

---

## Story Traceability

| Story | Steps |
|---|---|
| US-2.19 — Mandatory description on complete | 5, 25 |
| US-2.20 — Standalone Content Library browse/search | 1, 2, 4, 13, 15, 16, 17, 20, 21, 22, 23 |
| US-2.22 — Path 1 auto-promotion | 2, 3, 5, 6, 7, 8, 10, 11, 23, 25 |
| US-2.23 — Path 3 curator direct add | 2, 4, 16, 18, 23 |
| US-2.24 — Path 2 member contribution opt-in | 3, 4, 9, 14, 23, 24, 26 |
| US-2.25 — Curator edit and delete | 2, 4, 16, 19, 23 |
| US-2.26 — Topics autocomplete | 2, 4, 16, 17, 23 |

---

## Total: 28 steps
