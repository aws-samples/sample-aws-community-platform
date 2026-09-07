# Requirements — Point Ledger tab (US-7.9)

**Date**: 2026-08-11
**Units**: Unit 7 (Contributions & Scoring), Unit 15 (SPA)
**Story**: US-7.9 Export Contribution Data — implemented interactively as a browsable Point Ledger
**Source**: change request `audit.md` 2026-08-11T20:10:00Z; answers in `point-ledger-questions.md`

---

## 1. Intent analysis

| Aspect | Assessment |
|---|---|
| Request type | **New feature** — a browsable, filterable, exportable point ledger for leaders; motivated by "no way to verify a +5 adjustment" |
| Scope | Unit 7 (additive filters on an existing endpoint) + Unit 15 (new tab). **No new data model, no new index, no infrastructure change** |
| Complexity | **Standard** — reuses the existing per-group-per-quarter index and established table/export patterns |
| Depth | Standard |
| Risk | **Low** — read/export only; writes nothing; stays on the proven fast query path |

### Key simplification from the answers

The original request said "custom date range" and implied "all groups." **Q2=B and Q3 overrode both**: single group required, **no all-groups**, **no custom date range** — a **quarter filter** (defaulted to current) instead, and **no data load on page open**. This deliberately keeps every query on the existing `GLEDGER#<groupId>#<quarter>` index (GSI3), so there is **no new GSI and no backfill migration**. Recorded as a conscious change from the original wording, per the user's Q3 answer.

---

## 2. Functional requirements

### Placement & access
- **FR-1** — A new **"Point Ledger"** tab on the Contributions page, shown to **Community Leaders and User Group Leaders** (Q1=B). Members and Administrators do not see it and are denied server-side.
- **FR-2** — A **CL** may view any one group's ledger; a **UGL** is **locked to the group they lead** (Q1=B). Enforced server-side (BR-A5, SECURITY-08); the UI scoping is convenience only.

### Filters
- **FR-3** — **Group** — required, single select (Q2=B). No "All groups". For a CL, a dropdown of all groups with **no default**; for a UGL, fixed to their led group. Until a group is chosen, **no data is loaded** (Q3, Q9).
- **FR-4** — **Quarter** — a dropdown of the current + previous 7 quarters, **defaulted to the current quarter** (Q3). Replaces the originally-requested custom date range.
- **FR-5** — **Member** — optional searchable picker (Q4=A), reusing the Adjust Points people picker, scoped to the selected group for a UGL. Narrows the ledger to one member — the direct path to "verify this member's +5 adjustment".
- **FR-6** — **Source** — multi-select of `auto`, `evidence`, `adjustment`, all selected by default (Q5=C).
- **FR-7** — **Activity type** — multi-select of the ledger's activity types (framework activities + the system/auto activities: event attendance, event delivery, organize event, forum post, forum accepted-reply, certification approval; and "Manual adjustment"), all selected by default (Q5=C).
- **FR-8** — Filters combine (AND across filter kinds, OR within a multi-select). Changing any filter resets pagination to the first page.

### Table
- **FR-9** — Columns (Q6=B): **Member name, Email, Points, Activity, Group name, Earned date, Source, Pillar**. Group shown by **name** (resolved client-side; no raw ids — NFR-6 convention). Pillar shown by its label, not the number.
- **FR-10** — **Default sort: earned date, newest first** (the index order — no client sort needed).
- **FR-11** — **Cursor pagination with Prev/Next and a rows-per-page control** (Q8=A), matching the Member Directory / Admin Users tables: skeleton on first load, "Refreshing…" between pages. This is the "lazy loading" — one page fetched at a time, never the whole quarter.

### Export
- **FR-12** — An **Export CSV** button (Q7=A) that walks **all rows matching the current filters** (not just the visible page) via the cursor contract, with a safety cap (100k rows).
- **FR-13** — Export columns are the **full US-7.9 set**: `member_name, member_email, user_group, activity_type, pillar, points, source, earned_date, quarter`. Dates are calendar-date only (no time). The **filename encodes the group and quarter** (and member, if filtered).
- **FR-14** — Deactivated members' historical entries are included (they are in the ledger; US-7.9) — nothing extra to do, but not filtered out.

---

