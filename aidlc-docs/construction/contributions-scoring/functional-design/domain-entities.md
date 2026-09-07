# Unit 7 — Contributions & Scoring: Domain Entities

**Stage**: CONSTRUCTION → Functional Design. Companion to `business-logic-model.md` + `business-rules.md`. Technology-agnostic entities + contract deltas vs the frozen `contracts/services/contributions-scoring/openapi.yaml` (scaffold-thin).

## E1 — LedgerEntry (append-only, system of record — DL1)
| Field | Type | Notes |
|---|---|---|
| ledgerId | string | unique; for reversals derived as `rev-<targetLedgerId>` (single-use guard, BR-J2) |
| memberId | string | earner |
| groupId | string | attributed group ("scope") |
| activity | string | activity name (or system activity id) |
| pillar | int (1–4) | — |
| points | int (±) | negative for adjustments/reversals |
| source | enum | `auto` \| `evidence` \| `adjustment` |
| earnedDate | date | drives the quarter (BR-Q1) |
| quarter | string | e.g. `2026-Q2`, derived from earnedDate (adjustments: leader-selected) |
| sourceRef | string | eventId / postId / replyId / claimId / submissionId |
| idempotencyKey | string | auto awards only (BR-P6) |
| activityDate | date? | evidence: member-entered date, display-only (DL2) |
| adjustorId | string? | adjustments |
| reason | string? | adjustments/reversals; rejection handled on Submission |
| reverses | string? | adjustments of type reverse → target ledgerId (BR-J2) |
| createdAt | timestamp | write time (audit) |

Immutable — never updated/deleted (BR-J1).

## E2 — FrameworkActivity (US-6.1)
`id · name · description · pillar(1–4) · points(int≥0) · evidenceRequired(bool) · auto(bool) · active(bool) · systemDefined(bool)`
- `auto = !evidenceRequired`. UI-created activities are always `evidenceRequired=true` (BR-F1). `systemDefined=true` for the fixed auto set (BR-F3) — certification approval, organize an event, create a forum post, accepted reply (attendance/delivery live in E3).

## E3 — EventPoints (US-6.1)
`eventType (enum: Meetup|Workshop|Hackathon|Webinar|AMA|Conference|Presentation|Social) · attendancePoints(int) · deliveryPoints(int)`. Seeded delivery = 2× attendance (DL16).

## E4 — TierThreshold (US-6.1)
`tier (Gold|Silver|Bronze|Rising) · minPoints(int) · recognitionLabel(string)`. Seeded 75/50/25/0 (DL16). Used at read time to derive tiers (BR-T1); never snapshotted.

## E5 — Submission (evidence workflow — US-6.6/6.7/6.8)
`id · memberId · groupId · activity · pillar · description · evidenceUrl? · evidenceFileKey? · activityDate · submittedAt · status(Pending|Approved|Rejected|Withdrawn) · decidedBy? · decidedAt? · rejectionReason? · systemRejected(bool)`
- `submittedAt` sets the eventual ledger `earnedDate` on approval (DL2). On approve → an E1 entry (source=evidence).

## E6 — Rollup (derived cache — DL15; not a source of truth)
- **L1**: `memberId + groupId + quarter → total, pillar1..4`
- **L1-life**: `memberId + groupId → totalLifetime`
- **L2**: `groupId + quarter → total, pillar1..4`
- **L3**: `communityId + quarter → total, pillar1..4`
- Maintained by the Stream maintainer (BR-R1); rebuildable by replay. **L1 GSI**: partition `groupId+quarter`, sort `total` (leaderboard/top-N — BR-R3).

## E7 — SweepAggregate (nightly — DL14)
`scope(group|community) · scopeId · quarter · tierCounts{Gold,Silver,Bronze,Rising} · activeContributorCount · topContributors[] · computedAt`. Community `topContributors` ranked by each member's highest single-group total (DL18). The only lagged data (BR-R4).

## E8 — ReplyAwardState (forum accepted-reply toggle — DL17)
`replyId · awarded(bool) · groupId · authorId · replyPostDate`. Guards the accept/un-accept toggle so redelivery can't double-award/double-reverse (BR-P7).

## E9 — MembershipProjection (for community-wide split — DL12 + B3)
`memberId · groupId · joinedAt · active(bool)`. Built from Identity `MembershipChanged` + `UserDeactivated`/`UserReactivated`. Supplies current groups + join order for the split (BR-S1/S2) and the B3 read-time exclusion (BR-B3). (Not a membership source of truth — a local cache.)

## E10 — IdempotencyRecord
`key · consumedAt`. Run-once store for event consumers (award idempotency BR-P6, Stream maintainer BR-R2, auto-reject BR-E7) — same pattern as sibling services.

---

## Contract deltas (vs frozen openapi.yaml v1.0.0)

The frozen contract is scaffold-thin; changes are additive except where already consumed. Target **v2.0.0** (bumped by the entity-shape expansions).

| Op / path | Change |
|---|---|
| `GET /contributions/framework` | Return full `FrameworkActivity` (description, evidenceRequired, active, auto, systemDefined) + separate `eventPoints[]` + `tiers[]`. |
| `POST /contributions/framework` | Force evidenceRequired=true; reject auto creation (BR-F1). Add description, pillar, active. |
| `PUT /contributions/framework/{id}` | evidenceRequired read-only (BR-F2); allow active toggle (deactivate flow). |
| `PUT /contributions/event-points/{eventType}` | **new** — edit attendance/delivery per type. |
| `PUT /contributions/tiers` | **new** — edit tier thresholds. |
| `GET /contributions/me` | **Keep the deployed shape** Member-Profiles reads (`points, quarter, groupId, tier, submissionCount`); extend additively: accept `memberId`, `groupId`, `quarter` params; add lifetime, pillar breakdown, days-remaining, and quarter list. |
| `GET /contributions/history` | **new** — member's ledger entries (activity/group/pillar/points/date), filter quarter/all-time (US-6.10). |
| `GET /contributions/tiers-earned?memberId=` | **new** — historical per-group/per-quarter tier badges for the profile shelf (DL21/Q8). |
| `GET /contributions/leaderboard` | Add rank + memberName/avatar (denormalized), pillar filter; already has groupId/quarter/limit. |
| `GET /contributions/summary/{scope}` | Add pillar breakdown, member/active-contributor count, top-contributors, `from`/`to` (month/custom range), `computedAt` on lagged fields. |
| `GET /contributions/export` | US-6.14 aggregated CSV: one row per member per group (name/email/tier/total + 4 pillar cols); honors from/to. |
| `POST /contributions/adjustments` | Add `quarter` (leader-selected, DL20) + optional `reverses` (target ledgerId). |
| `GET /contributions/ledger?memberId=&groupId=` | **new** — list a member's entries for the reverse-entry browser (DL20). |
| `POST /contributions/submissions` | Validate active+evidence-required activity + group membership; add activityDate. |
| Events schemas | **`ForumPostCreated`, `ReplyAccepted` (+ un-accept)** authored under `contracts/services/forums/published-events/` (dormant, DL10); `EventCompleted` consumed (DL4); `CertificationApproved` gains `submittedAt` (DL13). |
| Published | `PointsAwarded`, `PointsAdjusted` schemas under this service's `published-events/`. **No** `TierAchieved` (DL19). |

Denormalized `memberName`/`avatar` on rollups/ledger (DL9-adjacent) so leaderboard/summary/export are self-contained.
