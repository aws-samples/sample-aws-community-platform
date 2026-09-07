# Certification Ledger + Dashboard Charts — Business Logic Model

**Stage**: CONSTRUCTION → Functional Design (additive to Unit 6).
**Extends**: `business-logic-model.md` (base Unit 6). Companions: `certification-ledger-business-rules.md` (BR-L*), `certification-ledger-domain-entities.md` (index + contract deltas), `certification-ledger-frontend-components.md`.
**Source**: `certification-ledger-requirements.md` (FR-1..17, DR-1..8) + FD-1=A, FD-2=A.

This design adds three **read-only** capabilities to the shipped Certifications service — a member-wise ledger and two dashboard charts — plus one small write-path change (mandatory earned date). The **ledger** reads a new sparse **granted index** (GSI4); the **charts** read a small **maintained rollup** of counters (not a live scan). Nothing about the certification lifecycle, verification, revoke, or expiry flows changes except the points in §5, §6, and the rollup maintenance in §6a.

> **Scale revision (2026-08-12, during Infrastructure-Design brainstorm).** The expected volume is **30k–200k granted claims** (with 20–30 certification definitions and <10 groups), not "thousands". At that size, computing the charts' *valid-holdings-as-of-quarter-end* live by reading every granted claim per dashboard load is too slow/costly. The charts are therefore served by a **maintained rollup** (small per-scope/quarter and per-scope/cert/quarter counters, updated inside the transactional transition writes) — the A5→B "pre-aggregate now" path. The **ledger keeps the GSI4 design** (single-quarter paginated reads). This supersedes the earlier "live cross-partition aggregation" wording in §3/§4 below. No backfill ships (development-stage data will be cleaned before deploy; a prod backfill is a recorded follow-up).

---

## 1. The granted index (foundation for everything here)

A new sparse GSI, **GSI4**, indexes **every claim that has ever been granted** — status ∈ {`Approved`, `Expired`, `Revoked`} (a granted claim that later lapsed or was pulled). `Pending`, `Rejected`, and `Withdrawn` claims are **never** in this index (they were never granted).

```
gsi4pk = GLED#<earnedQuarter>
gsi4sk = <earnedDate>#<claimId>
```

- **`earnedQuarter`** = the calendar quarter (`YYYY-Qn`) of the claim's **earned date**; **fallback to the approval date** (`decidedAt`) when `dateEarned` is absent (historical non-expiring claims — DR-6).
- **`earnedDate`** (sort) = `dateEarned` (`YYYY-MM-DD`) when present, else the date part of `decidedAt`. Sorting the partition descending gives newest-earned-first, the ledger's default order.
- The index item **projects** the fields the ledger and charts read so neither needs a base-table Get per row: `memberId, memberName, certId, certName, certCategory, creditedGroupId, creditedGroupName, status, dateEarned, decidedAt, expiresAt, revokedAt` (projection type finalized at Infrastructure Design; ALL is acceptable — items are small).

