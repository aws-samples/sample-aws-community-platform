# Infrastructure Design — Unit 5: Forums

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Forums
Maps logical components (`../nfr-design/logical-components.md`) to AWS resources in the `-data`/`-app` CloudFormation/SAM stacks. Inherits Unit 1 foundation (VPC, EventBridge bus, API edge) + shared Cognito authorizer. Companion: `deployment-architecture.md`. Plan: `../../plans/forums-infrastructure-design-plan.md`.

## Resource inventory
| Logical component | AWS resource | Stack | Notes |
|---|---|---|---|
| Forums store | `AWS::DynamoDB::Table` (single table, pk/sk + **4 GSIs**) | `-data` | Scaffold has PITR ✓, SSE ✓, Stream ✓, Retain ✓, **0 GSIs → add 4** (ID-1=A). |
| Inverted-index (search) | **GSI3** (sparse) on same table | `-data` | PK=`gsi3pk` (`TERM#<normalized>`), SK=`gsi3sk` (`<postId>`). Sparse: only term-items carry these attributes. |
| Moderation queue index | **GSI4** (sparse) on same table | `-data` | PK=`gsi4pk` (`REPORTGROUP#<groupId>`), SK=`gsi4sk` (`<createdAt>`). Sparse: only Report items. |
| Listings index | **GSI1** on same table | `-data` | PK=`gsi1pk` (`GROUP#<groupId>`), SK=`gsi1sk` (type-prefixed: `FORUM#`, `CHANNEL#<forumId>#`). Serves browse + channel listing. |
| Post-list / thread index | **GSI2** on same table | `-data` | PK=`gsi2pk` (overloaded: `CHANNEL#<channelId>` for post-list, `POST#<postId>` for replies), SK=`gsi2sk` (`<createdAt>`). |
| Idempotency store | `AWS::DynamoDB::Table` (`eventId` HASH, TTL) | `-data` | Scaffold already correct. No change. |
| Compute | `AWS::Serverless::Function` (python3.12, **512MB/900s**, Tracing Active) | `-app` | Handler → `app.handler`. 512MB/900s for the nightly sweep (ID-2=A); API routes self-time at 29s. |
| API path | Shared API GW REST + Cognito authorizer | consumed | All ops under `/forums` `{proxy+}` — **no api-edge regen**. |
| Event publish | `events:PutEvents` on platform bus | `-app` | `ForumPostCreated`, `ForumReplyCreated`, `MemberMentioned`, `PostReported`, `PostDeleted`, `ForumChannelDeleted`. |
| Event consume | `AWS::Events::Rule` → this Fn + **DLQ** (`AWS::SQS::Queue`) | `-app` | Pattern: `GroupHardDeleted`/`GroupSoftDeleted`/`GroupRestored` (source `identity-access`). |
| Nightly sweep trigger | `AWS::Scheduler::Schedule` → this Fn | `-app` | Daily cron (e.g., `cron(0 3 * * ? *)`). Invokes with `{"source": "sweep"}` payload. |
| Mention read (cross-service) | `execute-api:Invoke` scoped to Identity `GET /members` | `-app` | JWT-forwarded; 1.5s fail-soft. |
| Observability | `AWS::CloudWatch::Alarm` (errors + throttles + DLQ depth + sweep-stall) | `-app` | Wired to `OpsAlarmTopicArn`. |

## `-data` stack changes (over scaffold)

### GSI additions (4 GSIs, ID-1=A)
```yaml
# service-forums-data.yaml — Table gains:
      AttributeDefinitions:
        # existing:
        - { AttributeName: pk, AttributeType: S }
        - { AttributeName: sk, AttributeType: S }
        # new for GSIs:
        - { AttributeName: gsi1pk, AttributeType: S }
        - { AttributeName: gsi1sk, AttributeType: S }
        - { AttributeName: gsi2pk, AttributeType: S }
        - { AttributeName: gsi2sk, AttributeType: S }
        - { AttributeName: gsi3pk, AttributeType: S }
        - { AttributeName: gsi3sk, AttributeType: S }
        - { AttributeName: gsi4pk, AttributeType: S }
        - { AttributeName: gsi4sk, AttributeType: S }
      GlobalSecondaryIndexes:
        - IndexName: GSI1
          KeySchema: [ { AttributeName: gsi1pk, KeyType: HASH }, { AttributeName: gsi1sk, KeyType: RANGE } ]
          Projection: { ProjectionType: ALL }
        - IndexName: GSI2
          KeySchema: [ { AttributeName: gsi2pk, KeyType: HASH }, { AttributeName: gsi2sk, KeyType: RANGE } ]
          Projection: { ProjectionType: ALL }
        - IndexName: GSI3
          KeySchema: [ { AttributeName: gsi3pk, KeyType: HASH }, { AttributeName: gsi3sk, KeyType: RANGE } ]
          Projection: { ProjectionType: KEYS_ONLY }   # sparse; search returns postIds → BatchGetItem
        - IndexName: GSI4
          KeySchema: [ { AttributeName: gsi4pk, KeyType: HASH }, { AttributeName: gsi4sk, KeyType: RANGE } ]
          Projection: { ProjectionType: ALL }
```

