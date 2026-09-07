# Functional Design Plan — Unit 4: Events

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Events (21 stories, US-2.1–2.21)
**Contract (frozen, amendable)**: `contracts/services/events/openapi.yaml` (17 operations) · **Permission spec**: `contracts/platform/permissions/role-permission-matrix.v1.json`
**Paths**: `/events` · **Owns**: Events, RSVPs, Materials metadata, Upload-links · S3 for materials
**Depends on**: Unit 1 (infra), Unit 2 (identity truth) · **Consumes**: `GroupSoftDeleted` · **Publishes**: `AttendanceRecorded`, `EventDelivered`, `EventOrganized`, `EventCompleted`, `EventCancelled`, `EventReminderDue`, `MaterialsAdded`
**Fourth real service** (after Identity & Access, Member Profiles, Settings)

## Scope
All 21 stories: creation (2.1), reminders (2.2), recurring (2.3), edit (2.4), cancel (2.5), RSVP (2.6), RSVP list + CSV (2.7), .ics invite (2.8), calendar view (2.9), reminder delivery (2.10), MS Teams config (2.11), Teams attendance with review-before-award (2.12), browse (2.13), detail (2.14), materials (2.15), manual/bulk attendance (2.16), event-type point values (2.17), presenter/organizer designation (2.18), mark completed (2.19), Content Library (2.20), event-scoped external upload links (2.21).

## Analysis completed before this plan (per user instruction)

### Sources read
| Source | What it settled |
|---|---|
| `stories.md` Module 2 (US-2.1–2.21) + `requirements/usecases/02-events-and-meetups.md` | Full acceptance criteria, 8 event types, 3 delivery modes, role matrix, status transitions (Upcoming → Completed \| Cancelled only) |
| 9 Events mockups (leader/ugl/member × events, event-manage, calendar) + `file-share.html` + `assets/content-library.js` | Exact fields, filters, columns, badges, actions, modals, microcopy; Content Library search-first behavior + page size 5 + result-row shape; recipient upload page |
| `contracts/services/events/openapi.yaml` | 17 frozen operations already routed through `api-edge.yaml` (`/events` + `{proxy+}`) — no new base path needed |
| `role-permission-matrix.v1.json` | CL: create global, edit/cancel/complete/materials/rsvp-list/attendance/designate/upload-link **own**; UGL: same but **group**; Member: rsvp + browse + download materials + search content-library; **Administrator: no event permissions at all** except `configure ms-teams-integration` |
| `unit-of-work-dependency.md` | Unit 4 ← Unit 1, 2 only; Unit 7 (Contributions) consumes this unit's events; Unit 3 calls this unit by REST for activity counts |
| `services/member-profiles/*`, `services/settings/*` | Conventions to follow: `OPERATIONS` router table + regex match, `Principal.from_claims` + `Authorizer` fail-closed, single-table repo, `FanOutClient` (parallel + per-call timeout + degrade), idempotent event consumer, opaque cursor pagination, S3 presigned-URL broker |

