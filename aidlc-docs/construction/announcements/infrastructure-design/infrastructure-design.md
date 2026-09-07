# Infrastructure Design — Unit 9: Announcements

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Announcements
Maps logical components (`../nfr-design/logical-components.md`) to AWS resources in the `-data`/`-app` CloudFormation/SAM stacks. Inherits Unit 1 foundation (VPC, EventBridge bus, API edge) + the shared Cognito authorizer. Companion: `deployment-architecture.md`. Plan: `../../plans/announcements-infrastructure-design-plan.md`.

## Resource inventory
| Logical component | AWS resource | Stack | Notes |
|---|---|---|---|
| Announcement store | `AWS::DynamoDB::Table` (single table, pk/sk) | `-data` | Scaffold already: **PITR on**, SSE (KMS-managed), Stream NEW_AND_OLD_IMAGES, `Retain`. **Add TTL on `ttl`** (D-INFRA-1). **No GSIs** (D-INFRA-2). |
| Idempotency store | `AWS::DynamoDB::Table` (`eventId` HASH, TTL) | `-data` | Unchanged from scaffold. |
| Compute | `AWS::Serverless::Function` (python3.x, 256MB/15s, Tracing Active) | `-app` | Handler `mock_handler.handler` → **`app.handler`**. No provisioned concurrency. |
| Panel/API path | Shared API GW REST + Cognito authorizer (Params `RestApiId`,`RootResourceId`) | consumed from api-edge | All ops under `/announcements` `{proxy+}` — **no api-edge regen** for contract changes. |
| Event publish | `events:PutEvents` on platform bus (Param `EventBusName`) | `-app` | `AnnouncementPublished`. Scaffold lacks this permission → **add**. |
| Event consume | `AWS::Events::Rule` on the platform bus → this `Fn`, **+ DLQ** (`AWS::SQS::Queue`) + `AWS::Lambda::Permission` | `-app` | Pattern: `EventCreated` (source `events`, `detail.announce=true`) + `GroupSoftDeleted`/`GroupRestored` (source `identity-access`). New (D-INFRA-3). |
| Directory read (author/group name) | `execute-api:Invoke` IAM, scoped to Members `GET /members/{id}` + Groups `GET /groups/{id}` method ARNs on the shared `RestApiId` | `-app` | JWT-forwarded, read-only; 1.5s fail-closed (NFR-AN-REL-1). Same-account invoke — no new API resource. |
| Client sanitizer | `dompurify` (SPA build, Unit 15) | frontend | NFR-AN-SEC-2. Not an AWS resource. |
| Observability | `AWS::CloudWatch::Alarm` (errors — existing; **add** throttles + consumer/DLQ-depth) + EMF metrics | `-app` | Wired to shared `OpsAlarmTopicArn`. |

