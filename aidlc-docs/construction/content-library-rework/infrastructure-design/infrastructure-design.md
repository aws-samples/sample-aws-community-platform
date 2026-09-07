# Infrastructure Design — Content Library Rework

**Stage**: CONSTRUCTION → Infrastructure Design
**Unit**: content-library-rework
Maps functional design components to concrete AWS resources. Companion: `deployment-architecture.md`.

---

## Resource Inventory

| Logical Component | AWS Resource | Stack | New? |
|---|---|---|---|
| Library data store | DynamoDB `library-${Stage}`, on-demand, PITR, SSE, Retain | `service-events-data` | **new** |
| Library primary index | Table key: `pk` (hash) / `sk` (range) — `RESOURCE#<id>` / `META` | `service-events-data` | **new** |
| Library newest-first index | **GSI1** `gsi1pk=COMMUNITY` / `gsi1sk=<addedAt>#<id>`, projection ALL | `service-events-data` | **new** |
| TagRegistry singleton | Same `library-${Stage}` table, item `pk=TAGS#ALL` | `service-events-data` | **new** |
| Library idempotency store | Reuse existing `events-idem-${Stage}` table (TTL-keyed on contributionId) | `service-events-data` | exists (shared) |
| Compute | Lambda `events-${Stage}` (existing) — new routes + consumer added | `service-events-app` | modified |
| File storage | S3 Foundation community bucket, new prefix `library/<id>/` | `foundation` (shared) | prefix new |
| Malware scanning | GuardDuty Malware Protection plan (existing, covers whole bucket) | `foundation` (shared) | exists |
| Library scan-result routing | Extend existing GuardDuty EventBridge rule to include `library/` prefix | `service-events-app` | modified |
| Library S3 object events | Extend existing S3 Object Created/Deleted rule to include `library/` prefix | `service-events-app` | modified |
| Path 2 consumer | New EventBridge rule: `ContributionApproved` → Events Lambda | `service-events-app` | **new** |
| Authenticated edge — Library | API Gateway REST `/library` + `/library/{proxy+}`, Cognito authorizer | `api-edge` | **new paths** |
| Domain event publication | EventBridge platform bus (existing) | `foundation` (shared) | exists |
| Alarms | 1 new CloudWatch alarm: `library-contribution-consumer-failures` | `service-events-app` | **new** |

---

## DynamoDB — New `library-${Stage}` Table

### Key design

```
RESOURCE#<id>  /  META                → LibraryResource item
    GSI1: COMMUNITY / <addedAt>#<id>  → newest-first search (sparse: only Clean resources)

TAGS#ALL       /  META                → TagRegistry singleton
```

### Access patterns

| Pattern | Method | Key |
|---|---|---|
| Get resource by id | `GetItem` | `pk=RESOURCE#<id>`, `sk=META` |
| Search (newest first, all Clean) | `Query GSI1` | `gsi1pk=COMMUNITY`, `ScanIndexForward=False`, predicate in Lambda |
| Get TagRegistry | `GetItem` | `pk=TAGS#ALL`, `sk=META` |
| Get by materialId (auto-removal) | `Query` on table with `GSI2` (materialId → id) OR scan partition — see note below |
| Get by contributionId (idempotency) | `Query GSI3` (contributionId → id) |

**Note on materialId / contributionId lookups**: To avoid a Scan, a second sparse GSI (GSI2) indexes `materialId` for Path 1 auto-removal, and GSI3 indexes `contributionId` for Path 2 idempotency. Both are sparse — only Path 1 resources carry `materialId`, only Path 2 resources carry `contributionId`.

### Full index set

| Index | pk | sk | Sparse? | Purpose |
|---|---|---|---|---|
| GSI1 | `gsi1pk = COMMUNITY` | `gsi1sk = <addedAt>#<id>` | Yes — only `Clean` resources | Newest-first search |
| GSI2 | `gsi2pk = MAT#<materialId>` | `gsi2sk = <id>` | Yes — Path 1 only | Auto-removal lookup |
| GSI3 | `gsi3pk = CON#<contributionId>` | `gsi3sk = <id>` | Yes — Path 2 only | Idempotency check |

GSI1 is the hot path (all searches). GSI2 and GSI3 are write-time-only lookups — low read volume.

### Table definition (CloudFormation)

