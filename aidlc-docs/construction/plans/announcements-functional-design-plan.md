# Functional Design Plan — Unit 9: Announcements

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Announcements (5 stories, US-10.1–10.5)
**Contract (frozen, to be amended)**: `contracts/services/announcements/openapi.yaml` · **Permission spec**: `contracts/platform/permissions/role-permission-matrix.v1.json`

## Scope
Stories US-10.1 (Create), US-10.2 (Target), US-10.3 (Manage — edit/delete), US-10.4 (View panel), US-10.5 (Dismiss). Path base `/announcements`. Owns **Announcements** and **Dismissals** tables. Publishes `AnnouncementPublished`. Consumes `GroupSoftDeleted` (Identity & Access, hide group announcements) and `EventCreated` (Events, auto-post an announcement when `announce=true` — US-2.1 integration). Optional email is delegated to Notifications (Unit 10) via the published event — this service never calls SES directly.

Announcements is a broadcast panel capability, **distinct from bell/in-portal notifications and forum posts**. Posting an announcement does NOT create a bell notification (use case 10, US-10.1). Administrators neither author nor receive community announcements.

## Amendments from UI-mockup cross-check (2026-08-07, user-prompted "did you refer the UI mockup?")
Initial analysis read only `leader/announcements.html`. A full sweep of `ugl/announcements.html`, `member/dashboard.html`, `leader/dashboard.html`, `ugl/dashboard.html`, and `coverage.html` confirmed the recommended directions below and added these concrete, binding UI facts (the design + `frontend-components.md` will follow them):

1. **The recipient panel is on all three landing pages, not just Member Home.** `coverage.html` maps US-10.4/10.5 only to Member Home, but the use case and the mockups agree the collapsible panel also renders on `leader/dashboard.html` ("Community-wide announcements + announcements you authored") and `ugl/dashboard.html` ("Community-wide announcements + your group (Serverless Guild)"). The panel is a **collapsed card** with a chevron and a header active-count badge — `📣 Announcements (N)`.
2. **Each panel card's meta line is `<source> · <authorName> (<authorRoleLabel>) · <date>` and shows `· expires <date>` when an expiry is set** (e.g., "Community-wide · Dana Cross (Community Leader) · Jun 8, 2026"; "AI/ML Guild · Sam Kim (User Group Leader) · Jun 3, 2026 · expires Jun 30"). This means the panel payload must carry `source`, `authorName`, **`authorRoleLabel`**, `createdAt`, and `expiresAt` — and needs them with **zero per-row cross-service calls** (strengthens Q4 → denormalize-at-create). The card body renders **rich-text HTML with links** (reinforces Q7). A `✕` dismiss button sits on every card (US-10.5).
3. **UGL authoring has no audience choice** — the Audience field is a **readonly** "Serverless Guild (your group)"; the server derives the target from the UGL's `ledGroupId` (the UI never offers a picker). CL authoring offers `community` vs `Selected user group(s)` with a **multi-select group toggle list** → confirms `target = {scope: community|groups, groupIds: [...]}` with `groupIds` being an array (multiple groups).
4. **The author management list (US-10.3, `view=mine`) columns differ by role**: CL table = Title · Audience · Created · Expiry · Email · Status; UGL table = Title · Created · Expiry · Email · Status (no Audience column, since it is always their group). `Email` renders Sent/No; `Status` renders Active/Expired (derived, D4). CL footer states CL may delete any announcement (incl. group) for moderation; UGL footer states its reach includes co-leaders. This confirms `emailSent` and derived `status` on the `view=mine` payload.

None of these contradict the proposed decisions; they confirm Q3 (view selector), Q4-A (denormalize author name — **plus author role label** — and group name/source at create), Q5-A (claims-based targeting), and Q7 (sanitized rich-text HTML). Q4 below is updated to include the author role label and the inline expiry display.