## `-data` stack change (over scaffold) — the only one
```yaml
# service-announcements-data.yaml — main Table gains:
      TimeToLiveSpecification: { AttributeName: ttl, Enabled: true }
```
- A plain `UpdateTable` (not a GSI) → no staged-deployment concern (unlike Events' 4-GSI dance). PITR/SSE/Stream/Retain already present. Idempotency table unchanged.
- **Deployment note**: enabling TTL on a table that already exists in dev is a single online update; expired items are purged by the TTL sweep (up to ~48h lag) — the read-time filter (BR-6) is the authoritative "not shown" mechanism, so TTL lag is invisible to users.

## `-app` stack changes (over scaffold)
- **Handler** → `app.handler`.
- **Parameters add**: `ApiBaseUrl` (for the DirectoryClient base URL — same pattern as Members/Events). `RestApiId` already present (used for `ApiInvokePermission` + the new `execute-api` resource ARNs).
- **Env vars add**: `API_BASE_URL` (DirectoryClient), `ACTIVE_SET_CACHE_TTL_SECONDS=30`, `DIRECTORY_TIMEOUT_MS=1500`. Keep `TABLE_NAME`, `IDEMPOTENCY_TABLE`, `EVENT_BUS_NAME`.
- **IAM** (D-INFRA-4) — replace broad scaffold policies with least-privilege (SECURITY-06):
  - `dynamodb:{GetItem,PutItem,UpdateItem,DeleteItem,Query,Scan}` on the announcements table ARN; same CRUD on the idempotency table ARN. No GSI actions (none exist).
  - `events:PutEvents` on the platform bus ARN only.
  - `execute-api:Invoke` on exactly the Members `GET /members/*` and Groups `GET /groups/*` method ARNs of the shared `RestApiId` — read-only, resource-scoped, no wildcard on the API.
  - `sqs:SendMessage` on the DLQ ARN (for the event target); CloudWatch Logs on own log group.
  - No `cognito-idp:*`/`ses:*`/`secretsmanager:*`/`s3:*` (none needed).
- **`AWS::Events::Rule`** (new) — event pattern:
  ```json
  { "source": ["events", "identity-access"],
    "detail-type": ["EventCreated", "GroupSoftDeleted", "GroupRestored"] }
  ```
  (auto-post work is further gated in-handler on `detail.announce=true`; a `detail.announce:[true]` content filter on the rule is applied so non-announcing `EventCreated` never wakes the Lambda — D-INFRA-3.) Target = `Fn` with a **DLQ** (SQS) + `RetryPolicy`; `AWS::Lambda::Permission` for `events.amazonaws.com`.
- **Alarms** — keep `ErrorAlarm`; add Lambda `Throttles`, EventBridge target failures, and a **DLQ `ApproximateNumberOfMessagesVisible`** alarm (a message in the DLQ means an event consumer permanently failed). All → `OpsAlarmTopicArn`.
- No provisioned concurrency / alias block.

## Contract/route change (executed at Code Generation; documented here)
`contracts/services/announcements/openapi.yaml` → **v2.0.0**: structured `target`, mandatory `expiresAt`, `view`/`scope` params on `listAnnouncements`, extended `Announcement` schema, and **removal of `dismissAnnouncement` (`POST /announcements/{id}/dismiss`)** (dismissal is client-side, BR-11). Because every op is under the `/announcements` `{proxy+}` aws_proxy route, **no `gen_api_edge.py`/api-edge regeneration is required** — the removed dismiss path simply stops being handled by the real router (returns 404 via the router, not a distinct API GW resource). New event schema `published-events/AnnouncementPublished.v1.json`.

## IAM execution role (least privilege — SECURITY-06)
Small footprint (no credentials held, like Member Profiles):
- DynamoDB CRUD on own table + idempotency table only.
- `events:PutEvents` on the platform bus only.
- `execute-api:Invoke` on Members/Groups GET method ARNs only (read-only, JWT-forwarded — downstream `authz.py` enforces unchanged; no service credential minted).
- `sqs:SendMessage` on the consumer DLQ.
- CloudWatch Logs on own log group. No wildcard actions/resources.

## Encryption & network (inherited)
- At rest: DynamoDB SSE (AWS-managed KMS). In transit: TLS 1.2+ to all AWS endpoints and the intra-account `execute-api` invoke (SECURITY-01).
- Lambda in private subnets; egress to the shared API Gateway via the same path other services already use; VPC endpoints for DynamoDB/EventBridge as per foundation (SECURITY-07).

## Cost notes
- No provisioned concurrency; on-demand DynamoDB; **no GSIs** (lowest storage/write cost of the units so far). TTL actively shrinks the table. `execute-api:Invoke` calls are ordinary requests on the already-provisioned shared API. One small SQS DLQ (near-zero cost, empty in steady state).

## Compliance (this stage)
SECURITY-01/06/07 realized in IaC (KMS inherited, scoped role, private networking inherited); SECURITY-02 at edge (Unit 1); SECURITY-08 via forwarded-JWT read + own authz.py; SECURITY-14 alarms incl. DLQ depth. RESILIENCY-08/09/12 (multi-AZ managed, on-demand scaling, PITR + TTL). SECURITY-04/12 remain **N/A** (JSON not HTML; no credentials). **No blocking findings.**
