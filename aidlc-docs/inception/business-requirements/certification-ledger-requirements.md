# Requirements — Certification Ledger tab + CL/UGL Dashboard Charts

**Date**: 2026-08-12
**Units**: Unit 6 (Certifications) backend + Unit 15 (SPA)
**Stories**: builds on US-5.4/5.6/5.7/5.8 (claims, verification, revoke, expiry); new leader-facing read/reporting surface
**Source**: change request `audit.md` 2026-08-12; answers in `certification-ledger-questions.md` (Round 1 + Round 2)

---

## 1. Intent analysis

| Aspect | Assessment |
|---|---|
| Request type | **New feature (Enhancement)** — a browsable, filterable, exportable member-wise certification ledger for leaders, plus two leader-dashboard charts |
| Scope | Unit 6 (new read + aggregation access pattern, **one new GSI + backfill**, new endpoints, a small submission-flow change) + Unit 15 (new tab + 2 charts on both leader dashboards) |
| Complexity | **Moderate** — new index/migration and two time-series aggregations, but heavily reuses proven table/paging/export/chart patterns |
| Depth | Standard → the new index/migration warrants an **Infrastructure-Design** pass |
| Risk | **Medium** — a live DynamoDB `-data` table change + one-time backfill; read/report feature otherwise; small write-path change (mandatory earned date) |

### Confirmed answers (Round 1 + Round 2)
Ledger: **A1=A** (CL all groups; UGL locked to led group), **A2=B** (Certification Date = earned date; earned date mandatory going forward), **A3=B** (include Approved + Expired **+ Revoked**; add Revoked to the status filter), **A4=A** (include all; no approver column), **A5=A** (new "granted" GSI + backfill — taken as the confirmed direction since the other answers require it; A5-R2 left blank, **flagged for approval**), **A6=A** (quarter picker, default current), **A7=B** (richer columns), **A8=A** (full paged CSV export), **A9=A** (cursor paging), **A10=C** (add tab; no data load until a filter is chosen).
Charts: **B1=A** (cumulative valid holdings as of quarter-end), **B2=B** (new-in-quarter by earned date), **B3=A** (expiry & revoke decrement holdings), **B4=A** (CL group filter; UGL locked), **B5=B** (Snapshot = stock: certifications held as of the quarter, by name), **B6=A** (community-wide vs specific-group scope + quarter; UGL locked), **B7=A** (both charts on both dashboards).

---

## 2. Functional requirements — Certification Ledger tab

### Placement & access
- **FR-1** — A new **"Certification Ledger"** tab is added to the Certifications page for **Community Leaders and User Group Leaders** (A10). Members and Administrators do not see it and are denied server-side (BR-A1/BR-A5, SECURITY-08).
- **FR-2** — A **CL** may view **all groups or one specific group**; a **UGL is locked to the group they lead** — no group picker, no other group's data (A1). Scope is enforced server-side; UI scoping is convenience only.
- **FR-3** — The existing default tab (**Pending Verifications**) is unchanged. Opening the Ledger tab **loads no data until a filter is chosen** (A10): for a CL that means a group selection is required first (or an explicit "All groups" choice); a UGL is already pre-scoped to their led group, so the current quarter loads on open.

### Filters
- **FR-4** — **Group** — for a CL, **All groups | specific group** (A1). For a UGL, fixed to the led group.
- **FR-5** — **Certification** — **All certificates | a specific certificate** (from the certification catalog).
- **FR-6** — **Quarter** — dropdown of the current + previous quarters, **defaulted to the current quarter** (A6), buckets on **earned date** (see FR-9). Replaces the free "date range" wording from the original request while still meaning "certification date".
- **FR-7** — **Status** — **Active | Expired | Revoked** (A3). Active = `Approved` (currently held), Expired = `Expired`, Revoked = `Revoked` (was approved, later revoked). May be a multi-select; all shown by default. `Pending`/`Rejected`/`Withdrawn` never appear (never granted).
- **FR-8** — **Member** — optional searchable member picker (scoped to the selected group for a UGL) to narrow to one member.
- Filters combine with AND across kinds. Changing any filter resets pagination to the first page.

### Table
- **FR-9** — Columns (A7=B): **Member, Certification Name, Certification Date, User Group, Status, Category, Expires On**.
  - **Certification Date = earned date** (`dateEarned`) — the date on the certificate, i.e. when the member earned it (A2). For historical granted claims that never captured an earned date (non-expiring certs approved before this change), the ledger falls back to the approval date (`decidedAt`) — see FR-16/DR-6.
  - **User Group** shown by **name** (denormalized on the claim / resolved from `/groups`; no raw ids — NFR-6 convention).
  - **Category** = the certification's category (e.g. AWS Certification / Community Badge). **Expires On** = `expiresAt` (blank when the certification never expires).
- **FR-10** — Default sort: **certification (earned) date, newest first** — the index order.
- **FR-11** — **Cursor pagination with Prev/Next and a rows-per-page control** (A9), matching Member Directory / Admin Users / Point Ledger: skeleton on first load, "Refreshing…" between pages. This is the "big list" lazy loading — one page fetched at a time.

