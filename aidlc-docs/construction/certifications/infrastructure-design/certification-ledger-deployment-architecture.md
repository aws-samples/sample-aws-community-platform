# Deployment Architecture — Certification Ledger + CL/UGL Dashboard Charts

**Stage**: CONSTRUCTION → Infrastructure Design (additive to Unit 6). Companion: `certification-ledger-infrastructure-design.md`.

## Change footprint
- **`-data`**: add **GSI4** (`granted-ledger`, sparse, ProjectionType ALL). One `UpdateTable` (3→4).
- **`-app`**: code only — new read endpoints, inline rollup-counter maintenance in transition writes, mandatory-earned-date validation. No IAM/route/rule/schedule/bucket change; 256 MB/15 s retained; existing alarms reused.
- **Contract**: additive OpenAPI ops + permission-matrix rows (no api-edge regen).
- **Frontend**: ledger tab + two dashboard charts + ClaimModal earned-date-required.
- **No backfill this release.**

## ⚠️ Pre-deploy prerequisite — clean existing certifications data
This feature ships **without a backfill**. Any pre-feature granted claims left in the `certifications-<stage>` table would be **invisible in the ledger** (they lack the new GSI4 keys) and would make the rollup counters **wrong** (counters start at zero and only count transitions after deploy). Since the service is in development:

1. **Delete/reset the existing `certifications-<stage>` table items** before (or as the first step of) deployment, so the ledger starts clean and counters start from a correct zero.

This prerequisite is also enforced interactively by the **`clean-cert-data-before-deploy` agent hook**, which reminds and asks for confirmation before any deploy command runs.

## Deploy sequence (ID-3)
1. **Clean existing certifications data** (prerequisite above).
2. **Deploy `-data` with GSI4** → run `infra/tools/wait_for_gsi.sh` until GSI4 is `ACTIVE`. (Single `UpdateTable`; near-instant on the cleaned/empty table. CloudFormation `UPDATE_COMPLETE` is **not** the readiness signal — the poll is.)
3. **Deploy `-app`** (new endpoints + inline counter maintenance + mandatory earned date). Safe only after GSI4 exists, so ledger reads have an index and counter writes land correctly.
4. **Ship the frontend** (ledger tab, charts, ClaimModal change).

Because data is cleaned first, there is **no drift window** — no live claims exist to be miscounted while the index builds or while code is mid-rollout.

## Rollback
- **App**: redeploy the previous Lambda version/bundle. The new endpoints simply disappear; the mandatory-earned-date validation reverts with the code.
- **GSI4**: additive — safe to leave in place on rollback (an unused sparse index costs nothing meaningful). Standing repo note applies: *GSIs do not roll back usefully; roll the handler back instead.*
- **Rollup counters**: harmless if orphaned after a rollback; re-derivable by the recompute utility if the feature is re-deployed.
- **Frontend**: redeploy previous SPA bundle (`aws s3 sync` without `--delete`, excluding `config.json`, + invalidation).

## Restore / DR
- GSI4 and the rollup counters live in the PITR-enabled, `Retain` certifications table — recovered with the rest of the service. Counters are additionally **absolute-recomputable** from the claims (the deferred recompute utility) if a restore leaves them inconsistent.

## Deferred follow-up — production backfill
If this feature is later deployed onto an environment that already holds granted claims, add a one-time operator migration before exposing the tab/charts: (1) set `gsi4pk`/`gsi4sk` on existing Approved/Expired/Revoked claims; (2) rebuild the rollup counters (absolute) from those claims. Operator-script pattern (`infra/tools/`, deploy creds, idempotent, re-runnable); one-time table Scan permitted as maintenance. Out of scope for this development-stage release.

## Verification (at Build and Test / Operations)
- GSI4 `ACTIVE`; ledger returns rows for a chosen quarter; export walks all filtered rows.
- Approvals/expiries/revocations move the rollup counters atomically; charts reconcile with the ledger.
- Members/Administrators receive 403 on ledger/stats; UGL locked to led group.
- No Scan in the runtime path (code review + IAM has no `dynamodb:Scan`).
