# Infrastructure Design — Unit 7: Contributions & Scoring

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Contributions & Scoring
Maps the NFR-design logical components to AWS resources. Companion: `deployment-architecture.md`. Plan/answers: `../../plans/contributions-scoring-infrastructure-design-plan.md` (Q1=B link-only, Q2=A one table, Q3=A 5 functions, Q4=A standard SQS+DLQ, Q5=coordinated big-bang). Inherits Foundation + API Edge (`../../shared-infrastructure.md`) as Parameters (D1).

## Resource inventory

### Compute — 5 Lambdas (Q3), one code package, private subnets
| Function | Trigger | Reserved concurrency | Memory/Timeout | Notes |
|---|---|---|---|---|
| **ApiHandler** | API GW (proxy) | unreserved | modest / ~29s (API GW cap) | framework CRUD, submissions, approvals, adjustments, me/history/leaderboard/summary/export/tiers-earned |
| **AsyncConsumer** | SQS: EventCompleted + Forum/Cert/Identity event queues | **10** | modest / ~60s | fan-out **expander** (reads Events) + idempotent event consumers + evidence auto-reject |
| **AwardWorker** | SQS: per-earner queue | **25** | modest / ~30s | guard pipeline → append ledger; paces DynamoDB; drains 1000 in ~2s |
| **RollupMaintainer** | DynamoDB Stream (ledger, NEW_IMAGE) | unreserved (= shard count) | modest / ~60s | filters to **ledger INSERTs only**; atomic guarded rollup ADD (Q2=A′) |
| **NightlySweep** | EventBridge Scheduler (daily) | unreserved | **higher memory / long timeout** | tier distributions + active-contributor count + community top-N; stamps `computedAt` |

*Total deliberate reserved carve-out = 35 of the ~1000 account pool.*

### Storage (Q2=A)
| Resource | Config |
|---|---|
| **Main table** (`contributions-scoring-<stage>`) | single-table (ledger, rollups L1/L1-life/L2/L3, `rollup-applied` guards, framework, submissions, reply-award-state, membership projection, sweep aggregates); on-demand; **PITR on**; **Streams NEW_IMAGE**; `DeletionPolicy/UpdateReplacePolicy: Retain`; SSE (AWS-managed KMS) |
| **Leaderboard GSI** | partition `group#quarter`, sort `points` — defined **at table creation** (greenfield → no sequential-GSI problem); projection = fields leaderboard/top-N render (incl. denormalized `memberName`/`avatar`) |
| **Idempotency table** (`contributions-scoring-idem-<stage>`) | run-once markers (AwardWorker + auto-reject); on-demand; **TTL**; no PITR (ephemeral); Retain not required |

**No S3 / GuardDuty / FileShareBucket usage** (Q1=B link-only) — no bucket prefix, no scan rule, **no change to `shared-infrastructure.md`** or Settings' exclusion list.