## Established context (from artifacts — no question needed)
| Source | Fact that constrains this design |
|---|---|
| `role-permission-matrix.v1.json` | **CL**: `create announcement/global`, `delete announcement/global` (moderation — any announcement). **UGL**: `create announcement/group`, `delete announcement/own`. **Member**: `view announcement/global`, `dismiss announcement/own`. **Administrator**: no announcement actions (excluded). |
| use case 10 | Rich-text body; optional expiry (auto-removed after); optional email opt-in (default off); target = community-wide OR one/more groups (CL) / own led group only (UGL); panel is collapsed-by-default with active count; per-member dismissal; author edit/delete for everyone; CL can delete any for moderation; expired not shown; no separate top banner. |
| use case 10 (Notes) + `events` contract | An announcement can also be created as part of event creation (US-2.1). Events publishes `EventCreated{announce, announceByEmail, groupId, title, ...}` — the intent travels on the event (async), Events never calls Announcements synchronously. |
| frozen contract | Current ops: `listAnnouncements`, `createAnnouncement`, `editAnnouncement`, `deleteAnnouncement`, `dismissAnnouncement`. The `Announcement` schema is minimal (`id,title,body,audience,active`) and **lacks** body/expiry/structured-target/author/source/created-date/email-sent/status/dismissed fields the use case requires → **additive contract amendment expected** (backward-compatible, mirrors the Events/Member-Profiles precedent). |
| FQ2 / precedent (Events, Member Profiles) | Async events for cross-service workflows; REST only for synchronous reads. Member group membership is available from JWT claims (as Events uses `memberGroupIds`/`ledGroupId`); denormalized display names are not in claims (claims carry no name — the lesson from Events' designation UUID defect). |

## Steps
- [x] 1. Analyze unit context (unit-of-work.md, story-map, use case 10, frozen contract, mock_operations/fixtures, permission matrix, both announcements mockups, shipped `AnnouncementsPage`, Events `EventCreated` integration)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (below, with `[Answer]:` tags)
- [x] 4. Store plan
- [x] 5. Collect + analyze answers (brainstormed 2026-08-07; two requirement deviations approved — see Finalized decisions)
- [x] 6. Generate functional design artifacts (`business-logic-model.md`, `business-rules.md`, `domain-entities.md`, `frontend-components.md`)
- [x] 7. Present completion message
- [x] 8. Await explicit approval (approved 2026-08-07)
- [x] 9. Record approval + update aidlc-state.md
- [ ] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update aidlc-state.md

---

## Proposed decisions (resolved from artifacts + precedent — flagged for review; override any)
These are not open questions; they are the design directions I will take unless you object at the gate. The genuinely open items are the numbered questions after this table.

| Ref | Area | Proposed decision |
|---|---|---|
| D1 | Email delivery | Announcements **publishes `AnnouncementPublished`** carrying `emailOptIn` + resolved audience; **Notifications (Unit 10) delivers** the email. Announcements never touches SES. Matches unit-of-work ("optional email via Notifications") and the Events precedent of intent-on-event. |
| D2 | No bell notification | Creating an announcement does **not** emit an in-portal/bell notification (US-10.1 explicit). `AnnouncementPublished` is consumed only for the optional email; it is not a US-8.15 recipient-matrix trigger. |
| D3 | Authorization | In-service, fail-closed, from the permission matrix: create → CL(any target)/UGL(own led group only); edit → author only; delete → author, **plus CL on any** (moderation); dismiss/view → any Member+leader in audience; **Administrator 403 on all** announcement ops incl. read (they don't participate). |
| D4 | Status is derived | `status` (Active/Expired) is **computed at read time** from `expiresAt` vs now — never a stored mutable flag. |
| D5 | Contract amendment | Extend additively (no breaking change, no api-edge regen — all under the already-routed `/announcements` base path): `Announcement` gains `body, target{scope,groupIds}, authorId, authorName, source, createdAt, expiresAt, emailSent, status, dismissed`; create/edit bodies gain `body, target, expiresAt, emailOptIn`; `listAnnouncements` gains a `view` selector (see Q3). Bump `announcements/openapi.yaml` to v2.0.0. |
| D6 | Ownership boundary | Announcements owns Announcements + Dismissals tables only. It does **not** own group membership, group names, or user identity — those are read from JWT claims and/or denormalized per Q4/Q5. |

---

## Finalized decisions (2026-08-07, after brainstorming — user-approved)
The model is **fan-out-on-read on a single shared announcement definition** (no per-user materialization, no write fan-out). Answers:

| Q | Decision |
|---|---|
| Q1 Dismissal | **UI-only (browser localStorage), NOT persisted server-side — no Dismissals table.** Acceptable because expiry is now mandatory + short (Q2), so cross-device reappearance is bounded and self-clears. (Requirement deviation — US-10.5 updated.) |
| Q2 Expiry | **Mandatory expiry, default 2 days, max 90 days.** Read-time filter (`expiresAt <= now` never returned) is authoritative; **DynamoDB TTL** on `expiresAt` reclaims storage. Keeps the read set bounded — the basis of the fan-out-on-read design. (Requirement deviation — US-10.1 updated.) |
| Q3 List op | **A** — one `GET /announcements` with a `view` param (`panel` default / `mine` for author+moderation). |
| Q4 Display denorm | **A** — denormalize `authorName`, `authorRoleLabel`, `source` (group name / "Community-wide") at create; panel/list reads need zero per-row cross-service calls. |
| Q5 Targeting | **A** — from JWT claims (`memberGroupIds`/`ledGroupId`/role); zero lookups on the hot path. |
| Q6 Events auto-post | **A** — consume `EventCreated` (idempotent on envelope id); `announce=true` → create via the same path, `emailOptIn = announceByEmail`. |
| Q7 Rich text | **A** — store a sanitized constrained-HTML subset (sanitize-on-write at the trust boundary). |
| Q8 GroupSoftDeleted | **A** — consume it, set a `groupHidden` flag folded into the read filter; reversible on `GroupRestored`. |

**Performance shape**: post/edit/delete are single O(1) writes (no audience fan-out); the panel (hot path, all members) is a small bounded query over a warm-container-cached active set (tens of items), filtered in-memory by claims + expiry + `groupHidden`; TTL handles all cleanup so the table stays bounded. Two requirement deviations recorded in stories.md, use case 10, and unit-of-work.md (Dismissals table removed); both authoring mockups updated (expiry now required).

---

## Questions (original — retained for traceability; see Finalized decisions above)

Recommended option is marked **(recommended)**.

## Question 1
**Per-member dismissal persistence (US-10.5).** The use case explicitly defers this to design: "persistence of per-member dismissal state will be elaborated during the design phase." How should a dismissal be stored and enforced?

A) **(recommended)** Dedicated **Dismissals table** — one item per `(memberId, announcementId)`; the panel query (US-10.4) filters out any announcement the caller has dismissed. Durable, exact, survives re-login; matches "Owns: Dismissals table" in unit-of-work.md.

B) Store dismissed member ids as a list attribute **on the announcement item** (no separate table). Simpler, but unbounded growth on a community-wide announcement (up to 13k ids on one item) and item-size risk.

