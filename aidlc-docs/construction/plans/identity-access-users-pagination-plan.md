# Unit 2 — Admin User Management: Search Filters + Cursor Pagination (Change Request Plan)

**Origin**: User request (2026-08-03): Admin > User Management will deal with 13,000+ records; apply the Member Directory approach; filters proposed and approved in chat: **search + role + status + group**.
**Stories affected**: US-1.5/1.6 (admin user management), US-3.8/3.9 (admin member list + export, reassigned to Unit 2), US-8.9 (data table).

## Findings
- `GET /users` returns ALL users; for each Member row the backend runs `current_groups_for_member()` — a query per member (~12k+ queries per request at 13k users) plus a multi-MB response. Pagination bounds group resolution to page size.
- Users are already indexed by role: GSI2 (`gsi2pk=ROLE#<role>`, `gsi2sk=USER#<id>`) — Query-based paging, no Scan, no new GSI.
- Frontend page (`admin.tsx` AdminUsersPage) has no filters, full-page Loading gate, client-mode DataTable. Reusable pieces from the directory change already exist (DataTable `server` mode, `useDebounced`, `useApi.fetching`, `loadRowsPref`).

## Design decisions
- **D-U1 Composite cursor**: opaque URL-safe base64 JSON `{role, id}` of the last returned row; resumes as GSI2 `ExclusiveStartKey` (`gsi2pk/gsi2sk/pk/sk` all reconstructible from role+id). No role filter → walk role partitions in fixed order (Administrator → CommunityLeader → UserGroupLeader → Member), cursor carries the partition. Invalid cursor → 400.
- **D-U2 Fetch-until-full**: status/keyword/id-set post-filters applied inside the page loop (same as directory D-P2), so pages come back full.
- **D-U3 Group filter as id-set**: computed once per request = `current_members_of_group(groupId)` ∪ that group's `leaderIds` (a UGL leads without membership), then pushed into the page loop. One membership query per request instead of one per user.
- **D-U4 Search scope**: keyword substring on firstName/lastName/email/professionalRole (no semantic search — this is the admin list, not the directory; Search service doesn't index admin rows).
- **D-U5 Backward compatible**: no `limit`/`cursor` → existing full-listing behavior (CSV export unchanged). `limit` bounds 1..200 → 400 otherwise; `role`/`status` params validated against enums → 400.
- **D-U6 Contract**: additive — `q`, `role`, `status`, `groupId`, `limit`, `cursor` params on GET /users; `cursor` added to `UserList`.

## Steps
- [x] Step 1 — Contract: extend GET /users params + UserList.cursor (additive). (`contracts/services/identity-access/openapi.yaml`)
- [x] Step 2 — Repository: cursor helpers + `list_users_page()` (role-partition walk, fetch-until-full, post-filters incl. id_filter). (`services/identity-access/src/repository.py`)
- [x] Step 3 — Service: `list_users_page()` on UserService — group id-set computation, per-page serialization (bounded group lookups). (`services/identity-access/src/user_service.py`)
- [x] Step 4 — API layer: listUsers branch parses/validates q/role/status/groupId/limit/cursor; paged when limit or cursor present. (`services/identity-access/src/app.py`)
- [x] Step 5 — Backend tests: repository paging (partition walk, cursor round-trip, filters), service group id-set + serialization, API 400s + paging. (`services/identity-access/tests/`)
- [x] Step 6 — Frontend: AdminUsersPage — search (debounced) + role + status + group filters, server-mode DataTable, always-rendered shell, cursor stack, export/add/bulk-import/edit/disable unchanged. (`frontend/src/features/admin.tsx`)
- [x] Step 7 — Verify: identity-access pytest, ruff, contract gate, `npm run build`.
- [x] Step 8 — Docs: code summary, aidlc-state.md, audit entries.

## Extension compliance (Security + Resiliency baselines)
- SECURITY-05: compliant — cursor decoded to key attributes only, parameterized expressions throughout.
- SECURITY-08: compliant — listUsers authz (`list`/`admin-member-list`) unchanged.
- SECURITY-15: compliant — malformed cursor/limit/role/status → 400 ValidationError, fail-closed handler unchanged.
- Other rules: N/A — no new endpoints, auth surface, secrets, or infra.