### Messaging (Q4=A)
| Resource | Config |
|---|---|
| **EventCompleted queue** + DLQ | EventBridge rule (Events `EventCompleted`) → SQS → AsyncConsumer(expander) |
| **Per-earner award queue** + DLQ | expander → SQS → AwardWorker |
| **Event-consumer queue(s)** + DLQ | EventBridge rules (Forum dormant / Cert / Identity) → SQS → AsyncConsumer |
| All queues | **Standard**; SSE-KMS; **maxReceiveCount 5** → DLQ; **visibility timeout ≥ 6× worker timeout**; DLQ-not-empty alarm → Ops SNS |
| **Stream on-failure** | destination → a DLQ (poison ledger record can't wedge RollupMaintainer) |
| **EventBridge Scheduler** | daily → NightlySweep |

### EventBridge rules (consumed events)
`EventCompleted` (Events), `ForumPostCreated`/`ReplyAccepted` (Forums — **authored, dormant** until Forums real), `CertificationApproved` (Certs, with `submittedAt`), `MembershipChanged`/`UserDeactivated`/`UserReactivated`/`GroupHardDeleted` (Identity). Published: `PointsAwarded`, `PointsAdjusted` (no `TierAchieved` — DL19).

### IAM (per-function least privilege — SECURITY-06)
| Function | Grants (no wildcards) |
|---|---|
| ApiHandler | main table RW; EventBridge PutEvents (`PointsAdjusted`); (reads denormalized projection from own table) |
| AsyncConsumer | main + idempotency table RW; SQS consume + DLQ; **read-only `execute-api:Invoke` on Events `GET /events/*` routes** (fan-out earner-list read); EventBridge PutEvents |
| AwardWorker | main + idempotency table RW; SQS consume + DLQ; EventBridge PutEvents (`PointsAwarded`) |
| RollupMaintainer | Stream read; main table RW (rollups + `rollup-applied` guards) |
| NightlySweep | main table read + sweep-aggregate write |

### Monitoring (inherited Ops SNS topic)
SQS depth + message age (both queues), **DLQ-not-empty**, worker error rate, **Stream iterator age** (rollup lag), award end-to-end latency, GSI/rollup read p95, **NightlySweep failure / `computedAt` staleness > ~26h**, DynamoDB throttles, **service-quota utilization at 80%** (SQS / Lambda concurrency / Stream shards / EventBridge). X-Ray across API→Lambda→DDB and consumer→ledger→Stream→rollup.

## `-data` / `-app` split (D9)
- **`service-contributions-scoring-data.yaml`**: main table (+ GSI + Streams + PITR), idempotency table, DLQs. Deployed once; Retain.
- **`service-contributions-scoring-app.yaml`**: 5 Lambdas, SQS source queues, EventBridge rules + Scheduler, IAM roles, alarms, API routes (receives RestApiId/RootResourceId/EventBusName/table refs as Parameters). Redeployed each change.

## Cross-unit changes bundled in this unit (Q5 — coordinated big-bang)
| Unit | Change | Type |
|---|---|---|
| Events (Unit 4) | emit **`EventCompleted`** (single trigger) + stamp earner **role** on award events (DL4/DL8) | producer + contract (additive) |
| Certifications (Unit 6) | add **`submittedAt`** to `CertificationApproved` (DL13) | producer + contract (additive) |
| Forums (Unit 5) | author **`ForumPostCreated`/`ReplyAccepted`** schemas (dormant — Forums still mock) | contract only |
| Contracts | `contributions-scoring/openapi.yaml` → **v2.0.0** (expanded shapes + new endpoints per domain-entities deltas; `/contributions/me` shape preserved for Member-Profiles) | contract |

All applied together; user undeploys + redeploys all units together once Unit 7 is ready → consumers built against final shapes (no dual-shape tolerance). **Forum auto-award remains dormant** until Forums is built (this redeploy does not make Forums real).

## Cross-unit conflict checks (vs Events F1/F2/F3, Certs F-A/F-B)
- **No public base path** — `/contributions` authenticated; no `PUBLIC_BASES`/gen_api_edge collision. ✅
- **GSI at creation** — greenfield table, GSI defined at create; no sequential single-GSI-per-UpdateTable issue (F2 avoided). Still poll DescribeTable for GSI `ACTIVE` post-deploy. ✅
- **No shared-bucket consumer** (Q1=B) — no F3/F-A/F-B prefix-filter obligations; Settings' exclusion list untouched. ✅
- **API routes** — `/contributions/*` already routed via api-edge; contract expansion is additive under the routed base path → **no gen_api_edge regen** needed.

## Security & Resiliency compliance (this stage)
| Rule | Status | Note |
|---|---|---|
| SECURITY-01/06/08/13/14/15 | Compliant | KMS tables+queues; per-function scoped IAM; fail-closed authZ; append-only audit ledger; DLQ+alarms; fail-closed |
| SECURITY-04/12 | N/A | no HTML; no credentials |
| RESILIENCY-02/11/12 | Compliant | PITR on main table (ledger authoritative); rollups rebuildable; DLQs |
| RESILIENCY-05/07/09/10 | Compliant | metrics/alarms; bounded concurrency; quota alarms; timeouts + DLQ + short-circuit |
| RESILIENCY-08 | Compliant (inherited) | managed multi-AZ |
| RESILIENCY-03/04/13/14/15 | Inherited / deferred | platform change-mgmt/CI-CD/runbook/IR; DR test scenarios captured in NFR design |

**No blocking security or resiliency findings.**
