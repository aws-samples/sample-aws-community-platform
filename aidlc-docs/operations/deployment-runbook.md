# Deployment Runbook — AWS Community Portal

**Ownership**: Deployment is an **operator action** run via `infra/tools/deploy.sh` (policy revised 2026-08-08 — supersedes the original *"IaC only, not deployed by AI"* decision). This runbook gives the exact steps to run in **your** AWS account/region. Note: the AI assistant still declines to execute a live full-infrastructure deploy itself (creates real identities + billable resources against an account it can't verify) — the operator runs the command.

## Preconditions (all must be true before deploying)
- [ ] **All units complete** — every service either `complete` or intentionally `mock` in `service-mode.json`. (As of 2026-08-07: Forums still in progress; complete it first for a full coordinated redeploy.)
- [ ] **Frontend build green** — `cd frontend && npm ci && npm run build` succeeds. (Currently blocked by an in-progress `features/pages.tsx` edit — must be resolved.)
- [ ] **Backend suites green** — per-service `pytest` + platform contract-test gate.
- [ ] **Events↔Unit 7 event integration wired** — otherwise event/cert auto-award (US-6.3/6.5/6.17/6.18) won't flow at runtime (see "Known integration gap" below).
- [ ] **Target account/region confirmed** — `aws sts get-caller-identity` shows the account you intend.

## Build & deploy
```bash
# 1. Build the SPA and stage it for the seed Lambda
cd frontend && npm ci && npm run build
rm -rf ../platform/seed/spa && mkdir -p ../platform/seed/spa
cp -R dist/. ../platform/seed/spa/
cd ..

# 2. Validate IaC (read-only)
cfn-lint infra/**/*.yaml
sam validate --lint -t infra/root-template.yaml

# 3. Build + deploy (into YOUR account/region)
sam build -t infra/root-template.yaml
sam deploy --guided        # first time: sets stack name, region, params, confirms changeset
# subsequent deploys: sam deploy

# 4. Post-deploy: seed default framework (Unit 7, DL16)
#    The seed handler's reference-data extension point loads
#    services/contributions-scoring/seed_framework.json into the main table.
#    Verify the framework via GET /contributions/framework (as a Community Leader).
```

## Unit 7 (Contributions & Scoring) — deploy notes
- **DynamoDB GSIs** are created with the table (greenfield) — no sequential staging. Still poll `aws dynamodb describe-table` until GSI1/2/3 are `ACTIVE` before relying on the leaderboard.
- **Reserved concurrency**: AwardWorker=25, Consumer=10 (carved from the ~1000 account pool). Confirm the account limit accommodates all services' reservations.
- **Data safety**: main + idempotency tables are `Retain` + PITR — an app redeploy never touches data.
- **Rollback**: redeploy the previous `-app` version; `-data` untouched. Ledger loss → PITR restore, then rebuild rollups by replaying the ledger.

## Coordinated big-bang (Infra Q5) — cross-unit producer changes
Unit 7 consumes new/changed events; deploy these together:
- **Certifications** — `CertificationApproved.submittedAt` — ✅ DONE (2026-08-07).
- **Events** — needs `eventDate` on award/EventCompleted events + attendee **role** resolution — ⚠️ **NOT WIRED** (see below).
- **Forums** — `ForumPostCreated`/`ReplyAccepted` — dormant (Forums not yet built).

## Known integration gap (blocks event auto-award only)
Events (deployed) publishes per-earner `AttendanceRecorded`/`EventDelivered`/`EventOrganized` + a summary `EventCompleted`, but **without the event date or attendee role** that Unit 7 needs. Reconciling Events' publish model with Unit 7's consumer (incl. deciding where attendance-role resolution happens) is a focused cross-unit change with both suites run. Until done: evidence submissions, manual adjustments, leaderboards, summaries, framework, tiers all work; **event/cert-attendance auto-award does not flow at runtime**. (Certification auto-award is wired via the Certs `submittedAt` edit.)

## Status snapshot (2026-08-07)
- Unit 7: code-complete, 27 tests pass, IaC cfn-lint clean, service-mode → complete.
- Not deploy-ready system-wide: Forums pending, frontend build red (parallel edit), Events integration pending.
