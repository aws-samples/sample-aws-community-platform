# Infrastructure Design Plan — Certification Ledger + CL/UGL Dashboard Charts

**Unit**: Unit 6 (Certifications)
**Inputs**: `certification-ledger-requirements.md` (APPROVED) · `certifications/functional-design/certification-ledger-*.md` (APPROVED) · base `certifications/infrastructure-design/` · deployed `.deploy-staging/service-certifications-{data,app}.yaml`
**NFR Design**: skipped per the execution plan (baseline unchanged); the new NFR-relevant concerns are handled here + in Functional Design.

## What the code inspection already settled (so the plan is grounded)
- The deployed `-data` table already defines **GSI1, GSI2, GSI3** (all `ProjectionType: ALL`). This feature adds **one** GSI → **GSI4**. DynamoDB allows one GSI change per `UpdateTable`, so 3→4 is a **single** staged `UpdateTable` (not the 0→3 staging the base doc described).
- The `-app` Lambda role's `OwnTables` statement already grants `dynamodb:Query` on `table/${TableName}` **and** `table/${TableName}/index/*` → **GSI4 reads need no IAM change**.
- The role has **no `dynamodb:Scan`** permission (deliberate — no runtime Scan). A backfill that enumerates existing claims by Scan therefore must **not** run under the runtime Lambda role unless we add Scan.
- New endpoints (`/certifications/ledger`, `/stats/growth`, `/stats/snapshot`) ride the existing `/certifications {proxy+}` route + `ApiInvokePermission /*/*` → **no api-edge regeneration, no new route/CFN resources**.
- The submission change (mandatory earned date) is **code-only** (no infra).

**Net infra change**: add GSI4 to `-data`; choose a backfill runner; possibly tune Lambda size for the growth aggregation; possibly add a monitoring alarm. Everything else is unchanged.

---

## Part 1 — Clarifying questions (please answer)

Each has a recommended default; answering "go with recommendations" is fine.

### Question ID-1 — GSI4 projection type
The ledger and both charts read a fixed set of fields (memberId, memberName, certId, certName, certCategory, creditedGroupId/name, status, dateEarned, decidedAt, expiresAt, revokedAt).

A) **`ProjectionType: ALL`** — consistent with GSI1–GSI3 (all ALL); simplest; no risk of a missing attribute forcing a base-table read. Slightly higher index storage/write cost.

B) **`ProjectionType: INCLUDE`** with exactly the ~11 attributes above — leaner storage/writes, but must be kept in sync if a new column is ever added.

X) Other (describe after [Answer]:)

[Answer]:

### Question ID-2 — Backfill runner (populate GSI4 on existing granted claims)
Existing Approved/Expired/Revoked claims need `gsi4pk`/`gsi4sk` written once. Enumerating them is a one-time Scan.

A) **Standalone operator migration script** (like the existing `infra/tools/stage_*_gsis.py` / `wait_for_gsi.sh`), run with deploy/admin credentials after the GSI is ACTIVE. Idempotent (writes keys only when absent). **Runtime Lambda gets no new permission** (no `dynamodb:Scan` grant) — keeps least privilege and the no-runtime-Scan rule intact. *(Recommended.)*

B) **A one-time job branch on the certifications Lambda** (`{"job":"backfill-granted"}`, invoked manually once) — reuses the deployed code but requires adding `dynamodb:Scan` to the runtime role (a standing permission for a one-time need).

C) **CloudFormation custom resource** that runs the backfill automatically on deploy — most automated, but adds a custom-resource Lambda + rollback complexity for a one-shot task.

X) Other (describe after [Answer]:)

[Answer]:

### Question ID-3 — Deploy sequencing & history completeness
Until the backfill finishes, the ledger/charts return only claims granted/updated after GSI4 exists (historical rows appear once backfilled).

A) **One coordinated deploy, gated ordering**: (1) deploy `-data` with GSI4 → wait ACTIVE (`wait_for_gsi.sh`); (2) run the backfill to completion; (3) the ledger/stats endpoints + frontend are then serving complete history. Ship backend + frontend together; the tab/charts are only exposed to users after backfill completes. *(Recommended.)*

B) Ship the GSI + endpoints + frontend immediately and let the backfill run in the background (users may briefly see incomplete history for older quarters).

X) Other (describe after [Answer]:)

[Answer]:

### Question ID-4 — Lambda sizing for the growth aggregation
Chart 1's *Total* line reads granted items across multiple quarter partitions in memory. Current function: 256 MB / 15 s.