**Why partition by earned-quarter:** the ledger is always viewed one quarter at a time (A6), so a ledger page is a **single-partition query**. (The charts do **not** read GSI4 in bulk — they read the maintained rollup, §6a; GSI4 exists for the ledger's row-level reads.) No runtime read is ever a Scan (BR-L5).

**Key lifecycle (BR-L6):** the GSI4 keys are written **at approval** (in the same conditional write that moves the claim to `Approved`) and are **retained through the terminal transitions to `Expired`/`Revoked`** — those transitions update `status` (and set `expiresAt`/`revokedAt`) but do **not** remove the GSI4 keys, so an Expired/Revoked holding stays queryable in the ledger with its correct status. This is the one behavioral change to the transition writes (see §5 of `certification-ledger-domain-entities.md`); it deliberately differs from GSI2/GSI3, which are removed on terminal transitions.

---

## 2. Ledger read model (FR-1..13)

`GET /certifications/ledger?groupId=&certId=&status=&quarter=&memberId=&limit=&cursor=`

1. **Authorization (BR-L1)** — caller must be `CommunityLeader` or `UserGroupLeader` (Members/Administrators → 403). A **UGL's `groupId` is forced server-side to their led group** (JWT-first, Identity fallback, fail-closed — BR-A4); any client-supplied `groupId` is ignored for a UGL.
2. **Quarter** — defaults to the current quarter; selects the `GLED#<quarter>` partition.
3. **Query** — one partition query, `ScanIndexForward=false` (newest earned first, FR-10), inside a **fetch-until-full cursor loop** (the exact pattern already proven by `query_pending_page`): rows are collected while an in-memory predicate matches, one past the page size signals a next page, and an opaque cursor is emitted. A page never comes back short while more matches exist, and no full-partition fold happens.
4. **Predicate (AND across kinds):**
   - `status` — one or more of {`Approved`, `Expired`, `Revoked`}; default = all three (Active|Expired|Revoked). `Active` maps to `Approved`.
   - `groupId` — for a CL, absent/"all" = every group (no filter); a specific value filters `creditedGroupId == groupId`. For a UGL, always the led group.
   - `certId` — absent = all certifications; a value filters `certId == certId`.
   - `memberId` — optional; filters `memberId == memberId`.
5. **Row shape** — from the projected index fields; **Certification Date = `dateEarned` else `decidedAt`** (DR-6). No approver field is ever returned (BR-L7).
6. **Bucketing (FD-2=A / BR-L2):** a row always sits in its **earned quarter**; Expired/Revoked never migrate to the quarter they changed — status is only a column/filter.

### Export (FR-12/13)
`exportPagedCsv` walks **all** pages of the same query+filters (cursor contract, ~100k safety cap) and maps each row to the CSV column set: `member, email, certification, category, certification_date (earned), approved_date, user_group, status, expires_on`. Dates are calendar-date only; the filename encodes scope (group or "all") + quarter (+ member when filtered). Email is resolved the same way the base service already resolves display fields (denormalized where available; no per-row identity fan-out).

---

## 3. Chart 1 — Quarterly Certification Growth (FR-14/15)

Last 4 quarters (oldest→newest on the axis), two series, scoped by the CL group filter (All groups aggregate or a specific group) or locked to a UGL's led group.

- **New in quarter (FD-1=A / BR-L4):** for each quarter `Q`, the count of granted claims with `earnedQuarter == Q` (optionally `creditedGroupId == group`). This is a **single-partition count per quarter** (`GLED#<Q>`). It counts by earned quarter **permanently** — a badge later expired/revoked still counts in the quarter it was earned, so historical bars never shift.
- **Total (cumulative valid holdings as of quarter-end) (B1/B3 / BR-L3):** for each quarter-end `Qend`, the count of granted claims whose **active window covers `Qend`**:
  `decidedAt ≤ Qend AND (expiresAt is null OR expiresAt > Qend) AND (revokedAt is null OR revokedAt > Qend)`
  (optionally `creditedGroupId == group`). A holding is valid from approval until it expires or is revoked, so expiry and revocation **decrement** this line.

**Read strategy (rollup, per the scale revision):** both series come from the **maintained rollup** (§6a), not from scanning claims. Per scope (community + each group) and quarter the rollup holds `new`, `activated`, and `deactivated` counters:
- *New in quarter* = `new[scope][Q]` (one counter read per quarter).
- *Total as of quarter-end* = `Σ activated[scope][≤Q] − Σ deactivated[scope][≤Q]` — read the scope's per-quarter counters up to `Q` (≤ ~40 tiny items) and net them.
Community scope is maintained directly (also equals the sum of the <10 groups). Reads are a few dozen tiny items — index/partition reads only, never a claim Scan (BR-L5).

> **Both series share the EARNED-date basis (2026-08-12 correction).** `new` **and** `activated` are incremented in the **earned quarter** at approval, so a certification earned in Q2 but approved in Q3 counts toward New *and* Total from Q2 — the two lines cannot diverge by an approval-lag quarter (the earlier approval-date `activated` produced a confusing crossover where New rose a quarter before Total). `deactivated` is still bucketed at the quarter expiry/revoke occurs, so validity ends at the real event.

**Community vs group (BR-L8):** because a member holds a given certification at most once across all groups (BR-C2), credited to exactly one group, the community ("All groups") figure is the sum over groups with **no double counting** — each holding is counted once under its credited group.

---

## 4. Chart 2 — Certification Snapshot (FR-16/17)

`GET /certifications/stats/snapshot?quarter=&groupId=`

For the selected quarter, a **stock** measure (B5=B): certifications **held (valid) as of the end of the selected quarter**, **grouped by certification name**. Served from the **per-(scope, cert, quarter) rollup** (§6a): for the chosen scope, read each certification's `activated`/`deactivated` counters up to the selected quarter and net them (`held[cert] = Σ activated[≤Q] − Σ deactivated[≤Q]`), yielding one bar per certification. At 20–30 certs × ≤40 quarters this is ~1,200 tiny reads, no claim Scan. For the current quarter the boundary is "as of now". Scope: CL community-wide (no `groupId`) or a specific group; a UGL is locked to their led group. Output `{items: [{certId, certName, count}], quarter, scope}`, count-descending.

---

## 5. Submission change — mandatory earned date (DR-6, amends base §2 / BR-C5)

- Earned date becomes **required for every claim submission**, not only for certifications that carry an expiry period. Still validated as a real ISO date and **not in the future**; the existing "already expired at submission" guard (BR-C6) is unchanged for expiring certs.
- **Historical claims** submitted before this change (non-expiring certs without a `dateEarned`) are not rewritten — the ledger and charts fall back to their approval date for bucketing and the "Certification Date" column.
- This is the only write-path change; verification, approval, revoke, and expiry logic are otherwise untouched.

## 6. Granted-index maintenance (amends base transition writes — BR-L6)
- **Approve** (`transition_to_approved`): additionally SET `gsi4pk`/`gsi4sk` (earnedQuarter/earnedDate computed from the frozen `dateEarned` else `decidedAt`) and ensure the projected fields are present on the item.
- **Expire / Revoke** (`transition_to_terminal` for these two statuses): keep `gsi4pk`/`gsi4sk`; the same write already updates `status` and sets `expiresAt`/`revokedAt`, which the index projects — so the ledger sees the new status without any extra write.
- **Reject / Withdraw**: come from `Pending` (never had GSI4 keys) → no GSI4 involvement.
- **Backfill** (one-time, DR-3): populate GSI4 keys on existing `Approved`/`Expired`/`Revoked` claims. Enumerating existing claims for a one-time migration is the single place a table Scan is permitted (a maintenance operation, not a runtime read); the runner is idempotent (writes keys only when absent). Mechanism/rollback detailed at Infrastructure Design.

## 6a. Rollup maintenance (the chart data source — scale revision)

The charts read counters, so those counters must be kept correct as claims move through their lifecycle. **Counters are updated inside the same `transact_write_items` that performs the claim transition** — atomic with the claim/slot write, so a counter can never partially diverge from the claim change (BR-L10). No DynamoDB Stream consumer is added (the table's stream stays unused); no separate write path.

**Counter items** (same table, own key space — no GSI needed; read by Query on a counter partition):
- Per-scope/quarter (Chart 1): `pk = CROLL#<scope>`, `sk = <quarter>` → `{ new, activated, deactivated }`.
- Per-scope/cert/quarter (Chart 2): `pk = CROLLC#<scope>`, `sk = <quarter>#<certId>` → `{ activated, deactivated }` (plus `certName` denormalized for labels).
- `scope` ∈ { `COMMUNITY`, `GROUP#<groupId>` }. A holding belongs to exactly one credited group (BR-C2), so COMMUNITY = the sum of groups; COMMUNITY counters are maintained directly to keep community reads O(quarters) rather than O(groups×quarters).

**When counters move:**
- **Approve** → in the claim's **earned quarter**: `new += 1` and `activated += 1`, for both `COMMUNITY` and `GROUP#<creditedGroupId>`, at the per-scope/quarter and per-scope/cert/quarter items. **Both use the earned quarter** (2026-08-12 correction) so the New and Total series share one axis and never diverge by an approval-lag quarter.
- **Expire / Revoke** → in the **quarter the change occurs**: `deactivated += 1` for both scopes at both counter granularities. This is what makes the Total line and the snapshot decrement (B3) — validity ends at the real event, even though it began at the earned quarter.
- **Reject / Withdraw** → no counter change (never granted).

**Correctness & remediation:** transactional updates guarantee no partial-write drift (BR-L10). Counters are **absolute-recomputable** from the claims if drift is ever suspected (the deferred prod-backfill/recompute utility) — the "fix-it" path, not a runtime alarm. Contention: all approvals in a quarter increment the same `CROLL#COMMUNITY / <quarter>` item; at <10 groups and human-paced approvals this is far below DynamoDB's per-item write ceiling (watch-item only).

**No backfill this release:** development-stage data is cleaned before deploy, so counters start from a correct zero and no pre-feature claim lacks GSI4 keys. A production rollout onto pre-existing data would require a one-time recompute (recorded follow-up).

## 7. Story / requirement traceability
| Requirement | Where |
|---|---|
| FR-1..3 (tab, access, no-load) | §2 authz + frontend-components |
| FR-4..8 (filters) | §2 predicate |
| FR-9..11 (columns, sort, paging) | §1 projection + §2 query loop |
| FR-12..13 (export) | §2 export |
| FR-14..15 (growth) | §3 + §6a rollup |
| FR-16..17 (snapshot) | §4 + §6a rollup |
| DR-1/2 (granted GSI, retained keys) | §1, §6 |
| DR-3 (backfill) | deferred (no history; §6a) |
| Rollup counters (scale revision, A5→B) | §6a |
| DR-6 (mandatory earned date) | §5 |
| DR-7 (endpoints) | domain-entities contract deltas |
