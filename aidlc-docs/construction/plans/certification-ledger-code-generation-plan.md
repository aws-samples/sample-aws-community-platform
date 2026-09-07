# Code Generation Plan — Certification Ledger + CL/UGL Dashboard Charts

**Unit**: Unit 6 (Certifications) + Unit 15 (SPA) · **Brownfield** — modify existing files in place.
**Inputs (approved)**: requirements `certification-ledger-requirements.md`; functional design `certifications/functional-design/certification-ledger-*.md` (incl. 2026-08-12 rollup revision); infrastructure design `certifications/infrastructure-design/certification-ledger-*.md`.
**This plan is the single source of truth for Code Generation.** Part 2 executes these steps in order, marking each [x] on completion.

## Context & key decisions
- **Ledger** → new **GSI4** (`GLED#<earnedQuarter>` / `<earnedDate>#<claimId>`, ProjectionType ALL), single-quarter paginated reads (fetch-until-full cursor loop).
- **Charts** → **maintained rollup counters** in the base table (`CROLL#<scope>`/`<quarter>`, `CROLLC#<scope>`/`<quarter>#<certId>`), updated **inside the existing transactional transition writes** — centralized in `repository.transition_to_approved` / `transition_to_terminal` so verification/revocation/expiry all get it for free.
- **Mandatory earned date** on submit (BR-C5′).
- **No backfill** (dev data cleaned before deploy — enforced by the `clean-cert-data-before-deploy` hook).
- Scope: CL global / UGL forced to led group; Members/Admin denied.
- No api-edge regen (additive under `/certifications {proxy+}`); no new IAM (existing Query/Put/Update + no Scan); keep 256 MB/15 s; reuse existing alarms.

---

## Backend — `services/certifications/src/` (+ contracts, infra)

### Step 1 — Contracts (additive) — FR-4..17, DR-7
- [x] `contracts/services/certifications/openapi.*`: add `GET /certifications/ledger` (params `quarter?,groupId?,certId?,status?,memberId?,limit?,cursor?` → `{items:LedgerRow[],cursor?}`), `GET /certifications/stats/growth` (`quarters?,groupId?` → `{items:[{quarter,total,new}],scope}`), `GET /certifications/stats/snapshot` (`quarter?,groupId?` → `{items:[{certId,certName,count}],quarter,scope}`); mark `submitClaim.dateEarned` **required**. Define `LedgerRow` (no approver field, BR-L7). Version bump (minor).
- [x] `contracts/platform/permissions/role-permission-matrix.v1.json`: add CL `view certification-ledger`/`certification-stats` (global) and UGL (group) rows.

### Step 2 — Domain helpers `models.py` — DR-1, BR-L2/L9
- [x] Add `earned_quarter(claim)` (quarter of `dateEarned` else `decidedAt`), `earned_date(claim)`, `quarter_of(iso)`, `quarter_end_date(quarter)`, and `LEDGER_STATUSES = {Approved, Expired, Revoked}`.
- [x] Add scope/counter key constants (`SCOPE_COMMUNITY = "COMMUNITY"`, `scope_group(id)`), counter pk builders (`CROLL#`, `CROLLC#`).
- [x] Add `ledger_row(item)` serializer (projected fields incl. `certificationDate = dateEarned or decidedAt`; **no approver**).

### Step 3 — Repository: granted index + ledger read `repository.py` — DR-1/2, BR-L5/L6
- [x] `create_claim`: (claims are created Pending → no GSI4 keys yet; unchanged except confirm no gsi4 on Pending).
- [x] `transition_to_approved`: additionally `SET gsi4pk = GLED#<earnedQuarter>, gsi4sk = <earnedDate>#<claimId>` and ensure projected fields present.
- [x] `transition_to_terminal`: for `Expired`/`Revoked` **retain** gsi4 keys (verify the REMOVE list is only gsi2/gsi3); status/expiresAt/revokedAt already updated.
- [x] New `query_ledger_page(quarter, *, predicate, limit, cursor)` — GSI4 partition `GLED#<quarter>`, `ScanIndexForward=False`, fetch-until-full loop + opaque cursor (mirror `query_pending_page`). Cursor attrs whitelist for GSI4.

