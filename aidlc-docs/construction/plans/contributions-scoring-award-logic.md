# Unit 7 — Contributions & Scoring: Point-Award Logic (per activity)

**Stage**: CONSTRUCTION → Functional Design (brainstorming record, feeds `business-logic-model.md`).

## Decisions log (agreed in brainstorming)
| # | Decision |
|---|---|
| DL1 | **Append-only ledger** is the system of record; one uniform entry shape for all sources; balances/tiers/leaderboards are all derived (nothing pre-summed). |
| DL2 | **Evidence `earnedDate` = submission date** (not approval date, not the member-entered activity date). Activity date is display-only. Sets the quarter (late approvals land in the submission quarter). |
| DL3 | **Staged fan-out — a user click never waits on point-awarding.** The source unit commits its own data and returns 200; awarding happens async off the request path. |
| DL4 | **One trigger event per event, fan-out inside Unit 7.** Events emits a single `EventCompleted`; a Unit 7 Lambda reads the earner list and enqueues one job per earner onto Unit 7's own SQS; batched, concurrent worker Lambdas write the ledger entries. (Requires reopening the deployed Events contract — replaces per-attendee publish.) |
| DL5 | **Per-earner idempotency key** on every automatic award (`<id>#<userId>#<kind>`) so redelivery/retry never double-awards. |
| DL6 | **Queue path for message-driven autos** (event/forum/cert); **direct synchronous write** for evidence approvals and manual adjustments (single leader click = one entry, no queue). |
| DL7 | **Forum channel always belongs to exactly one group** (selected at creation). So forum points are always single-group — `groupId` always present on the message, never null, no split. |
| DL8 | **Source unit stamps the earner's role on every award message** (role is available at action time). Forums → `authorRole`; Events → attendee/presenter/organizer role (present/organize already Member-filtered; attendance now stamped too). Unit 7 does not maintain a role projection for award eligibility. |
| DL9 | **Deactivated / left-group status is a separate read-time concern** (B3 leaderboard/summary exclusion), not part of the award-time role check. |
| DL10 | **Dormant-consumer pattern for not-yet-built producers** (Forums): author the event schemas now, build + deploy the consumer/rule/queue/guard now, seed the framework activities; it receives 0 messages until the producer goes live, then lights up with no Unit 7 change. |
| DL11 | **Event date/type/scope resolved from the Events read** the fan-out Lambda already does (DL4). The `EventCompleted` trigger carries only `eventId`; the Lambda reads event date + eventType + groupId + attendee list in one call. No extra cost. |
| DL12 | **Community-wide split uses CURRENT membership at award time** (not an event-date snapshot). Deliberate deviation from the spec's "snapshot at event date" rule — acceptable because awarding usually fires moments after completion. Current group-join dates still drive the deterministic remainder rule (earliest-join-first). Bites only when completion lags the event AND membership changed in that window. |
| DL13 | **`CertificationApproved` gains a `submittedAt` field** (reopens deployed Certifications, additive) so cert points attribute to the **submission quarter** per US-6.12. Consistent with DL8 (source stamps what it knows at action time). |
| DL14 | **Nightly batch sweep** (not real-time) for derived/cross-group aggregates. A scheduled job reads the quarter's L1 rollups, applies current thresholds + the B3 active/in-group filter, and writes small items (per group+quarter and community+quarter) stamped with `computedAt`. **Lagged (up to a day) metrics — exhaustive list:** (1) community tier distribution, (2) group tier distribution, (3) active-contributors count, (4) **community top-contributors** (DL18). Everything else is real-time (incl. **group** top-contributors via the L1 GSI). Threshold edits reflect on the next nightly run. **UI shows a disclaimer on those items only** (freshness + ranking rule — see DL18). |
| DL15 | **Three-level rollup + GSI (all DynamoDB, maintained by the Stream maintainer with additive `ADD`).** L1 = member+group+quarter (+4 pillar subtotals) + a member+group **lifetime** rollup; L2 = group+quarter (total + 4 pillars); L3 = community+quarter (total + 4 pillars). **Leaderboard / top-contributors = a GSI on L1** (partition group+quarter, sort by points) → read top-N only (scales to 13k). Sums are real-time & exact; tier buckets are nightly (DL14). Ledger is truth; all rollups are rebuildable by replay. |
| DL16 | **Seeded default framework** (install-time via the service's `-data` stack, D7; all activities seeded **Active**) — tiers Gold/Silver/Bronze/Rising = 75/50/25/0; event points normalized to **delivery = 2× attendance**; activity values per the Seed Defaults section. Auto-award works day one before any CL edit. |
| DL22 | **Events integration: consume Events' existing per-earner events directly — SUPERSEDES the DL4 read-back.** At integration time Events (deployed) already publishes per-earner `AttendanceRecorded`/`EventDelivered`/`EventOrganized` (delivery/organize pre-filtered to Member role) — so Unit 7 consumes those directly via an EventBridge rule → AwardQueue → AwardWorker, rather than reading the attendee list back after an `EventCompleted` (DL4). This **eliminates the fan-out service-to-service auth gap** entirely (no read-back). Events change is purely additive: stamp **`eventDate`** on the three award events (for quarter attribution). Attendance is Member-filtered by Unit 7 using its identity projection role (known leaders excluded; unknown/absent role treated as Member so members aren't dropped while the projection catches up); delivery/organize need no check (Events already Member-filters). Idempotency on the event's `idempotencyKey`. Certs `submittedAt` shipped (DL13). |
| DL21 | **Frontend scope = full rebuild of Unit 7's own screens** (Units 3/4/6 precedent) + two placement reconciliations. **Unit 7 builds:** (1) member Home **"My Contributions" section** on DashboardPage (group switcher, per-group cards, pillar chart, quarter selector + empty state, points history, my submissions + submit/withdraw/resubmit) — US-6.10/6.11; (2) **Leaderboard page** (per-group top-10, quarter + pillar filters); (3) CL **Scoring Framework** page (Activity Types / Event Points / Tier Thresholds tabs + modals); (4) CL **Contributions** page (Pending Approvals / Community Summary w/ CSV + lagged-metric disclaimer / Adjust Points w/ quarter picker + reverse browser); (5) UGL group-scoped **Contributions** queue + adjust from member detail; (6) **profile tier-badge shelf** on **both** My Profile and view-other-profile (Unit 3's pages, fed by our `GET /contributions/tiers`, added alongside Unit 3's existing current-quarter fan-out — no Unit 3 reopen); (7) CL/UGL **nav pending-count badge**. **Reconciliations:** member contributions move to Home + Leaderboard (drop the standalone member Contributions page; `ContributionsPage` becomes leader-only). **Boundary (Option 1):** UGL Group Dashboard (US-7.2) + CL Community Analytics (US-7.1) are **Unit 8 Analytics' frontend** — Unit 7 provides the data endpoints (group/community summary, leaderboard, nightly sweep histograms, pending count) but does NOT build those dashboard pages; their contribution tiles light up when Analytics wires them. |
| DL20 | **Manual adjustment = quarter-selectable append-only entry, with a "reverse entry" convenience (Option Y).** One mechanism: append an `adjustment` entry to `(member, group, quarter, delta±, reason)`; leader **picks the quarter** (current + previous 7). **Path 1** = manual free delta (any quarter, bonus/correction). **Path 2 "Reverse"** = same entry, UI **pre-fills** quarter + `−(entry points)` + a `reverses: <ledgerId>` link from a chosen ledger entry; **single-use guard** (an entry can be reversed at most once via the `reverses` reference). Any source reversible; reversal touches the **ledger only** (never flips the source submission/event). CL any group · UGL led-group only (checked on the entry's/target's group). Reason required; entry stores adjustorId/reason/createdAt. Below-zero allowed (no floor). Member notified in-portal via `PointsAdjusted` (no email). Contract adds: quarter param on adjust + a "list member ledger entries" read for the reverse browser. |
| DL19 | **Tier-achievement notifications REMOVED** (requirement change — drops the notify half of US-6.12). No "you earned Gold" email/in-portal notice; **no last-notified-tier tracker**, **no `TierAchieved` event** (Unit 7 publishes `PointsAwarded` + `PointsAdjusted` only). Tier **display** is unaffected — still derived at read time on the member view, leaderboard badges, and profile badges. Deviation from the member-dashboard mockup's "You earned Gold …" notification. **Reflected in the Notifications spec**: removed the "Quarterly tier badge awarded" trigger from use case 08 (US-8.2 email triggers, US-8.6 in-portal triggers, US-8.5 templates 22→21, US-8.7 opt-out list, recipient matrix row 19 removed + renumbered) and struck the notification criterion in use case 06 US-6.12. |
| DL18 | **Community top-contributors = rank by each member's HIGHEST single-group quarter total** (Option A) — one row per member, points never combined across groups. Computed in the nightly sweep (DL14, 4th lagged metric). **Group** top-contributors stays real-time (L1 GSI). The **CSV export keeps one row per member-per-group** (Option C, US-6.14 granularity). **UI disclaimer on the community top-contributors card:** "Ranked by each member's best single-group total; points aren't combined across groups. Updated daily · as of {computedAt}." |
| DL17 | **Forum reply scores only when accepted as answer (US-4.15), reversible.** Two forum autos: **Create a forum post = 1** (trigger `ForumPostCreated`, earnedDate = post date) and **Accepted reply = 2** (trigger `ReplyAccepted`, earnedDate = the reply's **post date**, credited to the reply author). Deviates from US-6.4's "reply created" scoring (better anti-farming). **Un-accept reverses** (−2, same quarter) → per-reply accept/un-accept **state toggle** (idempotent on redelivery, no double-award/double-reverse); re-accept re-awards. Forums publishes both the accepted and un-accepted/accepted-changed transitions; the dormant schemas (DL10) are `ForumPostCreated` + `ReplyAccepted` (+ un-accept). |

## Ledger entry (one shape, all sources; append-only, balances/tiers are derived)
`ledgerId · memberId · groupId (scope) · activity · pillar · points (±) · source (auto|evidence|adjustment) · earnedDate · quarter · sourceRef · idempotencyKey`

## Staged fan-out (event-driven autos — user never waits on awarding)
`user click → source unit commits + returns 200 → source emits ONE trigger event → Unit 7 expands to earners → per-earner job onto Unit 7 SQS → parallel workers run guard pipeline → write ledger`

## Guard pipeline (per earner)
`idempotency check → Member-role check → resolve value (framework) → resolve earnedDate → resolve attribution (1 group | community-wide split) → append entry`

## Community-wide split (attend/present/organize with no group)
`groups at event date → base = pts÷N → remainder 1pt at a time, earliest-join first → 1 entry per group · no group that date → award nothing · later join/leave never redistributes`

---

## Master logic table

| Pillar | Activity | Type | Trigger → transport | Fan-out (message → queue → workers → entries) | Eligibility | Point value | earnedDate → quarter | Attribution | Idempotency key |
|---|---|---|---|---|---|---|---|---|---|
| 1 Upskilling | **Attend an event** | auto | attendance saved + event completed → `EventCompleted` (1 msg) | Lambda reads attendee list → **N attendee jobs → SQS** → Lambda polls **batches ≤10**, concurrent → **N ledger entries** | Member only — **role stamped on the message by Events** (DL8) | Event Points table → **attendance** col, per eventType | **event date** | group event → that group · community-wide → split | `<eventId>#<userId>#attendance` |
| 1 Upskilling | **Present at an event** (delivery) | auto | same `EventCompleted` | presenter set (usually 1–few) → **M jobs → same SQS** → Lambda batch ≤10 → **M ledger entries** | Member only, internal only | Event Points table → **delivery** col, per eventType | **event date** | same as attend | `<eventId>#<userId>#presenter` |
| 1 Upskilling | **Organize an event** *(was missing)* | auto | same `EventCompleted` | organizer set (1–few) → **K jobs → same SQS** → Lambda batch ≤10 → **K ledger entries** | Member only, internal only | single **"Organize an event"** value (not per type) | **event date** | same as attend | `<eventId>#<userId>#organizer` |
| 1 Upskilling | **Certification** | auto | claim approved → `CertificationApproved` (1 msg, carries `submittedAt` — DL13) | single earner → **1 job → SQS** → Lambda batch → **1 ledger entry** | Member (by construction) | **per-cert** value on event (frozen at approval) | quarter of **`submittedAt`** (DL13) | single group chosen at claim | `<certId>#<memberId>#approved` |
| 1 Upskilling | **Mentor a member** | evidence | leader clicks Approve (sync) | none → **direct write of 1 ledger entry** on approval (no queue) | Member submits | framework value (seed 15) | **submission date** | chosen group | — |
| 2 Peer Learning | **Create a forum post** | auto | posts → `ForumPostCreated` (carries `groupId`, `authorRole`, `postDate`) | single earner → **1 job → SQS** → 1 entry | Member only — role stamped by Forums (DL8) | **1** (seed) | **post date** | forum's group (always 1, uncapped) — DL7 | `<postId>#post` |
| 2 Peer Learning | **Accepted reply** *(reply accepted as answer, US-4.15 — DL17)* | auto | reply accepted → `ReplyAccepted`; un-accept → reversal (carries `groupId`, `authorRole`, reply `postDate`) | single earner → **+2 entry** on accept · **−2 reversal** on un-accept (state toggle) | reply author, Member only (DL8) | **2** (seed) | reply's **post date** (DL17) | forum's group (always 1) — DL7 | `<replyId>#accepted` (toggle) |
| 2 Peer Learning | **Lessons-learned writeup** | evidence | leader clicks Approve (sync) | none → **direct write of 1 ledger entry** on approval (no queue) | Member submits | framework value (seed 10) | **submission date** | chosen group | — |
| 3 Assets | **Open-source contribution** | evidence | leader clicks Approve (sync) | none → **direct write of 1 ledger entry** on approval (no queue) | Member submits | framework value (seed 15) | **submission date** | chosen group | — |
| 3 Assets | **Reusable asset / demo** | evidence | leader clicks Approve (sync) | none → **direct write of 1 ledger entry** on approval (no queue) | Member submits | framework value (seed 12) | **submission date** | chosen group | — |
| 4 Thought Leadership | **Blog / article** | evidence | leader clicks Approve (sync) | none → **direct write of 1 ledger entry** on approval (no queue) | Member submits | framework value (seed 15) | **submission date** | chosen group | — |
| 4 Thought Leadership | **Public speaking** | evidence | leader clicks Approve (sync) | none → **direct write of 1 ledger entry** on approval (no queue) | Member submits | framework value (seed 20) | **submission date** | chosen group | — |
| — | **Manual adjustment** *(was missing)* | adjustment | CL/UGL UI action (sync, no event) | none → **direct write of 1 ledger entry** (no queue) | CL any · UGL own group | leader-entered ± delta | **leader-selected quarter** (DL20) | chosen group (Path 1) / entry's group (Path 2 reverse) | — |

> One `EventCompleted` can yield attend + present + organize entries — for different people or the same person — never collapsed.

## Evidence flow (all `evidence` rows)
`submit (activity + group + evidence + activity-date) → status Pending (no points)` → `approve → 1 ledger entry (points=framework, group=chosen, earnedDate=submission date, activityDate=display only)` · `reject → reason, no entry` · `withdraw (owner, Pending only) → no entry` · `member leaves chosen group before approval → auto-reject "No longer a member of the selected group"`

## Manual adjustment (DL20 — Option Y; append-only, never physical delete)
One mechanism → append an `adjustment` entry to `(member, group, quarter, delta±, reason)`; leader **picks the quarter** (current + prev 7).
- **Path 1 — free delta**: `member · group · quarter · ±delta · reason` → entry in the chosen quarter (bonus/correction, any quarter incl. closed).
- **Path 2 — reverse entry** (convenience): pick a ledger entry → UI pre-fills `quarter = entry's quarter`, `delta = −entry.points`, `reverses = <ledgerId>` → confirm + reason. Same entry shape as Path 1, plus the link.
- **Single-use guard**: `reverses` reference makes an entry reversible at most once. Any source (auto/evidence/adjustment) reversible; touches **ledger only** (never flips source submission/event).
- Scope: CL any group · UGL led-group only. Below-zero allowed (no floor). Reason required; stores adjustorId/createdAt. Member notified in-portal (`PointsAdjusted`, no email).
- Tier re-derives on read for the affected quarter; nightly sweep catches the distribution.

## Storage & read model (DL15 + DL14)

`ledger entry (truth) → DynamoDB Stream → maintainer Lambda → additive ADD on rollups`

| Level | Key | Holds | Feeds | Freshness |
|---|---|---|---|---|
| Ledger | append-only entries | the truth (per DL1) | history, "this week", replay/rebuild | real-time |
| L1 | member+group+quarter | total + 4 pillar subtotals | my points/tier, leaderboard | real-time |
| L1-life | member+group | all-time total | "Lifetime (this group)" | real-time |
| L2 | group+quarter | total + 4 pillars | group dashboard/summary totals | real-time |
| L3 | community+quarter | total + 4 pillars | community dashboard/summary totals | real-time |
| GSI on L1 | partition group+quarter, sort points | — | leaderboard / **group** top-N (B3-filtered at read) | real-time |
| Sweep output | group+quarter & community+quarter | per-tier counts + active-contributor count + **community top-N** + `computedAt` | tier-distribution donuts + community top-contributors card | **nightly (DL14)** |

- Tiers are **never stored** — derived on read from L1 totals vs current thresholds.
- Late/cross-quarter awards & reversals land in the correct quarter's rollup → tier recomputes on next read.
- **Nightly-lagged metrics (only these four):** community tier distribution · group tier distribution · active-contributors count · **community top-contributors** (DL18). Group top-contributors is real-time (GSI). UI disclaimer "updated daily · as of {computedAt}" on those items only.

## Seed defaults (DL16)

**Tiers (per quarter):** Gold 75 (Community Star) · Silver 50 (Active Contributor) · Bronze 25 (Engaged Member) · Rising 0 (Rising Participant)

**Event points (delivery = 2× attendance):**
Social 3/6 · Meetup 5/10 · Webinar 8/16 · AMA 8/16 · Presentation 10/20 · Workshop 10/20 · Conference 15/30 · Hackathon 25/50

**Activity types:**
| Pillar | Activity | Points | Evidence | Auto? |
|---|---|---|---|---|
| 1 Upskilling | Certification approval | per-cert | no | ✅ |
| 1 | Organize an event | 20 | no | ✅ |
| 1 | Mentor a member | 15 | yes | — |
| 2 Peer Learning | Create a forum post | **1** | no | ✅ |
| 2 | Accepted reply (DL17) | **2** | no | ✅ |
| 2 | Lessons-learned writeup | 10 | yes | — |
| 3 Assets | Open-source contribution | 15 | yes | — |
| 3 | Reusable asset / demo | 12 | yes | — |
| 4 Thought Leadership | Blog / article | 15 | yes | — |
| 4 | Public speaking | 20 | yes | — |

All seeded **Active**; seeded at install via the service's `-data` stack (D7). Cert per-cert default guidance (on cert definitions, Unit 6): Associate ≈ 15, Professional/Specialty ≈ 25.

## Open cross-unit decisions this logic still depends on
| Ref | Decision | Affects | Status |
|---|---|---|---|
| Q1 | Author `ForumPostCreated`/`ForumReplyCreated` schemas now (dormant consumer) | forum post/reply | **Resolved → DL10** (author now, build dormant consumer) |
| Q2 | How Unit 7 gets **event date** | attend/present/organize | **Resolved → DL11** (from the Events read the Lambda already does) |
| Q3 | Membership for the community-wide **split** | community-wide autos | **Resolved → DL12** (current membership at award time) |
| Q4 | Attendance **role check** | attend | **Resolved → DL8** (Events stamps role on the message) |
| Q5 | Cert **submission-quarter** date source | certification | **Resolved → DL13** (add `submittedAt` to the cert event) |
| — | **Fan-out shift** reopens the deployed Events contract (one `EventCompleted`, Unit 7 fans out) | attend/present/organize | **Resolved → DL4** (accepted; reopen Events) |

*(Decisions log at top of file. All award-logic decisions resolved.)*
