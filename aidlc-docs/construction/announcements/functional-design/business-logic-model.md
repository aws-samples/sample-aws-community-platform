# Business Logic Model — Unit 9: Announcements

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Announcements (US-10.1–10.5)
Technology-agnostic business logic for the Announcements service. Companions: `business-rules.md`, `domain-entities.md`, `frontend-components.md`. Conforms to `contracts/services/announcements/openapi.yaml` (to be amended additively — see domain-entities.md). Reflects the finalized functional-design decisions (`aidlc-docs/construction/plans/announcements-functional-design-plan.md`) and the two user-approved requirement deviations (mandatory expiry; UI-only dismissal).

## Purpose & boundary
A broadcast **announcement panel**, distinct from the notification bell and from forum posts. Community Leaders and User Group Leaders author announcements targeted community-wide or to selected user group(s); the targeted audience sees them in a collapsible panel on their landing page. Announcements owns **one table** (the announcement definitions) and is a **single source of truth** per announcement — there is no per-user materialization and no server-side dismissal store.

**Core architectural choice: fan-out-on-read.** Posting, editing, and deleting are each **one O(1) write** regardless of audience size (up to 13k+ members). The panel is computed at read time from the caller's audience (JWT claims) against a small, cacheable set of active announcements. This avoids write amplification, keeps edit/delete "for everyone, immediately" correct, and shows announcements to members who qualify even if they joined a group after the post.

## Actors
- **Community Leader (CL)** — create community-wide or for selected group(s); edit/delete own; **delete any** announcement (moderation); sees the panel on the community analytics dashboard.
- **User Group Leader (UGL)** — create for the one group they lead only (target derived from `ledGroupId`, not chosen); edit/delete own; sees the panel on the group analytics dashboard.
- **Member** — sees the panel on Member Home; dismisses from own view (client-side).
- **Administrator** — excluded entirely (does not author or receive community announcements). 403 on every announcement operation, including reads.
- **Events service (system actor)** — emits `EventCreated{announce}`; Announcements auto-posts on its behalf (US-2.1).
- **Identity & Access (system actor)** — emits `GroupSoftDeleted`/`GroupRestored`; Announcements hides/restores that group's announcements.

## Operations (synchronous REST)

### OP-1 `listAnnouncements` — `GET /announcements?view=panel|mine` (default `panel`)
Two modes on one operation (plan Q3=A):
- **`view=panel` (US-10.4)** — the recipient's active panel. Logic:
  1. Resolve the caller's audience from JWT claims: everyone matches `community`; a member matches a group announcement if its `groupId ∈ memberGroupIds`; a UGL additionally matches their `ledGroupId`; a CL additionally matches any group announcement **they authored** (per the leader-dashboard mockup subtitle "community-wide + announcements you authored").
  2. From the active-announcement set, keep those the caller matches, **excluding** `expiresAt <= now` (BR-6) and `groupHidden == true` (BR-13).
  3. Sort newest-first (`createdAt` desc); return each with `title, body(sanitized HTML), authorName, authorRoleLabel, source, createdAt, expiresAt` (BR-9). The active count is `items.length` (drives the panel header badge).
  4. **Administrator → 403** (BR-3). Client-side dismissal is applied by the frontend, not here (BR-11).
- **`view=mine` (US-10.3)** — the author's management list: announcements where `authorId == caller` (any status, including expired), newest-first, each with `title, target/audience label, createdAt, expiresAt, emailSent, status(Active|Expired derived)`. A **CL may additionally pass `scope=all`** to list every announcement for moderation (BR-4). UGL/Member cannot use `scope=all`.

### OP-2 `createAnnouncement` — `POST /announcements` (US-10.1/10.2)
1. Authorize: CL (`create announcement/global`) or UGL (`create announcement/group`); else 403 (BR-1, BR-2). Administrator 403.
2. Validate input (BR-16): `title` required; `body` sanitized to the allowed HTML subset (BR-14); resolve `target`:
   - CL: `{scope: community}` or `{scope: groups, groupIds: [...]}` (≥1 group).
   - UGL: target is **forced** to `{scope: groups, groupIds: [ledGroupId]}` — any client-supplied target is ignored/rejected (BR-2).
