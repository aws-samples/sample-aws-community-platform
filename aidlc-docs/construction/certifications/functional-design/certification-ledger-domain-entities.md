# Certification Ledger + Dashboard Charts — Domain Entities & Contract Deltas

**Stage**: CONSTRUCTION → Functional Design (additive to Unit 6).
**Extends**: `domain-entities.md` (base Unit 6). No new entity — this adds an index and projected attributes to the existing **Claim** (E2), plus additive contract operations.

---

## 1. Claim (E2) — additions

No new fields on the claim's own semantics; the change is a new **secondary-index projection** over granted claims and the derived key attributes.

| Field | Type | Notes |
|---|---|---|
| `gsi4pk` | string | `GLED#<earnedQuarter>` — present only while the claim is granted (Approved/Expired/Revoked). Set at approval, retained through Expired/Revoked. |
| `gsi4sk` | string | `<earnedDate>#<claimId>` — `earnedDate` = `dateEarned` (YYYY-MM-DD) else date part of `decidedAt`. Descending sort = newest earned first. |

**Derived values (not stored beyond the keys):**
- `earnedQuarter` = calendar quarter (`YYYY-Qn`) of `dateEarned`, fallback `decidedAt`.
- The **projected attribute set** on GSI4 (so ledger/stats read no base item): `memberId, memberName, certId, certName, certCategory, creditedGroupId, creditedGroupName, status, dateEarned, decidedAt, expiresAt, revokedAt`. (Projection type — INCLUDE vs ALL — decided at Infrastructure Design; ALL is acceptable given small items.)

**Index population rule (BR-L6):** GSI4 holds exactly the claims that have ever been granted. Keys are written in `transition_to_approved`; retained (status/expiresAt/revokedAt updated in place) in `transition_to_terminal` when the new status is `Expired` or `Revoked`. `Rejected`/`Withdrawn` transitions (from `Pending`) never involve GSI4.

**`creditedGroupName`:** already denormalized on many claims; where absent it is resolved once per page from `/groups` (client) or left to the row's `creditedGroupId`→name resolution — never a per-row identity fan-out.

---

## 1a. Rollup counter items (new — chart data source, scale revision)

New item types in the same table (own key space; read by Query on a counter partition — **no GSI**). Maintained transactionally with claim transitions (BR-L10).

| Item | Key | Value | Serves |
|---|---|---|---|
| Scope/quarter counter | `pk = CROLL#<scope>`, `sk = <quarter>` | `{ new, activated, deactivated }` | Chart 1 (growth) |
| Scope/cert/quarter counter | `pk = CROLLC#<scope>`, `sk = <quarter>#<certId>` | `{ activated, deactivated, certName }` | Chart 2 (snapshot) |

- `scope` ∈ { `COMMUNITY`, `GROUP#<groupId>` }. COMMUNITY maintained directly (= Σ groups).
- Counter mutations (atomic `ADD` inside the transition transaction): **approve** → `new += 1`, `activated += 1` in the claim's earned quarter (both scopes, both granularities); **expire/revoke** → `deactivated += 1` in the change quarter; **reject/withdraw** → none.
- Chart reads: growth Total = `Σ activated[≤Q] − Σ deactivated[≤Q]`; snapshot per cert = same net per cert. New-in-quarter = `new[Q]`.
- These items carry **no GSI4 keys** (they are not claims and must never appear in the ledger).

## 2. Table / index summary (certifications single table)

| Index | Key | Purpose | Change |
|---|---|---|---|
| (base) | `pk`/`sk` | claim, definition, slot, filekey | — |
| GSI1 | `MEMBER#<memberId>` / `<submittedAt>#<claimId>` | my claims, listClaims | — |
| GSI2 | `PENDING` / `<submittedAt>#…` (sparse) | verification queue | — |
| GSI3 | `EXPIRY`/`SCANWATCH` (sparse) | expiry + scan windows | — |
| **GSI4 (new)** | `GLED#<earnedQuarter>` / `<earnedDate>#<claimId>` (sparse) | **ledger + growth + snapshot** | **added (this feature)** |

The certifications table currently defines GSI1–GSI3; GSI4 is one additional sparse GSI. Live-table add + backfill are the Infrastructure-Design concern.

---

## 3. Backfill — DEFERRED (scale revision)

**No backfill ships this release.** The service is in development; existing certification data is cleaned before deploy (enforced by the pre-deploy reminder hook), so GSI4 starts empty-and-correct and the rollup counters start from zero. Going forward, each approval writes GSI4 keys and increments counters inline — no migration needed.

**Deferred follow-up (future prod migration only):** if this feature is ever deployed onto an environment that already holds granted claims, run a one-time recompute — (1) set `gsi4pk`/`gsi4sk` on existing Approved/Expired/Revoked claims; (2) rebuild the rollup counters (absolute) from those claims. Enumeration would be a one-time operator-script table Scan (maintenance, not runtime; BR-L5), idempotent/re-runnable. Detailed if/when needed.

---

## 4. Contract deltas (certifications OpenAPI — additive; no api-edge regeneration)

All new routes live under the already-routed `/certifications` base path.

| Op | Method / Path | Auth | Request | Response |
|---|---|---|---|---|
| **NEW** `listLedger` | `GET /certifications/ledger` | CL global / UGL group | query: `quarter?` (default current), `groupId?` (CL only; UGL forced to led group), `certId?`, `status?` (csv/repeat of Active\|Expired\|Revoked → Approved/Expired/Revoked), `memberId?`, `limit?` (1–200), `cursor?` | `{ items: LedgerRow[], cursor?: string }` |
| **NEW** `statsGrowth` | `GET /certifications/stats/growth` | CL global / UGL group | query: `quarters?` (default 4), `groupId?` (CL only) | `{ items: [{ quarter, total, new }], scope }` (oldest→newest) |
| **NEW** `statsSnapshot` | `GET /certifications/stats/snapshot` | CL global / UGL group | query: `quarter?` (default current), `groupId?` (CL only) | `{ items: [{ certId, certName, count }], quarter, scope }` (count desc) |
| `submitClaim` | `POST /certifications/claims` | Member/UGL | **`dateEarned` now required** (was conditional) | unchanged |

**`LedgerRow`** = `{ claimId, memberId, memberName, certId, certName, certCategory, creditedGroupId, creditedGroupName, status, certificationDate (dateEarned else decidedAt), dateEarned?, decidedAt, expiresAt?, revokedAt? }` — **no approver field** (BR-L7).

**Permission matrix** (`contracts/platform/permissions/role-permission-matrix.v1.json`): add rows for `certification-ledger` and `certification-stats` — CL global, UGL group (defer-group); Members/Admin absent (denied). Consistent with the verification-queue rows.

**Version**: certifications OpenAPI bumped additively (e.g. minor bump); `submitClaim`'s `dateEarned`-required is the only tightened field and is enforced in-service regardless.

---

## 5. Transition-write changes (repository, BR-L6)
- `transition_to_approved(...)` — additionally `SET gsi4pk, gsi4sk` (+ ensure projected fields on the item).
- `transition_to_terminal(...)` for `Expired`/`Revoked` — **must not** remove `gsi4pk`/`gsi4sk` (it already only removes gsi2/gsi3); the existing `SET status`/`revokedAt`/`expiresAt` keeps the projected row current.
- No change for `Rejected`/`Withdrawn` (no GSI4 keys exist on Pending claims).
