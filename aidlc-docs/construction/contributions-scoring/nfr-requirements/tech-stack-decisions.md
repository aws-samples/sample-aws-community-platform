# Tech Stack Decisions — Unit 7: Contributions & Scoring

**Stage**: CONSTRUCTION → NFR Requirements. Companion to `nfr-requirements.md`. Platform stack (Unit 1) is inherited; this records Unit-7 choices + rationale. No new runtime dependencies beyond the platform's AWS-native set.

## Inherited platform stack (unchanged)
| Layer | Choice |
|---|---|
| Backend runtime | Python on AWS Lambda |
| IaC | CloudFormation + SAM; `-data`/`-app` split; per-service pipeline |
| API | Amazon API Gateway (REST) + Cognito authorizer (authN); in-service authZ |
| Eventing | EventBridge (cross-service), DynamoDB Streams (CDC), SQS (+DLQ) |
| Data | DynamoDB (on-demand), `DeletionPolicy/UpdateReplacePolicy: Retain` |
| Frontend | React + Vite + TypeScript |
| CI/CD | CodePipeline, contract-test gate; redeploy-previous rollback |

## Unit-7-specific decisions
| # | Decision | Rationale |
|---|---|---|
| TS-1 | **DynamoDB single-table-ish design**: ledger (append-only), rollups (L1/L1-life/L2/L3), submissions, framework, reply-award-state, membership projection, idempotency — modeled per `domain-entities.md`; ledger + rollup separation drives the read model. Exact table/GSI layout finalized in Infrastructure Design. | Ledger = truth; rollups = derived cache; leaderboard needs a points-sorted GSI (BR-R3). |
| TS-2 | **DynamoDB Streams → rollup maintainer Lambda** (idempotent, additive ADD). | Decouples the fast ledger write from rollup maintenance; rebuildable by replay (NFR-CS-AVAIL-3). |
| TS-3 | **SQS (standard) + DLQ** for the event-completion fan-out (per-earner jobs) and award workers; **bounded worker concurrency**. | At-least-once + idempotent exactly-once effect (NFR-CS-REL-1); absorbs the 1000-attendee burst without blocking the user (DL3/DL4). |
| TS-4 | **DynamoDB PITR mandatory** on ledger + submissions tables; on-demand backups. | Authoritative, non-replay-reconstructible data (NFR-CS-AVAIL-2/4). |
| TS-5 | **EventBridge Scheduler → nightly sweep Lambda** (router branch of the service, per the Units 3/4/6 single-Lambda convention). | Produces the four lagged aggregates (DL14); batch, no interactive SLA. |
| TS-6 | **Consumers via EventBridge rules → SQS → Lambda**: `EventCompleted` (fan-out), `ForumPostCreated`/`ReplyAccepted` (dormant — DL10), `CertificationApproved`, Identity `MembershipChanged`/`UserDeactivated`/`UserReactivated`/`GroupHardDeleted`. | Standard async consumption; dormant forum consumer lights up when Forums is real. |
| TS-7 | **Read-time REST to Events** (`GET /events/{eventId}` + attendee/presenter/organizer lists) for the fan-out, forwarding the caller/service context; explicit timeout. | DL4/DL11 — event date/type/scope + earner lists from the read the Lambda already does. |
| TS-8 | **No new third-party libraries** — quarter math, equal-split/remainder, CSV export are stdlib; no xlsx (CVEs), no date libs beyond stdlib. | Matches the Events/Identity precedent; smaller supply-chain surface (SECURITY-10). |
| TS-9 | **Cross-unit contract reopens** (additive): Events `EventCompleted` + role stamp (DL4/DL8); Certifications `CertificationApproved.submittedAt` (DL13); Forums `ForumPostCreated`/`ReplyAccepted` schemas authored (DL10). Coordinate as deployed-service changes. | Required by the award logic; additive + backward-compatible. |
| TS-10 | **Contract v2.0.0** for `contributions-scoring/openapi.yaml` — expanded framework/rollup/leaderboard/summary/adjust shapes + new endpoints (event-points, tiers, history, tiers-earned, ledger) per `domain-entities.md` deltas; keep the deployed `GET /contributions/me` shape Member-Profiles reads. | Frozen contract was scaffold-thin; expansion is required, `/me` compatibility preserved. |

## Deliberately NOT added
- No cross-region replication (Q2=A, single-region + PITR).
- No provisioned/reserved concurrency (Q5=A, bounded on-demand + SQS buffering; awards are async).
- No Step Functions / ElastiCache / OpenSearch (rollups + GSI cover the read model).
- No real-time tier-distribution (nightly sweep, DL14); no `TierAchieved` event / notification (DL19).
