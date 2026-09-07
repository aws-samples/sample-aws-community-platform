# Certification Ledger + Dashboard Charts — Business Rules

**Stage**: CONSTRUCTION → Functional Design (additive to Unit 6). Numbered `BR-L*` for the new surface, plus one amendment to a base rule. Enforced in-service, fail-closed (SECURITY-08). Companion: `certification-ledger-business-logic.md`.

## Authorization
- **BR-L1 (ledger + stats authz)** — `GET /certifications/ledger`, `/certifications/stats/growth`, `/certifications/stats/snapshot` are **CL global / UGL group** (`defer-group` ops, mirroring the verification queue): a Community Leader reads all groups (and may filter to one); a User Group Leader reads **only the group they lead**, resolved JWT-first then Identity, **fail-closed** (unresolvable led group → deny, never "all"). **Members and Administrators → 403** on all three. Any client-supplied `groupId` is **ignored/overridden** for a UGL (no IDOR into another group).
- **BR-L7 (approver never exposed)** — the ledger, its export, and the stats never expose who approved a claim (A4=A). No approver id, name, or role is projected or returned.

## Ledger membership & bucketing
- **BR-L2 (ledger population + bucket)** — the ledger includes claims with status ∈ {`Approved`, `Expired`, `Revoked`} only (never `Pending`/`Rejected`/`Withdrawn`). The status filter offers **Active | Expired | Revoked** (Active = `Approved`), multi-select, all shown by default. Every row is bucketed by its **earned quarter** (earned date, fallback approval date); status is a column/filter and **never** changes which quarter a row falls in (FD-2=A).
- **BR-L9 (certification date)** — the "Certification Date" shown (and used for quarter bucketing/sort) is `dateEarned` when present, else `decidedAt` (approval date) for historical claims that never captured an earned date (DR-6).

## Chart semantics
- **BR-L3 (valid-holding active window — earned-date basis, amended 2026-08-12)** — for the growth *Total* line and the snapshot *stock*, a certification counts as held "as of quarter-end `Qend`" iff it was **earned** in a quarter `≤ Qend` and has not since expired/been revoked: `earnedQuarter ≤ Qend AND (expiresAt is null OR expiresAt > Qend) AND (revokedAt is null OR revokedAt > Qend)`. Both `new` and `activated` counters are incremented in the **earned quarter** (so the growth New and Total series share the earned-date basis and cannot diverge by an approval-lag quarter — the original approval-date `activated` produced a confusing crossover). Expiry and revocation still decrement in the quarter they occur (B1/B3/B5). Current quarter boundary = "as of now". **Served from the maintained rollup (BR-L10), not a live claim scan**: `held-as-of-Q = Σ activated[≤Q] − Σ deactivated[≤Q]`.
- **BR-L10 (rollup maintenance — scale revision, A5→B)** — the dashboard charts read maintained counters, not the claims. Counters (`new`/`activated`/`deactivated`, per scope=COMMUNITY|GROUP#<id>, per quarter, and per cert) are updated **inside the same transactional write as the claim transition** (approve → new+activated in earned quarter; expire/revoke → deactivated in the change quarter; reject/withdraw → none), so a counter can never partially diverge from the claim change. Counters are **absolute-recomputable** from the claims (remediation for any drift). Community counters are maintained directly (= sum of groups). No Stream consumer; no backfill this release (data cleaned before deploy).
- **BR-L4 (new-in-quarter is permanent)** — the growth *New in quarter* series counts granted claims by the quarter they were **earned**, permanently; a later expiry/revoke does **not** retroactively change a past bar (FD-1=A).
- **BR-L8 (community no double-count)** — because a member holds a given certification at most once across all groups (BR-C2), credited to exactly one group, the community/all-groups figures are the sum over groups with each holding counted **once** under its credited group.

## Data access & index
- **BR-L5 (no runtime Scan)** — every runtime read (ledger page, export walk, both aggregations) is a Query on the granted index (GSI4) or a bounded set of its partitions; no runtime Scan. The **one-time backfill** migration is the only place a table Scan is permitted, and it is a maintenance operation, not a runtime path.
- **BR-L6 (granted-index retention)** — GSI4 keys (`gsi4pk = GLED#<earnedQuarter>`, `gsi4sk = <earnedDate>#<claimId>`) are written at approval and **retained through the terminal transitions to `Expired`/`Revoked`** (which update `status`/`expiresAt`/`revokedAt` in place). `Rejected`/`Withdrawn` (from `Pending`) never carry GSI4 keys. No granted claim may be left unindexed.

## Submission (amendment to a base rule)
- **BR-C5′ (mandatory earned date — amends base BR-C5, DR-6)** — `dateEarned` is now **required on every claim submission**, not only when the certification has an expiry period. It must be a valid ISO date and **not in the future**. The already-expired-at-submission guard (BR-C6) continues to apply to expiring certifications. Historical claims predating this rule keep their (possibly absent) earned date and fall back to approval date in the ledger/charts (BR-L9).

## Validation (client mirrors, server authoritative)
| Field / param | Rule |
|---|---|
| ledger `quarter` | valid `YYYY-Qn`; defaults to current |
| ledger `status` | subset of {Approved, Expired, Revoked} |
| ledger `groupId` | optional for CL; ignored/forced-to-led-group for UGL |
| ledger `certId` / `memberId` | optional; length-bounded ids |
| ledger `limit` / `cursor` | limit 1–200; cursor opaque, whitelisted key attrs only |
| stats `quarters` | small positive int (default 4) |
| stats `quarter` (snapshot) | valid `YYYY-Qn` |
| submit `dateEarned` | required (BR-C5′); ISO date; not future |

## Unchanged / inherited
- All base Unit 6 rules (BR-A*, BR-C*, BR-V*, BR-W*, BR-R*, BR-X*, BR-S*, BR-P*, BR-E*) remain in force; this surface reads the same claims and changes only what is stated above.
