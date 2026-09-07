# Deployment Architecture — Unit 9: Announcements

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Announcements
How the unit deploys within the root-template / per-service pipeline model. Companion: `infrastructure-design.md`.

## Stack topology (unchanged model)
```
root-template.yaml
  └── service-announcements-data.yaml   (Table [+TTL], IdempotencyTable)   — deployed once, Retain
  └── service-announcements-app.yaml     (Fn app.handler, EventRule+DLQ, IAM, alarms, ApiInvokePermission)
        Params in: Stage, RestApiId, RootResourceId, EventBusName, TableName,
                   IdempotencyTableName, ApiBaseUrl, OpsAlarmTopicArn
```
- Databases are service-owned (D-data creates the announcements tables). Root passes foundation/api-edge/data outputs as **Parameters** (never `Fn::ImportValue`).
- Mock→real transition = ordinary contract-test-gated code deploy (FQ7): same function/routes/table; handler swaps to `app.handler`. Rollback = redeploy previous Lambda version (project default).

## Deployment order (this unit)
1. **`sam package`** the `-app` (bundles `services/announcements/src/` incl. `app.py`, domain modules, `nh3` wheel, `_conventions/`) with `CodeUri` rewritten to `s3://` (per `infra/tools/deploy.sh`).
2. Deploy **`-data`** update first — adds TTL on the main table (single online `UpdateTable`, no GSI staging). Verify TTL enabled before/independently of the app cutover (TTL lag is invisible due to read-time filter, so ordering is not load-bearing here).
3. Deploy **`-app`** — new handler, EventRule + DLQ, scoped IAM, alarms.
4. **API `create-deployment`** on the shared stage (serialized with other services' dev deploys).
5. **Frontend**: rebuild the SPA (adds `dompurify`, rebuilt `AnnouncementsPage` + `AnnouncementPanel`); republish via the seed custom resource — **verify the served bundle hash matches the built hash** (the repo's stale-SPA lesson).
6. Smoke test (below); update `service-mode.json` → `announcements: complete`.

## Smoke / verification checklist (deploy-time)
- `POST /announcements` as CL (community + multi-group) → 201; as UGL → target forced to led group; as Member/Administrator → 403.
- `GET /announcements?view=panel` as a member → only targeted, active, non-hidden items; expired excluded; Administrator → 403.
- `GET /announcements?view=mine` → author's list incl. Expired status; CL `scope=all` → all (paginated).
- `PUT` by non-author → 403; `DELETE` by author → 204; `DELETE` by CL on another's → 204 (moderation); by UGL on another's → 403.
- XSS body payload (`<script>`, `onerror=`, `javascript:` link) → stored sanitized (nh3); panel renders safe HTML (DOMPurify).
- Publish a test `EventCreated{announce=true}` → one auto-announcement created; redeliver → still one (idempotent). `announce=false` → none.
- Publish `GroupSoftDeleted` → that group's announcements drop from panels; `GroupRestored` → reappear.
- TTL: an item past `expiresAt` is absent from panel + count immediately (read-time filter), physically purged later.
- DLQ empty; no `[ERROR]` logs; alarms OK.

## Alarms → `OpsAlarmTopicArn`
| Alarm | Condition |
|---|---|
| `announcements-<stage>-errors` | Lambda Errors ≥ 1 / 5min (scaffold) |
| `announcements-<stage>-throttles` | Lambda Throttles ≥ 1 |
| `announcements-<stage>-consumer-dlq` | DLQ `ApproximateNumberOfMessagesVisible` ≥ 1 (an event consumer permanently failed) |
| `announcements-<stage>-directory-timeouts` | sustained `DirectoryLookupTimeoutCount` (informational — degrades gracefully; signals Identity/Members outage) |

## DR posture (inherited + PITR)
- Backup & Restore (RTO/RPO hours) + **PITR** on the announcements table (content non-reconstructible). Region loss → redeploy `-data`/`-app` from IaC + PITR restore. TTL means restored data is naturally scoped to still-relevant (non-expired) announcements.
- Multi-AZ is managed (Lambda + DynamoDB). No cross-region replication (single-region project default).

## Explicitly NOT added
No Foundation/shared-infra change (no GuardDuty, no S3, no cross-unit stack edits — unlike Events). No SQS beyond the consumer DLQ. No Step Functions, ElastiCache, WAF, provisioned concurrency, or GSIs. No api-edge regeneration.