### Confirmed from the mockups (no question needed)
- Event list is **role-shaped**: CL table has a **Scope** column, UGL's does not; Member gets a **card grid** with status tabs (Upcoming/Completed/Cancelled) + search + type/mode/group filters. Leader/UGL lists have **no** filters in the mockup (gap G12 — see Q12).
- Recurring series renders as a **series row + indented occurrence rows**; series row shows `Weekly` in Date, `—` in RSVP, badge `Recurring`, and only an **Edit series** action; occurrences get Manage/Edit/Cancel.
- Manage screen = 5 stat cards (RSVP'd Yes, Attended, Presenters, Organizers, Points Awarded) + 4 tabs (Attendance, RSVP List, Materials, MS Teams). Materials tab also hosts **External Upload Links**.
- Teams tab is explicitly a **review-then-apply** screen: matched/unmatched badges, per-row Include toggle, `✓ Apply & Award Points`, `Re-fetch from Teams`.
- Member detail: RSVP `✓ Going` / `Not going` (no Maybe), Yes/No counters, points-to-attend tag, `Download .ics`, materials with Download only.
- Content Library: tab **inside** Events, search-first (nothing until Search/Enter), keyword-only over material title + event title + event description, filters = content type (Slides/PDF/Doc/Recording/Link) + user group, paginated list, per-row open-online/play-online + download.
- Administrators see no Events nav item anywhere in the mockups — consistent with the permission matrix.

### Mockup gaps found (26, G1–G26) — the ones that change the design
- **G8** — event-manage says the upload-link recipient "cannot list, view, or delete files", but `file-share.html` shows the recipient a full file list with Download buttons. Contradiction inside the same feature → **Q6**.
- **G9** — create modal says "Designated presenters earn delivery points on completion"; member detail shows a leader presenter with "no delivery points (leader)". Story US-2.18 says only Members earn → the authoring UI must state the exclusion.
- **G17** — there is **no Designations panel** on the manage screen and **no organizer field anywhere**, yet the contract has `setDesignations(presenters, organizers)` and the footnote references organizers. → **Q9**.
- **G16/G19** — no confirmation dialogs on Cancel Event / occurrence Cancel; almost no empty states.
- **G20** — series expand/collapse is implied by `▾` but not implemented; Edit series vs Edit occurrence use the identical modal with no scope indicator.
- **G12** — leader/UGL lists have no search/status/type/group filter despite "37 events".
- **G4** — three different group lists across mockups (create modal, calendar filter, Content Library data).
- Full list in the mockup analysis (kept in this plan's discussion, not a separate artifact).

## Steps
- [x] 1. Analyze unit context (unit-of-work.md, story-map, dependency matrix, use case 02, all 21 stories, frozen contract, mock operations + fixtures, permission matrix)
- [x] 1b. Analyze ALL Events UI mockups + shared Content Library script + recipient file-share page (user instruction) — 26 gaps recorded
- [x] 1c. Review reference implementations (member-profiles, settings) for conventions to reuse
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (Q1–Q12 below)
- [x] 4. Store plan
- [x] 5. Collect and analyze answers — user replied "proceed" (2026-08-05), accepting the recommended answers; all 12 = A, no ambiguity, no clarification round needed
- [x] 6. Generate functional design artifacts (`business-logic-model.md`, `business-rules.md`, `domain-entities.md`, `frontend-components.md` — this unit has substantial UI)
- [x] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update `aidlc-state.md`

---

# Questions

Answer by putting a letter after each `[Answer]:` tag. Choose the last option (Other) and describe if none fit.

## Question 1
**MS Teams integration (US-2.11/2.12).** A real Microsoft Graph integration needs an Azure app registration, tenant credentials, and a live Teams meeting to test against — none of which exist in this workspace. How should Teams attendance be built?

A) Provider interface + **stub adapter** now (returns an empty participant list, `503 NOT_CONFIGURED` when the integration is disabled), real Graph adapter deferred to a later change request. Everything downstream of the fetch — the review screen, email matching, include/exclude, Apply & Award — is fully real and testable.

B) Full Microsoft Graph adapter written now against the documented API, untestable end-to-end until credentials are supplied (unit-tested with recorded/faked Graph responses only).

C) Skip US-2.11/2.12 entirely for this unit and log them as deferred stories.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
**Reminders and calendar invites (US-2.2/2.8/2.10).** Notifications (Unit 10) is still a mock, so nothing can actually send email yet. Architecture says Events publishes domain events and Notifications owns SES.

A) **Events owns the .ics generation and the schedule, Notifications owns delivery.** Events writes a due-time record and a scheduled sweep publishes `EventReminderDue` / `CalendarInviteDue` with the rendered .ics attached to the event payload; no email is sent until Unit 10 is real. Events also exposes `GET /events/{id}/ics` so the mockup's `Download .ics` button works today.

B) Events calls SES directly for event email (reminders, change notices, cancellations, .ics), duplicating what Notifications will own later.

C) Events only publishes bare events with no .ics rendering; Notifications renders the .ics when it is built. `Download .ics` in the UI stays non-functional for now.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3
**Event-type point values (US-2.17/2.18).** Point values are owned centrally by Contributions & Scoring (US-6.1), which is still a mock. The UI shows `+10 pts to attend` on cards/detail and a `Points Awarded` stat on the manage screen.

