# Unit 7 — Contributions & Scoring: Functional Design Plan

**Stage**: CONSTRUCTION → Per-Unit Loop → Functional Design (Part 1 — Planning)
**Unit**: Unit 7 — Contributions & Scoring (`/contributions`, service `services/contributions-scoring/`)
**Stories (18)**: US-6.1–6.18 (framework config, auto-award attendance/delivery/organize/forum/cert, evidence submit/view/withdraw, approve/reject, pending queue, points & tier, tier standings, runtime tier badge, group/community summary, adjust points, leaderboard)
**Status**: ANALYSIS COMPLETE — clarifying/brainstorming questions below. AWAITING ANSWERS.

---

## Context loaded (analysis complete)

- **Use case** `requirements/usecases/06-member-contribution-tracking.md` + stories US-6.1–6.18. This is the richest scoring spec in the portal: single community-wide framework, **per-group per-quarter** points/tiers, an **append-only ledger (B1)** as system of record, **runtime-computed tiers (never snapshotted)**, and an **equal-distribution rule** for community-wide events.
- **Frozen contract** `contracts/services/contributions-scoring/openapi.yaml` v1.0.0 — **scaffold-thin** (13 ops, flat schemas). It predates the detail in the use case and is missing most of the real surface (see gaps G7–G14 below).
- **Mockups**: `leader/scoring-framework.html` (Activity Types / Event Points / Tier Thresholds tabs + add/edit/delete activity modals), `leader/contributions.html` (Pending Approvals / Community Summary / Adjust Points tabs), `ugl/contributions.html` (group-scoped approval queue), `member/leaderboard.html` (per-group top-10, quarter + pillar filters). **No member "My Points & Tier" mockup exists** (G8).
- **Existing mock UI** `frontend/src/features/ContributionsPage.tsx` — tabs My Points / Leaderboard / My Submissions / Framework / Summary / Approvals, all bound to the thin contract with hardcoded groups/activities.
- **Upstream event schemas** (what Unit 7 must consume for auto-award):
  - `events/published-events/event-awards.v1.json` — `AttendanceRecorded`, `EventDelivered`, `EventOrganized`. Each carries `idempotencyKey, eventId, userId, groupId (nullable), eventType, points (nullable)`, attendance also `source`. **No date field.** Delivery/Organize are pre-filtered to Member-role designees; attendance is **not** role-filtered.
  - `certifications/published-events/certification-lifecycle.v1.json` — `CertificationApproved` carries `certId, memberId, groupId (credited), points, dateEarned?, expiresAt?, decidedAt`. **No submission date.**
  - `identity-access/published-events/group-events.v1.json` — `MembershipChanged` (`MemberJoinedGroup|MemberLeftGroup|MemberRemoved`, payload `{memberId, groupId, at}`), plus `GroupHardDeleted`. `user-events.v1.json` carries role/deactivation events.
  - **Forums publishes NO events yet** — `contracts/services/forums/` has only `openapi.yaml`, no `published-events/`. Forums (Unit 5) is still mock. So `ForumPostCreated`/`ForumReplyCreated` (needed by US-6.4) **do not exist as a contract** (G1).
- **Live contract debt** — Member Profiles (Unit 3, deployed) already calls `GET /contributions/me?memberId={id}` (and `&from=&to=`) and reads `{points, quarter, groupId, tier, submissionCount}` from the response (`services/member-profiles/src/profile_service.py`, `activity_service.py`). Whatever we design for `/contributions/me` must keep serving that shape or we break a deployed service (G7/G9).
- **Deployment reality** — Units 2, 3, 4 (Events), 11, 6 (Certifications) are **COMPLETE and deployed to dev**. Reopening the Events or Certifications published-event contracts touches a deployed producer (raises cost of G2/G5).
- **Reference implementations**: certifications (append-only-ish lifecycle, sparse-GSI sweep, EventPublisher, idempotent consumer, queue-as-query with free leader reassignment); member-profiles (parallel FanOutClient, idempotent event_consumer); identity-access (declarative OP_AUTHZ map).