## 3. Non-functional requirements
- **NFR-1 (Performance)** — Every read stays on the `GLEDGER#<groupId>#<quarter>` index (one group, one quarter), cursor-paginated. Filters (member/source/activity) are applied in a **fetch-until-full** page loop so a page returns up to `limit` matching rows with a correct opaque cursor — never a full-partition fold, never a Scan.
- **NFR-2 (Security, SECURITY-08)** — The endpoint enforces CL/UGL only, UGL forced to their led group; Members/Admin get 403. Unchanged from the existing group-ledger authorization.
- **NFR-3 (Security, SECURITY-05)** — All filter params validated: quarter against the allowed window, source/activity against known enums, limit 1–200, cursor opaque-and-whitelisted (existing behaviour).
- **NFR-4 (Resiliency)** — No new AWS resource, no index, no migration; the change cannot affect the ledger's durability or the write path.
- **NFR-5 (Maintainability)** — Reuse `group-ledger`'s query + email-resolution rather than a parallel path; add tests for each new filter.

---

## 4. Design decisions (from the answers)
- **DR-1** — Reuse and extend the existing `GET /contributions/group-ledger` endpoint with additive optional params (`memberId`, `source` repeated/csv, `activityType` repeated/csv). No new endpoint, no new index. The response already carries every field the columns need (memberName, memberEmail, points, activity, groupId, earnedDate, source, pillar, quarter).
- **DR-2** — Filters applied server-side in the GSI3 page loop (fetch-until-full), so pagination and export both stay correct and bounded.
- **DR-3** — Activity-type options are assembled on the client from the framework (`GET /contributions/framework`) plus the fixed system activities and "Manual adjustment". The exact stored `activity` strings for auto awards will be reconciled during code generation so the filter values match what the ledger stores.
- **DR-4** — Export reuses `exportPagedCsv` (cursor-walk, 100k cap) against the same endpoint+filters, transforming rows to the US-7.9 column names/order.

## 4b. Companion change — move the Leaderboard off the CL Contributions page (added 2026-08-11)

Bundled here because it reshapes the same CL Contributions tab strip.

- **FR-15** — For a **Community Leader**, the **Leaderboard tab is removed from the Contributions page**. Members and UGLs keep it there (this is a CL-only change). After this, a CL's Contributions tabs are **Approvals + Point Ledger** (the Scoring Framework tab already moved to its own page).
- **FR-16** — The Leaderboard is **added to the CL Community Dashboard** (`CLDashboardPage`, "Community Analytics") as its own section — the full interactive component (group selector, quarter, pillar filter, podium + ranked table), same as the tab showed.
- **FR-17** — The Home/deep-link path `?tab=leaderboard` must **degrade gracefully for a CL** (who no longer has that tab): a CL landing on the Contributions page falls back to their default tab instead of a blank/again-empty leaderboard.
- **DR-5 (open decision — recommended default)** — The dashboard already has a **nightly, community-ranked "Top Contributors"** panel; the Leaderboard is **live and per-group**. They are different cuts, so the recommended default is to **keep Top Contributors and add the Leaderboard as a separate section**. Alternative: replace Top Contributors with the Leaderboard. **Flagged for the user to choose at approval.**

## 5. Explicitly unchanged / out of scope
- No new DynamoDB index, no backfill/migration, no infrastructure change.
- No custom date range and no all-groups view (deliberately dropped per Q2/Q3).
- No write path change; the ledger and adjustment logic are untouched.
- The Leaderboard move is **frontend-only** (CL tab strip + CL dashboard); no backend change.

## 6. Traceability
| Requirement | Source | Verification |
|---|---|---|
| FR-1, FR-2 | Q1=B | Backend test: UGL forced to led group, Member/Admin 403 |
| FR-3, FR-4 | Q2=B, Q3 | Frontend: no load until group chosen; quarter defaults to current |
| FR-5 | Q4=A | Member picker narrows results; backend memberId filter test |
| FR-6, FR-7 | Q5=C | Backend tests: source and activity-type filters, defaults = all |
| FR-9, FR-10 | Q6=B | Columns render names/labels, no raw ids; newest-first |
| FR-11 | Q8=A | Cursor Prev/Next, fetch-until-full returns full pages |
| FR-12, FR-13 | Q7=A | Export walks all filtered rows; US-7.9 columns; filename encodes scope |

## 7. Extension compliance
- **Security**: SECURITY-05 (filter validation), SECURITY-08 (unchanged authz) — compliant. Others N/A.
- **Resiliency**: RESILIENCY-10 (bounded queries, no scan) — compliant. No new resource, so DR/backup rules N/A.
- No blocking findings.
