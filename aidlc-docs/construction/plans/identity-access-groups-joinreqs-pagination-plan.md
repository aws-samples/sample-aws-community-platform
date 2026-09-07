# Unit 2 — Community Leader User Groups: "All Groups" + "Join Requests" Cursor Pagination (Change Request Plan)

**Origin**: User request (2026-08-08, item 3): for the Community Leader, the "All Groups" and "Join Requests" tables under User Groups could be very large. Apply the same server-side pagination approach used for Admin > User Management.
**Stories affected**: US-1.16 (group directory), US-1.11 (soft-delete grace rows), US-1.21 (cross-group join-request queue), US-8.9 (data table).

## Findings
- **All Groups** (`GET /groups`): returned every group in one response; for the CL table each row also costs a member-count read + leader resolution. Groups are enumerated by a **Scan** (group ids aren't in one partition), same basis as the unpaged path and the Member Directory. No GSI exists for groups.
- **Join Requests** (`GET /join-requests`, `listAllJoinRequests`): the cross-group CL queue enumerated ALL active groups, queried each group's pending requests, and did **one profile read per request** (`_enrich_request`) before sorting the whole set by `requestedAt`. The per-row profile read across the entire pending backlog is the dominant cost.
- The frontend `GroupsPage` fetched both endpoints in full up front and rendered every row client-side; the tab badge counted `items.length`.
- Reusable pieces already exist: `DataTable` server mode, `useApi.fetching`, `loadRowsPref`, `_parse_limit` (app layer), and the `JoinRequestList` schema already carries `total` + `cursor` (added for the per-group paged queue on 2026-08-05).

## Design decisions (mirror Admin > User Management)
- **D-G1 All Groups = Scan cursor**: `list_groups_page()` Scans META rows only, fetch-until-full with the status filter applied in-loop, returns `(groups, next_cursor)`. Cursor = opaque base64 of the last META row's `{pk, sk}` (resumed as `ExclusiveStartKey`); invalid cursor → 400. Member count + leaders are resolved **per page**, bounding that work to page size. `myState` is omitted on the paged path (CL-only table, no Joined/Requested tag) — the Member/UGL card grid keeps the unpaged `list_groups` with `myState`.
- **D-G2 Join Requests = bounded aggregate + window**: `list_all_pending_requests_page()` gathers pending requests across active groups as lightweight rows (NO per-row profile read), sorts by `(requestedAt, id)` for a stable global oldest-first order, slices the cursor window, and enriches **only that window** with member name/email + group name. This cuts the profile reads from O(all pending) to O(page). `total` is returned for the badge/heading; cursor = last request id (reuses the member cursor helper). **FOLLOW-UP**: a sparse pending-join-request GSI (Query, oldest-first) would remove the full cross-group enumeration entirely — deferred (needs a -data GSI + backfill).
- **D-G3 Backward compatible**: paged mode engages only when `limit`/`cursor` is present. Bare `GET /groups` (Member/UGL grid, CSV-free) and bare `GET /join-requests` are unchanged.
- **D-G4 Contract additive**: `limit`/`cursor` params on GET /groups and GET /join-requests; `cursor` added to `GroupList` (`JoinRequestList` already had `total`+`cursor`).
- **D-G5 Frontend**: `GroupsPage` split into a thin shell + `MemberGroupsGrid` (unpaged), `AllGroupsTable` (paged, DataTable server mode), `CrossGroupRequests` (paged). Each CL table owns a cursor stack (Prev) and a page-size pref. The tab badge reads `total` from a `limit=1` join-requests page. Server owns order (client column-sort disabled in server mode).

## Steps
- [x] Step 1 — Contract: limit/cursor on GET /groups + GroupList.cursor; limit/cursor on GET /join-requests (additive). (`contracts/services/identity-access/openapi.yaml`)
- [x] Step 2 — Repository: `encode/decode_group_cursor` + `list_groups_page()` (Scan META, fetch-until-full, opaque {pk,sk} cursor). (`services/identity-access/src/repository.py`)
- [x] Step 3 — Service: `list_groups_page()` (per-page count+leaders, no myState) + `list_all_pending_requests_page()` (aggregate, window-enrich, total+cursor). (`services/identity-access/src/group_service.py`)
- [x] Step 4 — API layer: listGroups + listAllJoinRequests parse limit/cursor → paged mode; bare paths unchanged. (`services/identity-access/src/app.py`)
- [x] Step 5 — Frontend: GroupsPage split; AllGroupsTable + CrossGroupRequests on DataTable server mode; badge from paged `total`. (`frontend/src/features/pages.tsx`)
- [x] Step 6 — Verify: identity-access pytest, ruff, contract gate, tsc + npm build.
- [x] Step 7 — Docs: code summary, aidlc-state.md, audit entries.

## Extension compliance (Security + Resiliency baselines)
- SECURITY-05 (input validation): compliant — limit validated (1..200 → 400 via `_parse_limit`), cursors decoded to whitelisted key attrs only ({pk,sk} for groups; last-id for requests), DynamoDB expressions parameterized.
- SECURITY-08 (authz): compliant — listGroups/listAllJoinRequests authorization unchanged (CL-only cross-group queue; includeDeleted still CL-gated).
- SECURITY-15 (fail-closed errors): compliant — malformed cursor/limit → 400 ValidationError; fail-closed handler unchanged.
- Resiliency: N/A — no new endpoints/dependencies/infra; paging strictly reduces per-request work (All Groups fully; Join Requests reduces the dominant per-row profile reads to page size).

## Not deployed
Code + all gates green locally; not redeployed to the dev stack in this change.
