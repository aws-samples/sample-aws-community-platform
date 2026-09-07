# Build and Test Report — Certification Ledger + CL/UGL Dashboard Charts

**Date**: 2026-08-12 · **Scope**: Unit 6 (Certifications) + Unit 15 (SPA). Change-scoped run.

The 7 project-wide instruction files (`build-instructions.md`, `unit-test-instructions.md`, etc.) were **not** rewritten — this change adds no new build step, service, or dependency; its only infra delta is one GSI on the existing certifications `-data` table.

## Gates

| Gate | Command | Result |
|---|---|---|
| Repo-wide tests | `make test` | **exit 0** — platform + all 8 service suites + frontend, no regressions |
| certifications unit tests | `pytest services/certifications/tests` | **all pass** (incl. 8 new in `test_ledger_and_charts.py`; 4 existing updated for BR-C5′; conftest GSI4 added) |
| Frontend tests | `npm test` | **139 pass** (incl. 11 new `certLedger.test.ts`) |
| Frontend typecheck | `tsc -b` | clean |
| Frontend build | `npm run build` | clean (bundle 649.18 kB / 200.59 kB gzip; the >500 kB chunk warning is pre-existing) |
| Contract gate | `contract-tests/run_service.py certifications` | **16/16 pass** |
| Python lint (change) | `ruff check services/certifications` | clean |
| CFN lint (change) | `cfn-lint …service-certifications-{data,app}.yaml` | clean (exit 0) |

## Pre-existing findings (NOT attributable to this change — proven)
- **`make lint` (ruff check .) reports 4 `S310` errors in `infra/tools/verify_materials_sigv4_deploy.py`.** `git status` confirms that file is **not** in this change's footprint. Pre-existing; unrelated. Ruff on the changed Python is clean.
- The working tree also carries unrelated uncommitted edits from prior sessions (`.deploy-staging/seed.yaml`, `.deploy-staging/service-contributions-scoring-app.yaml`, `frontend/src/components/AppLayout.tsx`, `frontend/src/features/AuthScreen.tsx`, `frontend/src/features/contributions/PointLedgerPanel.tsx`, `frontend/src/styles/portal.css`). This change's footprint is: `services/certifications/**`, `frontend/src/features/certifications/**` (+ CertificationsPage/CLDashboardPage/UglDashboardPage/ClaimModal), `contracts/services/certifications/openapi.yaml`, `infra/services/service-certifications-data.yaml`, `.deploy-staging/service-certifications-data.yaml`, and `aidlc-docs/**`.

## What the new backend tests cover
- Ledger listing + earned-quarter bucketing (FD-2); status filter incl. **Revoked**; UGL locked to led group (client `groupId` ignored); Member/Admin **403**.
- Rollup-driven **growth** (New permanent + Total valid-holdings with **revoke decrement**) and earned-vs-approval-quarter bucketing; **snapshot** per certification with revoke drop-off.
- Mandatory earned date on submission (BR-C5′).

## Not run (unchanged project position)
- **Integration / performance / E2E**: no such suites exist in the repo; this change adds no new cross-service coupling (ledger/stats are read-only within the certifications service).
- **Security scan / SBOM / bandit**: project-level gaps unchanged; no new dependency added (`package.json` and service `requirements` untouched).

## Manual verification outstanding (no component-test library renders React)
1. **CL** Certifications → *Certification Ledger* tab: nothing loads until a group (or "All groups") is chosen; pick a quarter; verify rows (Member, Certification Name, Certification Date, User Group, Status, Category, Expires On); toggle Active/Expired/Revoked; filter by certification and member; Prev/Next paging; **Export CSV** downloads all filtered rows (filename encodes scope + quarter).
2. **UGL** Certification Ledger tab: locked to led group (no group picker); loads current quarter.
3. **Dashboards** (CL "Community Analytics" + UGL): *Quarterly Certification Growth* (Total + New over 4 quarters, follows the CL group scope / UGL led group) and *Certification Snapshot* bar chart; verify a revoke/expire moves the Total/snapshot but not the New bar.
4. **Claim submission**: earned date is now required for every certification (including never-expiring) — submit is blocked without it.
5. **Deploy prerequisite** (Operations): clean the `certifications-<stage>` table before deploy (enforced by the `clean-cert-data-before-deploy` hook); deploy `-data` GSI4 → `wait_for_gsi` ACTIVE → `-app` → SPA.

## Status
- **Build**: success. **All automated tests**: pass. **Ready for Operations**: yes (with the manual pass + the data-clean deploy prerequisite).