A) **Read-time REST fan-out to Contributions** (same `FanOutClient` pattern Member Profiles uses: parallel, per-call timeout, degrade). When Contributions is unreachable or the value is unknown, the points tag/stat is simply omitted from the response and the UI hides it. Events never stores point values.

B) Events caches the framework values in its own table, refreshed by consuming a `ScoringFrameworkChanged` event (adds a new event to Unit 7's contract).

C) Events stores its own per-event-type point values (fastest, but contradicts US-2.17's "creator cannot override, controlled centrally").

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4
**Recurring series materialisation (US-2.3).** Each occurrence must be an individually editable/cancellable event.

A) **Materialise all occurrences at create time**, capped (proposal: **max 104 occurrences**, i.e. two years weekly; over the cap → `400` telling the creator to shorten the range). Series parent record holds the recurrence rule and renders as the expandable row; occurrences are real events linked by `seriesId`. `Edit series` updates the rule and **future, unmodified** occurrences only (never past or individually-edited ones).

B) Materialise a rolling window (e.g. next 90 days) and extend by a scheduled job — smaller writes, but the list/calendar cannot show the full series.

C) Store only the rule and expand virtually at read time — but then occurrences have no identity to RSVP against or cancel individually (conflicts with US-2.3).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5
**Event materials upload mechanism (US-2.15).** The mockup has an in-page `⬆ Upload file` button, and Settings' US-8.13 rework deliberately chose **curl-only** for external recipients.

A) **In-browser direct-to-S3 upload**: `POST /events/{id}/materials/upload-url` mints a short-lived presigned PUT, the SPA PUTs the file straight to S3, then confirms the material record. Metadata (name/type/size) is stamped by an S3-event consumer, mirroring Settings' `file_share_event_consumer`. Curl stays available but is not the primary path. Allowed types: PDF, PPT/PPTX, DOC/DOCX, XLS/XLSX, PNG/JPG, MP4; **max 500 MB** (the number the mockup already shows).

B) Same presigned-PUT model but **curl-only**, matching Settings exactly (no in-browser upload).

C) Upload through the Lambda (multipart proxy) — simplest client, but caps files at API Gateway's 10 MB payload limit and burns Lambda time.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6
**Event-scoped external upload links (US-2.21) — the one real conflict.** US-2.21 asks for a link an external party with **no portal account** can use to upload multiple files into the event's folder, with 7/14/30/90-day expiry and optional max size. Settings' US-8.13 was reworked to the opposite model (one link = one file slot, no expiry, authenticated-mint-only, curl command) with four approved deviations. `file-share.html` also contradicts itself (G8: "cannot list or view" vs a visible file list with Download).

A) **Follow US-2.21 as written**: a new **unauthenticated public route** (`GET/POST /public/event-uploads/{token}`, on the existing public base path) backed by an unguessable token with a stored expiry; the recipient gets a real upload page, uploads are brokered per-file by short-lived presigned PUTs, write-only (no list/no download for the recipient — resolving G8 in favour of the security statement). Leaders view/download uploaded files inside the event Materials tab. Revoke is immediate at mint time; expiry enforced server-side.

B) **Reuse Settings' US-8.13 model verbatim**, scoped to the event: one slot per expected file, no expiry, leader copies a curl command with a ≤1h presigned PUT and sends it to the external party. Cheapest and consistent with the shipped code, but drops US-2.21's expiry choice and the multi-file folder, and the external party needs curl.

C) Hybrid: Settings' slot model for the record and uniqueness, plus a public token page so the recipient can upload without curl, keeping the 7/14/30/90-day expiry from US-2.21.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 7
**Bulk attendance import (US-2.16).** The story says "Excel/CSV". Identity & Access's bulk import went **CSV-only** deliberately — the `xlsx`/SheetJS npm package has unpatched high-severity CVEs and was uninstalled in favour of a hand-written CSV parser.

