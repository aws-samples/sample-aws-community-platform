# Code Generation Summary — Certification Ledger + CL/UGL Dashboard Charts

**Date**: 2026-08-12 · **Unit 6 (Certifications) + Unit 15 (SPA)** · Brownfield (modified in place).
**Plan**: `aidlc-docs/construction/plans/certification-ledger-code-generation-plan.md` (all steps [x]).

## What shipped

### Backend (`services/certifications/`)
- **Modified `src/models.py`** — quarter/scope helpers (`quarter_of`, `earned_quarter`, `earned_date_key`, `quarter_end_date`), `SCOPE_COMMUNITY`/`scope_group`, `LEDGER_STATUSES`, and the `ledger_row` serializer (Certification Date = earned date, fallback approval date; **no approver field**, BR-L7).
- **Modified `src/repository.py`** —
  - GSI4 keys (`gsi4pk=GLED#<earnedQuarter>`, `gsi4sk=<earnedDate>#<claimId>`) set in `transition_to_approved` and **retained** through `transition_to_terminal` for Expired/Revoked (BR-L6).
  - `query_ledger_page` — single earned-quarter GSI4 partition, newest-first, fetch-until-full cursor loop (no Scan).
  - **Rollup counters** maintained inside the same `transact_write_items` as each transition (`_counter_transact_items` merges same-item deltas to respect the one-op-per-item rule): approve → `newCount`(earned q) + `activatedCount`(approval q); expire/revoke → `deactivatedCount`(change q); COMMUNITY + GROUP#<id> scopes, per-quarter and per-cert.
  - `read_scope_quarter_counters` / `read_scope_cert_counters` for the charts.
- **Created `src/ledger_service.py`** — `list_ledger` (scope resolve, filters, cursor page), `growth` (New + cumulative-valid-holdings), `snapshot` (per-cert held-as-of). CL global / UGL forced to led group.
- **Modified `src/claim_service.py`** — earned date now required for every claim (BR-C5′/DR-6).
- **Modified `src/authz.py`** + `src/permission_matrix.json` — `listLedger`/`statsGrowth`/`statsSnapshot` = CL global / UGL group (defer-group); Members/Admin denied.
- **Modified `src/app.py`** — three GET routes + dispatch + `LedgerService` wired into `Context`.
- **Regenerated** `src/mock_handler.py` / `mock_operations.json`; added `certLedger`/`certGrowth`/`certSnapshot` fixtures.
- **Tests** — `tests/test_ledger_and_charts.py` (8 new: ledger listing/bucketing, status incl. Revoked, UGL scoping, Member/Admin denial, growth New+Total+revoke-decrement, earned-vs-approval bucketing, snapshot by cert). Updated 4 existing tests for the mandatory-earned-date rule; added GSI4 to `conftest.py`.

### Contracts / IaC
- **`contracts/services/certifications/openapi.yaml`** — additive `listLedger`/`statsGrowth`/`statsSnapshot` + schemas (`LedgerRow`, `LedgerList`, `GrowthResponse`, `SnapshotResponse`); `submitClaim.dateEarned` now required. No api-edge regen.
- **`infra/services/service-certifications-data.yaml`** + `.deploy-staging/…` — GSI4 added (sparse, ProjectionType ALL). Single `UpdateTable` (3→4); no `-app` change.

### Frontend (`frontend/src/`)
- **Created** `features/certifications/certLedger.ts` (+ `.test.ts`, 11 tests) — query building, status options/label, CSV mapping.
- **Created** `features/certifications/CertificationLedgerPanel.tsx` — filters (group All|specific / UGL-locked, certification, quarter, status multi, member picker), `DataTable` cursor paging, no-load-until-filter, CSV export.
- **Created** `features/certifications/CertificationGrowthChart.tsx` + `CertificationSnapshotChart.tsx`.
- **Modified** `features/CertificationsPage.tsx` (Certification Ledger tab for CL + UGL; Pending stays default), `features/certifications/ClaimModal.tsx` (earned date always required), `features/CLDashboardPage.tsx` + `features/UglDashboardPage.tsx` (both charts, scoped).

## Verification
- certifications pytest: **all pass** (incl. 8 new); ruff clean; **contract gate 16/16**; cfn-lint clean.
- frontend: `tsc -b` clean; **139 tests pass** (incl. 11 new); `npm run build` clean.

## Known limitations / deviations
- **Email omitted from the ledger export** — it is not denormalized on the claim; including it would require a per-row cross-service lookup the ledger deliberately avoids. Export carries member name, not email. (Minor deviation from the FR-13 column wishlist.)
- **No component tests** for the panel/charts (no component-test library in the repo) — logic is covered via the extracted `certLedger.ts` helpers; the rendered panel/charts need a manual pass at Build and Test.
- **No backfill** — dev data cleaned before deploy (enforced by the `clean-cert-data-before-deploy` hook); prod backfill deferred.
