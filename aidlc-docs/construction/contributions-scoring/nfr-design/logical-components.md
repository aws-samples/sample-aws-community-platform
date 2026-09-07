# Logical Components — Unit 7: Contributions & Scoring

**Stage**: CONSTRUCTION → NFR Design. Companion to `nfr-design-patterns.md`. Technology-agnostic component map (concrete AWS resources finalized in Infrastructure Design).

## Compute (Q1=A — four purpose-separated functions, one code package)
| Component | Responsibility | Trigger | Notes |
|---|---|---|---|
| **ApiHandler** | framework CRUD, submissions, approvals, adjustments, me/history/leaderboard/summary/export/tiers-earned reads | API Gateway | fail-closed authZ; interactive latency budget |
| **AsyncWorker** | fan-out **expander** (reads Events, enqueues per-earner jobs) + per-earner **award writer** + Forum/Cert/Identity **event consumers** + evidence **auto-reject** | SQS (multiple source queues) | **bounded/reserved concurrency**; idempotent |
| **RollupMaintainer** | apply each ledger entry to L1/L1-life/L2/L3 (atomic guarded ADD) | DynamoDB Stream (ledger) | ordered per shard; exactly-once (Q2=A′) |
| **NightlySweep** | compute tier distributions + active-contributor count + community top-contributors; stamp `computedAt` | EventBridge Scheduler | batch; high memory / long timeout |

## Domain services (in the code package, shared by the functions)
- **FrameworkService** — activities / event-points / tier-thresholds CRUD (BR-F1..6); seeded defaults.
- **AwardService** — guard pipeline (idempotency → Member-role from stamped message → framework value → earnedDate/quarter → attribution/split → append ledger).
- **SplitCalculator** — community-wide equal split on current membership + earliest-join remainder (BR-S1/S2).
- **SubmissionService** — submit/withdraw/resubmit; approve/reject → ledger; queue-as-query; nav count.
- **AdjustmentService** — quarter-selectable free delta + reverse-entry (single-use `reverses` guard) (DL20).
- **LedgerRepository** — append-only writes + member-scoped reads (history, reverse browser).
- **RollupRepository** — atomic guarded increments; L1/L2/L3/lifetime reads; leaderboard GSI query (top-N, B3 filter).
- **TierResolver** — derive tier from a total vs current thresholds (never stored).
- **SweepService** — aggregate + histogram + top-N computation.
- **EventConsumers** — `EventCompleted`, `ForumPostCreated`/`ReplyAccepted` (dormant), `CertificationApproved`, `MembershipChanged`/`UserDeactivated`/`UserReactivated`/`GroupHardDeleted`.
- **EventPublisher** — `PointsAwarded`, `PointsAdjusted` (post-commit; no `TierAchieved` — DL19).
- **EventsClient** — timeout + per-container short-circuit read for the fan-out earner list (Q3).
- **authz / validation** — per-service convention modules (fail-closed map; input validation).

## Data (single-table design + small idempotency table)
| Store | Contents | Protection |
|---|---|---|
| **Main table** | ledger entries (append-only) · rollups L1/L1-life/L2/L3 · `rollup-applied#<ledgerId>` guards · framework (activities/event-points/tiers) · submissions · reply-award-state · membership projection · sweep aggregates | **PITR** + on-demand backups; `Retain` |
| **Main table GSI** | partition `group+quarter`, sort `points` | leaderboard / top-N |
| **Idempotency table** | run-once markers (award worker, auto-reject) | small, TTL-cleaned; not in the durable backup path |

## Messaging
| Queue / bus | Purpose | DLQ |
|---|---|---|
| EventCompleted queue | EventBridge rule → SQS → expander | ✅ |
| Per-earner award queue | expander → SQS → award writer | ✅ |
| Event-consumer queues (Forum/Cert/Identity) | EventBridge rules → SQS → consumers | ✅ |
| DynamoDB Stream (ledger) | → RollupMaintainer | (Stream on-failure → DLQ) |
| EventBridge Scheduler | → NightlySweep | — |

## Integration points
- **In (consume)**: Events `EventCompleted`; Forums `ForumPostCreated`/`ReplyAccepted` (+un-accept, dormant); Certifications `CertificationApproved` (+`submittedAt`); Identity `MembershipChanged`/`UserDeactivated`/`UserReactivated`/`GroupHardDeleted`.
- **Sync read (out)**: Events `GET /events/{eventId}` + earner lists (fan-out, timeout + short-circuit).
- **Out (publish)**: `PointsAwarded`, `PointsAdjusted`.
- **Consumed by**: Member Profiles (`GET /contributions/me`), Analytics Unit 8 (summary/leaderboard/sweep), Notifications, Frontend SPA.

## Per-function IAM (least privilege — SECURITY-06)
| Function | Grants |
|---|---|
| ApiHandler | main table RW; EventBridge PutEvents (adjust → PointsAdjusted); read Identity projection |
| AsyncWorker | main + idempotency table RW; SQS consume/DLQ; read-only `execute-api:Invoke` on Events routes; EventBridge PutEvents (PointsAwarded) |
| RollupMaintainer | Stream read; main table RW (rollups + guards) |
| NightlySweep | main table read + sweep-aggregate write |

No wildcards; read/write split; scoped to this unit's resources.