---

## Gap Analysis (spec ↔ contract ↔ mockups ↔ upstream events)

### A. Cross-unit event / auto-award gaps
- **G1 — Forum events undefined.** US-6.4 needs `ForumPostCreated`/`ForumReplyCreated` (author, groupId, date, role). Forums is mock and publishes nothing. → Q1.
- **G2 — No earned-date on Events award events.** US-6.12 attributes a point entry to a quarter by the **event date**; `event-awards.v1.json` carries no date. → Q2.
- **G3 — Community-wide equal-distribution needs point-in-time membership.** Splitting a community-wide event's points "across the member's groups **at the event date**" requires membership-as-of-a-date, not current membership. → Q3.
- **G4 — Attendance role eligibility.** US-6.3 restricts attendance points to Member-role attendees, but `AttendanceRecorded` is emitted for every attendee (not role-filtered like delivery/organize). Who enforces "Members only"? → Q4.
- **G5 — Certification submission-quarter.** US-6.12 says cert points count toward the **submission** quarter; `CertificationApproved` carries `decidedAt`/`dateEarned` but not the submission date. → Q5.
- **G6 — Point-value resolution.** Award events may carry `points: null`; framework is the source of truth (event points per type, organize single value, per-cert value on the cert event). Confirm "always resolve from framework, ignore event `points`". → Q6.

### B. Contract-shape gaps (thin scaffold vs rich spec)
- **G7 — `/contributions/me` (My Points & Tier) is vastly richer than `Rollup`.** US-6.10/6.11 need: quarter selector (trailing 8 quarters), per-group selection, **lifetime** totals (period-independent), selected-quarter points + tier, **per-pillar** breakdown (quarter + all-time), points **history** (activity/group/points/date/pillar, filterable, showing per-group split portions), days-remaining-in-quarter. Plus it must keep serving Member-Profiles' `{points,quarter,groupId,tier,submissionCount}` shape. → Q7 (screen), G-contract work.
- **G8 — No member "My Points & Tier" mockup, no member nav entry.** Member sidebar has no Contributions/Points link; leaderboard is reached "via a link on Home" (US-6.16). Where does the member view points/tier, and what does that screen look like? → Q7.
- **G9 — Profile tier badges (US-6.12).** Historical per-group/per-quarter badges ("Gold · Serverless Guild · Q2 2026") live on the profile (Unit 3, deployed). Today the fan-out captures only one `{groupId, tier}`. How do historical badges reach the profile? → Q8.
- **G10 — Leaderboard shape.** US-6.16 needs rank, member name+avatar, points, tier, per-group switch, **pillar filter**. Contract returns `{memberId, groupId, quarter, points, tier}` — no name/avatar/rank/pillar. Name/avatar resolution strategy? → Q9.
- **G11 — Summary time filters.** US-6.13/6.14 offer **quarter / month / custom range**; rollups are per-quarter. Month/custom-range needs ledger aggregation. Also summary needs member count, top contributors, per-pillar and per-group breakdowns not in the contract. → Q10.
- **G12 — Two different exports.** US-6.14 (this unit) = **aggregated** CSV, one row per member per group with name/email/tier/total + 4 pillar columns. US-7.9 (Analytics, Unit 8) = **granular per-entry** export. Contract's `export` returns raw ledger rows. Which does Unit 7 own, and how are name/email resolved? → Q10/Q11.
- **G13 — Adjust points: delete-a-specific-entry.** US-6.15 lets a leader **delete a specific point entry** OR apply a free +/- delta. Ledger is append-only, so "delete" = compensating reversal entry, and the UI needs an entry picker. Contract has only `{memberId, groupId, delta, reason}`. → Q11.
- **G14 — Framework model.** Contract `Framework{id,activity,pillar,points,auto}` omits: description, **evidence_required** (fixed yes on create, read-only on edit), **active/inactive**, the **Event Points table** (8 event types × attendance/delivery — a separate structure, not activity rows), and **Tier Thresholds** (name/min-points/recognition). Create must force evidence-required=yes and reject auto creation; delete only for evidence-required; deactivation triggers auto-reject+notify. → covered by generation + Q6/Q12.