3. Resolve/clamp `expiresAt`: **mandatory**; if absent default to `now + 2 days`; clamp to a maximum of `now + 90 days` (BR-5).
4. Denormalize display fields once (plan Q4=A): `authorName` (via a directory lookup forwarding the caller's JWT — fail-closed to email/id), `authorRoleLabel` (from the caller's role claim, no lookup), `source` ("Community-wide" or the group name(s) resolved once) (BR-8).
5. Write **one** announcement item (BR-7). Set the TTL attribute = `expiresAt` (BR-5).
6. Publish `AnnouncementPublished` carrying `emailOptIn` + resolved audience (BR-10). Does **not** create a bell notification (BR-9).
7. Return the created `Announcement` (201).

### OP-3 `editAnnouncement` — `PUT /announcements/{id}` (US-10.3)
1. Authorize: **author only** (BR-4) — CL's global delete right does not extend to editing others' content. Administrator 403.
2. Editable: `title`, `body` (re-sanitized), `target`, `expiresAt` (re-clamped to the 2-day default / 90-day max rule). Re-denormalize `source` if `target` changed.
3. Single write to the same item; re-publish `AnnouncementPublished` only if the edit changes audience or re-triggers email (design note: edits do not re-send email unless `emailOptIn` is newly set — avoids duplicate blasts). Return the updated item (200).

### OP-4 `deleteAnnouncement` — `DELETE /announcements/{id}` (US-10.3)
1. Authorize: **author**, or **any CL** (moderation, `delete announcement/global`); UGL only own (`delete announcement/own`); else 403 (BR-4). Administrator 403.
2. Single delete of the item → removed from **everyone's** view immediately (fan-out-on-read makes this O(1) and instantaneous). Return 204.

### OP-5 dismissal — **client-side only** (US-10.5)
There is **no server dismiss operation**. The frozen `dismissAnnouncement` (`POST /announcements/{id}/dismiss`) is **removed** from the real contract (it was mock-only; no real consumer depends on it — see domain-entities.md). The frontend records dismissed announcement ids in browser `localStorage` and filters the panel locally (BR-11, BR-12).

## Event-driven flows (asynchronous)

### EV-1 consume `EventCreated` (from Events, US-2.1) — auto-post
Idempotent on the envelope id (BR-15). When `announce == true`: create an announcement via the same OP-2 logic — `authorId = createdBy`, title derived from the event (e.g., "New event: {title}"), body a short summary + link, `target` = the event's group (`{groups,[groupId]}`) or `{community}` if the event has no group, `expiresAt` defaulted (event start or now+2d, clamped to 90d), `emailOptIn = announceByEmail`. When `announce == false`: no-op. Author name/role for the auto-post are resolved the same way (fail-closed).

### EV-2 consume `GroupSoftDeleted` / `GroupRestored` (from Identity) — hide/restore (US, plan Q8=A)
Idempotent. On `GroupSoftDeleted`: set `groupHidden = true` on announcements targeting that group (queried by group scope). On `GroupRestored`: clear the flag. Panel/list reads exclude `groupHidden` items (BR-13). Community-wide announcements are unaffected.

### EV-3 publish `AnnouncementPublished`
Emitted on create (and on qualifying edits) with the platform envelope. **Notifications (Unit 10)** consumes it and sends email when `emailOptIn` is true, using the configured sender/templates. Announcements never calls SES directly (BR-10).

## Read-set sizing & performance
- The set of active announcements in a community is small (tens — everything expires, default 2 days). It is held in a **warm-container cache** (short TTL, same pattern as Settings). The panel read then filters that cached set in memory by claims + expiry + `groupHidden`; a cache miss is a single small query. No scans, no per-row cross-service calls, no write fan-out.
- `view=mine` queries by `authorId` (bounded by what one author created). CL `scope=all` moderation is paginated.
- DynamoDB TTL on `expiresAt` reclaims expired items so the table never grows unbounded.

## Degrade behavior
- **Directory/group name lookup down at create time** → store `authorName`/`source` fail-closed (email or id / raw group id); the announcement still posts (BR-8). Never blocks authoring.
- **EventBridge/Notifications down** → `AnnouncementPublished` is at-least-once; email may be delayed but the in-portal panel is unaffected (the announcement is already written). No synchronous dependency on Notifications (BR-10).
- **Events service down** → irrelevant to Announcements' own reads/writes; auto-post is event-driven and resumes when `EventCreated` is delivered.
