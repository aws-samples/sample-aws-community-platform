# Functional Design Plan — Unit 10: Notifications

> ## ⏸️ PARKED 2026-08-05 — do not resume from this plan
>
> User decision: *"Will come back to Notification Unit of Work later. Will proceed with other Units for which we have requirement and design clarity."*
>
> This unit **restarts from Requirements Analysis (INCEPTION)**, not from this functional-design plan. Four requirement-level gaps, not design gaps, forced the step back:
> 1. **Scale is unspecified in every story** — the 13,000-recipients-per-notification figure that drives the whole architecture appears in no requirement or story.
> 2. **US-8.7 is withdrawn** (users get no preferences; the Administrator configures system-wide). That deletes the opt-out/mandatory taxonomy which US-8.2, US-8.5 and US-8.15 all reference, so three other stories now contain false statements.
> 3. **US-8.5 ownership is ambiguous** and ~1/3 built in Unit 11 Settings, which is not the unit the story map assigns it to.
> 4. **18 of the 23 recipient-matrix rows have no producer**, and rows 11 and 21 need events that the already-deployed Identity & Access does not publish. The trigger catalogue is not frozen.
>
> **Still valid as input to the requirements pass** (do not redo): the source analysis, the producer-readiness table, the shipped-code inventory (bell + Preferences tab + Settings templates + Identity's real event names), and the verified platform limits. **Answers Q1/Q4/Q6/Q7/Q8/Q10/Q11 = A were given but are NOT binding** — they were answers to design questions asked ahead of the requirements they depend on. Q8 A in particular was later shown to be unworkable at 13k (see the clarification file, section C3).
>
> Nothing was implemented: no contract, code, IaC or `aidlc-state.md` change. Unit 10 remains `mode: mock` in `service-mode.json`.

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Notifications (6 stories: US-8.2, 8.4, 8.5, 8.6, 8.7, 8.15)
**Contract (frozen, amendable)**: `contracts/services/notifications/openapi.yaml` (4 operations) · **Permission spec**: `contracts/platform/permissions/role-permission-matrix.v1.json`
**Paths**: `/notifications` · **Owns**: in-portal notifications table, per-user preferences table
**Depends on**: Unit 1 (infra) · **Consumes**: domain events from Units 2, 4, 5, 6, 7, 9 via EventBridge → SQS · **Publishes**: nothing
**Started in a parallel chat session** while Unit 4 (Events) functional design is under review in another session — see Q1.

## Scope
Six stories, but the unit is the delivery engine for the **entire portal's** notification surface:
- **US-8.15** — the authoritative recipient matrix: 23 rows × 4 roles, with the leader/Administrator exclusion rules. Single source of truth referenced by 8.2/8.6/8.7.
- **US-8.2** — 22 email types via SES, gated by (1) the admin per-type switch, then (2) the user's preference.
- **US-8.6** — in-portal bell: unread count, latest 20 unread, "+N older", mark-read removes from panel, never mutable, never gated by the admin switch.
- **US-8.7** — per-user opt-out preferences (Members/UGL/CL only; Administrators have none).
- **US-8.4** — sender name/address (SES-verified) + retry policy: exponential backoff, ≤3 retries / 15 min, then discard silently.
- **US-8.5** — 22 templates with `{{placeholders}}`, preview, defaults, **plus a per-type Enabled toggle** — currently *partially shipped inside Settings* (see Q2).

## Analysis completed before this plan

### Sources read
| Source | What it settled |
|---|---|
| `stories.md` US-8.2/8.4/8.5/8.6/8.7/8.15 + `requirements/usecases/08-cross-cutting-concerns.md` | Full trigger lists, the 23-row recipient matrix with footnotes 1–6, the two-independent-gates rule (admin switch first, user pref second), mandatory vs opt-out category split, panel behaviour (20 unread + "+N older" + auto-discard) |
| `requirements/mockup/{member,ugl,leader}/notifications-prefs.html` | Exact preference UI: 9 opt-out toggles, 4 mandatory rows rendered as read-only "Always on", Save Preferences, and the time-zone card (already owned by Settings/US-8.14) |
| `requirements/mockup/member/dashboard.html` (bell markup, shared across every mockup) | Bell with numeric dot, `dd-head` + "Mark all read", per-row icon/rich text/relative time, footer literal "Showing latest 20 · +2 older", read rows visually distinct from unread |
| `contracts/services/notifications/openapi.yaml` | Only 4 thin operations exist (`listNotifications`, `markRead`, `getPreferences`, `updatePreferences`); no unread count, no "+N older", no mark-all-read, no admin per-type switch. Contract will need additive amendment |
| `frontend/src/components/AppLayout.tsx` + `features/singletons.tsx` | The bell and the Preferences → Notifications tab are already built and already call the real routes (`/notifications`, `/notifications/{id}/read`, `/notifications/preferences`). Today they hit the mock. `markAll` currently loops client-side; unread count is computed client-side from the returned page |
| `services/settings/src/email_template_service.py` + `models.py` | Settings **already ships** template list/update (Administrator-only, `SettingsChanged` on write) — but with **3 default templates, not 22**, and **no Enabled toggle**. Direct ownership overlap with US-8.5 → Q2 |
| `services/identity-access/src/*` (real service) | Publishes `UserProvisioned`, `UserDeactivated`, `UserReactivated`, `UserRoleChanged`, `MemberJoinedGroup`, `MemberLeftGroup`, `MemberRemoved`, `GroupCreated/Updated/SoftDeleted/GroupRestored`. **No first-login event and no join-request-decision event** → Q6 |
| `aidlc-docs/construction/events/functional-design/*` (in flight, other session) | Events will publish `EventUpdated`, `EventCancelled`, `EventReminderDue`, `MaterialsAdded` for this unit, and BR-N2 fixes the split: *Events renders the .ics and publishes; Notifications delivers.* RSVP-confirmation email is implied by the same split |
| `services/member-profiles/*`, `services/settings/*` | Conventions to reuse: `OPERATIONS` router table, `Principal.from_claims` + fail-closed `Authorizer`, single-table repo, idempotent event consumer keyed on event id, opaque cursor pagination, `SettingsClient` 30 s warm-container cache |
| `unit-of-work.md` / `-dependency.md` | Unit 10 is a pure sink: consumes most domain events, publishes none, buffered by SQS + DLQ |

### Confirmed without needing a question
- The **frontend already exists** for both stories that have UI (bell + preferences), and it calls the final route shapes. This unit is overwhelmingly backend: no new screens, only additive fields (`unreadCount`, `olderCount`, richer notification rows) and a mark-all-read call.
- **Administrators are excluded everywhere** — no preferences, no community notifications, only row 23 (account deactivation). Consistent with the matrix and with the mockups (no bell content for admin).
- **In-portal is never suppressible** — not by user preference, not by the admin per-type switch. Only the email leg is gated.
- **Leader exclusions are structural**, not preferences: rows 13–20 never reach UGL/CL; rows 6/11/12 reach a UGL only as a member of a group they do not lead, and never a CL.

### Blocking observation — producer readiness
The recipient matrix has 23 rows. Grouped by whether anything can actually emit them today:

| Producer state | Rows | Detail |
|---|---|---|
| **Real and already emitting** | 6, 12, 23 | `MemberRemoved`, `GroupRestored`, `UserDeactivated` from Identity & Access |
| **Real service, event missing** | 11, 21 | Join-request approve/reject and first-login welcome (US-3.7) are not published by Identity & Access today → additive change request to a shipped service (Q6) |
| **Designed this week, not yet approved/built** | 1–5 | Events (Unit 4) — the four event names above are settled in its draft functional design but the schemas are not written to `contracts/` yet (Q1) |
| **Still mock** | 7–10, 13–20, 22 | Forums (7–10), Contributions (13, 14, 19, 20), Certifications (15–18), Announcements (22) |

So Notifications can be designed and built now, but **only 3 of 23 rows can fire end-to-end on the day it ships**. Q7 decides whether we build the whole registry anyway.

## Steps
- [x] 1. Analyze unit context (unit-of-work.md, story-map, dependency matrix, use case 08, the 6 stories, frozen contract, permission matrix)
- [x] 1b. Analyze the notification UI that already exists (bell in `AppLayout.tsx`, Preferences tab in `singletons.tsx`) + all 3 `notifications-prefs.html` mockups + the shared bell markup
- [x] 1c. Cross-check overlaps with shipped services (Settings email templates, Identity & Access published events) and with Unit 4's in-flight design
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (Q1–Q11 below)
- [x] 4. Store plan
- [x] 5a. Collect answers — 2026-08-05: **Q1 A · Q4 A · Q6 A · Q7 A · Q8 A · Q10 A · Q11 A** accepted. **Q2** ("tell me more about B"), **Q3** ("pros and cons for both… 13,000+ users per event notification"), **Q5** ("need more discussion") and **Q9** (per-user preferences withdrawn — Administrator configures system-wide) all require a follow-up round
- [ ] 5b. Resolve the follow-up round in `notifications-functional-design-clarification-questions.md` (C1 template ownership · C2/C2b pipeline at 13k scale · C3 the recipient-payload amendment the 13k figure forces on the accepted Q8 A · C4/C4b panel semantics · C5a–C5d the US-8.7 withdrawal)
- [ ] 6. Generate functional design artifacts (`business-logic-model.md`, `business-rules.md`, `domain-entities.md`, `frontend-components.md`)
- [ ] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update `aidlc-state.md`

---

# Questions

Answer by putting a letter after each `[Answer]:` tag. Choose the last option (Other) and describe if none fit.

## Question 1
**Running this unit in parallel with Unit 4 Events.** Both chat sessions share one working tree, one git branch, and one `aidlc-state.md` / `audit.md`. Notifications' own files (`aidlc-docs/construction/notifications/`, `contracts/services/notifications/`, `services/notifications/`, `.deploy-staging/service-notifications-*.yaml`) do not collide with Events' files at all. The real coupling is that rows 1–5 of the recipient matrix consume four Events events whose payload schemas are still unapproved.

A) **Design-only in parallel now** — run Functional Design → NFR Requirements → NFR Design → Infrastructure Design for Notifications while Events is in review, and hold Notifications *Code Generation* until Unit 4's event schemas are approved and written to `contracts/services/events/published-events/`. Design against the four event names as drafted and flag them as provisional.