C) Client-side only (localStorage) — no server persistence.

X) Other (describe after `[Answer]:`)

[Answer]: X — UI-only dismissal (browser localStorage), no Dismissals table. Chosen after brainstorming (see Finalized decisions): with mandatory short expiry, durable server-side dismissal is unnecessary and a per-read dismissal lookup + table are removed from the hot path. No per-user fan-out anywhere.

## Question 2
**Expiry enforcement (US-10.1 / US-10.4 — "automatically removed from all views" / "expired not shown").** How is expiry enforced?

A) **(recommended)** **Read-time filtering** as the source of truth (an announcement with `expiresAt <= now` is never returned by any list/panel query), **plus DynamoDB TTL on `expiresAt`** for eventual physical cleanup only. Read-time filter guarantees "not shown" immediately; TTL (which can lag up to ~48h) just reclaims storage. No scheduler needed.

B) Scheduled sweep (EventBridge Scheduler) that flips expired announcements to an inactive state on a cadence, like the Events reminder sweep.

C) Read-time filtering only (no physical cleanup — expired rows retained indefinitely for the author's history list per US-10.3, which shows Expired status).

X) Other (describe after `[Answer]:`)

[Answer]: X — Mandatory expiry (default 2 days, max 90 days) + read-time filter + DynamoDB TTL. (Variant of A made mandatory; requirement deviation approved.)

## Question 3
**One `listAnnouncements` serving two very different lists.** US-10.3 needs the **author's management list** (announcements *they created*, with audience/created/expiry/email-sent/status, incl. expired). US-10.4 needs the **recipient panel** (active, targeted-to-me, newest-first, dismissed+expired excluded). How should the frozen single `GET /announcements` op serve both?

A) **(recommended)** Keep one op with a **`view` query param**: `view=panel` (default — recipient's active panel, US-10.4) and `view=mine` (author/moderation management list, US-10.3; CL additionally may pass a filter to see all for moderation). Additive, no new route.

B) Two separate paths: `GET /announcements` (panel) + `GET /announcements/authored` (management list). Clearer, adds a route under the same base path (still no api-edge regen).