### C. Business-logic / lifecycle gaps (mostly modeling, flagged for confirmation)
- **G15 — Seeded default framework** (Gold/Silver/Bronze/Rising 75/50/25/0 + activities + event points) must exist day-one for auto-award. Seed mechanism? (platform `seed.yaml` vs this service's data seed) → Q12.
- **G16 — Fixed system auto-tracked set** (event attendance, event delivery, event organizing, forum post, forum reply, cert approval) is code-defined, not UI-editable.
- **G17 — Deterministic remainder distribution** (equal split; remainder one point at a time by earliest group-join order) needs per-member group-join ordering from `MembershipChanged.at`.
- **G18 — Pending-submission auto-reject** when the member leaves/removed from the selected group before approval (US-6.6), reason "No longer a member of the selected group" — mirrors Certifications' consumer.
- **G19 — Leader-change reassignment** (US-6.9, the authoritative rule referenced by US-1.26/US-5.7): queue = query by groupId, reassignment falls out for free.
- **G20 — Left-group / deactivated exclusion (B3)**: excluded from live leaderboard/tier-distribution/top-contributors, but their points **remain in group aggregate totals**. Needs member status + current membership.
- **G21 — Forum attribution** to the forum's group + Member-only author (tied to G1/G4).
- **G22 — Idempotency**: dedupe every award on `idempotencyKey` (append-only ledger uniqueness).
- **G23 — Ledger-vs-rollup**: ledger is truth; tiers computed at runtime; a maintained rollup is a **derived perf cache** (leaderboards over 13k-member groups can't recompute from raw ledger per request). → Q13 (confirm).
- **G25 — Negative adjustments** may drive totals below zero, applied as-is (no floor).
- **G28 — Tier-achievement notification (US-6.12)** fires when a runtime recompute crosses a higher threshold — but nothing stores the "previous" tier to compare against. Detecting the crossing needs a **last-notified-tier tracker** (not an authoritative tier). → Q14.

### D. Delivery
- **G29 — Frontend scope** — full ContributionsPage rebuild + member points entry + profile badges + leaderboard + leader pending-count nav badge (Units 3/4/6 precedent). → Q15.
- **Published events** — unit-of-work says Unit 7 emits `PointsAwarded`, `PointsAdjusted`, `TierAchieved` (author schemas now for Notifications-later). → Q14.

---

## Clarifying / Brainstorming Questions

## Question 1 — Forum auto-award (US-6.4), given Forums publishes no events yet
Forums (Unit 5) is still a mock and defines no `published-events`. US-6.4 needs `ForumPostCreated`/`ForumReplyCreated` to auto-award forum points.

A) **Author the two forum event schemas now** in `contracts/services/forums/published-events/` (payload incl. `authorId, groupId, postId/replyId, createdAt, authorRole`) as the contract Forums must honor when it goes real, and build Unit 7's consumer against them now (Certifications-precedent: consumer authored ahead of producer). Forum points simply don't flow until Forums is real, then light up with no change to Unit 7. (Recommended)

B) **Defer forum auto-award entirely** — build the consumer stub but no schema; revisit when Unit 5 is built (recorded deviation, US-6.4 not satisfied until then).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2 — Event-date for quarter attribution (G2)
Award events (`AttendanceRecorded`/`EventDelivered`/`EventOrganized`) carry **no date**, but US-6.12 attributes each entry to the quarter of the **event date**. Options to obtain it:

A) **Unit 7 resolves the event date by a read-time REST call to Events** (`GET /events/{eventId}`) when it processes an award, using `eventId` already in the event. No change to the deployed Events contract; adds a sync read per award-batch (cacheable per event). (Recommended — avoids reopening a deployed producer.)

B) **Reopen the Events published-event contract** to add `eventDate` (and re-deploy Events). Cleanest payload, but touches a completed/deployed unit.

C) **Use the envelope timestamp / receipt time** as the earned date (accept that late-applied attendance lands in the wrong quarter — recorded deviation from US-6.12).

D) Other (please describe after [Answer]: tag below)

[Answer]: 

## Question 3 — Community-wide equal-distribution: membership snapshot (G3/G17)
For a community-wide event (`groupId=null`), points are split equally across the member's groups **as of the event date**, remainder allocated by earliest-join order.

A) **Maintain a local per-member membership timeline** from `MembershipChanged` events (each carries `at`), so Unit 7 can reconstruct "groups the member belonged to on date D" and the join-order for remainder allocation. True to the spec's point-in-time rule. (Recommended)

B) **Use current membership via read-time REST to Identity** at award time (simpler, no local timeline) — accurate only when membership hasn't changed since the event; recorded deviation from the "at the event date" rule.

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 4 — Attendance role eligibility (G4)
US-6.3: attendance points go **only to Member-role attendees**. Delivery/Organize events are already pre-filtered to Members by Events, but `AttendanceRecorded` is emitted for every attendee.

A) **Unit 7 resolves the attendee's role** (maintain a local role projection from Identity's `UserProvisioned`/`UserRoleChanged`/deactivation events — Unit 7 needs member status anyway for B3 exclusion, Q-G20) and awards only when role == Member at award time. (Recommended — one local identity projection serves role-eligibility, B3 exclusion, and name/avatar if we denormalize.)

B) **Ask Events to pre-filter attendance to Members** before publishing (reopen/redeploy Events, consistent with how it already filters delivery/organize).

C) **REST to Identity per attendee** at award time to check role (no local projection; heavier per-batch).

D) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 5 — Certification submission-quarter (G5)
US-6.12: certification points count toward the **submission** quarter. `CertificationApproved` carries `decidedAt`, `dateEarned?`, `expiresAt?` — not the submission date.

A) **Attribute cert points to the quarter of `dateEarned` when present, else `decidedAt`** (approval date) — no reopen of the deployed Certifications contract; slight deviation from "submission quarter". (Recommended if reopening is unwanted.)

B) **Reopen Certifications' event** to add `submittedAt` and attribute to that (faithful to US-6.12; touches a deployed unit).

C) **Unit 7 RESTs to Certifications** for the claim's submission date at award time.

D) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 6 — Point-value source of truth (G6)
Award events may carry `points: null`; the framework holds the authoritative values (event points per type, organize single value; certs carry their own per-cert value).

A) **Always resolve the point value from Unit 7's framework** at award time (event-type → attendance/delivery table; organize activity value), and for certifications **trust the per-cert `points` on the event** (it was frozen at approval on the cert side). Ignore any `points` on event-award messages. (Recommended)

B) **Trust `points` on the event when present**, fall back to framework only when null.

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 7 — Member "My Points & Tier" screen (G7/G8) — no mockup exists
US-6.10/6.11 describe a rich per-group, per-quarter, per-pillar view with points history — but there is no member mockup and no member sidebar entry (leaderboard is reached from Home).

A) **Dedicated "My Contributions" page**, reached from a **Home dashboard card/link** (consistent with US-6.16's leaderboard entry), with: group selector, quarter selector (trailing 8 quarters + graceful empty state), lifetime + selected-quarter points, tier + days-remaining, per-pillar breakdown, and a filterable points history table. Design it from the spec (no mockup to match). (Recommended)

B) **Surface it on the existing Profile page** (Unit 3) as an expanded section rather than a standalone page.

