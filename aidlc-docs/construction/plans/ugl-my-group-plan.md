# Change Request Plan — "My Group" for User Group Leaders + 13k-member scale

**Units touched**: Unit 2 (Identity & Access), Unit 15 (SPA)
**Date**: 2026-08-05
**Request**: "For the User Group leader, User Group menu is not needed. Instead there should a link called My Group. Refer the User stories and the UI mockup. Keep in mind that Member list may include 13000+ records in the table."

---

## 1. Analysis (stories + mockup)

### Mockup — `requirements/mockup/ugl/group.html`

| Element | Mockup says |
|---|---|
| Nav | `My Group` is the FIRST item under the `Manage` heading, icon `👥`, links to `group.html`. There is no `User Groups` item anywhere in the UGL sidebar. |
| H1 | The **group name** ("Serverless Guild") — not the literal text "My Group" |
| Subtitle | "View group details and manage members, forums, events, and join requests. Group settings are managed by a Community Leader." |
| Tabs | `Overview` · `Join Requests` + red count badge. No Membership History tab. |
| Overview | `Group Details` card (Name / Members / Leaders / Forums / Created) + `Forums & Channels` card (Manage link, ＋ Create Forum / Channel, note "within your own group only") + Members table |
| Members table | Title `Members (412)` with the search box **in the card header**; toolbar `Showing 1–3 of 412 members`, Rows 10/25/50/100, column settings; columns `Member` (links to profile) / `Role` / `Points (Q2)` / `Joined` / Remove |
| Footnotes | Members: "Removed members are notified by email and can rejoin later. They lose access to this group's forums." Requests: approval/rejection semantics. |
| Requests tab | Info banner when approval is required; card `Pending Join Requests (2)`, oldest first, Member / Requested / Message / Approve+Reject |

### Governing stories

| Story | Bearing on this change |
|---|---|
| US-1.16 | View/manage the group directory. A UGL manages **only the group they lead** — hence one screen, no group picker. |
| US-1.17 | Remove a member — UGL, led group only. Removed member is notified and may rejoin. |
| US-1.21 | Join requests — explicitly "UGL on My Group (led group only)". Reject requires a reason. |
| US-1.18 | UGLs **cannot** edit group configuration → no Edit/Delete buttons, matching the mockup's "Group settings are managed by a Community Leader." |
| US-1.12 | Strict single-group scoping for UGLs. |
| US-3.4 | "Supports pagination for large member lists" — the scale requirement is already a story, not just a preference. |
| US-4.1–4.4 / 4.14 | Forums within the leader's own group → the Forums & Channels card. |
| US-6.13 / 6.16 | Group points → the Points (Q2) column. |
| US-3.3 / 3.10 | Member name links to the member profile. |

### The real 13k problem is on the backend, not the table

The existing `GroupDetailPage` Members tab **already** does server-side cursor
pagination. The bottleneck is that every one of those requests recomputed
membership by folding the group's entire append-only event history:

`list_group_members_page()` → `_member_id_order()` → `current_members_of_group()`
→ `group_events()` = every membership event ever recorded for the group, on
every page request, then one `get_item` per member id to apply the keyword
filter. `list_groups()` did the same fold **once per group in a loop**, so a
single `GET /groups` folded the whole community's history.

Measured cost shape for a 13,000-member group (per request):
- ≥ 13,000 event items read to derive the member set
- up to 13,000 `get_item` calls when a keyword filter is applied

That is the defect. Paging the UI does not fix it.

---

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| M1 | Materialise current membership as `pk=GROUP#<gid>, sk=MEMBER#<memberId>` items, maintained **inside `repository.append_membership_event()`** | Every membership mutation in the service (group_service, user_service, seed, tests) already funnels through that one method, so the projection cannot drift from the event log. Maintaining it in the callers would have meant four separate call sites and four chances to forget. |
| M2 | `current_members_of_group()` reads the projection partition; the event fold is kept as `derive_members_from_events()` for backfill/repair only | Query on one partition instead of a GSI scan of all history. The fold is still the source of truth for reconstruction. |
| M3 | Member count kept in a dedicated counter item `sk=MEMBERCOUNT`, incremented/decremented with conditional writes | Not stored on the group META item: `put_group()` does a full `put_item`, so any read-modify-write of a group (edit, assign leader, restore) would clobber a counter living there. Conditional put/delete on the projection makes the counter exact rather than best-effort. |
| M4 | Denormalise a lowercase `searchKey` onto the projection item and filter with a DynamoDB `contains()` FilterExpression | Without it, keyword search must read every member's profile to test the match — 13,000 `get_item` calls for a query that matches nothing. With it, non-matching rows are discarded server-side and profiles are fetched only for rows the page returns (≤ limit). |
| M5 | Profiles are still read live for returned rows; only `searchKey` is denormalised | Names/email/role/status stay fresh. Names are Cognito-owned and read-only in the portal, so the only field that can go stale is `professionalRole`, which `edit_user` now refreshes. |
| M6 | Paging = real DynamoDB Query with `ExclusiveStartKey`; leaders form a first block, members follow in id order | Leadership is not membership (a UGL has no join event) but the member screen lists both, so the cursor must record which block it stopped in — hence the two-field cursor below. |
| M7 | Member cursor becomes `{m, ld}` (last id + leaders-done flag), accepting the old `{m}` form | A single-field cursor cannot distinguish "stopped inside the leader block" from "stopped inside the member block"; resuming in the wrong block silently skips members whose id sorts below the last leader's id. |
| M8 | `joinedAt` comes from the projection item and is returned on member rows | Closes the mockup's missing `Joined` column with no extra read. |
| M9 | `membership-history` gains `limit`/`cursor`, newest first | The History view folded every event for the group and resolved a display name per row — the same 13k problem in a second place. |
| M10 | `/groups/{id}/requests` gains `limit`/`cursor` and the repository Query is now paginated | A single Query page silently truncated at 1 MB. |
| M11 | Group-member CSV export follows cursors client-side | The unpaged branch would have made 13k `get_item` calls and exceeded the 6 MB Lambda response limit. Export is now N bounded pages. |
| M12 | The leaderboard fetch behind the Points column is bounded (`limit`) | It was unbounded; a 13k-row payload rendered per page is a browser problem, not a server one. Members outside the window show "—", which is the same degrade the screen already uses when scoring is not live. |
| M13 | New `MyGroupPage` rather than a mode flag on `GroupDetailPage` | The two screens differ in layout, tabs, actions and permissions; the only genuinely shared part is the paging logic, which is extracted into `useGroupMembers`. |
| M14 | `/groups` route stays reachable, only the nav item changes for UGLs | The permission matrix grants a UGL `view user-group-directory` at global scope, so removing the route would remove a permission the matrix grants. The request was about the menu. |

