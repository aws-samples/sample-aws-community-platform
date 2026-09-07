# Deployment Architecture — Unit 5: Forums

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Forums
Deployment sequence, GSI staging, rollback, and verification. Companion: `infrastructure-design.md`.

## Deployment sequence

### Case A: Fresh table (customer install / new environment)
If the forums table does **not** exist (clean `sam deploy`), all 4 GSIs are created with the table in a single operation. The CFN template declares them all; DynamoDB creates them in parallel on a new table. No staged deployment needed.

### Case B: Existing table (dev environment — our case)
The dev table already exists with 0 GSIs. DynamoDB allows **one GSI create per UpdateTable**. The following sequence is required:

```
Step 1: Deploy -data with GSI1 only
        → wait for GSI1 status = ACTIVE (~2–5 min)
        
Step 2: Deploy -data with GSI1 + GSI2
        → wait for GSI2 status = ACTIVE
        
Step 3: Deploy -data with GSI1 + GSI2 + GSI3
        → wait for GSI3 status = ACTIVE
        
Step 4: Deploy -data with GSI1 + GSI2 + GSI3 + GSI4
        → wait for GSI4 status = ACTIVE
        
Step 5: Deploy -app (handler → app.handler, new IAM, EventBridge rule, Scheduler, alarms)
        
Step 6: Deploy SPA (frontend with Forums feature)
```

**CRITICAL**: CloudFormation reports `UPDATE_COMPLETE` while GSIs are still `CREATING` (backfilling). A Query against a `CREATING` index **returns incomplete results**. Always poll `DescribeTable` for `IndexStatus: ACTIVE` before deploying the `-app` that queries the index.

**Polling command**:
```bash
aws dynamodb describe-table --table-name forums-dev \
  --query "Table.GlobalSecondaryIndexes[?IndexName=='GSI1'].IndexStatus" \
  --output text
# Expect: ACTIVE
```

### GSI deployment order rationale
| Order | GSI | Why first |
|---|---|---|
| 1 | GSI1 (browse/channels) | Core navigation — without it, browse returns nothing |
| 2 | GSI2 (post-list/thread) | Reading posts — the next critical path after browse |
| 3 | GSI3 (search, sparse KEYS_ONLY) | Search is usable without full index (partial results acceptable during backfill) |
| 4 | GSI4 (moderation, sparse) | Moderation is a leader-only path; least critical for initial use |

### Alternative: clean + recreate (faster for dev)
Since dev data can be cleaned (the table is still on mock data), an alternative is:
1. Delete the existing table (or let CFN replace it)
2. Deploy the full -data template (all 4 GSIs created with the new table)
3. Continue with -app + SPA

This avoids the 4-step dance but loses any dev test data. Acceptable in dev (no real user data); NOT acceptable in a production environment.

## Pre-deployment prerequisites
1. **nh3 dependency**: the Lambda package must include `nh3` (native wheel). Build step: `pip install nh3 -t src/` targeting `manylinux2014_x86_64` (or use `--platform manylinux2014_x86_64 --only-binary=:all:`). Same approach as Announcements used before the Markdown pivot (but Forums keeps nh3).
2. **Contract v2.0.0**: updated `contracts/services/forums/openapi.yaml` must pass contract-test gate before deploy.
3. **Mock → real**: `service-mode.json` entry for `forums` changes from `mock` to `complete` after deployment.

## Rollback strategy

### `-data` (GSI additions)
- GSIs cannot be "rolled back" usefully — removing a GSI is a separate UpdateTable that takes minutes and the handler would fail Queries against a missing index.
- **Preferred rollback**: roll back the `-app` handler to the mock (which doesn't query GSIs). GSIs can remain harmlessly (they index nothing if the handler doesn't write GSI key attributes).

### `-app` (handler + config)
- Standard Lambda rollback: redeploy the previous code artifact (mock_handler or previous app.handler version).
- EventBridge rule + Scheduler continue to target the Lambda; the mock handler ignores events gracefully (returns 200 + no-op).

### SPA (frontend)
- Rebuild and redeploy the previous bundle via `aws s3 sync` + CloudFront invalidation.
- No `--delete` (preserves `config.json`).

## Verification checklist (post-deploy)
1. All 4 GSIs report `ACTIVE` via DescribeTable
2. `GET /forums` → 200 (browse; empty if no data)
3. `POST /forums` with valid JWT → 201 (creates forum + default channel)
4. `POST /forums/{id}/channels/{id}/posts` → 201 (creates post + search index)
5. `GET /forums/search?q=<term>` → 200 (search hits the inverted-index GSI)
6. Synthesized `GroupSoftDeleted` event → forums marked hidden (GET returns empty)
7. Synthesized `GroupRestored` → forums visible again
8. Sweep invocation (manual trigger with `{"source": "scheduler", "action": "sweep"}`) → no errors
9. DLQ depth = 0
10. SPA bundle contains Forums feature markup

## Environment config
| Param | Source | Value |
|---|---|---|
| `ApiBaseUrl` | Root stack output | `https://<RestApiId>.execute-api.<region>.amazonaws.com/<stage>` |
| `TableArn` | `-data` output | (passed by root) |
| `OpsAlarmTopicArn` | Foundation output | (passed by root) |
| `EventBusName` | Foundation output | (passed by root) |

## Root template wiring
`infra/root-template.yaml` passes the following to `service-forums-app`:
- `ApiBaseUrl` (new param — same as Events/Announcements)
- `TableArn` (new param — for GSI-scoped IAM)
- All existing params (Stage, RestApiId, RootResourceId, EventBusName, TableName, IdempotencyTableName, EnableSemanticSearch, OpsAlarmTopicArn)

No other stacks change. No api-edge regen. No Foundation changes. **Forums is self-contained.**