C) **Add a member sidebar "Contributions" nav item** to a dedicated page.

D) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 8 — Profile tier badges delivery (G9)
Historical per-group/per-quarter tier badges show on the member profile (Unit 3, deployed). Today the fan-out reads a single `{groupId, tier}` from `/contributions/me`.

A) **Add a dedicated read** `GET /contributions/tiers?memberId=X` (all historical per-group/per-quarter tiers) and have the **frontend Profile page call it directly** to render the badge shelf — no change to Member-Profiles' deployed fan-out (which keeps showing the current-quarter summary). (Recommended — additive, no reopen of Unit 3.)

B) **Extend Member-Profiles' fan-out** to call the new tiers endpoint and embed badges in the `Member` response (reopens/redeploys Unit 3).

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 9 — Leaderboard & summary member name/avatar (G10)
Mockups show member **name + avatar/initials**; Unit 7's ledger/rollups key on `memberId` only.

A) **Denormalize `memberName` + `avatar` onto the rollup/ledger** as Unit 7 consumes identity/profile events (Unit 7 already needs a local identity projection per Q4-A), so leaderboard/summary/export are self-contained single reads (critical for 13k-member groups and CSV export). (Recommended)

B) **Return `memberId` only; the frontend resolves names/avatars** via batch calls to Member Profiles/Identity (extra round-trips, awkward for CSV export which needs name+email server-side).

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 10 — Summary time filters & export ownership (G11/G12)
US-6.13/6.14 summaries offer **quarter / month / custom range**; the per-quarter rollup cache only answers "quarter". US-6.14 export is an **aggregated per-member-per-group** CSV (name/email/tier/total + 4 pillars); US-7.9 (Analytics) is the separate **granular per-entry** export.

A) **Rollup cache serves the quarter view fast; month/custom-range summaries and the US-6.14 aggregated export are computed by aggregating the ledger over the requested date range** (add `from`/`to` params). Unit 7 owns the US-6.14 aggregated export; Analytics (Unit 8) owns US-7.9's granular export by reading Unit 7's ledger. (Recommended)

B) **Quarter-only** summaries in v1; month/custom-range deferred (recorded deviation from US-6.13/6.14).

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 11 — Manual adjustment model (G13, append-only)
US-6.15: a leader can **delete a specific point entry** or apply a free **+/- delta** with a reason; the ledger is append-only.

A) **Both, as new ledger entries**: a free-delta adjustment writes a `source=adjustment` entry (earned-date = now → current quarter); "delete a specific entry" writes a **compensating reversal entry** (negative of the target, referencing its id) rather than a physical delete — history preserved, tiers recompute. UI gains an entry picker (list a member's entries for a group) plus the free-delta form. Contract adds a "list member ledger entries" read and a "reverse entry" op alongside the existing delta op. (Recommended — honors B1 append-only.)

B) **Free +/- delta only** in v1 (matches the current mockup's Adjust tab); "delete a specific entry" deferred (recorded deviation from US-6.15).

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 12 — Seeded default framework (G15)
The portal must ship with the default framework (activities, event points, Gold/Silver/Bronze/Rising 75/50/25/0) so auto-award works before any Community Leader edits it.

A) **Seed via this service's `-data` stack / install-time seeding custom resource** (the platform seeding mechanism, D7), writing the default framework rows into Unit 7's own table. (Recommended — keeps the framework service-owned.)

B) **Seed lazily in code** — if no framework exists, the service materializes defaults on first read.

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 13 — Ledger-as-truth + derived rollup cache (G23)
US-6.12 mandates **runtime-computed, never-snapshotted** tiers; the use case also names a **maintained rollup** as a derived perf cache. Leaderboards/summaries over 13k-member groups can't recompute from the raw ledger per request.

