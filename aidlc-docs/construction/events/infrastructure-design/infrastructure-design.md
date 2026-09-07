# Infrastructure Design — Unit 4: Events

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Events
Maps the logical components from `../nfr-design/logical-components.md` to concrete AWS resources. Companion: `deployment-architecture.md`. Plan: `../../plans/events-infrastructure-design-plan.md`.

## Resource inventory

| Logical component | AWS resource | Stack | New? |
|---|---|---|---|
| Event store | DynamoDB `events-<stage>`, on-demand, PITR, SSE, Retain, stream `NEW_AND_OLD_IMAGES` | `service-events-data` | exists |
| Scope-date index | **GSI1** `gsi1pk` / `gsi1sk`, projection ALL | `service-events-data` | **new** |
| User-RSVP index | **GSI2** `gsi2pk` / `gsi2sk`, projection ALL | `service-events-data` | **new** |
| Publishable-content index (sparse) | **GSI3** `gsi3pk` / `gsi3sk`, projection ALL | `service-events-data` | **new** |
| Due-schedule index (sparse) | **GSI4** `gsi4pk` / `gsi4sk`, projection **ALL** | `service-events-data` | **new** |
| Idempotency store | DynamoDB `events-idem-<stage>`, `eventId` hash, TTL | `service-events-data` | exists |
| Compute | Lambda `events-<stage>`, python3.12, **512 MB**, **60 s**, Tracing Active, handler `app.handler` | `service-events-app` | modified |
| Materials + external uploads | S3 Foundation community bucket, prefixes `events/<eventId>/materials/` and `events/<eventId>/uploads/` | `foundation` (shared) | exists |
| Malware scanning | `AWS::GuardDuty::MalwareProtectionPlan` on the community bucket + its service role | `foundation` (shared) | **new** |
| Scan-result consumption | EventBridge rule on GuardDuty scan-result events → Events Lambda | `service-events-app` | **new** |
| Object metadata consumption | EventBridge rule on S3 Object Created/Deleted, **prefix-filtered to `events/`** → Events Lambda | `service-events-app` | **new** |
| Group-event consumption | EventBridge rule on `GroupSoftDeleted` (platform bus) → Events Lambda | `service-events-app` | **new** |
| ~~Reminder sweep~~ | ~~`AWS::Scheduler::Schedule`, `rate(5 minutes)`~~ | `service-events-app` | **DELETED 2026-08-27** |
| Domain event publication | EventBridge platform bus, 9 detail-types | `foundation` (shared) | exists |
| Authenticated edge | API Gateway REST, `/events` + `/events/{proxy+}`, Cognito authorizer | `api-edge` (generated) | exists |
| **Public edge** | API Gateway REST, `/event-uploads` + `/event-uploads/{proxy+}`, **no authorizer**, usage-plan throttled | `api-edge` (generated) | **new — see F1** |
| Alarms | 7 CloudWatch alarms → Foundation ops SNS topic | `service-events-app` | modified |

## Index definitions

| Index | gsiNpk | gsiNsk | Written when | Removed when |
|---|---|---|---|---|
| GSI1 | `SCOPE#<groupId\|COMMUNITY>#<status>` | `<startsAt>` | always on an Event item | never (status change rewrites it) |
| GSI2 | `USER#<userId>` | `RSVP#<startsAt>#<eventId>` | always on an RSVP item | never |
| GSI3 | `CONTENT#<groupId\|COMMUNITY>` | `<eventStartsAt>#<materialId>` | material becomes `Clean` **and** event is `Completed` | quarantined, removed, or event leaves `Completed` |
| GSI4 | `DUE#Pending` | `<dueAt>` | schedule record created | published or skipped |

GSI3 and GSI4 are sparse by design (J2): the attribute is absent, so the item is simply not in the index.

**GSI4 is unused as of 2026-08-27.** It served the reminder sweep, which was removed with
US-2.2/2.10. The index is still deployed and now permanently empty; dropping it is staged as its
own change because index drops are irreversible. The projection debate below is therefore moot
and kept only as a record.

*Correction (2026-08-05, during deployment):* GSI4 was specified here as `KEYS_ONLY` plus
`eventId`, on the assumption that the sweep only needed enough to load the event. That was wrong
— the sweep read `id`, `status` and `dueAt` off each returned record, and `id` was not a key
attribute (the table key was `SCHED#<id>`), so a KEYS_ONLY projection would have returned rows
the sweep could not use. The template correctly used `ALL`; this document was the thing that was
wrong, and was corrected rather than the template changed.

## IAM (least privilege, SECURITY-06)

The Events execution role gets:

| Statement | Actions | Resource |
|---|---|---|
| Table access | DynamoDB CRUD + Query on indexes | `events-<stage>` and `events-<stage>/index/*` |
| Idempotency | DynamoDB CRUD | `events-idem-<stage>` |
| Publish | `events:PutEvents` | the platform bus ARN only |
| Materials broker | `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` | **`${FileShareBucketArn}/events/*`** — prefix-scoped, not `/*` |
| Materials listing | `s3:ListBucket` | bucket ARN, conditioned on `s3:prefix = events/*` |
| Point-value read | `execute-api:Invoke` | the single Contributions method ARN |

