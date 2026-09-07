# Unit 7 — Contributions & Scoring: Frontend Components

**Stage**: CONSTRUCTION → Functional Design. Companion to `business-logic-model.md`. Scope per **DL21** (full rebuild of Unit 7's own screens + placement reconciliations). Stack: React + Vite + TypeScript (existing SPA). Analytics dashboards (US-7.1/7.2) are **Unit 8's** frontend — out of scope; Unit 7 provides their data endpoints.

## Placement reconciliations (DL21)
- **Member contributions live on Home + a Leaderboard page** — the standalone member Contributions page is dropped; `ContributionsPage` becomes **leader-only** (approvals/summary/adjust).
- **Profile tier-badge shelf** is added to Unit 3's `ProfilePage` (own) and `MemberDetailPage` (view-other), fed by our endpoint — no Unit 3 backend reopen.

## Component tree

```
DashboardPage (Home — US-8.1 page owned by Frontend; Unit 7 injects this section)
└─ MyContributionsSection                     (US-6.10/6.11)
   ├─ QuarterSelector      props: quarters[], value; state: selectedQuarter (trailing 8 + empty state)
   ├─ GroupSwitcher        props: myGroups[]; state: selectedGroup
   ├─ GroupStandingCards   lifetime · quarter pts · tier(derived) · days-remaining|final
   ├─ PillarBarChart       props: pillar1..4 for group+quarter
   ├─ PointsHistoryTable   GET /contributions/history (filter quarter|all-time), paginated
   └─ MySubmissionsTable   GET /contributions/submissions
      └─ SubmitContributionModal  (group ctx + active evidence-required activities + evidence + activityDate)
      └─ withdraw / resubmit actions

LeaderboardPage                                (US-6.16; linked from Home, not sidebar)
├─ GroupSwitcher · QuarterFilter · PillarFilter
├─ Podium (top 3)   and   LeaderboardTable (rank, name+avatar, points, tier badge)

ScoringFrameworkPage (CL only)                 (US-6.1/6.2)
├─ Tab ActivityTypes  — by pillar; Add/EditActivityModal (evidence forced yes on create, read-only on edit); Delete confirm (evidence-only)
├─ Tab EventPoints    — 8 types × attendance/delivery; edit
└─ Tab TierThresholds — Gold/Silver/Bronze/Rising min points + recognition; save

ContributionsPage (leader — CL & UGL)          (US-6.8/6.9/6.13/6.14/6.15)
├─ Tab PendingApprovals  — queue (oldest-first; UGL=led group, CL=all), evidence link, Approve / Reject(reason)
├─ Tab Summary (CL)      — stat cards, PillarBarChart, by-group table, quarter|month|custom range, Export CSV, "as of {computedAt}" disclaimer on lagged tiles
└─ Tab AdjustPoints      — member search · group · QuarterPicker · ±delta · reason · Apply;  LedgerEntryBrowser → Reverse (pre-fills quarter+−points+reverses); RecentAdjustments list

ProfilePage / MemberDetailPage (Unit 3 pages — Unit 7 adds)
└─ TierBadgeShelf         GET /contributions/tiers-earned?memberId= (historical per-group/quarter badges)

Sidebar (CL/UGL)
└─ Contributions nav item + PendingCountBadge   GET /contributions/approvals?countOnly
```

## Key component contracts

| Component | Props / state | Endpoint(s) |
|---|---|---|
| MyContributionsSection | selectedGroup, selectedQuarter | `GET /contributions/me?groupId&quarter`, `GET /contributions/history` |
| SubmitContributionModal | myGroups, activities(active+evidence-required) | `POST /contributions/submissions` |
| MySubmissionsTable | rows; withdraw(id) | `GET /contributions/submissions`, `DELETE /contributions/submissions/{id}` |
| LeaderboardPage | group, quarter, pillar | `GET /contributions/leaderboard?groupId&quarter&pillar&limit` |
| ScoringFrameworkPage | activities, eventPoints, tiers | `GET/POST/PUT/DELETE /contributions/framework*`, `PUT /event-points`, `PUT /tiers` |
| PendingApprovals | queue rows; decide(id,decision,reason) | `GET /contributions/approvals`, `POST /contributions/submissions/{id}/decision` |
| Summary | scope, from/to/quarter | `GET /contributions/summary/{scope}`, `GET /contributions/export` |
| AdjustPoints | member, group, quarter, delta, reason | `POST /contributions/adjustments`, `GET /contributions/ledger?memberId&groupId` |
| TierBadgeShelf | memberId | `GET /contributions/tiers-earned?memberId` |
| PendingCountBadge | count | `GET /contributions/approvals?countOnly` |

## Interaction & validation rules
- **Quarter selector** offers current + previous 7; a quarter with no data for the selected group shows the graceful **empty state** (BR shows "no data for this quarter").
- **Submit modal** lists only **active, evidence-required** activities; requires a group the member belongs to + evidence + activity date; if the member has **no group**, show a "join a group first" prompt instead of the form.
- **Reject** requires a reason; **Withdraw** shown only for Pending; **Resubmit** for Rejected/Withdrawn.
- **Framework**: Add forces "Evidence required = yes" (read-only control); Edit shows evidence-required read-only; Delete offered only for evidence-required activities, with a confirm dialog warning of pending-submission auto-reject.
- **AdjustPoints**: quarter picker required; Reverse pre-fills and locks amount/quarter from the chosen entry; below-zero permitted (no client block).
- **Lagged tiles** (tier distribution, community top-contributors, active-contributors — rendered by Unit 8, but this is the shared rule) carry the "updated daily · as of {computedAt}" caption; Unit 7's own real-time views carry no such caption.
- **501 handling**: standard `ComingSoon` for any not-yet-implemented endpoint (consistent with the SPA convention).

## Role visibility
- **Member**: Home My Contributions section, Leaderboard, own profile badges. No framework, no approvals, no adjust.
- **UGL**: Contributions (PendingApprovals for led group) + adjust from member detail; Leaderboard for led group.
- **CL**: Scoring Framework, Contributions (Approvals/Summary/Adjust across all groups), any group's leaderboard.
- **Administrator**: no Unit 7 UI (BR-A2).
