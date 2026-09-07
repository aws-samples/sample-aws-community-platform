# Unit 6 — Certifications > Pending Verifications: Cursor Pagination (Change Request Plan)

**Origin**: User request (2026-08-08, item 15): as a CL, opening Certifications > Pending Verifications shows a table that will hold thousands of rows. Implement pagination the same way it was done for Admin > User Management.
**Stories affected**: US-5.6/5.7 (verification queue), US-8.9 (configurable data table).

## Findings
- `GET /certifications/verifications` returned **all** pending claims in one response; the frontend derived its cert/group filter dropdowns from that full set and rendered every row in a client-mode `DataTable`. This does not scale to thousands of pending claims (large payload + unbounded render).
- The pending set is already indexed for oldest-first reads: **GSI2** (`gsi2pk=PENDING`, `gsi2sk=<submittedAt>#<claimId>`, sparse) — a Query walk, no Scan, no new GSI.
- The repo already ships opaque-cursor helpers (`encode_cursor`/`decode_cursor`) used by the same single-table module; the frontend already ships all the reusable pieces from the Admin/Directory paging work (`DataTable` server mode, `useApi.fetching`, `loadRowsPref`).
- The `countOnly=true` nav-badge path must keep returning the **true total** (the tab badge shows the full pending count), independent of paging.

## Design decisions (mirror the Admin User list)
- **D-VP1 Cursor**: opaque URL-safe base64 of the GSI2 `ExclusiveStartKey` — `{pk, sk, gsi2pk, gsi2sk}` ONLY (a pending claim row also carries gsi1*/gsi3* attrs; DynamoDB rejects a start key with stray attributes). Invalid cursor → 400.
- **D-VP2 Fetch-until-full**: the scope/filter predicate (led-group for UGL, certId/groupId for CL) is applied inside the page read loop, accumulating one past the page to know whether a next page exists and to build the cursor. A page never comes back short while more matches exist.
- **D-VP3 countOnly unchanged semantics**: a dedicated `count_pending()` walk returns the total; it does NOT materialize rows and ignores limit/cursor.
- **D-VP4 Filter options from dedicated endpoints**: the cert dropdown is sourced from `/certifications?includeInactive=true` (complete definition list, incl. inactive certs that still have pending claims) and the CL group dropdown from `/groups` — not derived from the visible page, so filters stay complete under paging.
- **D-VP5 "Earned" column always present**: a per-page-derived optional column would flicker between pages; it is now always declared and hidden via the column-settings gear (US-8.9) if unwanted.
- **D-VP6 limit bounds**: 1..100 (matches the DataTable Rows options 10/25/50/100), default 25 → 400 otherwise.
- **D-VP7 Contract**: additive — `limit`/`cursor` params on GET /certifications/verifications; `cursor` on `ClaimList`.

## Steps
- [x] Step 1 — Contract: add limit/cursor params + ClaimList.cursor (additive). (`contracts/services/certifications/openapi.yaml`)
- [x] Step 2 — Repository: `query_pending_page()` → cursor + `(rows, next_cursor)` (GSI2 walk, fetch-until-full, whitelisted cursor attrs); add `count_pending()`. (`services/certifications/src/repository.py`)
- [x] Step 3 — Service: `queue()` parses/validates limit (`_parse_limit`, 1..100 → 400), returns paged items + cursor; countOnly uses `count_pending()`. (`services/certifications/src/verification_service.py`)
- [x] Step 4 — Frontend: `VerificationQueue` rebuilt on DataTable server mode — cursor stack (Prev/Next), Rows = page size, filter dropdowns from `/certifications` + `/groups`, always-rendered shell (full-page Loading gate removed), inline total removed (tab badge already shows it). (`frontend/src/features/certifications/VerificationQueue.tsx`)
- [x] Step 5 — DataTable: optional `emptyLabel` so the server-mode empty state isn't hardcoded to member-directory wording. (`frontend/src/components/DataTable.tsx`)
- [x] Step 6 — Verify: certifications pytest, ruff, contract gate, tsc/npm build.
- [x] Step 7 — Docs: code summary, aidlc-state.md, audit entries.

## Extension compliance (Security + Resiliency baselines)
- SECURITY-05 (input validation): compliant — limit validated (1..100 → 400), cursor decoded to whitelisted key attributes only, DynamoDB expressions parameterized.
- SECURITY-08 (authz): compliant — queue scope (CL = all, UGL = led group with fail-closed resolution, Admin denied) unchanged; the group filter cannot widen a UGL's scope (UGL scope overrides the groupId filter, as before).
- SECURITY-15 (fail-closed errors): compliant — malformed cursor/limit → 400 ValidationError; the fail-closed handler is unchanged.
- Resiliency: N/A — no new endpoints, dependencies, or infra; paging strictly reduces per-request work.

## Not deployed
Code + all gates green locally; not redeployed to the dev stack in this change.
