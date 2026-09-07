# Unit 7 — Contributions & Scoring: NFR Design Plan

**Stage**: CONSTRUCTION → Per-Unit Loop → NFR Design
**Unit**: Unit 7 — Contributions & Scoring
**Status**: AWAITING ANSWERS.

## Context loaded
- NFR requirements (NFR-CS-*) + tech-stack-decisions (TS-1..10); functional design + DL1–DL21.
- Reference patterns: member-profiles (FanOutClient, idempotent consumer, per-container short-circuit), events (sweep, EventPublisher), identity-access (declarative authZ).

## Already determined (no question needed — realized as patterns in the artifacts)
- Ledger append-only + Stream→rollup maintainer (additive ADD); L1/L1-life/L2/L3 + leaderboard GSI; tiers derived on read.
- Award path: EventBridge → SQS **+ DLQ** → workers; per-earner idempotency key; exactly-once ledger effect.
- Community-wide split computed in the worker's guard pipeline (current membership, earliest-join remainder).
- Nightly EventBridge Scheduler → sweep (four lagged aggregates + `computedAt`).
- Fail-closed in-service authZ (declarative map), input validation, least-privilege IAM, structured logs + X-Ray, health checks, PITR.
- Dormant forum consumer; reopened Events/Certs contracts.

---

## Clarifying Questions (only the genuinely open design choices)

## Question 1 — Lambda topology
How should this unit's compute be organized? It has an API handler + async award workers (SQS) + a Stream rollup maintainer + a nightly sweep + event consumers, which have **different scaling/concurrency profiles**.

A) **A small set of purpose-separated functions sharing one code package**: (1) API handler, (2) async worker (SQS consumer: fan-out expander + award), (3) Stream rollup maintainer, (4) nightly sweep. Each gets its own concurrency/timeout/memory. (Recommended — bounded worker concurrency, Stream, and a scheduled batch have genuinely different runtime needs; separating them isolates a burst/poison in one from the others.)

B) **Single Lambda with router branches** (Units 3/4/6 convention) handling API + consumers + sweep.

C) Other (please describe after [Answer]: tag below)

[Answer]: A (purpose-separated functions: API handler · async worker [expander+award+event consumers] · Stream maintainer · nightly sweep — sharing one code package)

## Question 2 — Rollup maintainer idempotency mechanism
The Stream is at-least-once; the maintainer must not double-apply a ledger entry to a rollup.

A) **Conditional bookkeeping in the maintainer**: track applied ledgerIds and apply each increment only once (idempotency table keyed by ledgerId, TTL-cleaned — same run-once pattern as the unit's other consumers, E10). (Recommended — one consistent idempotency mechanism across award workers, auto-reject, and the maintainer.)

B) Rely on DynamoDB Stream exactly-once semantics within a shard + a processed-sequence marker on the rollup item.

C) Other (please describe after [Answer]: tag below)

[Answer]: A′ — ledgerId run-once guard applied ATOMICALLY with the rollup increment (single conditional TransactWriteItems). Guard marker co-located with rollups in the main table (no second table for the maintainer). Unit-wide layout: one main table (single-table design) + one small dedicated TTL idempotency table for award-worker/auto-reject run-once markers (keeps ephemeral markers out of the PITR-backed durable table).

## Question 3 — Events read resilience (fan-out earner list)
The worker RESTs to Events for the event + earner lists (DL11). How resilient?

A) **Explicit timeout + bounded retry; on failure the SQS message is not deleted → SQS redelivers → DLQ after max receives** (so a transient Events outage self-heals when it recovers, and a persistent failure parks in the DLQ without losing the award intent). Reuse member-profiles' per-container short-circuit to avoid hammering a known-down Events. (Recommended)

B) Timeout + drop (accept award loss on Events outage). (Not recommended.)

C) Other (please describe after [Answer]: tag below)

[Answer]: A — timeout + per-container short-circuit on the Events read; on failure the SQS message is not deleted → redelivers → DLQ after maxReceiveCount (+ alarm); partial-progress replay is safe because the award worker is idempotent per earner (BR-P6).

## Question 4 — Leaderboard/summary name+avatar resolution (revisit DL9 at design depth)
Leaderboard/summary/export show member name+avatar; the ledger/rollups key on memberId.

A) **Denormalize `memberName`+`avatar` onto rollups** (populated from the local MembershipProjection / Identity events the unit already consumes), so leaderboard/summary/export are self-contained single reads — critical at 13k-member scale and for server-side CSV (name/email). Refresh on the relevant Identity events. (Recommended — matches DL9 lean.)

B) Return ids only; frontend/Analytics resolves names via batch calls.

C) Other (please describe after [Answer]: tag below)

[Answer]: A (scoped) — denormalize memberName+avatar onto ROLLUPS (leaderboard, group top-contributors) and the nightly SWEEP output (community top-contributors), refreshed from Identity events; CSV export pulls name+email from the Identity projection server-side; LOW-scale leader views capture memberName at write time (on the Submission at submit; on the adjustment ledger entry). Member's own pages need no denorm (logged-in user). explain more

---

## Part 1 — Planning checklist
- [x] Read NFR requirements + functional design + DL log
- [x] Identify determined patterns vs open design choices
- [x] Author clarifying questions (4)
- [x] Collect answers (brainstormed: Q1=A, Q2=A′, Q3=A, Q4=A-scoped) — no ambiguities
- [x] Generate `nfr-design-patterns.md` + `logical-components.md`; compliance summaries (no blocking findings); present gate
