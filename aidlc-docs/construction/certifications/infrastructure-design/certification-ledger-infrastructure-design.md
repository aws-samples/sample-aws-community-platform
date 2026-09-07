# Infrastructure Design — Certification Ledger + CL/UGL Dashboard Charts

**Stage**: CONSTRUCTION → Infrastructure Design (additive to Unit 6).
**Extends**: base `certifications/infrastructure-design/infrastructure-design.md`. Companion: `certification-ledger-deployment-architecture.md`.
**Inputs**: `certification-ledger-requirements.md`, `certifications/functional-design/certification-ledger-*.md` (incl. the 2026-08-12 rollup revision), deployed `.deploy-staging/service-certifications-{data,app}.yaml`.
**Decisions**: `certification-ledger-infrastructure-design-plan.md` → Resolved section (ID-1..5 + rollup + no backfill).

All facts below verified against the current IaC. Scale basis: **30k–200k granted claims, 20–30 cert definitions, <10 groups**, development stage.

---

## 1. Resource inventory (deltas only)

### `service-certifications-data.yaml` — add **GSI4** (the only `-data` change)
The deployed table already defines GSI1/GSI2/GSI3 (all `ProjectionType: ALL`) + PITR + SSE + Stream + idempotency table. Add one GSI:

| Add | Definition | Serves |
|---|---|---|
| **GSI4 `granted-ledger`** (sparse) | pk `gsi4pk` = `GLED#<earnedQuarter>`, sk `gsi4sk` = `<earnedDate>#<claimId>`; **`ProjectionType: ALL`** (ID-1) | the **ledger** (single-quarter paginated reads + export). |

- New `AttributeDefinitions`: `gsi4pk` (S), `gsi4sk` (S). New `GlobalSecondaryIndexes` entry `GSI4`.
- **Sparse**: only granted claims (Approved/Expired/Revoked) carry the keys; Pending/Rejected/Withdrawn do not. Keys written at approval and **retained through Expired/Revoked** (functional design §6/BR-L6) — the terminal-transition write updates `status`/`expiresAt`/`revokedAt` but does not remove `gsi4pk`/`gsi4sk`.
- **Staging (F-C discipline):** DynamoDB permits one GSI change per `UpdateTable`; this is **3→4 = a single `UpdateTable`**. Still poll `DescribeTable` until GSI4 is `ACTIVE` with `infra/tools/wait_for_gsi.sh` before any query — CloudFormation reports `UPDATE_COMPLETE` while the index is still building. Since dev data is cleaned first, the build is near-instant.

**No new GSI for the charts.** The rollup counters live in the base table key space (`CROLL#<scope>`/`<quarter>` and `CROLLC#<scope>`/`<quarter>#<certId>`) and are read by `Query` on their `pk` — served by the base table, no index.

### `service-certifications-app.yaml` — code + config only
| Area | Change |
|---|---|
| **Routes** | **None in CFN.** `/certifications/ledger`, `/certifications/stats/growth`, `/certifications/stats/snapshot` ride the existing `/certifications {proxy+}` integration and the existing `ApiInvokePermission` (`/*/*`). **No api-edge regeneration, no new base path, no public surface.** |
| **IAM (DynamoDB)** | **None.** The `OwnTables` statement already grants `dynamodb:Query` on `table/${TableName}` **and** `table/${TableName}/index/*`, and `PutItem`/`UpdateItem` on the table — so GSI4 reads and the rollup-counter `ADD`s are already permitted. **No `dynamodb:Scan`** is added (there is no runtime Scan; BR-L5). |
| **Handler code** | New read endpoints (ledger + 2 stats), inline **rollup-counter maintenance** folded into the existing `transact_write_items` transitions (approve/expire/revoke), and mandatory-earned-date validation on submit. Bundled in the same package (`app.handler`). |
| **Sizing** | **Unchanged — 256 MB / 15 s** (ID-4). Charts read tiny rollups; ledger reads one page/call. |
| **Monitoring** | **Unchanged — reuse existing** `Errors`/`Throttles` (function) + `5XXError` (API) alarms (ID-5). No new alarm. Counter integrity is a transactional guarantee (BR-L10), not a runtime alarm. |
| **Events / Schedules / Buckets** | **None.** No new EventBridge rule, no Scheduler, no S3, no Stream consumer (counters are maintained inline, not via the table stream). |

### Cross-unit / shared infra
- **None.** No `api-edge.yaml`, `foundation.yaml`, `root-template.yaml`, or sibling-service template change. (Unlike the base Unit 6 build, this feature adds no new S3 prefix, event rule, or cross-stack parameter.)

---

## 2. Rollup counters — infrastructure view

- **Storage**: base certifications table (no new table, no GSI). Counter items are tiny (`{new, activated, deactivated}` numbers + a denormalized `certName`).
- **Cardinality** (worst case at the stated scale): scope/quarter = (1 community + <10 groups) × ~40 quarters ≈ ~440 items; scope/cert/quarter = ~11 scopes × ~30 certs × ~40 quarters ≈ ~13k items. Trivial storage; each an independent key.
- **Write path**: atomic `ADD` operations added to the existing transition `transact_write_items` (claim + slot + counters). Approve touches ~claim+slot+4–6 counter items (well under the 100-item transaction limit).
- **Read path**: `Query` on `CROLL#<scope>` (growth: ~40 items) or `CROLLC#<scope>` filtered to `<= quarter>` (snapshot: ~30 certs × ≤40 quarters). Covered by the existing `Query` IAM grant.
- **PITR**: counters live in the PITR-enabled table; recoverable with the rest of the data. They are also absolute-recomputable from the claims (remediation).

---

## 3. Security & compliance mapping (deltas only)
| Control | Realization |
|---|---|
| SECURITY-08 (fail-closed authz) | New ledger/stats ops added to the bundled permission matrix + `OP_AUTHZ` as **CL global / UGL group** (defer-group, like the verification queue); Members/Administrators denied; UGL `groupId` forced to led group server-side. |
| SECURITY-06 (least privilege) | **No IAM widening** — reuses existing table Query/Put/Update; no `Scan`; no new resource grant. |
| NFR-1 (no runtime Scan) | Ledger = GSI4 single-partition paginated; charts = counter Query; neither Scans. |
| NFR-4 (resiliency) | GSI4 under existing PITR; rollup counters under PITR + absolute-recomputable; additive/safe rollback. |
| Data privacy (BR-L7) | No approver identity projected/returned anywhere. |

## 4. Permission matrix / contract
- `contracts/services/certifications` OpenAPI: additive `GET /certifications/ledger`, `/stats/growth`, `/stats/snapshot`; `submitClaim.dateEarned` tightened to required (enforced in-service regardless). Additive → **no api-edge regen**.
- `contracts/platform/permissions/role-permission-matrix`: add `certification-ledger` + `certification-stats` rows (CL global, UGL group). Bundled matrix copy updated (SECURITY-08 loader).

## 5. Mock→real / service mode
Service is already `complete`. Contract regen + contract-test gate cover the additive ops; handler already `app.handler`. Rollback = redeploy previous Lambda version (GSI4 additive, safe to retain).

## Compliance summary
No blocking findings. Single `-data` change (GSI4, one `UpdateTable`); zero IAM/route/shared-infra change; no new runtime Scan; charts served by a transactionally-maintained rollup. Deployment ordering + the data-clean prerequisite are in `certification-ledger-deployment-architecture.md`.
