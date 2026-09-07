# NFR Requirements — Unit 7: Contributions & Scoring

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Contributions & Scoring
Platform-wide NFRs (Unit 1) are **inherited**; this document records Unit-7-specific requirements and deltas. Companion: `tech-stack-decisions.md`. Plan/answers: `../../plans/contributions-scoring-nfr-requirements-plan.md` (Q1–Q6 = A).

## Workload criticality (RESILIENCY-01) — Q1=A
- **Criticality: STANDARD.** No service blocks on Unit 7 at runtime. Awards are async (EventBridge→SQS→workers), so upstream producers never wait; interactive reads (points/tier/leaderboard/summary) degrade to "—" when unavailable, the same degrade used before scoring is live. Unavailability delays points/leaderboards but does not block login, events, forums, or certifications.
- **BUT — data durability is CRITICAL** (see RESILIENCY-02/11/12): the **ledger is an authoritative system of record**; points/balances/tiers are derived from it and are **not reliably reconstructible** by replaying upstream events once EventBridge/archive retention lapses. Runtime availability is STANDARD; data loss tolerance is near-zero.
- **Upstream deps**: Events (`EventCompleted` → fan-out read for attendee/presenter/organizer lists + event date/type/scope), Forums (`ForumPostCreated`/`ReplyAccepted` — dormant until Forums is real), Certifications (`CertificationApproved` incl. `submittedAt`), Identity (`MembershipChanged`, `UserDeactivated`/`UserReactivated`, `GroupHardDeleted`). REST read to Events for the fan-out earner list.
- **Downstream consumers**: Member Profiles (deployed — `GET /contributions/me` fan-out), Analytics Unit 8 (summary/leaderboard/sweep data), Notifications (`PointsAwarded`/`PointsAdjusted`), Frontend SPA.

## Availability & recovery (RESILIENCY-02/08/11/12) — Q2=A
- **NFR-CS-AVAIL-1**: Single-region, multi-AZ on managed services (Lambda, DynamoDB, EventBridge, SQS, EventBridge Scheduler). API target **99.5%** (STANDARD tier).
- **NFR-CS-AVAIL-2 (DR)**: **Backup & Restore** posture (RTO/RPO hours) **+ DynamoDB PITR MANDATORY on the ledger table** (continuous, restore-to-the-second, 35-day window) + on-demand backups. PITR gives an effective **RPO of seconds** for the authoritative ledger at low cost.
- **NFR-CS-AVAIL-3 (rollups are disposable)**: L1/L2/L3 rollups and the sweep aggregates are a **derived cache** — no independent backup required; they are **rebuildable by replaying the ledger** (BR-R1). Recovery = restore the ledger (PITR) then rebuild rollups. The **ledger is the only stateful asset that must survive**.
- **NFR-CS-AVAIL-4**: Submissions table (evidence workflow) also on PITR (pending/approved state is not reconstructible).