B) **Full unit in parallel, including code generation** — build the consumers against Events' draft schemas now and accept a follow-up change request if Unit 4's review changes a payload.

C) **Design and build only the rows whose producers exist today** (rows 6, 12, 23), and extend Notifications once per unit as each publisher becomes real.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
**US-8.5 email templates — ownership conflict with shipped code.** The story map assigns US-8.5 to Unit 10, but Settings (Unit 11, already real and deployed) ships `listEmailTemplates` / `updateEmailTemplate`, an admin Email Templates screen, and `SettingsChanged` on write. It has only 3 default templates and no per-type Enabled toggle, so US-8.5 is roughly a third done in the wrong unit.

A) **Settings keeps the admin CRUD surface; Notifications owns the semantics.** Extend Settings' defaults from 3 to the full 22 types, add the per-type `enabled` toggle to its template records and screen, and have Notifications read templates + switches through a cached `SettingsClient` (the exact pattern Identity & Access already uses, 30 s warm-container cache) plus `SettingsChanged` invalidation. Amend the story map to record US-8.5 as jointly owned: admin UI in Unit 11, rendering and gating in Unit 10. No shipped code is thrown away.

B) **Move template ownership to Notifications** — new `/notifications/templates` routes, the 22 defaults and the toggle live here, and the Settings screen is repointed at the new endpoints. Story-map-conformant and puts notification content in the notification domain, but deletes working Settings code and reworks a live screen.

