# Unit 7 — Contributions & Scoring: Infrastructure Design Plan

**Stage**: CONSTRUCTION → Per-Unit Loop → Infrastructure Design
**Unit**: Unit 7 — Contributions & Scoring
**Status**: AWAITING ANSWERS.

## Context loaded
- Functional design + NFR design (patterns + logical-components) + DL1–DL21.
- `shared-infrastructure.md` (Foundation/API-Edge, shared FileShareBucket + GuardDuty scan discipline, `PUBLIC_BASES`, gen_api_edge collision rule).
- Reference: events + certifications infrastructure-design (cross-unit conflict findings F1/F2/F3/F-A/F-B).

## Inherited platform infra (not re-asked)
VPC + private subnets + NAT (Foundation), API Gateway REST + Cognito authorizer + throttling (API Edge), shared EventBridge bus, KMS AWS-managed keys, central log groups + X-Ray + Ops SNS alarm topic, CloudFront+S3 SPA. `Stage` param dev vs customer prod. Single-region multi-AZ.

## Determined by NFR design (confirm via Q2–Q4)
- 4 Lambdas (ApiHandler / AsyncWorker / RollupMaintainer / NightlySweep) in private subnets.
- Single **main DynamoDB table** (ledger, rollups, guards, framework, submissions, reply-state, membership projection, sweep aggregates) + **leaderboard GSI** + **Streams**; small **TTL idempotency table**.
- SQS queues (EventCompleted, per-earner, event-consumer) each **+ DLQ**; EventBridge Scheduler (nightly sweep); EventBridge rules for consumed events.
- PITR on the main table; per-function least-privilege IAM.

## Cross-unit checks (mirroring the Events/Certs findings)
- **No public base path** — `/contributions` is authenticated; no `PUBLIC_BASES`/collision issue (unlike Events F1). ✅
- **GSI creation** — the main table is **brand-new** (greenfield), so the leaderboard GSI is defined **at table creation** — no sequential single-GSI-per-UpdateTable problem (that was Events F2, which only bites when adding GSIs to an existing table). Still: after deploy, poll DescribeTable for GSI `ACTIVE` before relying on it. ✅
- **Contract reopens** — Events (`EventCompleted` + role stamp) and Certifications (`submittedAt`) are other units' deployed stacks → coordinate (Q5).

---

## Clarifying Questions

## Question 1 — Evidence file uploads (the one real infra decision)
US-6.6 evidence is "URL link **or file upload**". A file upload means storage + malware scanning + a serving path — the shared `FileShareBucket` + GuardDuty pattern that Certifications already uses.

A) **Reuse the shared scanned bucket** with a `contributions/evidence/` prefix: presigned-PUT upload, system-assigned unique key, submission not reviewable until the GuardDuty verdict is Clean; add the object-rule prefix filter + scan-rule prefix filter and extend Settings' `anything-but` exclusion list (findings F3/F-A/F-B discipline). Mirrors Certifications exactly. (Recommended if file-evidence is in scope.)

B) **Link-only (URL) in v1** — no file upload; evidence is a URL the reviewer opens. Simplest; recorded deviation from US-6.6's "or file upload". (Recommended if you want to avoid the bucket/scan surface for now — most evidence, blogs/talks/PRs, is a link anyway.)

C) Other (please describe after [Answer]: tag below)

[Answer]: B — link-only v1 (evidence = URL). Recorded deviation from US-6.6 "or file upload". No FileShareBucket prefix, no GuardDuty scan rule, no Settings exclusion change (no cross-unit bucket edits). Keep `evidenceFileKey` reserved in the schema + UI copy "URL" so file support is a later additive change with no contract break.

## Question 2 — DynamoDB table & indexes
Confirm the data-layer shape:

A) **One new main table** (single-table design) with the **leaderboard GSI defined at creation**, DynamoDB **Streams (NEW_IMAGE)** enabled for the RollupMaintainer, **on-demand** billing, **PITR on**, `DeletionPolicy/UpdateReplacePolicy: Retain`; **separate small idempotency table** (TTL, on-demand, no PITR). (Recommended)

B) Different split (specify — e.g., separate ledger vs rollup tables).

C) Other (please describe after [Answer]: tag below)

[Answer]: A — one main table (single-table design) + leaderboard GSI at creation + Streams (NEW_IMAGE) + on-demand + PITR + Retain; separate small TTL idempotency table (no PITR). Keeps the Q2=A′ rollup-guard transaction local (ledger+rollup+guard same table). RollupMaintainer filters the Stream to ledger INSERTs only (ignores its own rollup/guard writes — no loop).