### Export
- **FR-12** — An **Export CSV** button (A8) that walks **all rows matching the current filters** (not just the visible page) via the cursor contract (`exportPagedCsv`), with a safety cap (~100k rows).
- **FR-13** — Export columns (superset of the on-screen set): `member, email, certification, category, certification_date (earned), approved_date, user_group, status, expires_on`. Dates are calendar-date only (no time). The **filename encodes the scope (group / all) + quarter** (and member, if filtered).

---

## 3. Functional requirements — Dashboard charts (CL + UGL)

Both charts are added to **both** the CL dashboard (`CLDashboardPage`, "Community Analytics") and the UGL dashboard (`UglDashboardPage`), the UGL versions scoped to their led group (B7, B4, B6).

### Chart 1 — Quarterly Certification Growth (last 4 quarters)
- **FR-14** — A quarter-by-quarter chart over the **last 4 quarters** with two series:
  - **Total Number of Certifications** = **cumulative valid holdings as of each quarter-end** (B1) — a certification counts while it is held, i.e. from its approval date until it expires or is revoked. **Expiry and revocation decrement** the count (B3). A holding is "valid as of quarter-end Q" when `decidedAt ≤ Qend AND (expiresAt is null OR expiresAt > Qend) AND (revokedAt is null OR revokedAt > Qend)`.
  - **New Certifications in this Quarter** = certifications **newly earned in the quarter, bucketed by earned date** (`dateEarned`, fallback approval date) (B2).
- **FR-15 (CL scope)** — CL gets a group filter: **All groups** (aggregate) + a specific group (B4). **UGL** is locked to the led group (no picker).

### Chart 2 — Certification Snapshot
- **FR-16** — A **bar chart of certification name → count** for the selected quarter, where **count = certifications held (valid) as of the selected quarter** (stock, B5=B) — the same valid-as-of-quarter-end computation as Chart 1's Total line, grouped by certification name.
- **FR-17 (scope)** — CL selects **Community-wide (all groups) vs a specific group** + quarter (B6). **UGL** is locked to the led group + quarter.

> **Date-basis note (amended 2026-08-12):** the ledger's "Certification Date", the ledger's quarter buckets, **and both Chart 1 series (New and Total) plus Chart 2's stock all use the EARNED date**. A certification earned in a quarter counts toward New and Total from that (earned) quarter, regardless of when it was approved — so the two growth lines share one axis and never diverge by an approval-lag quarter. Expiry/revoke still decrement Total/stock at the quarter they occur (validity ends at the real event). *(Superseded the original design, where Total/stock used the approval date; that produced a confusing crossover when approval lagged into the next quarter.)*

---

## 4. Design decisions & architecture (A5=A)

- **DR-1 — One new sparse "granted" GSI on the certifications table.** Indexes **every claim that has ever been granted** — `Approved`, `Expired`, and `Revoked` (Revoked-after-approval). Partitioned by **earned-quarter**, sorted by earned date:
  - `gsi4pk = GLED#<earnedQuarter>`, `gsi4sk = <earnedDate>#<claimId>` (earnedQuarter derived from earned date, falling back to approval date where earned date is absent).
  - Item projects the fields the ledger and charts read: `memberId, memberName, certId, certName, certCategory, creditedGroupId (+name), status, dateEarned, decidedAt, expiresAt, revokedAt`.
- **DR-2 — The granted-index keys are RETAINED through terminal transitions.** Unlike GSI2/GSI3 (which are `REMOVE`d on expiry/revoke), the granted index must persist and have its `status`/`expiresAt`/`revokedAt` **updated** on expiry and revocation, so Expired/Revoked rows remain queryable. This is an explicit change to `transition_to_approved` / `transition_to_terminal` in the repository (to be detailed in Functional/Infra Design).
- **DR-3 — Backfill migration** over existing granted claims (Approved/Expired/Revoked) to populate the new index keys. One-time, idempotent; runs against the live `-data` table.
- **DR-4 — Ledger read (single quarter):** one `GLED#<quarter>` partition query with an in-memory predicate for group/certification/status/member, using the **fetch-until-full cursor loop already proven by the pending queue** — bounded by claims-in-that-quarter, never a Scan. A UGL's group predicate is forced to their led group server-side.
- **DR-5 — Chart aggregations:** computed from the granted index (index-only, no Scan). *New-in-quarter* = per-quarter partition counts. *Valid-holdings-as-of-quarter-end* (Chart 1 Total + Chart 2 stock) reads granted items across earned-quarter partitions up to each target quarter and applies the active-window test in memory. Scale assumption: thousands of claims / tens of certifications, consistent with how the CL/UGL dashboards already compute live figures; a nightly pre-aggregation is the future option if volume grows (out of scope now).
- **DR-6 — Earned date becomes mandatory on submission (A2).** The claim form and server validation require an earned date for **all** new claims (extends BR-C5, which today requires it only for expiring certs); still must not be in the future. Historical claims lacking it fall back to approval date in the ledger/charts (no invented dates).
- **DR-7 — New endpoints, additive, under the `/certifications` base path (no api-edge regeneration):**
  - `GET /certifications/ledger` — paged, filtered (`groupId`, `certId`, `status`, `quarter`, `memberId`, `limit`, `cursor`); CL/UGL only, UGL forced to led group.
  - `GET /certifications/stats/growth?quarters=4[&groupId=]` — Chart 1 series.
  - `GET /certifications/stats/snapshot?quarter=[&groupId=]` — Chart 2 bars.
  - Contract `certifications` openapi bumped additively; permission-matrix rows added (ledger/stats = CL global, UGL group).
