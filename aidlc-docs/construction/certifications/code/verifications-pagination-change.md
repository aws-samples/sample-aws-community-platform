# Change Summary — Certifications > Pending Verifications: Cursor Pagination (2026-08-08)

**Trigger**: As a CL, the Pending Verifications tab will hold thousands of claims. Apply the same server-side cursor pagination used for Admin > User Management.
**Plan**: `aidlc-docs/construction/plans/certifications-verifications-pagination-plan.md`.

## Root cause at scale
`GET /certifications/verifications` returned **every** pending claim in one response, and the SPA both derived its filter dropdowns from that full set and rendered all rows client-side. Unbounded payload + render as the pending queue grows to thousands.

## Backend (services/certifications)
- **Modified**: `src/repository.py`
  - `query_pending_page()` — now takes `limit` (default 25) + `cursor`, returns `(rows, next_cursor)`. GSI2 `PENDING` partition Query (oldest-first, no Scan), predicate applied in a fetch-until-full loop (accumulates one past the page to detect a next page). Cursor built from **`_PENDING_CURSOR_ATTRS` = (pk, sk, gsi2pk, gsi2sk)** only — a pending row also carries gsi1*/gsi3* attrs that DynamoDB would reject in an ExclusiveStartKey.
  - `count_pending()` — new: walks the PENDING partition counting matches for the nav badge; materializes no rows; ignores paging.
- **Modified**: `src/verification_service.py`
  - `queue()` — countOnly path uses `count_pending()` (true total, unchanged semantics); the list path parses/validates `limit` (`_parse_limit`, 1..100 → 400), calls the paged repo method, and adds `cursor` to the response when more pages exist. Scope/filter predicate (UGL led-group, certId/groupId) unchanged; UGL scope still overrides the groupId filter.
  - `_parse_limit()` — new helper (mirrors identity's `_parse_limit`); imports `ValidationError`.
- **Contract**: `contracts/services/certifications/openapi.yaml` — additive: `limit` (1..100, default 25) + `cursor` params on GET /certifications/verifications; `cursor` on `ClaimList`.
- **Not edited**: `services/certifications/build/*` is generated (`make clean` removes it) — source-only change.

## Frontend (frontend/src/features/certifications/VerificationQueue.tsx)
- Server-mode `DataTable` (Rows dropdown = page size, Prev/Next via a cursor stack, skeleton first load, "Refreshing…" on refetch); page shell always renders (full-page `Loading` gate removed); errors inline.
- Filter dropdowns sourced from dedicated endpoints so they stay complete under paging: cert options from `/certifications?includeInactive=true`, CL group options from `/groups` (was derived from the visible page).
- "Earned" column always declared (a per-page-derived column would flicker between pages) — hideable via the column-settings gear.
- Inline "N pending verifications" text removed from the filter bar; the tab badge (CertificationsPage, `countOnly=true`) already shows the true total. Cursor stack resets on filter/page-size change; the `_` nonce param refetches the current page after an approve/reject.
- **Modified**: `frontend/src/components/DataTable.tsx` — optional `emptyLabel` prop so the server-mode empty state reads "No pending verifications match the current filters." instead of the hardcoded member-directory wording. Default preserves existing behavior.

## Verification (2026-08-08)
- `pytest services/certifications` — **42 passed** (no regressions; existing queue/countOnly/UGL-scope/own-flag tests unchanged). Cursor paging across page boundaries + prev + true-total countOnly + bad-limit→400 confirmed via a temporary test, then removed.
- `ruff check` (changed files) — clean. Contract gate — **13/13 passed**. `tsc -b` + `npm run build` — clean.
- NOT redeployed.
