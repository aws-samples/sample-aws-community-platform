# NFR Design Patterns — Unit 7: Contributions & Scoring

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Contributions & Scoring
How the NFR requirements (NFR-CS-*) are realized as concrete patterns. Companion: `logical-components.md`. Plan/answers: `../../plans/contributions-scoring-nfr-design-plan.md` (Q1=A, Q2=A′, Q3=A, Q4=A-scoped).

## Compute topology (Q1=A) — the defining structural choice
Four **purpose-separated functions sharing one code package**, each with its own concurrency/memory/timeout, so the async and batch tiers can never starve the interactive API (the DL3 "click never waits" goal enforced at the infra layer):

| Function | Trigger | Profile |
|---|---|---|
| **API handler** | API Gateway | interactive, low latency; standard on-demand scaling |
| **Async worker** | SQS (EventCompleted queue + per-earner queue + event-consumer queues) | **bounded/reserved concurrency**; fan-out expander + per-earner award + Forum/Cert/Identity consumers |
| **Rollup maintainer** | DynamoDB Stream (ledger) | ordered per shard, continuous; keeps rollups in sync |
| **Nightly sweep** | EventBridge Scheduler | heavy batch, high memory + long timeout, once daily |

Rationale: a 1000-attendee award burst or a multi-minute sweep runs in its own function/concurrency pool — it cannot consume the interactive API's latency budget, and a poison message is isolated to the worker's DLQ.

## Award correctness patterns (NFR-CS-REL-1)
- **Staged fan-out, SQS-buffered (DL4)**: `EventCompleted` → async worker (expander) reads Events, enqueues one per-earner job → per-earner SQS → worker awards. Two queues (event-level, earner-level), each with a **DLQ**.
- **At-least-once + idempotent exactly-once effect**: every auto award carries an identity-derived idempotency key (`<sourceId>#<userId>#<kind>`, BR-P6); the worker check-then-writes a run-once marker (small TTL idempotency table) before appending the ledger entry. Redelivery/partial-replay never double-awards (a re-run of a half-finished expander is safe because each earner job dedups independently).
- **Poison isolation**: max-receive → DLQ (alarmed), queue keeps draining.
- **Forum accept/un-accept (BR-P7)**: per-reply `ReplyAwardState` toggle — accept awards +2 once, un-accept reverses −2 once; redelivery of either transition is a no-op against current state.

## Read-model patterns (NFR-CS-PERF-1/3, NFR-CS-SCALE-1)
- **Ledger truth → Stream → rollup maintainer (additive ADD)**: L1/L1-life/L2/L3 kept current; ledger is the sole source of truth, rollups rebuildable by replay (NFR-CS-AVAIL-3).
- **Exactly-once rollup increment (Q2=A′)**: the maintainer applies each ledger entry via a **single conditional `TransactWriteItems`** — a `rollup-applied#<ledgerId>` guard marker (`attribute_not_exists` condition) **plus** the rollup `ADD`, atomically. Redelivery fails the condition → whole transaction rejected → no drift; a crash between "increment" and "mark" is impossible because they are one transaction. The guard marker is **co-located with the rollups in the main table** (no cross-table transaction, no second table for the maintainer). Community-wide split writes one ledger entry per group, each with its own ledgerId guard → each group rolls up once.
- **Leaderboard/top-N via GSI (BR-R3)**: partition `group+quarter`, sort by points → read only top-N; never scans the group (13k-safe). B3 filter applied at read (read top-N+buffer, drop left/deactivated).
- **Tiers derived on read (BR-T1/T2)**: O(1) compare of a rollup total vs current thresholds; never stored; late/cross-quarter awards recompute on next read.
- **Nightly sweep (DL14, Q6)**: computes only the four derived/cross-group aggregates (community + group tier distributions, active-contributor count, community top-contributors) with current thresholds + B3 filter; stamps `computedAt`. Failed run leaves last good `computedAt`; staleness > ~26 h alarms. Real-time metrics (sums, individual tiers, rankings) never touch the sweep.

## Identity denormalization pattern (Q4=A-scoped)
Names/avatars/email are stamped where a per-row lookup would hurt, and captured-at-write where it wouldn't:
- **Rollups carry `memberName` + `avatar`** (leaderboard, group top-contributors) — populated/refreshed from the `MembershipProjection` (E9), which the unit already maintains from Identity events for the split + B3. Brief post-rename staleness (seconds) accepted.
- **Nightly sweep output carries `memberName` + `avatar`** (community top-contributors).
- **CSV export** pulls `member_name` + `member_email` from the Identity projection **server-side** at generate time (US-6.14 needs both columns) — no per-row fan-out.
- **Submissions capture `memberName` at submit**; **adjustment ledger entries capture `memberName` at creation** — low-scale leader views (approval queue, recent adjustments) are self-contained without the projection.
- **Member's own pages** (my points/submissions) need no denormalization — it's the logged-in user.