## Performance — Q4=A
- **NFR-CS-PERF-1** (p95): leaderboard/top-N (GSI, bounded `limit`) **< 500 ms**; `my-points`/tier (rollup reads) **< 600 ms**; group/community summary (rollup reads) **< 800 ms**.
- **NFR-CS-PERF-2** (async awards): a point award is **visible end-to-end < ~60 s** after the triggering action (event completion / forum accept / cert approval). No interactive SLA on the award path — it is explicitly asynchronous (DL3).
- **NFR-CS-PERF-3**: tiers are derived at read time from rollup totals vs thresholds — an O(1) comparison, no ledger scan on the interactive path (BR-T1).
- **NFR-CS-PERF-4**: the **nightly sweep is a batch job** — no interactive SLA; must complete well within its 24 h window (see NFR-CS-SCALE-3).
- **NFR-CS-PERF-5**: `my-points` history reads the ledger member-scoped (bounded by a member's own entries) — cheap; "this week" trend likewise.

## Scalability — Q5=A
- **NFR-CS-SCALE-1**: DynamoDB **on-demand** for ledger + rollups (platform default). Leaderboard reads never scan the group — the **L1 GSI** (partition group+quarter, sort points) returns only top-N, so 13k+-member groups are bounded (BR-R3).
- **NFR-CS-SCALE-2 (fan-out ceiling)**: event-completion fan-out enqueues one job per earner onto SQS; sized for the Events unit's **1000-attendee-per-apply ceiling**, draining within the ~60 s target with **bounded worker concurrency**. SQS absorbs bursts; the user's click never waits (DL3/DL4).
- **NFR-CS-SCALE-3 (sweep)**: the nightly sweep reads the quarter's L1 rollups (≈ number of active member-group pairs, not raw ledger) — tens of thousands of items at community scale, comfortably within a batch window; paginated/segmented as needed.
- **NFR-CS-SCALE-4 (Stream maintainer)**: the ledger DynamoDB Stream → rollup maintainer must keep pace with award write volume; Lambda scales with shard count; idempotent per ledgerId so reprocessing is safe.
- **NFR-CS-SCALE-5 (service quotas)**: identify + monitor SQS throughput, Lambda concurrency, DynamoDB Stream shard limits, and EventBridge PutEvents limits; alarm at 80% (RESILIENCY-09).

## Reliability / Resiliency (Resiliency Baseline) — Q3=A, Q5=A, Q6=A
- **NFR-CS-REL-1 (RESILIENCY-10, delivery guarantee)**: award path is **at-least-once delivery with an idempotent, exactly-once ledger effect** — SQS **+ DLQ**; every auto award deduped by its identity-derived idempotency key (BR-P6); the Stream→rollup maintainer deduped per ledgerId (BR-R2). **No award is ever lost or double-counted**; a poison message parks in the DLQ without blocking the queue.
- **NFR-CS-REL-2 (forum toggle)**: accepted-reply accept/un-accept is a per-reply state toggle (BR-P7) — redelivery of either transition is a no-op against current state, so the ±2 never double-applies.
- **NFR-CS-REL-3 (timeouts)**: explicit timeouts on the REST read to Events (fan-out earner list) and on all event consumption; a slow Events read must not stall the worker indefinitely.
- **NFR-CS-REL-4 (idempotent consumers)**: all consumers (award, auto-reject on `MemberLeftGroup`/`MemberRemoved`, Stream maintainer) use a run-once idempotency store (E10), safe to redeliver/replay.
- **NFR-CS-REL-5 (health checks, RESILIENCY-06)**: shallow health endpoint + deep check verifying DynamoDB reachability.
- **NFR-CS-REL-6 (monitoring, RESILIENCY-05/07)**: metrics/alarms — SQS queue depth + message age, **DLQ not-empty (alarm)**, worker error rate, Stream maintainer iterator age (rollup lag), award end-to-end latency, GSI/rollup read p95, **nightly sweep success + staleness (`computedAt` older than ~26 h → alarm)**, service-quota utilization. X-Ray across API→Lambda→DynamoDB and consumer→ledger→Stream→rollup.
- **NFR-CS-REL-7 (nightly sweep failure, Q6)**: once-daily schedule; a failed run leaves the **last good `computedAt`** standing and the UI keeps showing "as of {computedAt}"; alarm on sweep failure/staleness. No real-time SLA on the four lagged aggregates.
- **NFR-CS-REL-8 (backups, RESILIENCY-12)**: PITR + on-demand backups on ledger + submissions tables; backups encrypted; ledger entries are append-only (never hard-deleted — BR-J1), so no destructive-delete risk beyond standard hygiene.

## Security (Security Baseline)
- **NFR-CS-SEC-1 (SECURITY-08)**: fail-closed in-service authZ on every handler from the permission matrix — Member-only earning/submit/view-own (BR-A2/A4); CL any-group vs UGL led-group for approvals/adjustments (BR-A3/A5); framework CL-only (BR-A1); **Administrator 403** across the service. Object-level checks (a member reads only their own points/submissions; a UGL adjusts only their group). Enforced server-side, never relying on the frontend to hide actions.
- **NFR-CS-SEC-2 (SECURITY-05)**: validate all inputs — `delta` (integer bounds), `quarter` (enum of the trailing-8 window), `groupId`/`memberId` (format + existence), `reason` (length cap, reject HTML/script), evidence URL format / file key, `limit` bounds on leaderboard, date-range params on summary/export. Reject unexpected types; body size caps.
- **NFR-CS-SEC-3 (SECURITY-06)**: per-Lambda execution role scoped to this service's DynamoDB tables (ledger, submissions, rollups, framework, idempotency) + its SQS queues + EventBridge (PutEvents for `PointsAwarded`/`PointsAdjusted`; subscribe to consumed events) + read-only `execute-api:Invoke` on the Events routes used for the fan-out earner-list read — **no wildcards**, read/write split.
- **NFR-CS-SEC-4 (SECURITY-01)**: ledger/rollups/submissions/framework tables + SQS queues encrypted at rest (AWS-managed KMS); TLS 1.2+ to all AWS APIs and the intra-account REST read.
- **NFR-CS-SEC-5 (SECURITY-13/14, integrity + audit)**: the append-only ledger **is** the tamper-evident audit trail for point changes — who/what/when/before-after is inherent (every award, adjustment, and reversal is an immutable entry with `adjustorId`/`reason`/`reverses`/`createdAt`). Application code must not be able to update/delete ledger entries (append-only enforced). Log retention ≥ 90 days.
- **NFR-CS-SEC-6 (SECURITY-15)**: fail-closed exception handling; a consumer failure parks in the DLQ (never silently drops an award); generic user-facing errors; global handler; resource cleanup on error paths.
- **NFR-CS-SEC-7 (SECURITY-11, abuse)**: forum post points are uncapped by design (US-6.4) but low-value (1) to remove the farming incentive (DL16); moderation/dup-detection are the backstop (Forums). Manual adjustment is leader-only and fully audit-logged. API GW throttling inherited.
- **NFR-CS-SEC-8 (SECURITY-03)**: structured logging w/ correlation IDs; no PII beyond member/group ids; never log secrets.

## Maintainability
- **NFR-CS-MAINT-1**: contract-test gate (Schemathesis + pytest) — **plus** mandatory suites for: (a) **idempotency** (redelivered award / reprocessed Stream record produces no double-count), (b) **community-wide split determinism** (equal division + earliest-join remainder sums exactly), (c) **runtime tier derivation** incl. late cross-quarter award lifting a closed quarter, (d) **reversal single-use guard**, (e) **B3 exclusion** (left/deactivated members excluded from live views, retained in aggregates). These encode the unit's non-obvious rules and must not regress.
- **NFR-CS-MAINT-2**: bandit + cfn-lint/cfn_nag + dependency scan + SBOM in CI (platform default).

## Compliance / scope
- **NFR-CS-COMP-1**: no regulated regime (Phase 1). Point data is community-internal, non-financial. PII limited to member/group identifiers (minimized in logs/events). Data residency = customer's single region (inherited).

## Security Compliance Summary
| Rule | Status | Note |
|---|---|---|
| SECURITY-01 Encryption | Compliant | KMS at rest (tables + SQS); TLS in transit |
| SECURITY-02 Access logging | Compliant (inherited) | API GW execution/access logs at edge |
| SECURITY-03 App logging | Compliant | JSON + correlation IDs; no PII/secrets |
| SECURITY-04 Security headers | N/A | No HTML served (SPA/CloudFront) |
| SECURITY-05 Input validation | Compliant | delta/quarter/ids/reason/limits validated |
| SECURITY-06 Least privilege | Compliant | Scoped role (own tables + SQS + EventBridge + read-only Events invoke) |
| SECURITY-07 Network | Compliant (inherited) | Private subnets, VPC endpoints |
| SECURITY-08 Access control | Compliant | Fail-closed authZ; Member-only earning; CL/UGL scoping; Admin 403; object-level checks |
| SECURITY-09 Hardening | Compliant | Generic errors; no default creds |
| SECURITY-10 Supply chain | Compliant | Pinned reqs + scan/SBOM in CI |
| SECURITY-11 Rate limiting / abuse | Compliant | API GW throttling; low forum points; leader-only audited adjustments |
| SECURITY-12 Auth & credentials | N/A | Holds no credentials — authN is Identity's |
| SECURITY-13 Integrity | Compliant | Append-only ledger = tamper-evident audit; safe parsing |
| SECURITY-14 Alerting | Compliant | DLQ/consumer-lag/sweep-staleness alarms; ≥90d retention |
| SECURITY-15 Exception handling | Compliant | Fail-closed; DLQ; global handler |

## Resiliency Compliance Summary
| Rule | Status | Note |
|---|---|---|
| RESILIENCY-01 Criticality | Compliant | STANDARD runtime; data durability CRITICAL |
| RESILIENCY-02 RTO/RPO | Compliant | Backup&Restore + PITR mandatory (RPO seconds) |
| RESILIENCY-03 Change mgmt | N/A (inherited) | Platform exemption |
| RESILIENCY-04 Deploy/rollback | Compliant (inherited) | CodePipeline; redeploy previous version |
| RESILIENCY-05 Monitoring | Compliant | Queue/DLQ/lag/sweep/latency metrics + alarms |
| RESILIENCY-06 Health checks | Compliant | Shallow + deep (DynamoDB) |
| RESILIENCY-07 Resiliency monitoring | Compliant | DLQ + Stream iterator-age + sweep-staleness alarms; quota monitoring |
| RESILIENCY-08 Multi-zone | Compliant (inherited) | Managed multi-AZ services |
| RESILIENCY-09 Auto-scaling | Compliant | On-demand DDB; bounded worker concurrency; quota alarms |
| RESILIENCY-10 Circuit breaking | Compliant | Timeouts on Events read + consumers; DLQ; graceful "—" degrade |
| RESILIENCY-11 DR strategy | Compliant | Backup&Restore; ledger via PITR, rollups by replay |
| RESILIENCY-12 Backup | Compliant | PITR + on-demand on ledger + submissions; encrypted; append-only |
| RESILIENCY-13 Failover procedures | Compliant (inherited) | Platform runbook; single-region restore + rollup rebuild step |
| RESILIENCY-14 Resiliency testing | Deferred-to-Operations (inherited) | Scenarios captured in NFR Design |
| RESILIENCY-15 Incident response | Compliant (inherited) | Lightweight IR + COE |

**No blocking security or resiliency findings.**