- **DR-8 — Frontend reuse:** new `CertificationLedgerPanel` tab modeled on `PointLedgerPanel` (filters, `DataTable` cursor paging, `exportPagedCsv`); charts reuse `TrendChart` (growth) and `RankedBarChart` (snapshot); quarters via the shared `quarters.ts` helpers.

---

## 5. Non-functional requirements
- **NFR-1 (Performance)** — All reads are Get/Query only (no Scan): the ledger stays on the single-quarter granted partition with fetch-until-full cursor paging; chart aggregations are index-only across bounded partitions.
- **NFR-2 (Security, SECURITY-08)** — Ledger and stats endpoints enforce CL (community-wide) / UGL (led group only); Members and Administrators get 403. UGL group scope resolved JWT-first then Identity, fail-closed (BR-A4). IDOR-safe.
- **NFR-3 (Security, SECURITY-05)** — All params validated: quarter against the allowed window, status against the enum, ids length-bounded, `limit` 1–200, cursor opaque-and-whitelisted (existing repo pattern).
- **NFR-4 (Resiliency)** — The new GSI is added to the service-owned `-data` stack with PITR unchanged; the backfill is idempotent and re-runnable. Chart/ledger reads degrade gracefully (a slow/failed panel cannot blank the dashboard — existing per-panel isolation).
- **NFR-5 (Maintainability)** — Reuse existing repository paging, export, chart, and quarter primitives; add tests per new filter, per endpoint, and for the active-window aggregation and the backfill.
- **NFR-6** — No raw ids in the UI or exports; group/cert shown by name.

---

## 6. Explicitly out of scope / unchanged
- No change to the certification **lifecycle** (submission→verify→approve/reject→expire/revoke) beyond making earned date mandatory (DR-6).
- No "Approved By" column or approver filter (A4=A).
- No custom free-form date range (quarter picker instead, A6); no all-time ledger view.
- No nightly pre-aggregation now (DR-5 future option).
- Member/Admin access to the ledger or charts.

---

## 7. Traceability
| Requirement | Source | Verification |
|---|---|---|
| FR-1, FR-2, FR-3 | A1, A10 | Backend: UGL forced to led group, Member/Admin 403; frontend: no load until filter chosen |
| FR-4, FR-5, FR-6, FR-7, FR-8 | A1, A3, A6 | Backend filter tests (group/cert/quarter/status/member); status enum incl. Revoked |
| FR-9, FR-10 | A2, A7 | Columns render names/labels + earned date (fallback); Category/Expires On; newest-first |
| FR-11 | A9 | Cursor Prev/Next; fetch-until-full returns full pages |
| FR-12, FR-13 | A8 | Export walks all filtered rows; column set; filename encodes scope |
| FR-14, FR-15 | B1, B2, B3, B4 | Growth series: cumulative valid holdings (expiry/revoke decrement) + new-in-quarter; CL group filter, UGL locked |
| FR-16, FR-17 | B5, B6 | Snapshot = valid holdings as of quarter by cert name; scope selector; UGL locked |
| FR-14–FR-17, FR-1–FR-13 | A5=A | New granted GSI + backfill; index-only reads (no Scan) |
| DR-6 | A2 | Submission requires earned date; historical fallback |

## 8. Extension compliance
- **Security**: SECURITY-05 (param validation), SECURITY-08 (fail-closed CL/UGL authz, IDOR) — compliant. SECURITY-04/07/11 N/A (no new unauthenticated surface, JSON responses).
- **Resiliency**: bounded queries/no-Scan (compliant); new GSI under Backup & Restore + PITR (unchanged); idempotent, re-runnable backfill. To be confirmed at Infrastructure Design.
- **Property-Based Testing**: disabled for this project (N/A).
- No blocking findings at Requirements stage. The live-table GSI add + backfill is the one item to design carefully at Infrastructure Design.

## 9. Open item for approval
- **A5-R2 was left blank.** This document assumes **A5=A** (new granted GSI + backfill + Infrastructure-Design pass) because every other confirmed answer (Expired **and** Revoked rows, group filtering, earned-date quarter buckets, historical growth curve) requires it. If you prefer **A5=C** (no migration; quarter-scoped, best-effort growth) or **A5=B** (also add a nightly rollup now), say so at the gate and this will be revised.
