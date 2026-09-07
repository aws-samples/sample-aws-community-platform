# Unit 7 — Contributions & Scoring: NFR Requirements Plan

**Stage**: CONSTRUCTION → Per-Unit Loop → NFR Requirements
**Unit**: Unit 7 — Contributions & Scoring
**Extensions enabled**: Security Baseline ✅, Resiliency Baseline ✅, Property-Based Testing ❌
**Status**: AWAITING ANSWERS to the clarifying questions below.

## Context loaded
- Functional design (business-logic-model / business-rules / domain-entities / frontend-components) + decision log DL1–DL21.
- Platform NFRs (Unit 1) are **inherited**; this stage records Unit-7 deltas.
- Reference: member-profiles + events NFR requirements.

## Platform-inherited decisions (not re-asked — confirm only if you want to override)
| Area | Inherited value |
|---|---|
| Change management (RESILIENCY-03) | Exempt (platform decision) |
| CI/CD (RESILIENCY-04) | AWS CodePipeline, one pipeline per service, contract-test gate |
| Rollback (RESILIENCY-04) | Redeploy previous version |
| Deployment style (RESILIENCY-04) | Direct/in-place (per-service) |
| Regional topology (RESILIENCY-08) | Single-region, multi-AZ (managed services) |
| Incident response (RESILIENCY-15) | Lightweight IR + COE (platform) |
| Resiliency testing (RESILIENCY-14) | Deferred to Operations; scenarios captured at design |
| Encryption / logging / network baseline | Inherited platform defaults (KMS at rest, TLS, private subnets, API GW logs) |

## Key NFR characteristic (why this unit differs)
Unit 7's **ledger is an authoritative system of record** — points, balances, and tiers are derived from it and are **NOT reconstructible by replaying upstream events** once EventBridge/archive retention lapses (unlike Member Profiles' rebuildable cache). This makes **data durability (RPO)** the defining NFR. Awards are async (SQS-buffered), so the award path tolerates delay but must never lose or double-count an entry.

---

## Clarifying Questions

## Question 1 — Workload criticality (RESILIENCY-01)
How critical is Contributions & Scoring at runtime?

A) **STANDARD** — no other service blocks on it at runtime; awards are async (SQS-buffered) and reads degrade to "—". Unavailability delays points/leaderboards but doesn't block login/events/forums/certs. (Recommended — mirrors Member Profiles' classification; the ledger's *durability* is handled separately in Q2, independent of runtime criticality.)

B) **HIGH/CRITICAL** — treat points availability as business-critical (tighter availability target, provisioned capacity).

C) Other (please describe after [Answer]: tag below)

[Answer]:A

## Question 2 — RTO/RPO & data durability (RESILIENCY-02/11/12) — the important one
The ledger is authoritative and not reliably reconstructible. What recovery targets?

A) **Backup & Restore (RTO/RPO: hours)** + **DynamoDB PITR mandatory** on the ledger (point-in-time restore to the second, 35-day window) + on-demand backups; rollups are rebuildable from the ledger by replay, so they need no independent backup. (Recommended — PITR gives an effective RPO of seconds for the authoritative ledger at low cost, while keeping the platform's Backup&Restore posture; matches the Events unit, whose data is likewise not replay-reconstructible.)

B) **Warm Standby / cross-region (RTO/RPO: minutes)** — cross-region replicate the ledger (higher cost).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3 — Award delivery guarantee
Points awarding is async (EventBridge → SQS → workers). What correctness guarantee?

A) **At-least-once delivery + idempotent, exactly-once ledger effect** — SQS with a **DLQ**; every award deduped by its identity-derived idempotency key (BR-P6), and the Stream→rollup maintainer deduped per ledgerId (BR-R2). A poison message parks in the DLQ without blocking others; no award is ever lost or double-counted. (Recommended)

B) Best-effort (accept possible loss/duplication). (Not recommended for point data.)

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — Performance targets (interactive reads)
Confirm p95 targets for the interactive paths (13k+-member groups):

A) **Leaderboard/top-N (GSI, bounded limit) p95 < 500 ms; my-points/tier p95 < 600 ms (rollup reads); group/community summary p95 < 800 ms; award end-to-end visible < ~60 s after the triggering action (async).** Nightly sweep is a batch job (no interactive SLA). (Recommended — aligns with Member Profiles' read budgets; awards are explicitly async so no interactive SLA on them.)

B) Tighter (specify).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5 — Fan-out scale ceiling & throughput
The event-completion fan-out can enqueue many per-earner jobs (e.g., a 1000-attendee event).

A) **Bound worker concurrency + rely on SQS buffering**; size for the Events unit's stated **1000-attendee ceiling per apply**, draining within the ~60 s target; DynamoDB on-demand for ledger + rollups. Monitor SQS depth + age; alarm on DLQ. (Recommended)

B) Provisioned/reserved concurrency or tighter drain SLA (specify).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6 — Nightly sweep freshness/failure (RESILIENCY-05)
The nightly sweep produces the four lagged aggregates (DL14).

A) **Once-daily schedule; on a failed run the last good `computedAt` stands and the UI keeps showing "as of {computedAt}"; alarm on sweep failure / staleness beyond ~26 h.** No real-time SLA on these aggregates. (Recommended)

B) More frequent (specify) / add an on-threshold-edit trigger.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Part 1 — Planning checklist
- [x] Read functional design + DL1–DL21
- [x] Load security + resiliency baselines; identify inherited platform decisions
- [x] Author clarifying questions (6, Unit-7-specific)
- [x] Collect answers (Q1–Q6 = A; Q6 took recommended default) — no ambiguities
- [x] Generate `nfr-requirements.md` + `tech-stack-decisions.md`; security/resiliency compliance summaries (no blocking findings); present gate