```yaml
LibraryTable:
  Type: AWS::DynamoDB::Table
  DeletionPolicy: Delete          # dev — change to Retain for prod
  UpdateReplacePolicy: Delete
  Properties:
    TableName: !Sub "library-${Stage}"
    BillingMode: PAY_PER_REQUEST
    PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true }
    SSESpecification: { SSEEnabled: true }
    AttributeDefinitions:
      - { AttributeName: pk,     AttributeType: S }
      - { AttributeName: sk,     AttributeType: S }
      - { AttributeName: gsi1pk, AttributeType: S }
      - { AttributeName: gsi1sk, AttributeType: S }
      - { AttributeName: gsi2pk, AttributeType: S }
      - { AttributeName: gsi2sk, AttributeType: S }
      - { AttributeName: gsi3pk, AttributeType: S }
      - { AttributeName: gsi3sk, AttributeType: S }
    KeySchema:
      - { AttributeName: pk, KeyType: HASH }
      - { AttributeName: sk, KeyType: RANGE }
    GlobalSecondaryIndexes:
      - IndexName: GSI1
        KeySchema:
          - { AttributeName: gsi1pk, KeyType: HASH }
          - { AttributeName: gsi1sk, KeyType: RANGE }
        Projection: { ProjectionType: ALL }
      - IndexName: GSI2
        KeySchema:
          - { AttributeName: gsi2pk, KeyType: HASH }
          - { AttributeName: gsi2sk, KeyType: RANGE }
        Projection: { ProjectionType: ALL }
      - IndexName: GSI3
        KeySchema:
          - { AttributeName: gsi3pk, KeyType: HASH }
          - { AttributeName: gsi3sk, KeyType: RANGE }
        Projection: { ProjectionType: ALL }
```

---

## GSI1 Sparse Index Maintenance

GSI1 (`COMMUNITY / <addedAt>#<id>`) is the search index. It must only contain `Clean` resources so the search query needs no post-scan filter for scan state.

| Event | GSI1 key action |
|---|---|
| Resource created (Link or Clean file) | Write `gsi1pk=COMMUNITY`, `gsi1sk=<addedAt>#<id>` |
| Resource created (PendingScan file) | **Omit** GSI1 keys |
| Scan result: Clean | **Add** GSI1 keys |
| Scan result: Quarantined | **Omit/remove** GSI1 keys |
| Resource edited (title/description/format/topics/url) | Rewrite item — GSI1 keys unchanged |
| Resource deleted | Item deleted — automatically leaves GSI1 |

---

## Path 2 — New `ContributionApproved` EventBridge Event

The Contributions service currently publishes `PointsAwarded` on approval but does not carry Library opt-in data. A new dedicated `ContributionApproved` event is introduced.

### Why a new event (not extending `PointsAwarded`)
`PointsAwarded` is also published for auto-tracked activities (attendance, organizing, etc.) where Library opt-in is irrelevant. A dedicated `ContributionApproved` event is cleaner and avoids the consumer having to filter on `source=evidence`.

### Event schema addition to `contracts/services/contributions-scoring/openapi.yaml`

```yaml
ContributionApproved:
  type: object
  required: [submissionId, memberId, memberName, groupId, addToLibrary]
  properties:
    submissionId:        { type: string }
    memberId:            { type: string }
    memberName:          { type: string }
    groupId:             { type: string }
    approverId:          { type: string }
    approverName:        { type: string }
    addToLibrary:        { type: boolean }
    libraryTitle:        { type: string }
    libraryDescription:  { type: string }
    libraryFormat:
      type: string
      enum: [Slides, PDF, Doc, Recording, Link]
    libraryTopics:
      type: array
      items: { type: string }
    libraryUrl:          { type: string, nullable: true }
    libraryS3Key:        { type: string, nullable: true }
```

### EventBridge rule (new, in `service-events-app.yaml`)

```yaml
ContributionApprovedRule:
  Type: AWS::Events::Rule
  Properties:
    Name: !Sub "library-contribution-approved-${Stage}"
    EventBusName: !Ref EventBusName
    EventPattern:
      detail-type: [ ContributionApproved ]
    State: ENABLED
    Targets:
      - Id: library-contribution-consumer
        Arn: !GetAtt Fn.Arn
```

---

## S3 — New `library/` Prefix

Library file uploads use the existing shared community S3 bucket under a new prefix:
`library/<resourceId>/<filename>`

### Existing rules that need extending

The existing GuardDuty scan-result EventBridge rule and S3 Object Created/Deleted rule are
currently filtered to `events/` prefix only. Both must be extended to also match `library/`:

```yaml
# GuardDuty rule — extend object key prefix filter
detail:
  s3ObjectDetails:
    objectKey:
      - prefix: "events/"
      - prefix: "library/"      # NEW

# S3 Object Created/Deleted rule — extend object key prefix filter
detail:
  object:
    key:
      - prefix: "events/"
      - prefix: "library/"      # NEW
```

The consumers (`MalwareScanConsumer`, `S3ObjectConsumer`) already branch on key prefix.
Both will be extended to handle the `library/` prefix and route to `LibraryService`.

---

## IAM — Additional Permissions for Events Lambda

New statements added to the existing Events Lambda execution role:

```yaml
- Sid: LibraryTable
  Effect: Allow
  Action:
    - dynamodb:GetItem
    - dynamodb:PutItem
    - dynamodb:UpdateItem
    - dynamodb:DeleteItem
    - dynamodb:Query
  Resource:
    - !GetAtt LibraryTable.Arn
    - !Sub "${LibraryTable.Arn}/index/*"

- Sid: LibraryFiles
  Effect: Allow
  Action: [ s3:PutObject, s3:GetObject, s3:DeleteObject ]
  Resource: !Sub "${FileShareBucketArn}/library/*"   # prefix-scoped (SECURITY-06)
```

---

## API Routes — New `/library` Paths

Added to `contracts/services/events/openapi.yaml` (additive — no api-edge regen needed,
`/events` base path already routes `{proxy+}` to the Events Lambda):

**Wait** — `/library` is a new base path, not under `/events`. This requires:
1. Adding `library` to the base-path routing table in `infra/api-edge.yaml`
2. Running `gen_api_edge.py` to regenerate with the new base path → Events Lambda

New routes:

| Method | Path | Auth | operationId |
|---|---|---|---|
| GET | /library | Cognito | searchLibrary |
| GET | /library/tags | Cognito | listLibraryTags |
| POST | /library | Cognito | addLibraryResource |
| PUT | /library/{id} | Cognito | updateLibraryResource |
| DELETE | /library/{id} | Cognito | deleteLibraryResource |

All five routes are authenticated (Cognito authorizer). No public routes for Library.

---

## Environment Variables — New Additions to Events Lambda

| Variable | Value | Purpose |
|---|---|---|
| `LIBRARY_TABLE_NAME` | `!Ref LibraryTable` | Library DynamoDB table |
| `LIBRARY_DOWNLOAD_URL_SECONDS` | `3600` | Presigned GET URL TTL (same as event materials) |
| `LIBRARY_UPLOAD_URL_SECONDS` | `900` | Presigned PUT URL TTL for Path 3 file uploads |

---

## Alarms

One new alarm added to `service-events-app.yaml`:

```yaml
LibraryContributionConsumerFailureAlarm:
  Type: AWS::CloudWatch::Alarm
  Properties:
    AlarmName: !Sub "library-${Stage}-contribution-consumer-failures"
    AlarmDescription: >-
      ContributionApproved events failing to create Library resources.
      Silent — no error propagates to the approver. Must be visible operationally.
    Namespace: !Sub "CommunityPortal/events-${Stage}"
    MetricName: LibraryContributionConsumerFailures
    Statistic: Sum
    Period: 300
    EvaluationPeriods: 1
    Threshold: 1
    ComparisonOperator: GreaterThanOrEqualToThreshold
    TreatMissingData: notBreaching
    AlarmActions: [ !Ref OpsAlarmTopicArn ]
```

---

## Stack Parameter Changes

### `service-events-data.yaml`
- Add `LibraryTable` resource (new table)
- Add `LibraryTableName` + `LibraryTableArn` outputs

### `service-events-app.yaml`
- Add `LibraryTableName` parameter
- Add `LibraryTableArn` parameter (condition-gated, same pattern as existing `TableArn`)
- Add `ContributionApprovedRule` + `ContributionApprovedRulePermission`
- Extend GuardDuty rule prefix filter (`library/`)
- Extend S3 Object rule prefix filter (`library/`)
- Add Library IAM statements
- Add `LIBRARY_TABLE_NAME` env var
- Add `LibraryContributionConsumerFailureAlarm`

### `infra/root-template.yaml`
- Pass `LibraryTableName` + `LibraryTableArn` from data stack outputs to app stack

### `infra/api-edge.yaml` (via `gen_api_edge.py`)
- Add `library` base path → `events-${Stage}` Lambda (same target as `/events`)

---

## GSI3 Removal from Events Table

The existing GSI3 (`gsi3pk` / `gsi3sk`) on the `events-${Stage}` table is removed:
- Remove `gsi3pk` and `gsi3sk` from `AttributeDefinitions`
- Remove GSI3 from `GlobalSecondaryIndexes`
- Remove all code writing `gsi3pk`/`gsi3sk` from `repository.py`

**Deployment note**: Removing a GSI is a single `UpdateTable` operation. Unlike adding a GSI,
it completes quickly (no backfill). However it is irreversible — once removed the index and
its data are gone. Since there is no live data to preserve (confirmed), this is safe.

---

## Compliance

| Rule | Status |
|---|---|
| SECURITY-01 (SSE) | ✅ `SSEEnabled: true` on library table |
| SECURITY-06 (least-privilege IAM, prefix-scoped S3) | ✅ `library/*` prefix, table ARN + index ARN only |
| SECURITY-09 (no public routes for Library) | ✅ All 5 Library routes use Cognito authorizer |
| SECURITY-13 (GuardDuty scanning for file uploads) | ✅ Extended to `library/` prefix |
| RESILIENCY-02 (PITR) | ✅ `PointInTimeRecoveryEnabled: true` |
| RESILIENCY-05 (alarm coverage) | ✅ New alarm for silent Path 2 failures |

**No blocking findings.**