A) **CSV-only**, consistent with Identity & Access (downloadable template, per-row result report listing matched/unmatched emails). Label the button "⬆ Upload CSV" instead of the mockup's "⬆ Upload Excel/CSV".

B) CSV + xlsx (reintroduces the vulnerable dependency, or requires a server-side xlsx parser in Python).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 8
**Group-membership visibility source (US-2.13/2.9/2.20).** Members see their groups' events + community-wide; UGLs see their led group + community-wide; CLs see all. Events needs to know the caller's groups. `Principal.from_claims` already reads `member_group_ids` / `led_group_id` from the JWT claims.

A) **Trust the JWT claims** (`member_group_ids`, `led_group_id`), consistent with every other real service; a membership change takes effect on the caller's next token refresh.

B) REST call to Identity & Access per request for fresh membership (adds a synchronous dependency on Unit 2 to every event read, and a latency/failure mode on the hot path).

C) Consume Identity's `MemberJoinedGroup`/`MemberLeftGroup`/`MemberRemoved` events into an Events-owned membership cache (a third copy of membership data).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 9
**Presenter/organizer designation UI (US-2.18, gap G17).** The create modal has a free-text "Presenters / facilitators" input; there is **no** organizer field and **no** post-create designation UI anywhere in the mockups, yet the contract has `setDesignations(presenters, organizers)` and the manage screen counts both.

A) **Add a Designations panel to the manage screen** (member picker for presenters and organizers, editable until the event is completed) and make the create modal's presenter field a real member picker. Show the leader-ineligibility note (US-2.18: only Members earn delivery points) next to any non-Member designee — closing G9 too.

B) Designation only at create/edit time (no separate panel); organizers added to the create/edit modal.

C) Keep presenters only, drop organizers from this unit (would leave US-6.18 organize points unearnable).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 10
**Content Library scale (US-2.20).** Keyword search over materials of completed events, scoped by visibility, paginated.

A) **DynamoDB Query on a materials GSI** partitioned by visibility scope (groupId / `COMMUNITY`) and sorted by event date, with keyword matching applied as a post-filter inside a fetch-until-full page loop and an opaque cursor — the exact pattern already shipped for the Member Directory and File Share listings. Search-first means no query runs until the user submits.

B) Table Scan + filter (simplest, degrades with volume — this is what Member Profiles' directory started with and had to rework).

C) Delegate to the shared Search service (Unit 13) — but US-2.20 explicitly says keyword search, **no semantic search**, and Unit 13 is `Condition`-gated off by default.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 11
**"Also post an announcement" on event create (US-2.1).** Announcements is Unit 9 (still a mock).

A) **Publish an event** (`EventPublishedForAnnouncement` or reuse `EventCreated`) that Announcements consumes when it becomes real; the toggle is recorded on the event and no announcement appears until Unit 9 ships. Keeps Events free of a synchronous dependency.

B) Synchronous REST `POST /announcements` from Events at create time (fails or no-ops against the current mock; couples event creation to another service's availability).

C) Drop the toggle from this unit and add it when Announcements is implemented.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 12
**Mockup gaps in the leader/UGL list (G12, G16, G19, G20).** The leader list shows "37 events" with no search or filters, no confirmation on Cancel, no empty states, and a series `▾` that does not expand.

A) **Close all four**, consistent with what has already shipped elsewhere in this portal: server-side cursor pagination + debounced search + status/type/group filters (as on Admin Users and Member Directory), a confirmation dialog on Cancel Event / occurrence Cancel, empty states on every list, and a real expand/collapse for series rows with an explicit "this occurrence" vs "whole series" indicator on Edit.

B) Build exactly what the mockups show and log the gaps as follow-ups.

C) Close only the safety-relevant ones (cancel confirmation + empty states); leave list filters/pagination for a later change request.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

**Recommended answers** (what I would choose if you want to move fast): Q1 **A**, Q2 **A**, Q3 **A**, Q4 **A**, Q5 **A**, Q6 **A**, Q7 **A**, Q8 **A**, Q9 **A**, Q10 **A**, Q11 **A**, Q12 **A**. Reply "all A" to accept, or answer individually.
