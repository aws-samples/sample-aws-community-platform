# Unit 3 — Member Directory Pagination & Async Load (Change Request Plan)

**Origin**: User report — directory will hold 13,000+ members; page loads slowly with 3-4 users.
**Approved**: 2026-08-03 in chat ("Go ahead and implement this.") after design discussion.
**Stories affected**: US-3.4 (browse directory), US-3.5 (search + filters), US-8.9 (configurable data table).
**Contract impact**: NONE — `contracts/services/member-profiles/openapi.yaml` already declares `limit`, `cursor` params and `cursor` in the 200 response. Behavior is additive (omitting `limit` keeps full-listing behavior; CSV export unchanged).

## Design decisions
- **D-P1 Cursor pagination**: cursor = URL-safe base64 JSON of the last returned item's key (`{pk, sk}`), used as DynamoDB Scan `ExclusiveStartKey` (valid resume point for Scan). Opaque to clients. Invalid cursor → 400 VALIDATION_ERROR.
- **D-P2 Fetch-until-full**: post-filters (groupId, keyword, semantic ids, certId holders) can shrink a scan page, so the repository loops scan pages until `limit` matched rows are accumulated or the table is exhausted. Fan-out id-sets (semantic/cert) are computed once per request in the service and pushed into the page loop as an `id_filter`.
- **D-P3 Backward compatible**: `limit` absent → existing full-scan path (used by CSV export and existing tests). `count` remains "rows in this response".
- **D-P4 Limit bounds**: 1..200 enforced in app.py; non-integer → 400.
- **D-P5 Frontend server mode is opt-in per table**: `DataTable` gains an optional `server` prop; all other tables keep existing client-side behavior. In server mode: Rows dropdown = page size, Prev/Next buttons (previous via client-held cursor stack), no header sorting (server default order), skeleton rows while first page loads, "Refreshing…" indicator on refetch, toolbar shows "Showing N — more available" (no exact total, by design).
- **D-P6 Async shell**: DirectoryPage no longer returns a full-page `<Loading/>`; header/search/filters always render; data populates async in the table area. Search input debounced 300ms.
- **D-P7 GSI deferred**: replacing Scan with a GSI Query is a separate follow-up infrastructure-design change (revisits Infra Design Q4); NOT in this plan.

## Steps
- [x] Step 1 — Repository: add cursor encode/decode helpers + `scan_directory_page()` (fetch-until-full loop, returns `(items, next_cursor)`); keep `scan_directory()` unchanged. (`services/member-profiles/src/repository.py`)
- [x] Step 2 — Service: `DirectoryService.browse()` gains `cursor` param; computes semantic/cert id-filter once; paged path when `limit` set; unchanged full path otherwise. (`services/member-profiles/src/directory_service.py`)
- [x] Step 3 — API layer: pass `cursor` through, validate `limit` (int, 1..200 → 400 otherwise). (`services/member-profiles/src/app.py`)
- [x] Step 4 — Backend tests: repository paging (page fill across post-filters, cursor round-trip, exhaustion), service cursor/id-filter paths, app.py cursor param + invalid limit/cursor → 400. (`services/member-profiles/tests/`)
- [x] Step 5 — Frontend lib: `useDebounced` hook (new `frontend/src/lib/useDebounced.ts`); `useApi` gains non-breaking `fetching` flag (stale data kept during refetch). (`frontend/src/lib/useApi.ts`)
- [x] Step 6 — DataTable: optional `server` mode per D-P5 + exported `loadRowsPref()`; client mode untouched. (`frontend/src/components/DataTable.tsx`)
- [x] Step 7 — DirectoryPage: debounced q, cursor-stack state, limit param from Rows pref, always-rendered shell, skeleton/refresh states, error inline in table card. (`frontend/src/features/pages.tsx`)
- [x] Step 8 — Verify: member-profiles pytest, ruff, `npm run build`, member-profiles contract gate.
- [x] Step 9 — Docs: code summary in `aidlc-docs/construction/member-profiles/code/`; update `aidlc-state.md`; audit entries.

## Extension compliance (enabled: Security Baseline, Resiliency Baseline)
- SECURITY-05 (parameterized expressions): compliant — cursor is decoded to a key dict passed as `ExclusiveStartKey`; never interpolated into expressions.
- SECURITY-15 (fail-closed): compliant — invalid cursor/limit map to 400 via ValidationError; global_handler unchanged.
- Resiliency (graceful degrade BR-6b/NFR-MP-MAINT-1): compliant — semantic/cert fan-out failure behavior unchanged; paged path reuses same degrade logic.
- Other baseline rules: N/A to this change (no new authN/Z surface, no new infra, no secrets, no new dependencies).
