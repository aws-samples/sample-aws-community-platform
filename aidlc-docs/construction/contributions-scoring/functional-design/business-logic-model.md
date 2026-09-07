# Unit 7 — Contributions & Scoring: Business Logic Model

**Stage**: CONSTRUCTION → Functional Design. Technology-agnostic business logic. Companions: `business-rules.md` (BR-x), `domain-entities.md` (E-x + contract deltas), `frontend-components.md`. Brainstorming record + decision log (DL1–DL21): `../../plans/contributions-scoring-award-logic.md`.

## Confirmed design decisions (DL1–DL21, from brainstorming)
| # | Decision |
|---|---|
| DL1 | **Append-only ledger** is the system of record; one uniform entry shape for all sources; balances/tiers/leaderboards derived, nothing pre-summed. |
| DL2 | **Evidence `earnedDate` = submission date** (activity date is display-only). |
| DL3 | A user's click never waits on point-awarding (source commits + returns; awarding is async). |
| DL4 | Events emits **one `EventCompleted`**; a Unit 7 Lambda reads the earner list and self-enqueues per-earner jobs onto Unit 7's SQS; batched, concurrent workers write the ledger (reopens deployed Events). |
| DL5 | Per-earner **idempotency key** on every auto award. |
| DL6 | Queue path for message-driven autos; **direct synchronous write** for evidence approvals + adjustments. |
| DL7 | Forum channel always belongs to exactly one group → forum points single-group, no split. |
| DL8 | **Source unit stamps the earner's role** on every award message (no Unit 7 role projection for eligibility). |
| DL9 | Deactivated/left-group status is a **read-time** concern (B3), not the award-time role check. |
| DL10 | **Dormant-consumer** pattern for not-yet-built producers (Forums): author schemas + build consumer now; 0 messages until live. |
| DL11 | Event date/type/scope resolved from the Events read the fan-out Lambda already does. |
| DL12 | Community-wide split uses **current membership at award time** (deliberate deviation from event-date snapshot). |
| DL13 | `CertificationApproved` gains `submittedAt` → cert points attribute to the submission quarter. |
| DL14 | **Nightly sweep** for derived/cross-group aggregates (tier distributions, active-contributor count, community top-contributors) + `computedAt` UI disclaimer. |
| DL15 | **L1/L2/L3 rollups** (member/group/community × quarter, + lifetime) maintained by DynamoDB Streams; **leaderboard GSI** on L1; tiers never stored. |
| DL16 | **Seeded default framework** (install-time `-data` seed, all Active): tiers 75/50/25/0, event points delivery=2×attendance, activity values. |
| DL17 | Forum: **post=1** on create; **accepted reply=2** via `ReplyAccepted`, earnedDate = reply's post date, **un-accept reverses** (state toggle). Deviates from US-6.4 reply-created. |
| DL18 | Community top-contributors = rank by each member's **highest single-group** quarter total (one row/member); export stays one row per member-per-group; nightly. |
| DL19 | **Tier-achievement notifications removed** (no `TierAchieved` event, no tracker); tier display kept. |
| DL20 | **Manual adjustment = quarter-selectable append-only entry**; "reverse entry" is a pre-filled convenience with a `reverses` link + single-use guard. |
| DL21 | **Frontend**: Unit 7 builds its own screens + profile tier-badge shelf; UGL/CL analytics dashboards are Unit 8's (we provide data). |

---

## 1. The point ledger (system of record — DL1)

Every award, evidence approval, adjustment, and reversal is **one immutable append-only entry**. There is no stored balance. All balances, per-quarter totals, tiers, leaderboards, and summaries are **derived** from the ledger (rollups in §5 are a maintained cache, not a second source of truth).

Entry (see `domain-entities.md` E1): `memberId · groupId · activity · pillar · points(±) · source(auto|evidence|adjustment) · earnedDate · quarter · sourceRef · idempotencyKey · [adjustorId · reason · reverses]`.