C) Duplicate: Settings keeps its templates for admin editing, Notifications keeps its own copy for rendering. (Listed for completeness — two sources of truth for the same 22 records.)

D) Other (please describe after [Answer]: tag below)

[Answer]: Tell me more about B

## Question 3
**Delivery pipeline shape.** The unit-of-work says EventBridge → SQS (durable) → SES / in-portal.

A) **One EventBridge rule set → a single standard SQS queue → one consumer Lambda, with a DLQ.** The consumer resolves event → notification type → recipients → per-recipient fan-out, writing the in-portal row and enqueuing the email in the same invocation. Batch size > 1 with partial-batch-failure reporting so one bad message cannot poison a batch. Idempotency keyed on `(eventId, recipientId, channel)` in the shared idempotency store, so a redelivery can never double-send.

B) **Two queues** — one for in-portal writes, one for email — so an SES outage cannot delay the bell. More moving parts, but the channels fail independently.

C) EventBridge → Lambda directly, no SQS (simpler, but loses durable buffering and the retry/DLQ control US-8.4 asks for).

D) Other (please describe after [Answer]: tag below)

[Answer]: What i sthe proc and cons for both. Keep in mind that there will be 13000+ users for each events notfications needs to be delivered. 

## Question 4
**US-8.4 retry semantics: "exponential backoff, up to 3 retries over 15 minutes, then discard, no failure surfaced".**

