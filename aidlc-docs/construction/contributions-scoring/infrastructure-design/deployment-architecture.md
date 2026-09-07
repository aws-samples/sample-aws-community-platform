# Deployment Architecture — Unit 7: Contributions & Scoring

**Stage**: CONSTRUCTION → Infrastructure Design. Companion to `infrastructure-design.md`.

## Stack composition (D9 split)
```
root-template.yaml (Unit 1)
  └─ nests service-contributions-scoring-data.yaml   (once; Retain)
        outputs: MainTableName/Arn/StreamArn, IdemTableName, GSI name, DLQ ARNs
  └─ nests service-contributions-scoring-app.yaml    (redeployed each change)
        params in: VpcId, PrivateSubnetIds, EventBusName, RestApiId, RootResourceId,
                   OpsAlarmTopicArn, LogRetentionDays, + data-stack outputs
```

## Data-plane flows
```
AWARD (attendance/delivery/organize):
  Events marks complete → EventBridge EventCompleted
    → EventCompleted queue → AsyncConsumer(expander): read Events (GET /events/{id} + earner lists, timeout+short-circuit)
      → enqueue N per-earner jobs → per-earner queue
        → AwardWorker (reserved 25): idempotency guard → Member-role (stamped) → framework value
           → earnedDate/quarter → attribution/split → append ledger entry
    → ledger Stream → RollupMaintainer: atomic TransactWriteItems (rollup-applied#ledgerId guard + ADD)

AWARD (forum — dormant): ForumPostCreated/ReplyAccepted → consumer queue → AsyncConsumer → (post +1 / accepted-reply +2 toggle) → ledger
AWARD (cert):           CertificationApproved(submittedAt) → consumer queue → AsyncConsumer → ledger (quarter = submittedAt)

EVIDENCE:  submit (Pending, link evidence) → approve (CL/UGL) → ApiHandler writes ledger directly → Stream → rollup
ADJUST:    CL/UGL → ApiHandler writes adjustment/reversal ledger entry directly → Stream → rollup
READ:      leaderboard/top-N → GSI; my-points/summary → rollups; tier derived on read; history → ledger (member-scoped)
SWEEP:     daily Scheduler → NightlySweep → read quarter rollups + thresholds + B3 filter → write sweep aggregates (computedAt)
```

## Deployment order (within the coordinated big-bang, Q5)
1. **Contracts** — `contributions-scoring` v2.0.0; Events `EventCompleted`+role; Certs `submittedAt`; Forums `ForumPostCreated`/`ReplyAccepted`.
2. **Producers** — redeploy Events (EventCompleted + role stamp) and Certifications (submittedAt).
3. **Unit 7 `-data`** — main table (+GSI+Streams+PITR), idempotency table, DLQs. **Poll DescribeTable for GSI `ACTIVE`** before app go-live.
4. **Unit 7 `-app`** — 5 Lambdas, queues, EventBridge rules + Scheduler, alarms, routes.
5. **Seed** — install-time default framework (tiers 75/50/25/0, event points, activities all Active — DL16) into the main table.
6. **Frontend** — Unit 7 SPA screens (DL21).
7. User **undeploys + redeploys all units together** → attendance/delivery/organize + cert auto-award flow immediately; forum stays dormant until Forums is real.

## Rollback (inherited: redeploy previous version)
- `-app` rollback = redeploy previous Lambda versions/routes; `-data` untouched (Retain + PITR).
- **GSI note**: GSIs don't roll back usefully; roll back the handler, not the index.
- **DR**: ledger loss → **PITR restore** the main table, then **rebuild rollups by replaying the ledger** (rollups need no backup); idempotency table is ephemeral (TTL).

## Verification checklist (for Build & Test)
- GSI `ACTIVE` before leaderboard reads.
- Idempotency: replay an award event / reprocess a Stream record → no double-count.
- Community-wide split sums exactly (equal + earliest-join remainder).
- Late cross-quarter award lifts the closed quarter's tier on next read.
- Un-accept reverses (net zero); no double-reverse on redelivery.
- DLQ alarm fires on a poison message; queue keeps draining.
- NightlySweep staleness alarm; `computedAt` disclaimer surfaces last good run.
- `GET /contributions/me` still returns the shape Member-Profiles' fan-out reads.