**GSI3 is KEYS_ONLY** — search queries this GSI to get `postId` sets, then BatchGetItem fetches full posts from the base table. This keeps the sparse index small (term-items project only keys). Other GSIs are ALL (listing/moderation queries need full item attributes).

**Deployment constraint**: DynamoDB allows ONE GSI create/update per `UpdateTable`. The `-data` CFN template defines all 4 GSIs at table creation — if the table **already exists** (it does in dev), adding all 4 in one stack update will **fail**. See deployment-architecture.md for the sequential deployment procedure.

### Outputs (additions)
```yaml
Outputs:
  # existing: TableName, TableArn, StreamArn, IdempotencyTableName
  # add:
  GSI1Arn: { Value: !Sub "${Table.Arn}/index/GSI1" }
  GSI2Arn: { Value: !Sub "${Table.Arn}/index/GSI2" }
  GSI3Arn: { Value: !Sub "${Table.Arn}/index/GSI3" }
  GSI4Arn: { Value: !Sub "${Table.Arn}/index/GSI4" }
```

## `-app` stack changes (over scaffold)

### Handler + config
- **Handler** → `app.handler` (from `mock_handler.handler`)
- **MemorySize** → `512` (from 256)
- **Timeout** → `900` (from 15) — sweep needs up to 10 min; API self-times at 29s
- **Parameters add**: `ApiBaseUrl` (for MentionClient base URL), `TableArn` (for scoped IAM on GSI ARNs)
- **Parameters keep**: Stage, RestApiId, RootResourceId, EventBusName, TableName, IdempotencyTableName, EnableSemanticSearch, OpsAlarmTopicArn
- **Env vars add**: `API_BASE_URL`, `MENTION_TIMEOUT_MS=1500`, `SWEEP_TIME_CAP_SECONDS=600`, `RATE_LIMIT_POST_PER_HOUR=10`, `RATE_LIMIT_REPLY_PER_HOUR=30`, `MENTION_CAP=25`
- **Env vars keep**: `TABLE_NAME`, `IDEMPOTENCY_TABLE`, `EVENT_BUS_NAME`, `ENABLE_SEMANTIC_SEARCH`

### IAM (least-privilege, replaces broad DynamoDBCrudPolicy)
```yaml
Policies:
  - Version: '2012-10-17'
    Statement:
      # Own table: CRUD + Query on all 4 GSIs
      - Effect: Allow
        Action:
          - dynamodb:GetItem
          - dynamodb:PutItem
          - dynamodb:UpdateItem
          - dynamodb:DeleteItem
          - dynamodb:Query
          - dynamodb:BatchWriteItem
          - dynamodb:BatchGetItem
        Resource:
          - !Ref TableArn
          - !Sub "${TableArn}/index/*"
      # Idempotency table: CRUD
      - Effect: Allow
        Action: [ dynamodb:GetItem, dynamodb:PutItem, dynamodb:DeleteItem ]
        Resource: !Sub "arn:aws:dynamodb:${AWS::Region}:${AWS::AccountId}:table/forums-idem-${Stage}"
      # EventBridge: publish events
      - Effect: Allow
        Action: events:PutEvents
        Resource: !Sub "arn:aws:events:${AWS::Region}:${AWS::AccountId}:event-bus/${EventBusName}"
      # Cross-service: mentionSuggest (Identity members endpoint)
      - Effect: Allow
        Action: execute-api:Invoke
        Resource: !Sub "arn:aws:execute-api:${AWS::Region}:${AWS::AccountId}:${RestApiId}/*/GET/members"
      # DLQ: send failed events
      - Effect: Allow
        Action: sqs:SendMessage
        Resource: !GetAtt ConsumerDLQ.Arn
      # Scheduler: invoke self (for sweep)
      - Effect: Allow
        Action: lambda:InvokeFunction
        Resource: !GetAtt Fn.Arn
```

