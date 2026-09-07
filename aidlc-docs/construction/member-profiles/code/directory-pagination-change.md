# Change Summary — Directory Pagination & Async Load (2026-08-03)

**Trigger**: Directory will hold 13,000+ members; page loaded slowly with 3-4 concurrent users.
**Plan**: `aidlc-docs/construction/plans/member-profiles-directory-pagination-plan.md` (approved in chat).
**Contract**: unchanged — `limit`/`cursor` were already declared in `contracts/services/member-profiles/openapi.yaml`; this change wires them for real. Omitting `limit` preserves the full-listing behavior (CSV export unaffected).

## Root cause
Every `/members` request scanned the entire DynamoDB table (paging through all
`LastEvaluatedKey`s), post-filtered in Python, and returned ALL rows; the SPA
refetched on every keystroke and truncated client-side to the first N rows.

## Backend (services/member-profiles)
- **Modified**: `src/repository.py`
  - `encode_cursor()/decode_cursor()` — opaque URL-safe base64 of the last returned item's key, used as Scan `ExclusiveStartKey`. Malformed cursor → `ValidationError` (400), never a 500.
  - `scan_directory_page()` — fetch-until-full page loop: consumes scan pages until `limit` post-filter-matched rows accumulate (group/keyword/id-filter post-filters can shrink a raw page) or the table is exhausted. Returns `(rows, next_cursor)`; `next_cursor` is `None` on the last page. Still Scan-based — the GSI Query remains a deferred follow-up (Infra Design Q4).
  - `scan_directory()` unchanged (full-listing path).
- **Modified**: `src/directory_service.py` — `browse()` gains `cursor`; semantic-search ids and certification-holder ids are now computed once per request and intersected into an `id_filter` pushed into the page loop, so paginated pages never come back short. `limit`/`cursor` absent → previous full-listing behavior.
- **Modified**: `src/app.py` — passes `cursor` through; `_parse_limit()` validates limit (integer, 1..200 → 400 otherwise).

## Frontend (frontend/src)
- **Created**: `lib/useDebounced.ts` — 300ms debounce; directory search no longer fires a backend request per keystroke.
- **Modified**: `lib/useApi.ts` — new non-breaking `fetching` flag (any in-flight request); `loading` still means "no data yet". Stale data is kept visible during refetch.
- **Modified**: `components/DataTable.tsx` — opt-in `server` prop (per-table; all other tables keep client behavior): Rows dropdown = page size, Prev/Next buttons (`directory-prev`/`directory-next` testids), header sorting disabled (server owns order), skeleton rows on first load (`directory-skeleton`), dimmed rows + "Refreshing…" on refetch, "Showing N — more available" toolbar (no exact total by design), empty-state line. Exported `loadRowsPref()` so pages can initialize `limit` from the saved pref.
- **Modified**: `features/pages.tsx` (`DirectoryPage`) — page shell (header/search/filters) always renders; removed the blocking full-page `<Loading/>`; error shown inline in the table card; debounced `q`; cursor-stack state for Previous; stack resets on any filter/page-size change.

## Behavior notes
- Previous = client-held stack of visited cursors (DynamoDB cursors are forward-only).
- No exact total count in paged mode (that's the expensive full scan being removed).
- CSV export still fetches the full set via the unpaged path — unchanged, candidate for a later async-export improvement.
- Semantic-search relevance ordering was already lost by the pre-existing post-filter-over-scan approach; unchanged.

## Verification (all run 2026-08-03)
- `pytest services/member-profiles` — **63 passed** (was 51; +12 pagination tests: repository page loop/cursor walk/post-filter fill/invalid cursor, service paging + filter intersection + unpaged export path, API-layer paging + 400s).
- `ruff check services/member-profiles` — clean.
- `python3 platform/contract-tests/run_service.py member-profiles` — **5/5 passed**.
- `npm run build` (frontend) — clean.

## Deferred follow-up (needs its own Infrastructure Design approval)
Replace Scan with a GSI Query (e.g. `gsi1pk="DIRECTORY"`, `gsi1sk=lastName#firstName`):
`-data` stack change + writing GSI attributes on profile puts + one-off backfill of
existing items (a new GSI does not index items lacking its key attributes). This
revisits Infra Design Q4's "no GSIs pending load test" decision — the 13k/slow-load
report is that load-test signal.