- **`quarter`** is derived from **`earnedDate`** and is what tiering counts against (BR-Q1). Quarters are calendar quarters in **UTC** (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec).
- Entries are **never updated or deleted** — corrections are new entries (§4).

## 2. Point sources & the six automatic activities

Three `source` types resolve to the concrete origins:

| source | Origin | Trigger | Value from | Attribution |
|---|---|---|---|---|
| auto | Event **attendance** | `EventCompleted` → per-attendee | Event Points table, attendance col, by eventType | group / community split |
| auto | Event **delivery** | `EventCompleted` → per-presenter | Event Points table, delivery col | group / community split |
| auto | Event **organizing** | `EventCompleted` → per-organizer | "Organize an event" activity value | group / community split |
| auto | **Forum post** | `ForumPostCreated` | "Create a forum post" (1) | forum's group |
| auto | **Accepted reply** | `ReplyAccepted` / reversal on un-accept | "Accepted reply" (2) | forum's group |
| auto | **Certification** | `CertificationApproved` | per-cert value on the event | group chosen at claim |
| evidence | Member submission | leader approval | framework activity value | chosen group |
| adjustment | Leader correction | UI action | leader-entered ± | chosen/entry's group |

The **fixed system-defined auto set** (attendance, delivery, organize, forum post, accepted reply, cert approval) is code-defined and cannot be created/deleted/mode-switched via the UI (BR-F3).

## 3. Automatic award pipeline (DL3–DL13)

### 3.1 Staged fan-out (event completion — attendance/delivery/organize)
```
Stage 1 (sync) Events commits attendance + marks complete → returns 200 (user never waits — DL3)
Stage 2 (async) Events emits ONE EventCompleted (eventId) — DL4
Stage 3          Unit 7 fan-out Lambda reads the event from Events (date, type, scope + attendee/
                 presenter/organizer lists — DL11) → enqueues one job per earner onto Unit 7 SQS
Stage 4          worker Lambdas drain SQS in batches, concurrently → run the guard pipeline → append ledger
```
Forum post/reply and certification are **single-earner** (one message → one job → one entry, no fan-out). Evidence approval and adjustment are **direct synchronous writes** (DL6).

### 3.2 Guard pipeline (per earner — Stage 4)
```
1. Idempotency  — idempotencyKey already in ledger? → drop (BR-P6, DL5)
2. Eligibility  — earner role (stamped on the message — DL8) == Member? → else drop (BR-P3)
3. Value        — resolve from framework (event-points table / activity value) or per-cert value on the event (BR-P4)
4. earnedDate   — event date (DL11) / post date / reply's post date (DL17) / cert submittedAt (DL13) → quarter (BR-Q1)
5. Attribution  — one group, or community-wide split (§3.3)
6. Write        — append ledger entry/entries (source=auto)
```

### 3.3 Community-wide equal split (attendance/delivery/organize, no group — DL12)
```
groups = member's CURRENT groups at award time (DL12)
if none → award nothing (BR-A4)
base = points ÷ N ; remainder handed out 1 pt at a time, earliest-group-join first (BR-S2 determinism)
→ one ledger entry per group (each its portion; parts sum exactly to the original)
```
Group-scoped events (groupId present) → one entry to that group. Forum/cert are always single-group (no split — DL7).

### 3.4 Forum accepted-reply toggle (DL17)
```
ReplyAccepted        → if reply not currently awarded → +2 entry (earnedDate = reply POST date), mark awarded
Reply un-accepted    → if currently awarded → −2 reversal (same quarter), mark not-awarded
re-accept            → +2 again
```
Per-reply award **state** guards against double-award/double-reverse on redelivery (BR-P7). Post creation → +1 entry (earnedDate = post date), single award.

## 4. Manual adjustment (DL20 — Option Y)

