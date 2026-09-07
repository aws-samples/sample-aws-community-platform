# Deployment Architecture — Content Library Rework

---

## Deployment Overview

This rework modifies **three existing stacks** and adds **one new table** to an existing stack.
No new Lambda function — the Events Lambda handles all Library routes and consumers.

```
Stacks modified:
  service-events-data   → new library table + GSI3 removal from events table
  service-events-app    → new routes, new consumer rule, IAM, env vars, alarm
  api-edge              → new /library base path (regenerated via gen_api_edge.py)

Stacks unchanged:
  foundation            → GuardDuty plan already covers whole bucket
  service-contributions-scoring-app → ContributionApproved rule added here
  service-contributions-scoring-data → no change
  All other service stacks → no change
```

---

## Deployment Sequence

### Phase 1 — Data stack (Events)

**Action**: Update `service-events-data` stack.

Two changes in one stack update:
1. Add `library-${Stage}` table with 3 GSIs + PITR + SSE
2. Remove GSI3 from `events-${Stage}` table

**DynamoDB GSI note**: Adding 3 GSIs to the new library table in one `CreateTable` call is fine.
Removing GSI3 from the events table is a single `UpdateTable` — wait for `UPDATE_COMPLETE` and
confirm the index is gone via `DescribeTable` before deploying Phase 2.

**Verification**:
```bash
aws dynamodb describe-table --table-name library-dev --region us-east-1 \
  --query "Table.TableStatus"
# Expected: "ACTIVE"

aws dynamodb describe-table --table-name events-dev --region us-east-1 \
  --query "Table.GlobalSecondaryIndexes[*].IndexName"
# Expected: ["GSI1", "GSI2", "GSI4"] — GSI3 absent
```

---

### Phase 2 — Contributions service (new event)

**Action**: Update `service-contributions-scoring-app` stack + deploy contributions Lambda.

Changes:
1. `submission_service.py` — extend `_notify_decision()` to publish `ContributionApproved`
   in addition to `PointsAwarded`, carrying `addToLibrary` + library fields from approval body
2. `app.py` — extend approval endpoint to accept Library opt-in fields in request body
3. Frontend — extend `ApproveContributionModal` with `LibraryOptInSection`
4. Contract — add `ContributionApproved` schema to contributions contract

**No infrastructure change** to contributions stack — the EventBridge rule for
`ContributionApproved` is in the Events app stack (Phase 3), not contributions.

---

### Phase 3 — Events app stack

**Action**: Update `service-events-app` stack.

Changes:
1. New `ContributionApprovedRule` EventBridge rule → Events Lambda
2. Extend GuardDuty rule prefix filter to include `library/`
3. Extend S3 Object rule prefix filter to include `library/`
4. New IAM statements (library table + `library/*` S3 prefix)
5. New env vars (`LIBRARY_TABLE_NAME`, etc.)
6. New alarm (`library-contribution-consumer-failures`)
7. New Lambda code: `library_service.py`, `library_repository.py`, `library_consumers.py`,
   extended `app.py`, `material_service.py`, `event_service.py`, `consumers.py`

**Verification**:
```bash
# Invoke library search (expect 400 — search-first, no query params)
aws lambda invoke --function-name events-dev \
  --payload '{"httpMethod":"GET","path":"/library","queryStringParameters":{}}' \
  /tmp/out.json && cat /tmp/out.json
# Expected: 400 (search-first gate) or 200 with empty items

# Invoke tags endpoint
aws lambda invoke --function-name events-dev \
  --payload '{"httpMethod":"GET","path":"/library/tags","queryStringParameters":{"prefix":"ser"}}' \
  /tmp/out.json && cat /tmp/out.json
# Expected: 200 {"tags": []}  (empty — no resources yet)
```

---

### Phase 4 — API Edge

**Action**: Run `gen_api_edge.py`, deploy updated `api-edge` stack.

Add `library` to the base-path routing table so `/library` and `/library/{proxy+}` route to
`events-${Stage}` Lambda with Cognito authorizer.

```bash
python3 infra/tools/gen_api_edge.py
# Verify library routes appear in generated api-edge.yaml
grep "library" infra/api-edge.yaml

# Deploy
bash infra/tools/deploy.sh   # or targeted stack update
```

---

### Phase 5 — Frontend

**Action**: Build and deploy SPA.

Changes:
1. New `ContentLibraryPage.tsx` + `TopicTagInput.tsx` + updated modal components
2. Remove `ContentLibraryTab` from `EventsPage.tsx`
3. Add `/content-library` route in `App.tsx`
4. Add nav item in sidebar

```bash
cd frontend && npm run build
aws s3 sync dist/ s3://<spa-bucket>/ --exclude config.json
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```

---

## Rollback Plan

| Phase | Rollback |
|---|---|
| Phase 1 (data) | Re-add GSI3 to events table (one `UpdateTable`); delete library table |
| Phase 2 (contributions) | Redeploy previous contributions Lambda zip; revert contract |
| Phase 3 (events app) | Redeploy previous events Lambda zip; revert app stack (remove rule, IAM, alarm) |
| Phase 4 (api-edge) | Revert `api-edge.yaml` to previous version, redeploy |
| Phase 5 (frontend) | Sync previous SPA bundle; invalidate CloudFront |

GSI3 re-addition requires backfill. Since there is no live data to preserve (confirmed by user),
the table can be left empty after rollback — the GSI3 sparse index will self-populate as new
materials are written.

---

## Key Design Decisions Recorded

| # | Decision |
|---|---|
| D1 | Library table is separate from events table — all 4 GSI slots on events table are occupied |
| D2 | Events Lambda handles Library routes — no new Lambda function (consistent with existing pattern) |
| D3 | `ContributionApproved` is a new event, not an extension of `PointsAwarded` — cleaner consumer |
| D4 | `/library` is a new API Gateway base path — requires `gen_api_edge.py` re-run |
| D5 | GSI3 removal from events table is safe — no live data, single `UpdateTable` operation |
| D6 | GuardDuty and S3 rules extended (prefix added) rather than new rules created — avoids idempotency burn on wrong-prefix events |
| D7 | Library files under `library/` prefix in shared bucket — consistent with `events/` and `certifications/` pattern; prefix-scoped IAM |