A) **Let SQS own the retries.** `maxReceiveCount = 4` (initial + 3) with escalating per-message visibility timeouts to approximate the 15-minute window, then the message lands in the DLQ — which *is* the "discarded" state: nothing is sent, nothing is surfaced to the user, but the message is retained for operators and an alarm fires on DLQ depth. Only genuinely retryable SES errors (throttling, 5xx) are retried; permanent ones (unverified sender, malformed address, suppression-list) fail once and are recorded, not retried.

B) In-Lambda retry loop with sleeps between attempts (burns Lambda duration holding a message for up to 15 minutes; a container recycle loses the attempt).

C) Step Functions with a Retry policy per email (precise backoff, adds a state machine execution per email).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5
**In-portal panel: "latest 20 unread", "+N older", "older beyond the limit auto-discarded".** These three requirements read as slightly contradictory (a discarded notification cannot be counted as older).

A) **Store every notification with a TTL (proposal: 90 days) and treat "auto-discarded" as expiry, not truncation.** The panel Queries the user's notifications newest-first, returns up to 20 unread, and reports `olderCount` = remaining unread beyond those 20 (counted, capped at a sane display maximum). Mark-read removes the row from the panel but keeps it until TTL, which is what makes an accurate `olderCount` possible and keeps `unreadCount` on the bell cheap (a stored counter maintained on write/read).

B) Hard-delete anything beyond the newest 20 unread at write time. Literal reading of "auto-discarded", but `+N older` then always reads 0 and history is unrecoverable.

C) Keep everything forever (no TTL), rely on pagination only.

D) Other (please describe after [Answer]: tag below)

[Answer]: Need more discussion

## Question 6
**Two matrix rows have no producer in a service that is already real.** Row 11 (join request approved/rejected → the requester, email + in-portal) and row 21 (welcome on first login → the new user, email + in-portal, US-3.7). Identity & Access is deployed and publishes neither.

A) **Additive change request to Identity & Access** as part of this unit: publish `JoinRequestDecided` (approve/reject, with the requester and group) and `UserFirstLogin` (emitted once, on the first authenticated login of a user who has no prior login stamp). Both are additive to a shipped contract, no route changes, and both are needed for rows 11 and 21 to ever work.

B) Derive both inside Notifications from what already exists — infer the welcome from `UserProvisioned` (fires at registration, **not** first login, so it changes the story's trigger) and the join decision from `MemberJoinedGroup` (fires on approval only, so a **rejection** can never notify).

C) Defer rows 11 and 21 to a later change request and ship the other 21 rows.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 7
**How much to build while 5 of 6 publishers are still mock.**

A) **Build the complete engine, registry-driven.** A single in-service `NOTIFICATION_TYPES` registry encodes all 23 matrix rows — source event name, channels, recipient rule, template id, preference category, mandatory flag, role exclusions — and consumers are registered from it. Types whose producer is still a mock simply never receive an event; nothing is dead code, and each later unit becomes real with zero Notifications changes. Tests assert the registry stays one-to-one with the 22 template ids and with the US-8.7 opt-out/mandatory lists, which is the "lists cannot drift" requirement made executable.