One mechanism: append an `adjustment` entry to `(member, group, quarter, delta±, reason)`; the leader **selects the quarter** (current + previous 7).
- **Path 1 — free delta**: leader enters group + quarter + ±delta + reason → entry in the chosen quarter (any quarter, incl. closed).
- **Path 2 — reverse entry** (convenience): leader picks a ledger entry → UI pre-fills `quarter = entry.quarter`, `delta = −entry.points`, `reverses = entry.ledgerId` → confirm + reason. Same entry shape + the link.
- **Single-use guard** (BR-J2): an entry can be reversed at most once (enforced via the `reverses` reference). Any source reversible; reversal touches the **ledger only** — never flips the source submission/event.
- **Scope**: CL any member/group; UGL only their led group (BR-A5). **Below zero allowed**, no floor (BR-J3). Reason required; entry logs adjustorId + createdAt. Member notified in-portal via `PointsAdjusted` (BR-N1).

## 5. Derived read model — rollups & tiers (DL15, DL14)

`ledger entry → DynamoDB Stream → maintainer Lambda → idempotent additive ADD on rollups` (BR-R1). Maintainer is idempotent per ledgerId so Stream redelivery can't drift the cache (BR-R2).

| Level | Key | Holds | Feeds | Freshness |
|---|---|---|---|---|
| L1 | member+group+quarter | total + 4 pillar subtotals | my points/tier | real-time |
| L1-life | member+group | all-time total | lifetime (this group) | real-time |
| L2 | group+quarter | total + 4 pillars | group summary/dashboard totals | real-time |
| L3 | community+quarter | total + 4 pillars | community summary/dashboard totals | real-time |
| GSI on L1 | partition group+quarter, sort points | — | leaderboard / **group** top-N | real-time |
| Sweep output | group+quarter & community+quarter | per-tier counts + active-contributor count + community top-N + `computedAt` | tier-distribution donuts + community top-contributors | **nightly** |

- **Tiers are never stored** (DL1/US-6.12) — derived on read: member's group+quarter total vs current thresholds (BR-T1). A threshold change or a late/cross-quarter award simply changes the number the tier derives from; no reopen/refreeze step (BR-T2).
- **Nightly sweep (DL14)** recomputes derived buckets that a counter can't hold (tiers depend on mutable thresholds + the B3 active/in-group filter): (1) community tier distribution, (2) group tier distribution, (3) active-contributor count, (4) community top-contributors (DL18). All stamped `computedAt`; UI shows an "updated daily · as of {computedAt}" disclaimer on those four only (BR-R4). Everything else is real-time.
- **B3 exclusion (BR-B3)**: deactivated / left-group members are excluded from live leaderboards, tier distributions, and top-contributor lists, but their points **remain** in group/community aggregate totals. Applied at read (GSI top-N + buffer, filter) and in the nightly sweep.

## 6. Community top-contributors semantics (DL18)
Ranked by each member's **highest single-group** quarter total (one row per member; points never combined across groups). Computed in the nightly sweep. **Group** top-contributors is real-time (L1 GSI). The **CSV export** keeps one row per member-per-group (US-6.14 granularity).

## 7. Evidence submission lifecycle (US-6.6/6.7/6.8/6.9)

```
submit (Member, ≥1 group) → Pending ──approve(CL/led-UGL)→ Approved  → append ledger entry (source=evidence, earnedDate = SUBMISSION date — DL2)
                                   ├─reject(reason)──────→ Rejected  (no entry; resubmit allowed)
                                   ├─withdraw(owner)─────→ Withdrawn (Pending-only; no entry)
                                   └─member leaves chosen group before approval → auto-reject "No longer a member of the selected group"
```
- **Submit (BR-E1)**: role Member only; must belong to ≥1 group; activity must be an **active, evidence-required** framework activity; group context = one of the member's groups; provides description, evidence (URL/file), activity date. Status Pending; no points.
- **Approve (BR-E4)**: CL any group; UGL only their led group; on approve → one ledger entry, `points` = framework value, `groupId` = chosen group, `earnedDate` = submission date (DL2), `activityDate` retained for display. Member notified (contribution decision).
- **Queue (US-6.9, BR-E6)** = a **query** over Pending submissions by group (UGL) / all (CL), oldest-first. **Leader-change reassignment falls out for free** — routing is purely groupId-based, so a new UGL's query returns the group's pending items and a removed UGL loses them; nothing stored per-leader. Pending count for the nav badge = same query, countOnly.
- **Auto-reject consumer (BR-E7)**: consumes Identity `MemberLeftGroup`/`MemberRemoved` → rejects the member's Pending submissions credited to that group with the system reason; idempotent on envelope id.