## Dependency isolation (NFR-CS-REL-3, RESILIENCY-10)
- **Events read (Q3=A)**: explicit timeout + member-profiles-style **per-container short-circuit** on the fan-out earner-list read; on failure the SQS message is **not deleted** → SQS redelivers (transient outage self-heals) → DLQ after max-receives (persistent outage parks, alarmed) — award intent never lost. Partial-progress replay safe via per-earner idempotency.
- **Idempotent consumers (NFR-CS-REL-4)**: award worker, auto-reject (`MemberLeftGroup`/`MemberRemoved`), and Stream maintainer all use run-once guards (award/auto-reject via the small TTL idempotency table; maintainer via the co-located rollup guard).
- **Graceful read degrade**: when rollups/scoring aren't yet populated or a dependency is down, interactive reads return "—" (the same degrade used before scoring is live), never a 5xx.

## Security patterns (Security Baseline)
- **Fail-closed in-service authZ (SECURITY-08)**: declarative permission map (identity-access convention) on every API handler — Member-only earning/submit/own-views (BR-A2/A4), CL any-group vs UGL led-group for approvals/adjust (BR-A3/A5), CL-only framework (BR-A1), Administrator 403 across the service; object-level checks (own points/submissions; UGL adjusts only own group).
- **Input validation (SECURITY-05)**: `delta` bounds, `quarter` enum (trailing-8 window), id format/existence, `reason` length + HTML/script reject, evidence URL/file-key, `limit` bounds, date-range params — parameterized DynamoDB expressions, never string-built.
- **Least-privilege IAM (SECURITY-06)**: per-function roles — API handler (table RW + read-only `execute-api:Invoke` on nothing extra), worker (table RW + SQS + read-only Events invoke for the fan-out read + EventBridge PutEvents), maintainer (Stream read + rollup table RW), sweep (table read + aggregate write). No wildcards; read/write split; scoped to this unit's resources.
- **Append-only ledger = tamper-evident audit (SECURITY-13/14)**: every point change (award/adjustment/reversal) is an immutable entry with actor/reason/before-after inherent; application roles cannot update/delete ledger entries. Log retention ≥ 90 days.
- **Fail-closed exceptions (SECURITY-15)**: consumer failures park in DLQ (never silently dropped); generic user-facing errors; global handler; resource cleanup.

## Observability patterns (RESILIENCY-05/07)
- **Three pillars**: Powertools structured logs + correlation IDs; X-Ray across API→Lambda→DynamoDB and consumer→ledger→Stream→rollup; EMF metrics.
- **Alarms**: SQS depth + message age (both queues), **DLQ not-empty**, worker error rate, **Stream maintainer iterator age** (rollup lag), award end-to-end latency, GSI/rollup read p95, **nightly sweep failure / `computedAt` staleness > ~26 h**, service-quota utilization (SQS/Lambda concurrency/Stream shards/EventBridge) at 80%.
- **Health checks (RESILIENCY-06)**: shallow (process) + deep (own DynamoDB reachability); does not deep-check Events (expected-to-degrade dependency).

## Resiliency test scenarios (captured for Operations — RESILIENCY-14)
| Scenario | Expected behavior |
|---|---|
| Events 503/timeout during fan-out | EventCompleted redelivers; self-heals on recovery; DLQ + alarm if persistent; no award lost |
| Redelivered award / reprocessed Stream record | idempotency key / rollup guard dedups; no double-count |
| 1000-attendee event completed | SQS buffers; bounded worker concurrency drains within ~60 s; API latency unaffected |
| Poison per-earner message | parks in DLQ after max-receives; queue keeps draining; alarm |
| Late cross-quarter approval (Q1 submitted, Q3 approved) | entry lands in Q1; Q1 rollup + tier recompute on next read |
| Un-accept after accept | −2 reversal (same quarter) via toggle; net zero; no double-reverse on redelivery |
| Nightly sweep failure | last good `computedAt` stands; UI disclaimer shows it; alarm on staleness |
| Ledger table loss | restore via PITR, then rebuild rollups by replay (rollups need no backup) |
| DynamoDB throttle | botocore backoff within timeout; alarm on sustained throttles |
| Region/AZ event | managed multi-AZ absorbs AZ loss; region loss → Backup&Restore runbook + rollup rebuild |

## Compliance deltas (this stage)
All applicable SECURITY + RESILIENCY rules realized by the patterns above; SECURITY-04 N/A (no HTML), SECURITY-12 N/A (no credentials held). RESILIENCY-14 scenarios captured (execution deferred to Operations), with idempotency/split/tier/reversal/B3 also enforced as contract tests (NFR-CS-MAINT-1). **No blocking findings.**