No `s3:*`, `cognito-idp:*`, `ses:*`, `secretsmanager:*` (none needed — DV-4 no S3 bucket).

### EventBridge Rule (group lifecycle consumer)
```yaml
GroupLifecycleRule:
  Type: AWS::Events::Rule
  Properties:
    EventBusName: !Ref EventBusName
    EventPattern:
      source: [ "identity-access" ]
      detail-type: [ "GroupHardDeleted", "GroupSoftDeleted", "GroupRestored" ]
    Targets:
      - Id: ForumsConsumer
        Arn: !GetAtt Fn.Arn
        DeadLetterConfig:
          Arn: !GetAtt ConsumerDLQ.Arn
        RetryPolicy:
          MaximumRetryAttempts: 3
          MaximumEventAgeInSeconds: 86400
```

### EventBridge Scheduler (nightly sweep)
```yaml
SweepSchedule:
  Type: AWS::Scheduler::Schedule
  Properties:
    ScheduleExpression: "cron(0 3 * * ? *)"
    FlexibleTimeWindow: { Mode: "OFF" }
    Target:
      Arn: !GetAtt Fn.Arn
      RoleArn: !GetAtt SchedulerRole.Arn
      Input: '{"source": "scheduler", "action": "sweep"}'
```

### DLQ
```yaml
ConsumerDLQ:
  Type: AWS::SQS::Queue
  Properties:
    QueueName: !Sub "forums-consumer-dlq-${Stage}"
    MessageRetentionPeriod: 1209600  # 14 days
```

### Alarms (additions to existing ErrorAlarm)
```yaml
ThrottleAlarm:    # Lambda throttles
DLQDepthAlarm:    # ConsumerDLQ messages visible > 0
SweepStallAlarm:  # Custom metric: PURGING items remain after sweep run
```
All → `OpsAlarmTopicArn`.

### Permissions
```yaml
EventBridgeInvokePermission:
  Type: AWS::Lambda::Permission
  Properties:
    Action: lambda:InvokeFunction
    FunctionName: !Ref Fn
    Principal: events.amazonaws.com
    SourceArn: !GetAtt GroupLifecycleRule.Arn

SchedulerInvokePermission:
  Type: AWS::Lambda::Permission
  Properties:
    Action: lambda:InvokeFunction
    FunctionName: !Ref Fn
    Principal: scheduler.amazonaws.com
```

## Contract/route (no api-edge change)
All operations are under the existing `/forums` `{proxy+}` route. The contract will be updated to v2.0.0 at Code Generation (adding request/response schemas, rate-limit error codes, followerIds on events). **No `gen_api_edge.py` regeneration required** — no new base path, no new service, no route collision.

## Shared infrastructure: NO changes
- **No S3 bucket** (DV-4, no image uploads)
- **No new public base path** (all under `/forums`, authenticated)
- **No Foundation changes** (no GuardDuty, no new bucket, no VPC changes)
- **No api-edge changes** (routes already registered)

## Encryption & network (inherited)
- At rest: DynamoDB SSE (AWS-managed KMS). In transit: TLS 1.2+ to all AWS endpoints and the intra-account `execute-api` invoke (SECURITY-01).
- Lambda in private subnets; egress via NAT for EventBridge + Identity API call; Gateway VPC endpoints for DynamoDB (free, high-bandwidth) (SECURITY-07).

## Cost notes
- 4 GSIs add write/storage cost proportional to items carrying their key attributes (GSI3 is sparse KEYS_ONLY — cheapest). At community scale (~50k total items incl. search terms), cost is negligible on on-demand billing.
- 512MB Lambda is slightly more expensive per invocation than 256MB, but the sweep runs once daily and API calls are short (<1s). Net cost difference is cents/month.
- One SQS DLQ (near-zero; empty in steady state).
- No provisioned concurrency, no DAX, no OpenSearch, no S3.

## Compliance (this stage)
SECURITY-01/06/07 realized in IaC (SSE, scoped role, private networking). SECURITY-08 via forwarded-JWT + own authz. SECURITY-11 via API GW throttling + in-handler rate-limiter. SECURITY-14 alarms (errors + throttles + DLQ + sweep-stall). RESILIENCY-08/09/12 (multi-AZ managed, on-demand, PITR). SECURITY-04/09/12 remain **N/A** (JSON not HTML; no secrets; Cognito). **No blocking findings.**
