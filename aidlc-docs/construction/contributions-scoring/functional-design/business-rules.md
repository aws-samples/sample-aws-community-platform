# Unit 7 — Contributions & Scoring: Business Rules

**Stage**: CONSTRUCTION → Functional Design. Companion to `business-logic-model.md` + `domain-entities.md`. Rules are grouped; each is a hard constraint.

## Authorization (A)
- **BR-A1** — Only the **Community Leader** may view/configure the scoring framework (activities, event points, tier thresholds). Administrator, Member, and UGL cannot view it.
- **BR-A2** — Only **Members** submit evidence-based contributions and view their own points/tier/leaderboard. Administrators never participate in scoring (no earning, no framework, no approvals, no adjustments, no leaderboard).
- **BR-A3** — Approve/reject: **CL** for any group; **UGL** only for the group they lead. Fail-closed if the caller's led group can't be resolved.
- **BR-A4** — **Earning is Member-only** (BR-P3). Attendance/delivery/organize/forum/cert points are awarded only to earners holding the Member role at the moment of the action; leaders acting operationally earn nothing.
- **BR-A5** — Manual adjustment: **CL** any member/group; **UGL** only members in their led group. Enforced on the target entry's group (reverse) or the chosen group (free delta).

## Point awarding — automatic (P)
- **BR-P1** — Attendance points only for **confirmed, applied** attendance (never RSVP; a Teams fetch alone awards nothing).
- **BR-P2** — Delivery/organize points only for **internal members** designated as presenter/organizer (external SMEs never earn).
- **BR-P3** — Eligibility check uses the **role stamped on the award message** by the source unit (DL8); award only if role == Member.
- **BR-P4** — Point value is resolved from **Unit 7's framework** (event-points table by eventType for attendance/delivery; the single "Organize an event" value for organize; activity value for forum) — except **certification**, whose per-cert value is carried on the event (frozen at approval). Any `points` on an award message is ignored in favor of the framework (certs excepted).
- **BR-P5** — Attribution: group-scoped event → that group; community-wide event → equal split across the earner's current groups (BR-S1/S2); forum → the forum's group (always one — DL7); certification → the group chosen at claim submission.
- **BR-P6** — Every auto award carries an **identity-derived idempotency key**; an award whose key already exists in the ledger is dropped (no double-award on redelivery).
- **BR-P7** — Forum accepted-reply is a **per-reply award state toggle** (DL17): accept awards +2 once; un-accept reverses −2 once; redelivery of either transition is a no-op against the current state.

## Scoring / attribution (S)
- **BR-S1** — Community-wide split uses the earner's **current** group memberships at award time (DL12); if the earner belongs to no group, **no points are awarded**.
- **BR-S2** — Split is equal; the integer remainder is allocated **one point at a time, earliest-group-join first**, so the per-group parts sum exactly to the original value.
- **BR-S3** — Already-awarded points are **never redistributed** when the member later joins/leaves a group.

## Quarter & tier (Q, T)
- **BR-Q1** — An entry counts toward the quarter derived from its **`earnedDate`**: event date (attendance/delivery/organize), post date (forum post), the reply's **post date** (accepted reply — DL17), **submission date** (evidence — DL2, and certifications via `submittedAt` — DL13), chosen quarter (manual adjustment — DL20). Quarters are calendar quarters in **UTC**.
- **BR-T1** — Tiers are **never stored** — a member's tier for a group+quarter is derived on read from that quarter's total vs the **current** thresholds.
- **BR-T2** — A late/cross-quarter award or reversal lands in its `earnedDate` quarter; the tier for that (possibly closed) quarter simply recomputes on the next read. No reopen/refreeze.
- **BR-T3** — Points and tiers are **never combined across groups**; each group is independent.

## Evidence lifecycle (E)
- **BR-E1** — Submit requires role Member, membership in ≥1 group, an **active + evidence-required** activity, a group context the member belongs to, and evidence (URL or file) + description + activity date.
- **BR-E2** — A submission is worth **no points** until Approved.
- **BR-E3** — Withdraw is **owner-only** and **Pending-only**; sets Withdrawn; no points, no rejection reason shown.
- **BR-E4** — Approve appends one ledger entry (points = framework value, group = chosen, `earnedDate` = **submission date**, `activityDate` retained for display); reject requires a reason; both notify the member.
- **BR-E5** — A Rejected/Withdrawn submission may be **resubmitted** as a new submission.
- **BR-E6** — The pending queue is a **query by group** (UGL led group / CL all), oldest-first; leader-change reassignment is implicit (no per-leader storage). Nav badge = same query, count only.
- **BR-E7** — On Identity `MemberLeftGroup`/`MemberRemoved`, the member's **Pending** submissions credited to that group are auto-rejected with the system reason "No longer a member of the selected group"; consumer idempotent on envelope id.

## Framework (F)
- **BR-F1** — Create activity: CL only; **evidence-required forced to yes**; auto ("no") activities cannot be created via the UI.
- **BR-F2** — Edit activity: evidence-required is **read-only**; point/threshold changes apply to **new** contributions only (historical never recalculated).
- **BR-F3** — The auto-tracked set (attendance, delivery, organize, forum post, accepted reply, cert approval) is **system-defined**: not creatable, not deletable, not mode-switchable via the UI.
- **BR-F4** — Delete activity: **only evidence-required** activities; requires confirmation; auto-rejects that activity's pending submissions + notifies affected members; historical points preserved.
- **BR-F5** — Deactivate activity: no new points; auto-reject its pending submissions + notify ("Activity type deactivated"); historical points preserved.
- **BR-F6** — The framework is **single and community-wide**; the same values/thresholds apply to all groups. Seeded at install, all Active (DL16).

## Manual adjustment (J)
- **BR-J1** — Adjustments are **new append-only ledger entries** (free delta or reversal); no entry is ever mutated or physically deleted.
- **BR-J2** — Reverse-entry carries a `reverses` link and is **single-use** — a given entry can be reversed at most once. Reversal touches the ledger only (never the source submission/event).
- **BR-J3** — A negative adjustment/reversal **may drive a group/quarter total below zero**; applied as-is, no floor; tier re-derives from the resulting total.
- **BR-J4** — Free-delta quarter is **leader-selected** (current + previous 7); reverse-entry quarter = the target entry's quarter.

## Read model & aggregation (R, B)
- **BR-R1** — Rollups (L1/L1-life/L2/L3) are maintained from the ledger via DynamoDB Streams with **additive increments**; the ledger is the sole source of truth and rollups are rebuildable by replay.
- **BR-R2** — The rollup maintainer is **idempotent per ledgerId** (Stream is at-least-once).
- **BR-R3** — Leaderboard/group top-contributors read the **L1 GSI** (group+quarter, sorted by points), top-N, B3-filtered at read.
- **BR-R4** — The **nightly sweep** computes only: community tier distribution, group tier distribution, active-contributor count, community top-contributors — each stamped `computedAt`; the UI shows an "updated daily · as of {computedAt}" disclaimer on **only** these four. All other metrics are real-time.
- **BR-B3** — Deactivated members and members who have left a group are **excluded** from that group's live leaderboard, tier distribution, and top-contributor lists, but their points **remain** in the group's/community's aggregate totals; historical tier badges are preserved.

## Notifications (N)
- **BR-N1** — Member is notified **in-portal** of a manual adjustment (`PointsAdjusted`); contribution approve/reject notifies the member. **No tier-achievement notification** is emitted (DL19).
- **BR-N2** — Unit 7 publishes `PointsAwarded` and `PointsAdjusted` post-commit (best-effort); it does **not** publish `TierAchieved`.
