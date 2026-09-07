# Deployment Architecture — Unit 6: Certifications

## Runtime topology (text diagram)

```
                       +--------------------------------------+
                       |        API Gateway (shared)          |
                       |  /certifications/* (Cognito auth'd)  |
                       +------------------+-------------------+
                                          |
                                          v
+---------------------+     +--------------------------------+     +----------------------+
| EventBridge bus     |     |  certifications-<stage> Lambda |     | DynamoDB             |
|  MemberLeftGroup    +---->|  app.handler (3 branches)      +---->|  certifications table |
|  MemberRemoved      |     |   HTTP | events | scheduler    |     |  (+GSI1/2/3, PITR)   |
|  GuardDuty verdicts +---->|                                |     |  idem table (TTL)    |
+---------------------+     |  publishes 5 cert events ------+--+  +----------------------+
                            +---+------------+---------------+  |
                                |            |                   +--> EventBridge bus
              presign POST/GET  |            | copy-on-Clean          (Contributions/
                                v            v                         Notifications later)
                   +------------------+   +------------------+
                   | FileShareBucket  |   | SpaBucket        |
                   | certifications/  |   | badges/* (public |
                   |  evidence/ badges/|  |  via CloudFront) |
                   | (GuardDuty plan) |   +------------------+
                   +------------------+
    Schedulers: expiry daily 06:00 UTC · scan-watchdog rate(15 min)
    Sync REST out: Identity GET /groups* (submit only, fail-closed)
```

## Deployment order (F-C discipline)

Pre-step (per the RUN-AND-DEPLOY rule): build SPA → `rsync --delete` into `platform/seed/spa/` → `infra/tools/deploy.sh` handles packaging/upload; **verify the served bundle hash, not the stack status**.

1. **Contracts first**: openapi v2.0.0 + 5 event schemas + permission-matrix edit (D7) → regen mock + api-edge check (no-op expected) → contract gate green on the regenerated mock.
2. **`-data` staged ×3** (one GSI per UpdateTable): GSI1 member-claims → wait ACTIVE → GSI2 pending-queue → wait ACTIVE → GSI3 sweep → wait ACTIVE. `DescribeTable` polling via `wait_for_gsi.sh`; table is empty in dev (mock never wrote) so expect minutes. **Do not proceed on UPDATE_COMPLETE alone.**
3. **Cross-unit edits in one root deploy**: settings-app rule exclusion list (F-A) + events-app scan-rule prefix filter (F-B) + root-template param wiring. These are additive filters — deploying them BEFORE certifications writes any object means neither sibling ever sees a certifications event.
4. **`-app` real handler**: app.handler + IAM + 2 rules + 2 schedules + alarms + env vars.
5. **Seed/SPA republish** (frontend rebuild, D11) — no seed code change (F-D).
6. **service-mode.json** → certifications `complete` after the contract gate passes against the real service.

## Verification checklist (post-deploy)
1. Contract suite vs deployed real service (all v2.0.0 ops).
2. GSIs ACTIVE ×3 (`DescribeTable`), sample queries return (queue empty-OK).
3. AuthZ probes: Admin → 403 on `GET /certifications` (D7 live proof); Member submit → 201; UGL foreign-group decision → 403/404.
4. Upload path: presigned POST rejects a 6 MB object (door proof, N2) and a `.svg` content-type; accepted PDF lands under `certifications/evidence/` with a unique key.
5. **EICAR test file** upload → verdict → claim flagged Quarantined, never reviewable — the only real proof the scan gate works end-to-end (Unit 4 precedent).
6. Badge upload → Clean → object appears under `SpaBucket/badges/` → CloudFront URL renders; SPA redeploy → badge object still present (F-D proof).
7. Scheduler proofs: invoke Fn with `{"job":"expiry"}` and `{"job":"scanwatch"}` payloads → clean runs + `SweepRunOutcome`/`PendingScanAgeMinutes` metrics visible.
8. Cross-unit noise check: put/delete a `certifications/*` object → **Settings and Events logs show zero consumer invocations** (F-A/F-B live proof); and an `events/*` object does not invoke certifications' consumer.
9. Membership auto-reject: publish a synthetic `MemberLeftGroup` → pending claim flips Rejected with the system reason; replay the same envelope id → no double processing.
10. Alarms wired: force one `EventPublishFailure` metric datum → alarm transitions.

## Rollback
- App defects → redeploy previous Lambda version (routes/table unchanged).
- **GSIs don't roll back usefully** — never delete a backfilled index to "undo"; roll the handler back instead (F2 note).
- Cross-unit rule edits are pure filters — reverting them re-widens sibling consumers but breaks nothing.
- DynamoDB PITR + S3 versioning; restore skew: a table restore rewinds claim rows but not S3 objects — evidence keys in restored rows may point at later-deleted objects (orphans are re-uploadable via the quarantine path) and vice versa; runbook note carried from Events.

## Cost deltas (dev)
3 GSIs on a near-empty on-demand table (~nil) · 2 Scheduler schedules (~nil) · GuardDuty scan per-GB on certifications prefixes (5 MB cap × low volume — cents) · SPA-bucket badge storage (KBs–MBs). No new cost line comparable to Unit 4's GuardDuty introduction.