### Deliberately NOT done (and why)

- **`listGroupMembers` / `getGroup` group scoping.** Neither appears in `OP_AUTHZ`,
  so any authenticated user can read any group's member list. This is worth
  recording, but it is not an escalation: every role already holds
  `browse member-directory` at global scope, so the same member data is
  reachable by design. Adding a scope check here would restrict Member and
  Community Leader journeys that the matrix permits. Flagged as a follow-up
  rather than changed inside a UI change request.
- **Soft-delete of a 13k-member group** still writes one end event per member.
  Bounded by the projection now instead of an event fold, but still O(members)
  writes in one invocation. Recorded as a known limit.

---

## 3. Execution steps

### Backend — Unit 2 (Identity & Access)

- [x] B1. `models.py`: `member_search_key(user)` helper
- [x] B2. `repository.py`: membership projection (`put`/`delete`/`get`), conditional counter, `current_members_of_group` from the projection, `derive_members_from_events` kept for repair
- [x] B3. `repository.py`: `group_members_page()` — real Query + `ExclusiveStartKey` + `contains(searchKey)` filter
- [x] B4. `repository.py`: two-field member cursor (`{m, ld}`), old form accepted
- [x] B5. `repository.py`: `list_groups_with_counts()` (one Scan for groups + counters), paginated `list_join_requests`, `group_events_page()` (newest first)
- [x] B6. `group_service.py`: `list_groups`/`get_group`/`edit_group` use the counter, not a per-group fold
- [x] B7. `group_service.py`: `list_group_members_page()` rewritten on the projection; `joinedAt` on rows
- [x] B8. `group_service.py`: `list_group_members()` (export path) reads the projection
- [x] B9. `group_service.py`: `list_join_requests` + `membership_history` paged
- [x] B10. `user_service.py`: refresh `searchKey` when a profile field changes
- [x] B11. `app.py`: `limit`/`cursor` on `listJoinRequests` + `membershipHistory`
- [x] B12. `infra/tools/backfill_group_members.py` — derive the projection + counters from existing events for the already-deployed table

### Contract

- [x] C1. `Session` += `ledGroupId`
- [x] C2. `User` += `joinedAt`
- [x] C3. `listJoinRequests` + `membershipHistory` += `limit`/`cursor`; list schemas += `cursor`
- [x] C4. Regenerate mock, run the contract gate

### Frontend — Unit 15 (SPA)

- [x] F1. `roles.ts`: split `UGL_NAV` from `LEADER_NAV`; `User Groups` → `My Group` → `/my-group`
- [x] F2. `AuthScreen.tsx` + `App.tsx`: carry `ledGroupId` on the session
- [x] F3. `App.tsx`: `/my-group` route (before `/groups/:id`)
- [x] F4. `lib/useGroupMembers.ts`: shared server-paged member hook
- [x] F5. `DataTable`: optional `total`/`startIndex` so the toolbar can read "Showing 1–25 of 412"
- [x] F6. `MyGroupPage.tsx`: built to the mockup (Overview + Join Requests, Group Details / Forums & Channels cards, Members table with Joined column, footnotes)
- [x] F7. `GroupDetailPage.tsx`: reuse the hook, add the `Joined` column, bounded leaderboard fetch
- [x] F8. `exportCsv.ts`: cursor-following export

### Verification

- [x] V1. `python3 -m pytest services/identity-access` green
- [x] V2. New tests: projection consistency, counter, paged Query, search filter, joinedAt, history paging, backfill
- [x] V3. `make test` — no regression in any other service
- [x] V4. `make lint` (ruff) clean
- [x] V5. `npm run build` clean
- [x] V6. Contract gate for identity-access
- [x] V7. Update `aidlc-state.md` + `audit.md`
