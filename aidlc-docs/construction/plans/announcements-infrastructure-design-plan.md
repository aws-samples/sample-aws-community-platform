# Infrastructure Design Plan — Unit 9: Announcements

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Announcements
Maps the logical components (`../announcements/nfr-design/logical-components.md`) to AWS resources in the existing `-data`/`-app` scaffolds (`infra/services/service-announcements-{data,app}.yaml`). Inherits Unit 1 foundation (VPC, EventBridge bus, API edge + Cognito authorizer). No blocking questions — resolved from approved artifacts + the existing scaffolds + repo precedent (Member Profiles/Events); key decisions flagged for gate review.

## Steps
- [x] 1. Analyze functional + NFR design artifacts + existing scaffolds
- [x] 2. Create this plan
- [x] 3. Evaluate all infra categories (below; resolved from artifacts — no open questions)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (n/a — decisions flagged for the gate)
- [x] 6. Generate artifacts (`infrastructure-design.md`, `deployment-architecture.md`)
- [x] 7. Present completion message
- [x] 8. Await explicit approval (approved 2026-08-07)
- [x] 9. Record approval + update aidlc-state.md

## Category evaluation (resolved from approved artifacts + scaffolds)
| Category | Resolution |
|---|---|
| **Deployment environment** | AWS, single-region multi-AZ (project default). Existing `-data`/`-app` split + per-service CodePipeline. No change to the model. |
| **Compute** | `AWS::Serverless::Function` python3.x, **256MB/15s** (scaffold value kept — light service; create's only extra work is a 1.5s time-boxed lookup). Handler switches `mock_handler.handler` → `app.handler`. No provisioned concurrency (STANDARD, non-interactive-critical). |
| **Storage** | DynamoDB `announcements-<stage>` single table — scaffold already has **PITR on, SSE on, Stream** (NFR-AN-DATA-1/2 satisfied). **One data-stack change (D-INFRA-1): add TTL on `ttl`/`expiresAt`** to the main table (scaffold only TTLs the idempotency table). Idempotency table unchanged. |
| **Indexing** | **Zero GSIs (D-INFRA-2, deferred like Member Profiles)** — the table is inherently tiny (mandatory expiry ≤90d + low write volume), so the panel active-set load, `view=mine`, CL `scope=all`, and group hide/restore are all served by a bounded, 30s-cached Scan + in-memory filter. Revisit only if volume ever warrants a by-`authorId` GSI. Avoids the Events GSI-staging deploy dance entirely. |
| **Messaging** | EventBridge: **publish** `AnnouncementPublished` (`events:PutEvents`); **consume** via a new `AWS::Events::Rule` matching `EventCreated` (source Events) + `GroupSoftDeleted`/`GroupRestored` (source Identity) → this Lambda, **with a DLQ** on the target. Scaffold has neither today. |
| **Networking** | Shared API Gateway REST + Cognito authorizer (Unit 1). All routes under the already-registered `/announcements` base path via `{proxy+}` aws_proxy → **contract changes need no api-edge regen** (incl. removing the dismiss op). Lambda in private subnets; TLS everywhere (SECURITY-07 inherited). |
| **Monitoring** | Extend scaffold `ErrorAlarm` with throttles + EventBridge consumer failures / **DLQ-depth** alarm; EMF metrics (DirectoryLookupTimeoutCount, EventConsumerLagSeconds, PanelCacheMissRate, AutoPostCount). Wired to shared `OpsAlarmTopicArn`. |
| **Shared infrastructure** | **None.** Unlike Events (which added Foundation GuardDuty + a Settings prefix filter), Announcements adds no cross-unit/Foundation resources. No `shared-infrastructure.md` change. |

## Decisions flagged for gate review
- **D-INFRA-1** — Add `TimeToLiveSpecification {AttributeName: ttl, Enabled: true}` to the **main** announcements table (`-data`). This is the one data-stack change; a plain UpdateTable (not a GSI), no staged-deploy concern. Required by NFR-AN-DATA-3 (TTL cleanup of expired announcements).
- **D-INFRA-2** — **No GSIs.** Panel/mine/moderation/hide-restore all run off a bounded, cached Scan + in-memory filter, justified by the small TTL-bounded table. Documented deferral (Member Profiles precedent), not an oversight.
- **D-INFRA-3** — Consume events with a **single `AWS::Events::Rule`** (multi-source, multi-detail-type pattern) targeting the one Lambda (router branches by event shape, same as Identity's scheduled-sync branch and Members' consumer), **with a DLQ**. `EventCreated` is high-volume-ish (every event creation) but only `announce=true` triggers work; the rule pattern can pre-filter on `detail.announce=true` to avoid waking the Lambda for non-announcing events.
- **D-INFRA-4** — IAM: replace the scaffold's broad policies with least-privilege — DynamoDB CRUD on own two tables, `events:PutEvents` on the bus, `execute-api:Invoke` scoped to Members/Groups **GET** method ARNs only (JWT-forwarded, read-only), CloudWatch Logs. No wildcards. Stream retained from scaffold but currently unused (harmless; removing it is an unnecessary table change).
- **D-INFRA-5** — Stream on the main table: **retained** from scaffold, unused by this unit (no stream consumer). Kept to avoid an unnecessary table update; flagged in case you'd prefer it removed.