B) Build only the rows with live producers now (3, or 5 with Q6=A) and add the rest as each unit lands — smaller now, but touches Notifications six more times.

C) Build the full registry but keep email in dry-run (log, do not call SES) until more publishers are real.

D) Other (please describe after [Answer]: tag below)

[Answer]:A

## Question 8
**Who resolves recipients.** For most rows the publisher is the only service that knows the audience (Events knows the RSVP list, Forums knows followers and the mentioned user, Contributions knows the submitter).

A) **The publisher carries the recipient list in the event payload; Notifications never queries other services for audience.** Notifications then applies the US-8.15 matrix (role exclusions), the admin switch, and the user's preference. Recipient **roles** — needed for the exclusions — come from a small role cache Notifications maintains by consuming Identity's `UserProvisioned` / `UserRoleChanged` / `UserDeactivated` events (the same event-sourced-cache pattern Member Profiles uses), so no synchronous dependency on Identity on the send path.

B) Notifications resolves audiences itself by REST fan-out to the six publishers (couples the send path to every other service's availability).

C) Publisher sends the subject only (e.g. the event id) and Notifications calls back for the list (a narrower version of B, same coupling).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 9
**Preference storage and defaults (US-8.7).**

A) **Sparse per-user records, default = subscribed.** A user with no stored row receives every opt-out-eligible category; saving writes only the deviations. The category list served to the client is derived from the registry filtered by what that user's role can actually receive (a UGL/CL never sees contribution/certification/tier categories, per the mockups and footnote 3); Administrators get `403` on the preferences routes rather than an empty list. Mandatory categories are returned as read-only rows so the UI can render the "Always on" block without hardcoding it.

B) Materialise a full preference row for every user at first login (uniform reads, but needs a backfill for existing users and a migration whenever a category is added).

C) Store preferences in Settings alongside the user's time zone (one save for the whole Preferences screen, but splits notification policy across two services).

D) Other (please describe after [Answer]: tag below)

[Answer]: Users will not any notification preference. Admin will setup the notifcation preference at the system wide. 


## Question 10
**Leader review-queue counts in the bell (the Option 2A note on US-8.6).** Leaders may see pending counts for Contributions, Certification Verifications, Forum Moderation and Join Requests. The story is explicit that these are computed on the fly, are not stored notifications, generate no email, and are not matrix rows.

A) **Notifications does not serve them.** The SPA reads the same counts it already uses for the nav pending badges, straight from the owning services. Keeps Notifications free of a four-way fan-out to three still-mock services, and honours "not notifications".

B) Notifications aggregates the four counts and returns them alongside the panel (one call for the client, but adds a synchronous fan-out to three mock services on the bell's hot path).

C) Drop the leader queue counts from the bell entirely.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 11
**SES reality in a dev account.** US-8.4 requires an SES-verified sender, and a fresh account is in the SES sandbox (only verified addresses can be recipients).

A) **Send for real through SES, with a configurable sender from Settings, and degrade honestly.** If the sender is unverified or the recipient is rejected by the sandbox, the send is recorded as suppressed with a reason and a CloudWatch metric, no retry, and nothing surfaced to the user (exactly what US-8.4 prescribes for a failed send). A documented `EMAIL_DELIVERY_MODE` switch (`ses` \| `log`) lets a dev environment run the whole pipeline without a verified domain.

B) SES only, no log mode — the pipeline is untestable end-to-end until a domain is verified and production access is granted.

C) Log-only for now; wire SES in a later change request.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

**Recommended answers** (what I would choose if you want to move fast): Q1 **A**, Q2 **A**, Q3 **A**, Q4 **A**, Q5 **A**, Q6 **A**, Q7 **A**, Q8 **A**, Q9 **A**, Q10 **A**, Q11 **A**. Reply "all A" to accept, or answer individually.