### Step 4 — Repository: rollup counters `repository.py` — BR-L10 (rollup)
- [x] Add counter `ADD` operations to the `transact_write_items` in `transition_to_approved` (`new`+`activated` at earned quarter, for COMMUNITY and GROUP#<creditedGroupId>, at both `CROLL#` and `CROLLC#<...>#<certId>`) and `transition_to_terminal` for Expired/Revoked (`deactivated` at the change quarter, both scopes/granularities). Keep within the 100-item transaction limit.
- [x] `read_scope_quarter_counters(scope, upto_quarter)` and `read_scope_cert_counters(scope, upto_quarter)` — Query on the counter partition, bounded by quarter.

### Step 5 — Ledger + stats service `ledger_service.py` (new) — FR-4..17
- [x] `list_ledger(filters, *, principal, bearer_token)` — resolve scope (UGL→led group forced, CL→optional groupId), build predicate (group/cert/status/member), default quarter=current, call `query_ledger_page`, serialize `ledger_row`.
- [x] `growth(quarters, groupId, *, principal, bearer_token)` — per-quarter `new` + cumulative `Σactivated−Σdeactivated` from counters (last N quarters).
- [x] `snapshot(quarter, groupId, *, principal, bearer_token)` — per-cert net held-as-of counts from `CROLLC#` counters, sorted desc.

### Step 6 — Mandatory earned date `claim_service.py` — DR-6, BR-C5′
- [x] `_validate_date_earned`: require `dateEarned` for **all** submissions (not only expiring certs); keep not-in-future + already-expired guard for expiring certs.

### Step 7 — AuthZ + routing `authz.py`, `app.py` — BR-L1
- [x] `authz.py OP_AUTHZ`: add `listLedger`/`statsGrowth`/`statsSnapshot` → `("view","certification-ledger"|"certification-stats","defer-group")` (CL global / UGL group); `permission_matrix.json` mirror rows.
- [x] `app.py`: add to `OPERATIONS` (literal segments before templated) — `GET /certifications/ledger`, `/certifications/stats/growth`, `/certifications/stats/snapshot`; wire `_execute` to `ledger_service`; construct service in `Context`.

### Step 8 — Backend tests `services/certifications/tests/`
- [x] Ledger: filter-by group/cert/status/member; quarter bucketing (earned quarter, FD-2); Revoked/Expired included; cursor paging fetch-until-full; UGL forced to led group; Member/Admin 403.
- [x] Rollup: approve→new+activated; expire/revoke→deactivated; counters atomic with transition; growth Total = Σactivated−Σdeactivated; snapshot per cert; community=Σgroups.
- [x] Mandatory earned date: submit without dateEarned → 400.

### Step 9 — Mock parity — keep contract gate green
- [x] `mock_operations.json` + `fixtures.json`: add the three new ops with representative responses; ensure `submitClaim` fixture carries `dateEarned`.

### Step 10 — IaC: GSI4 — infra design §1
- [x] Certifications `-data` template (source template + `.deploy-staging/service-certifications-data.yaml`): add `gsi4pk`/`gsi4sk` AttributeDefinitions + `GSI4` GlobalSecondaryIndex (ProjectionType ALL); add the F-C staging note (single `UpdateTable` 3→4; `wait_for_gsi`).
- [x] Confirm **no `-app` change** (routes/IAM/sizing/alarms unchanged).

---

## Frontend — `frontend/src/`

### Step 11 — Pure helpers + tests `features/certifications/certLedger.ts` (+ `.test.ts`)
- [x] Query building (filters → querystring), status option set (Active|Expired|Revoked), CSV row mapping (export columns), quarter default. Unit tests (repo pattern — no DOM library).

### Step 12 — `features/certifications/CertificationLedgerPanel.tsx` (new) — FR-1..13
- [x] Filters (group All|specific for CL / locked UGL; certification All|specific; quarter default current; status multi; member picker); `DataTable` cursor paging; columns (Member, Certification Name, Certification Date, User Group, Status, Category, Expires On); no-load-until-filter (CL); `exportPagedCsv`. `data-testid`s (`cert-ledger-*`).

### Step 13 — `features/CertificationsPage.tsx` — FR-1/3, A10
- [x] Add "Certification Ledger" tab to CL and UGL views (default stays Pending Verifications); render `CertificationLedgerPanel` with role/ledGroupId.

### Step 14 — `features/certifications/ClaimModal.tsx` — DR-6
- [x] Earned date input **always required** (client validation); keep not-future.

### Step 15 — Dashboard charts — FR-14..17, B7
- [x] `features/certifications/CertificationGrowthChart.tsx` (TrendChart: Total + New) and `CertificationSnapshotChart.tsx` (RankedBarChart) with scope (community|group) + quarter controls.
- [x] Wire both into `features/CLDashboardPage.tsx` (group filter) and `features/UglDashboardPage.tsx` (locked to led group).

### Step 16 — Documentation
- [x] `aidlc-docs/construction/certifications/code/certification-ledger.md` — modified/created files, decisions, test notes, deploy prerequisite (data clean) + deferred prod backfill.

---

## Story / requirement traceability
| Item | Steps |
|---|---|
| FR-1..3 (tab/access/no-load) | 7, 12, 13 |
| FR-4..8 (filters) | 5, 11, 12 |
| FR-9..11 (columns/sort/paging) | 2, 3, 12 |
| FR-12..13 (export) | 11, 12 |
| FR-14..17 (charts) | 4, 5, 15 |
| DR-1/2 (GSI4 + retained keys) | 3, 10 |
| DR-6 / BR-C5′ (mandatory earned date) | 1, 6, 14 |
| BR-L1 (authz) | 1, 7, 8 |
| BR-L10 (rollup, transactional) | 4, 8 |
| No-backfill + deploy prereq | 10, 16 (+ hook) |

## Notes
- Brownfield: modify files in place; no `_new`/`_modified` duplicates.
- No integration/perf/E2E suites exist (repo position unchanged); backend pytest + frontend pure-helper tests + `make test` gate at Build and Test. The rendered panel/charts get a documented manual pass (no component-test library).
