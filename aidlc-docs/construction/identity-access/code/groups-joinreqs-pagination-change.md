# Change Summary — CL User Groups: "All Groups" + "Join Requests" Cursor Pagination (2026-08-08)

**Trigger**: For the Community Leader, the "All Groups" and cross-group "Join Requests" tables under User Groups could be very large. Apply the Admin > User Management server-side pagination approach.
**Plan**: `aidlc-docs/construction/plans/identity-access-groups-joinreqs-pagination-plan.md`.

## Root cause at scale
- `GET /groups` returned every group; the CL table also costs a member-count read + leader resolution per row.
- `GET /join-requests` (cross-group CL queue) enumerated all active groups, queried each group's pending requests, and did **one profile read per request** across the whole pending backlog before sorting — the dominant cost.
- The SPA fetched both endpoints in full and rendered all rows client-side; the tab badge counted `items.length`.

## Backend (services/identity-access)
- **Modified**: `src/repository.py`
  - `encode_group_cursor()/decode_group_cursor()` — opaque base64 of a group META row's `{pk, sk}` (resumed as a Scan `ExclusiveStartKey`); invalid → 400.
  - `list_groups_page()` — new: Scan filtered to META rows only (group ids aren't enumerable by one partition — same Scan basis as `list_groups_with_counts`), fetch-until-full with the status filter applied in-loop, returns `(groups, next_cursor)`.
- **Modified**: `src/group_service.py`
  - `list_groups_page()` — new: resolves member count + leaders **per page** (bounded to page size). Omits `myState` (CL-only management table renders no Joined/Requested tag, so the per-group pending-request lookup it would cost is not paid). The Member/UGL card grid keeps unpaged `list_groups` with `myState`.
  - `list_all_pending_requests_page()` — new: gathers pending requests across active groups as lightweight rows (no per-row profile read), sorts by `(requestedAt, id)`, slices the cursor window, and enriches **only that window** (name/email + groupName). Cuts profile reads from O(all pending) to O(page). Returns `total` (badge/heading) + `cursor` (last request id, reusing the member cursor helper).
- **Modified**: `src/app.py` — `listGroups` and `listAllJoinRequests` parse `limit`/`cursor` (existing `_parse_limit`, 1..200 → 400) and enter paged mode when either is present; bare paths unchanged (Member/UGL grid; pre-existing callers).
- **Contract**: `contracts/services/identity-access/openapi.yaml` — additive: `limit`/`cursor` on GET /groups + `GroupList.cursor`; `limit`/`cursor` on GET /join-requests (`JoinRequestList` already had `total`+`cursor`).
- **FOLLOW-UP**: a sparse pending-join-request GSI (global oldest-first Query) would remove the cross-group enumeration for join requests; deferred (needs a -data GSI + backfill of existing pending requests + the one-GSI-per-UpdateTable deploy dance).

## Frontend (frontend/src/features/pages.tsx)
- `GroupsPage` split into a thin shell + three components:
  - `MemberGroupsGrid` (Member/UGL, **unpaged** — naturally bounded, behavior unchanged): the browse-and-join card grid on `/groups`.
  - `AllGroupsTable` (CL, **paged**): DataTable server mode over `/groups?includeDeleted=true&limit=&cursor=`, cursor stack for Prev, Rows = page size, skeleton/Refreshing, always-rendered shell; Edit/Delete/Undo-Delete + soft-delete grace preserved.
  - `CrossGroupRequests` (CL, **paged**): DataTable server mode over `/join-requests?limit=&cursor=`; heading + tab badge use `total` from the paged response; approve/reject preserved.
- Tab badge now reads `total` from a `limit=1` join-requests page (paged mode) instead of counting all fetched items.
- **Modified**: `frontend/src/components/DataTable.tsx` — already had the optional `emptyLabel` prop (added in the certifications change); reused here.

## Verification (2026-08-08)
- `pytest services/identity-access` — **164 passed** (no regressions). Paged behavior confirmed via a temporary test (groups: 3+3+1 walk, no dupes/skips, invalid cursor → 400; join-requests: 2+2+1 walk, `total`=5 on every page, oldest-first), then removed.
- `ruff check` (changed files) — clean. Contract gate — **27/27 passed**. `tsc -b` + `npm run build` — clean.
- NOT redeployed.