C) Single op, role-inferred (leaders implicitly get the management list, members get the panel) with no explicit param.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 4
**Author name + role label + source (group name) for display (US-10.4 — panel meta `<source> · <authorName> (<authorRoleLabel>) · <date>`).** JWT claims carry ids/role/group ids but **not** display names (the UUID-in-UI defect from Events). The mockup panel shows the author's name **and** a role label ("Community Leader"/"User Group Leader") plus the source (group name or "Community-wide"). Where do the author's name and group name come from?

A) **(recommended)** **Denormalize at create time**: resolve author display name + selected group name(s) once via a read-time fan-out to Member Profiles / Identity (`GET /members/{id}`, `GET /groups/{id}`, forwarding the caller's JWT — same DirectoryClient pattern as Events), and store `authorName`, `authorRoleLabel` (from the caller's role claim — no lookup needed), and `source` on the announcement. Panel/list reads then need zero cross-service calls (required — a community-wide card would otherwise fan out per row for up to 13k readers). Fail-closed to email/id if the name lookup fails.

B) **Read-time fan-out** on every panel/list load (not stored) — always fresh if a group is renamed, but adds cross-service latency to the panel and repeats the Member-Directory anti-pattern this repo already reworked twice.

C) Store only ids (`authorId`, `target.groupIds`); the **frontend** resolves names from data it already holds. Smallest backend, but the panel needs those names and the SPA may not have them for arbitrary authors.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 5
**Recipient targeting source for the panel (US-10.4).** To decide which announcements a caller sees, the service needs the caller's group memberships (and, for a UGL, their led group). Where does that come from?

A) **(recommended)** From the caller's **JWT claims** (`memberGroupIds`, `ledGroupId`, role) — exactly as Events resolves audience today. No cross-service call, no local projection; a community announcement matches everyone, a group announcement matches if its `groupId` is in the caller's memberships (or is the UGL's led group). CL sees community-wide + any group announcement they authored.

B) Maintain a **local membership projection** by consuming Identity's `MemberJoinedGroup`/`MemberLeftGroup`/`MemberRemoved` events (like Member Profiles), and match against that. More moving parts; adds 3 consumed events beyond the `GroupSoftDeleted` in unit-of-work.md.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 6
**Auto-announcement from event creation (US-2.1 → US-10.1).** Events already publishes `EventCreated{eventId,title,groupId,announce,announceByEmail,createdBy,...}`. When `announce=true`, Announcements should create an announcement. How much of this is in scope for **this** unit's functional design, and what shape?

A) **(recommended)** In scope now. Announcements **consumes `EventCreated`** (idempotent on envelope id); when `announce=true` it creates an announcement authored by `createdBy`, titled from the event, bodied with a link/summary, targeted to the event's group (or community-wide if the event has no group), with `emailOptIn = announceByEmail`. This is the same create path as US-10.1, just event-triggered.

B) Model the consumer now but treat the auto-created announcement's title/body wording + link as a Code-Generation detail (design records the trigger + mapping only).

C) Defer entirely — out of scope for Announcements; revisit when both services are real.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 7
**Rich-text body handling + XSS (Security Baseline is enabled).** The body is rich text with formatting/links (US-10.1) rendered into other members' browsers. How should the body be stored/sanitized?

A) **(recommended)** Store a **constrained HTML subset, server-side sanitized on write** (allow-list of formatting tags + safe links; strip scripts/handlers/`javascript:` URIs). Rendered as HTML in the panel. Defends against stored XSS at the trust boundary regardless of client.

B) Store **Markdown**; render to sanitized HTML on the client. Body is inert at rest; sanitization still required at render.

C) Store raw HTML; rely on the frontend to escape/sanitize at render only. (Not recommended — stored-XSS risk if any other client renders it.)

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 8
**`GroupSoftDeleted` handling (consumed — "hide group announcements").** When a group is soft-deleted, its group-targeted announcements should disappear from views. Mechanism?

A) **(recommended)** Announcements **consumes `GroupSoftDeleted`** and marks that group's announcements hidden (a stored flag); panel/list queries exclude hidden ones. Reversible if a `GroupRestored` is later consumed (restore the flag). Symmetric with the soft-delete/restore model in Identity.

B) Don't consume the event; instead **filter at read time** against a locally cached set of soft-deleted group ids (still needs the event to maintain the set — effectively the same input, different storage).

C) Hard-hide only (mark hidden on soft-delete; do not restore on `GroupRestored`).

X) Other (describe after `[Answer]:`)

[Answer]: A