A) **Keep 256 MB / 15 s**; the aggregation is bounded (thousands of claims / tens of certs) and index-only. Revisit only if a latency/timeout alarm fires. *(Recommended.)*

B) **Bump to 512 MB / 20 s** for headroom on the stats path now.

X) Other (describe after [Answer]:)

[Answer]:

### Question ID-5 — Monitoring for the new endpoints
A) **Reuse the existing alarms** — the function-level `Errors`/`Throttles` and the API `5XXError` alarm already cover the new routes; add nothing. *(Recommended.)*

B) **Add a dedicated latency alarm** on the ledger/stats path (e.g. p95 duration) in addition.

X) Other (describe after [Answer]:)

[Answer]:

---

## Part 2 — Infrastructure Design artifact checklist (executed after answers)

Artifacts under `aidlc-docs/construction/certifications/infrastructure-design/` (feature-scoped, extending the base files):

- [x] `certification-ledger-infrastructure-design.md`
  - `-data` delta: GSI4 definition (`gsi4pk`/`gsi4sk` attribute defs + index, projection per ID-1), single staged `UpdateTable` (3→4) with `wait_for_gsi` discipline.
  - Backfill design (per ID-2): runner, idempotency, one-time-Scan justification, rollback.
  - `-app`: confirm no IAM/route change (GSI4 covered by `index/*`; `{proxy+}` covers routes); sizing per ID-4; monitoring per ID-5.
  - Contract/permission: additive OpenAPI + permission-matrix rows (no api-edge regen).
  - Security/compliance mapping (SECURITY-06/08, no-Scan, PITR covers GSI4).
- [x] `certification-ledger-deployment-architecture.md`
  - Deploy sequence (per ID-3): GSI add → wait ACTIVE → backfill → expose endpoints/frontend; rollback (roll handler/bundle back; GSI additive/safe to retain; backfill re-runnable).
  - Mock→real note (service already `complete`; contract regen + gate).
- [x] Update `aidlc-state.md` (Infrastructure Design complete) + log in `audit.md`.

## Requirement traceability
| Item | Covered by |
|---|---|
| DR-1 (granted GSI) | GSI4 in `-data` |
| DR-2 (retained keys) | code (transition writes) — infra confirms projection covers status/expiresAt/revokedAt |
| DR-3 (backfill) | backfill runner (ID-2) + deploy sequence (ID-3) |
| DR-7 (endpoints) | no api-edge/route change (rides `{proxy+}`) |
| NFR-1 (no-Scan runtime) | GSI4 reads only; Scan confined to one-time backfill off the runtime role |
| NFR-4 (resiliency) | GSI4 under existing PITR; idempotent re-runnable backfill; additive/safe rollback |

---

## Resolved (brainstorm, 2026-08-12)

Scale input from the user: **30k–200k total granted claims (all history)**, **20–30 certification definitions**, **<10 user groups**, development stage (existing data will be cleaned).

- **ID-1 = `ALL`** — GSI4 projected ALL (consistent with GSI1–3). Nothing bulk-reads GSI4 once charts move to a rollup, so no read-cost reason for INCLUDE.
- **Charts → maintained rollup (A5→B).** The 30k–200k volume makes live active-window aggregation on every dashboard load too costly, but the aggregate space (scopes × certs × quarters) is tiny. Counters maintained **inside the transactional transition writes** (no Stream consumer). This reshaped the Functional Design (business-logic §6a, business-rules BR-L10, domain-entities §1a — all amended 2026-08-12).
- **ID-2 = no backfill this release.** Dev data cleaned before deploy (enforced by the `clean-cert-data-before-deploy` agent hook). Prod backfill (GSI4 keys + counter recompute) is a **deferred follow-up**.
- **ID-3 = sequence**: clean data → deploy `-data` GSI4 & `wait_for_gsi` ACTIVE (single `UpdateTable`, 3→4) → deploy `-app` (endpoints + inline counter maintenance + mandatory earned date) → ship frontend. No drift window (data cleaned). Rollback = redeploy handler (GSI additive).
- **ID-4 = keep 256 MB / 15 s.** Charts read tiny rollups; ledger reads one page at a time. Watch-item: pathological rare-cert filter in a huge quarter partition (user-initiated, still < 15 s).
- **ID-5 = reuse existing alarms** (Errors/Throttles/5xx). Counter integrity guaranteed by transactionality (BR-L10) + absolute-recompute remediation; a reconciliation alarm would reintroduce the bulk read the rollup avoids.

Artifacts below are generated against these decisions.
