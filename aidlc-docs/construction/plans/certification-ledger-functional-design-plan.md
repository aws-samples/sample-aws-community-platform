# Functional Design Plan — Certification Ledger + CL/UGL Dashboard Charts

**Unit**: Unit 6 (Certifications) + Unit 15 (SPA)
**Requirements**: `aidlc-docs/inception/business-requirements/certification-ledger-requirements.md` (APPROVED)
**Execution plan**: `aidlc-docs/inception/plans/certification-ledger-execution-plan.md` (APPROVED)
**Extends**: `aidlc-docs/construction/certifications/functional-design/` (base Unit 6 FD — business-logic-model, business-rules, domain-entities, frontend-components)

This is an **additive** functional design for the ledger + charts on top of the shipped Certifications service. It does **not** restate the base Unit 6 design; it adds the new read/aggregation logic, the granted-index domain change, the mandatory-earned-date rule change, and the new frontend surfaces.

---

## Part 1 — Clarifying questions (please answer)

Most of the design is fixed by the approved requirements. Only two genuinely-open functional points remain — both affect the aggregation semantics, so I'd rather confirm than assume. Each has a recommended default.

### Question FD-1 — "New Certifications in this Quarter" (Chart 1, second series): counting basis over time
A certification earned in, say, 2024-Q1 that is later expired or revoked in 2024-Q3 — should it still count in the **2024-Q1 "new" bar**?

A) **Yes — count every certification by the quarter it was earned, permanently** (a stable historical flow). The 2024-Q1 bar never changes retroactively when a badge later expires/revokes. *(This is how "new in quarter" flow metrics normally behave, and it keeps past bars stable.)*

B) **No — the "new" bar counts only certifications earned that quarter that are still valid now** (past bars shrink as badges expire/revoke).

X) Other (please describe after [Answer]: tag below)

[Answer]: A

> Note: this only concerns Chart 1's *New-in-quarter* series. Chart 1's *Total* line and Chart 2's *stock* are already confirmed as **valid-holdings-as-of-quarter-end** (B1/B3/B5 — expiry & revoke do decrement those).

### Question FD-2 — Ledger quarter bucket for Expired/Revoked rows
The ledger's "Certification Date" is the **earned date** (A2) and the quarter filter buckets on it. So a certification **earned in 2024-Q1 but revoked in 2024-Q3** appears under **2024-Q1** (its earned quarter), with status "Revoked" — it does **not** move to 2024-Q3.

A) **Confirm** — the ledger is always bucketed by earned quarter; status (Active/Expired/Revoked) is just a column/filter, never changes which quarter a row falls in. *(Consistent with A2/A6; the "Certification Date" column is the earned date.)*

B) The ledger should bucket by the quarter of the **status change** for Expired/Revoked rows (earned quarter for Active) — i.e. "what changed this quarter".

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Part 2 — Functional Design artifact checklist (executed after answers)

Artifacts created under `aidlc-docs/construction/certifications/functional-design/` (feature-scoped, cross-referencing the base files):

- [x] `certification-ledger-business-logic.md`
  - Ledger read model: single earned-quarter partition query + in-memory predicate (group/cert/status/member) + fetch-until-full cursor paging (no Scan), UGL forced to led group.
  - Chart aggregations: *new-in-quarter* (per FD-1), *valid-holdings-as-of-quarter-end* active-window computation for Chart 1 Total + Chart 2 stock, group vs community scope, last-4-quarters series.
  - Mandatory earned-date submission change (extends the §2 submission flow + BR-C5) and the historical fallback to approval date.
  - The granted-index maintenance rule: keys written at approval, **retained and status-updated through expiry/revoke** (change to the transition writes), so Expired/Revoked rows stay queryable.
  - Export flow (walk all filtered rows) and CSV column mapping.
- [x] `certification-ledger-business-rules.md`
  - New/changed rules (e.g. BR-C5 amendment for mandatory earned date; ledger/stats authorization = CL global / UGL led-group, Members/Admin denied; ledger status set = Approved+Expired+Revoked; active-window validity definition; no-Scan/bounded-read rule; approver never exposed).
- [x] `certification-ledger-domain-entities.md`
  - Claim entity additions: the granted-index key attributes (`gsi4pk = GLED#<earnedQuarter>`, `gsi4sk = <earnedDate>#<claimId>`) + the projected fields (memberName, certName, certCategory, creditedGroupId/name, status, dateEarned, decidedAt, expiresAt, revokedAt) and their retain-through-terminal behavior.
  - `earnedQuarter` derivation (from dateEarned, fallback decidedAt).
  - Contract deltas: additive `GET /certifications/ledger`, `/certifications/stats/growth`, `/certifications/stats/snapshot` (params + response shapes); permission-matrix rows; submission body earned-date now required.
  - Backfill: which existing claims get indexed (Approved/Expired/Revoked) and how earnedQuarter is assigned.
- [x] `certification-ledger-frontend-components.md`
  - `CertificationLedgerPanel` (tab for CL + UGL): filters (group All|specific for CL / locked for UGL, certification, quarter default-current, status multi Active|Expired|Revoked, member picker), DataTable columns (Member, Certification Name, Certification Date, User Group, Status, Category, Expires On), cursor paging, no-load-until-filter, CSV export.
  - `CertificationsPage` tab wiring (add "Certification Ledger" to CL + UGL; Pending Verifications stays default).
  - `ClaimModal` change: earned date now always required.
  - Dashboard charts on `CLDashboardPage` + `UglDashboardPage`: Chart 1 (TrendChart — Total + New, group filter for CL / locked for UGL), Chart 2 (RankedBarChart — by certification name, community/group scope for CL / locked for UGL), quarter controls.
  - Endpoint map + validation summary.
- [x] Update `aidlc-state.md` (Functional Design complete) + log approval in `audit.md`.

## Story / requirement traceability
| FR | Artifact coverage |
|---|---|
| FR-1..3 (tab, access, no-load) | frontend-components + business-rules (authz) |
| FR-4..8 (filters) | business-logic (ledger read) + frontend-components |
| FR-9..11 (columns, sort, paging) | domain-entities (projection) + frontend-components |
| FR-12..13 (export) | business-logic (export) + frontend-components |
| FR-14..17 (charts) | business-logic (aggregations) + frontend-components |
| DR-1..3, DR-6 (granted GSI, retained keys, backfill, mandatory earned date) | domain-entities + business-logic + business-rules |
| DR-7 (endpoints) | domain-entities (contract deltas) |