## 8. Framework configuration (US-6.1/6.2, DL16)

- **Single community-wide framework**: activity types (name, description, pillar, points, evidence-required, active), the **Event Points table** (8 event types × attendance/delivery), and **Tier Thresholds** (name, min points, recognition label).
- **Create activity (BR-F1)**: CL only; **evidence-required is forced to yes** (the UI cannot create auto activities — those are the fixed system set, BR-F3). **Edit (BR-F2)**: evidence-required is read-only; point/threshold changes take effect for new contributions only (historical not recalculated). **Delete (BR-F4)**: only evidence-required activities; auto activities cannot be deleted. **Deactivate**: auto-rejects that activity's pending submissions + notifies affected members ("Activity type deactivated"); historical points preserved.
- **Seed (DL16)**: install-time via the `-data` stack; all activities Active; defaults per `../../plans/contributions-scoring-award-logic.md` Seed Defaults. Auto-award works day one.
- **Access (BR-A1)**: only Community Leader may view/configure the framework; Admin/Member/UGL cannot view it.

## 9. Member points & tier views (US-6.10/6.11)

- **My points** (`/contributions/me`, keeps the shape Member-Profiles' deployed fan-out reads — `points, quarter, groupId, tier, submissionCount`, extended additively): group selector, quarter selector (trailing 8 quarters + graceful empty state), lifetime (L1-life) + selected-quarter points, tier (derived), days-remaining (current) / final (past), per-pillar breakdown, points history (ledger direct, filter quarter/all-time). Tiers/thresholds are **not** shown to the member as a table; no progress-to-next-tier bar.
- Points/tiers **never combined across groups** (BR-T3).

## 10. Published & consumed events

- **Publishes**: `PointsAwarded`, `PointsAdjusted` (DL19 removed `TierAchieved`). Post-commit best-effort.
- **Consumes**: Events `EventCompleted` (fan-out); Forums `ForumPostCreated` / `ReplyAccepted` (+ un-accept) — dormant until Forums is real (DL10); Certifications `CertificationApproved` (with `submittedAt`); Identity `MembershipChanged` (`MemberJoinedGroup`/`MemberLeftGroup`/`MemberRemoved`) for split membership + evidence auto-reject + B3, `UserDeactivated`/`UserReactivated` for B3, `GroupHardDeleted` for purge.

## 11. Story traceability
| Story | Where |
|---|---|
| US-6.1/6.2 | §8 framework config + access |
| US-6.3 | §2/§3 attendance auto-award |
| US-6.4 | §3.4 forum post + accepted reply (DL17) |
| US-6.5 | §2/§3 certification auto-award (DL13) |
| US-6.6/6.7 | §7 submit / view / withdraw |
| US-6.8/6.9 | §7 approve/reject + queue (reassignment) |
| US-6.10/6.11 | §9 member points & tier |
| US-6.12 | §5 runtime tiers + badges; §5/DL19 no notification |
| US-6.13/6.14 | §5 L2/L3 summaries + §6 top-contributors + export |
| US-6.15 | §4 manual adjustment (DL20) |
| US-6.16 | §5 leaderboard (GSI) |
| US-6.17/6.18 | §2/§3 delivery + organize auto-award |