## Question 3 — Compute sizing & concurrency
A) **ApiHandler** on-demand (no provisioned concurrency — reads are rollup/GSI lookups, not on an auth-critical path); **AsyncWorker** with **reserved/bounded concurrency** (protects DynamoDB + isolates bursts, sized for the 1000-attendee ceiling draining < ~60 s); **RollupMaintainer** driven by Stream shard count; **NightlySweep** higher memory + long timeout (batch). All in private subnets. (Recommended)

B) Different sizing (specify).

C) Other (please describe after [Answer]: tag below)

[Answer]: A (refined) — **5 functions** (split the per-earner award worker out from the expander/consumers). Reserved concurrency: **Award worker = 25** (drains 1000 jobs in ~2s, paces DynamoDB, 2.5% of the 1000 account pool), **Expander + event consumers = 10** (bounds a MembershipChanged storm from a bulk import), **ApiHandler / RollupMaintainer / NightlySweep = unreserved**. Total carve-out 35/1000. Rationale: reserved concurrency is carved from the shared account pool (~1000, ~100 unreserved floor) across ~15 services — bounding the award worker both paces our DynamoDB writes and prevents starving other units. Values tunable at load test (quota alarms at 80%).

## Question 4 — Messaging (SQS/DLQ) specifics
A) **Standard SQS** queues (EventCompleted, per-earner, per-consumer) each with a **DLQ + redrive policy** (maxReceiveCount ~5); visibility timeout ≥ 6× the worker's function timeout; DLQ-not-empty alarm; Stream on-failure destination → DLQ. (Recommended — awards are commutative/idempotent so FIFO isn't required.)

B) FIFO or different parameters (specify).

C) Other (please describe after [Answer]: tag below)

[Answer]: A — **Standard** SQS (awards commutative + idempotent, so no FIFO needed); DLQ + redrive per source queue (EventCompleted, per-earner, each consumer), **maxReceiveCount 5**, **visibility timeout ≥ 6× the worker function timeout**; DLQ-not-empty alarms → Ops SNS; Stream on-failure destination → DLQ; KMS-encrypted queues (inherited). Specific timeout numbers finalized in infra artifacts per the ≥6× rule.

## Question 5 — Cross-unit contract reopens (deployed producers)
Events (`EventCompleted` + earner role stamp — DL4/DL8) and Certifications (`CertificationApproved.submittedAt` — DL13) are already deployed.

A) **Treat as additive, coordinated changes**: author the schema updates now (Forums `ForumPostCreated`/`ReplyAccepted` authored dormant); Events/Certs producer changes tracked as follow-up deploys of those units, and Unit 7's consumers built tolerant (accept messages with/without the new fields during the transition). Unit 7 does not block on those redeploys to ship. (Recommended)

B) Block Unit 7 rollout until Events/Certs are redeployed.

C) Other (please describe after [Answer]: tag below)

[Answer]: COORDINATED BIG-BANG — make all changes together (Events EventCompleted + earner role stamp; Certs CertificationApproved.submittedAt; Forums ForumPostCreated/ReplyAccepted schemas; Unit 7 consumers). User will undeploy + redeploy ALL units together once Unit 7 is ready. Consequences: (1) Unit 7 consumers built DIRECTLY against the final shapes — no backward-tolerant dual-shape handling (DL13 dateEarned/decidedAt fallback kept only as defensive code; submittedAt always present post-redeploy). (2) Unit 7's construction scope INCLUDES editing the deployed Events + Certifications producers. (3) Forums is still a MOCK — authoring its schemas + Unit 7's dormant forum consumer does NOT make forum points flow; attendance/delivery/organize + cert auto-award flow immediately after the coordinated redeploy, forum stays dormant until Forums is built.

---

## Part 1 — Planning checklist
- [x] Read functional + NFR design; shared-infrastructure; Events/Certs infra findings
- [x] Identify inherited vs determined vs open; cross-unit checks (no public path, greenfield GSI)
- [x] Author clarifying questions (5)
- [x] Collect answers (Q1=B link-only, Q2=A one table, Q3=A 5 functions + reserved 25/10, Q4=A standard SQS+DLQ, Q5=coordinated big-bang) — no ambiguities
- [x] Generate `infrastructure-design.md` + `deployment-architecture.md`; no shared-infrastructure.md change (link-only = no new bucket consumer); compliance summaries; present gate