No wildcard actions, no wildcard resources. The prefix scoping matters: Settings holds `s3:DeleteObject` on the same bucket at `/*`, so without a prefix condition the two services could delete each other's objects. Events is deliberately narrower.

## Cross-cutting findings that change other stacks

### F1 — New public base path `/event-uploads` (Unit 1 files)
The functional design's `POST /public/event-uploads/{token}` is not deployable: `gen_api_edge.py` maps one base path to one service and hard-fails on collision, and `/public` already belongs to Settings. Resolution:

1. Contract path becomes `POST /event-uploads/{token}` (Events' own base path).
2. `gen_api_edge.py` — add `"event-uploads"` to `PUBLIC_BASES`.
3. Regenerate `api-edge.yaml` (adds 2 unauthenticated paths + CORS mocks).

This is the portal's **second unauthenticated base path**. Its entire attack surface is one POST that mints a single-object presigned PUT after validating a hashed token, expiry, revocation, and upload count. No GET, no list, no delete.

### F3 — Key-prefix filters on both S3 rules (Unit 11 file)
Foundation enables EventBridge notifications bucket-wide, and Settings' rule filters only on bucket name. Once Events writes to the same bucket, Settings receives every Events object event. Both rules gain a prefix filter:

```yaml
# events
detail:
  bucket: { name: [ !Ref FileShareBucketName ] }
  object: { key: [ { prefix: "events/" } ] }
```

Settings' rule gets the complementary anything-but/own-prefix filter. Without this, Settings' consumer burns an idempotency record per Events upload and its logs stop being a reliable signal for its own feature.

### Shared infrastructure changes (Foundation)
- **GuardDuty Malware Protection plan** on the community bucket, with quarantine tagging and its service role. Placed on the bucket owner so protection does not depend on which consumer deployed last, and so Settings' uploads are covered too.
- **Lifecycle rules** for `events/*/uploads/` (expire at 180 days) and abort-incomplete-multipart at 7 days.
- Bucket versioning and public-access-block already in place; no change.

## Environment variables (Events Lambda)

| Variable | Source |
|---|---|
| `TABLE_NAME`, `IDEMPOTENCY_TABLE` | data stack outputs |
| `EVENT_BUS_NAME`, `EVENT_BUS_ARN` | Foundation |
| `FILE_SHARE_BUCKET` | Foundation |
| `API_BASE_URL` | root template (for the Contributions fan-out) |
| `PUBLIC_UPLOAD_BASE_URL` | root template (to build the recipient link) |
| `MS_TEAMS_ENABLED` | defaults false; real value read from Settings at runtime |
| `MAX_MATERIAL_BYTES` | `524288000` (500 MB) |
| `MAX_OCCURRENCES` | `104` |
| `MAX_ATTENDEES_PER_APPLY` | `1000` |

## Alarms (P-OBS-1)

| Alarm | Metric |
|---|---|
| `events-<stage>-errors` | Lambda Errors ≥ 1 / 5 min (exists) |
| `events-<stage>-throttles` | Lambda Throttles ≥ 1 |
| `events-<stage>-public-upload-4xx` | custom metric — token probing |
| `events-<stage>-authz-failures` | custom metric — 403 rate |
| `events-<stage>-malware-detected` | custom metric from the scan-result consumer |
| `events-<stage>-fanout-failures` | custom metric — Contributions degrade active |

All route to Foundation's `OpsAlarmTopic`. The last four cover conditions where the API looks healthy while something is wrong.

## Mock → real transition
1. Data stack: add GSIs in four staged deployments (F2).
2. App stack: handler → `app.handler`, memory/timeout raised, IAM statements, three rules, one schedule, four alarms.
3. Contract: additive operations + the `/event-uploads` path; regenerate the mock, then `gen_api_edge.py`.
4. Contract-test gate must pass before the handler switch is deployed.
5. `service-mode.json` → `events: complete`.
6. Root template: pass `FileShareBucketName`/`Arn`, `ApiBaseUrl`, `PublicUploadBaseUrl` to the Events app stack (Settings already receives the first two — same wiring pattern, no `Fn::ImportValue`, per D1).

## Compliance re-verification
SECURITY-01 (table + bucket SSE, TLS enforced), SECURITY-02 (API GW logging, inherited), SECURITY-06 (prefix-scoped S3, single-method invoke, no wildcards), SECURITY-07 (private subnets, inherited), SECURITY-09 (public access blocked, no default credentials), SECURITY-11 (usage-plan throttling on the public route), SECURITY-13 (GuardDuty scanning; create/revoke audited), SECURITY-14 (7 alarms, 90-day retention) — **all compliant**. SECURITY-04/12 **N/A**.
RESILIENCY-02/11/12 (PITR + on-demand backups + S3 versioning), RESILIENCY-05/07 (alarms, tracing), RESILIENCY-08 (managed multi-AZ), RESILIENCY-09 (on-demand, quotas identified) — **all compliant**.

**No blocking security or resiliency findings.** The three findings above are deployability and cross-unit-boundary issues, not baseline violations.