A) **Confirm the model**: append-only ledger = system of record; per-(member,group,quarter) and per-pillar **rollups maintained via DynamoDB Streams** as a derived cache; tiers derived at read time from rollup totals against thresholds (never stored); a late cross-quarter approval updates the old quarter's rollup and its tier recomputes on next read. (Recommended — matches the spec.)

B) **Pure runtime** (no rollup cache) — compute everything from the ledger on demand (simpler, but won't scale to 13k-member leaderboards; likely fails NFR later).

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 14 — Published events + tier-achievement detection (G28)
`unit-of-work.md` says Unit 7 publishes `PointsAwarded`, `PointsAdjusted`, `TierAchieved`. Tier badges are runtime-derived, so firing "you reached Gold" needs to detect a **threshold crossing** with nothing stored to compare against.

A) **Publish all three schemas now** (for Notifications-later, Certifications-precedent), and keep a **`last-notified-tier` tracker record** per (member, group, quarter) — not an authoritative tier — updated whenever a recompute detects a higher tier than last notified, which fires `TierAchieved`. Also publish decision/adjustment notifications (US-6.8/6.15). (Recommended)

B) **Publish `PointsAwarded`/`PointsAdjusted` only**; no proactive tier-achievement notification (recorded deviation from US-6.12's "notified of each tier achievement").

C) Other (please describe after [Answer]: tag below)

[Answer]:

## Question 15 — Frontend scope for this unit (G29)
Units 3/4/6 precedent: the unit's code generation rebuilds its SPA screens to mockup fidelity.

A) **Full frontend rebuild in this unit** — leader Scoring Framework (Activity Types + Event Points + Tier Thresholds tabs, add/edit/delete modals with the evidence-required rules), leader Contributions (Pending Approvals with reject-reason, Community Summary with pillar charts + CSV export, Adjust Points with entry picker), UGL group-scoped queue, member My Contributions page (Q7) + real submit modal (member's groups + active evidence-required activities), per-group Leaderboard (quarter + pillar filters, name/avatar), profile tier-badge shelf, leader nav pending-count badge. (Recommended)

B) **Backend + contract only** this round; frontend as a follow-up change request.

C) Other (please describe after [Answer]: tag below)

[Answer]:

---

## Part 1 — Planning checklist
- [x] Read unit definition (unit-of-work.md Unit 7) + dependency matrix + story map (US-6.1–6.18)
- [x] Read use case 06 end-to-end; frozen contract; all 4 mockups; existing mock ContributionsPage
- [x] Read upstream event schemas (events award, certification lifecycle, identity group/user events); confirmed Forums has none
- [x] Confirmed live contract debt (member-profiles fan-out → `/contributions/me`)
- [x] Confirmed deployment state (Events/Certifications deployed → reopen cost)
- [x] Author gap analysis (G1–G29) + clarifying/brainstorming questions (15)
- [ ] Collect answers; resolve any ambiguities/contradictions
- [ ] Plan approved → generate functional-design artifacts

## Part 2 — Generation checklist (executes after answers + approval)
- [x] Brainstorming resolved the substantive questions → decision log DL1–DL21 in `contributions-scoring-award-logic.md`
- [x] `aidlc-docs/construction/contributions-scoring/functional-design/business-logic-model.md` — ledger/rollup model, auto-award pipeline (staged fan-out), equal-distribution algorithm, runtime tier computation, submission lifecycle, adjustment model, queue-as-query, event publications
- [x] `.../business-rules.md` — numbered BR set (A/P/S/Q/T/E/F/J/R/B/N)
- [x] `.../domain-entities.md` — LedgerEntry, FrameworkActivity, EventPoints, TierThreshold, Submission, Rollup, SweepAggregate, ReplyAwardState, MembershipProjection, Idempotency; full contract deltas
- [x] `.../frontend-components.md` — component tree, props/state, flows, validation, endpoint map (DL21 scope)
- [x] Map all 18 stories to model elements (business-logic-model.md §11)
- [x] Update aidlc-state.md + audit.md; present completion gate
