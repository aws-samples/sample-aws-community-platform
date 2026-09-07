# Change Summary — Admin User Management: Filters + Cursor Pagination (2026-08-03)

**Trigger**: Admin > User Management will deal with 13,000+ records. Same approach as the Member Directory; filters approved in chat: search + role + status + group.
**Plan**: `aidlc-docs/construction/plans/identity-access-users-pagination-plan.md`.

## Root cause at scale
`GET /users` returned every user AND ran a membership query per Member row
(~12k+ DynamoDB queries per request at 13k users) plus a multi-MB response.

## Backend (services/identity-access)
- **Modified**: `src/repository.py`
  - `ROLE_PAGE_ORDER` — fixed partition-walk order (Administrator → CommunityLeader → UserGroupLeader → Member); `ROLES` is a set, so an explicit order keeps cursors stable.
  - `encode_user_cursor()/decode_user_cursor()` — opaque `{role, id}` cursor; all GSI2/table key attributes reconstructible. Malformed cursor or role-filter mismatch → 400.
  - `list_users_page()` — GSI2 Query per role partition (no Scan), fetch-until-full loop with status/keyword/id-set post-filters. Keyword matches firstName/lastName/email/professionalRole.
- **Modified**: `src/user_service.py` — `list_users_page()`: group filter resolved ONCE per request to an id-set (current members ∪ the group's leaderIds — a UGL leads without membership), pushed into the page loop; serialization (incl. per-Member group lookup) now bounded to page size.
- **Modified**: `src/app.py` — listUsers branch: `_parse_limit` (1..200), role/status enum validation (400 otherwise), paged mode when limit/cursor/any filter present (filters are never silently ignored); bare `GET /users` keeps the unpaged full listing (CSV export).
- **Contract**: `contracts/services/identity-access/openapi.yaml` — additive: q/role/status/groupId/limit/cursor params on GET /users; `cursor` on UserList.

## Frontend (frontend/src/features/admin.tsx)
- Filter bar: debounced search (name/email/professionalRole), role, status (Active/Inactive), group dropdowns.
- Server-mode DataTable (reused from the directory change): Rows dropdown = page size, Prev/Next via cursor stack, skeleton first load, "Refreshing…" on refetch; page shell always renders (full-page Loading gate removed); errors inline in the table card.
- Unchanged: Export CSV (unpaged path), Bulk Import, Add User, Edit/Disable/Enable (row actions refetch the current page via the nonce param).

## Verification (2026-08-03)
- `pytest services/identity-access` — **111 passed** (was 96; +15: repository partition walk/cursor round-trip/filters/id-set page fill/invalid+mismatched cursor, service paging + group id-set (members∪leaders) + unpaged export, API paging + 400s + filters-without-limit + bare-path compatibility). One test authoring error found and fixed during the run (MEVENT_START is a set of event types, not a type value).
- `ruff check` — clean. Contract gate — **26/26 passed**. `npm run build` — clean.
- NOT yet redeployed.
