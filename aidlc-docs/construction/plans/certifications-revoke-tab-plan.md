# Certifications — "Revoke" as a Tab (CL + UGL): Implementation Plan

**Unit**: 6 Certifications (deployed real service) · **Type**: change request · **Date**: 2026-08-07

## Requirement (as confirmed)
"Revoke a Certification" becomes its own tab for both Community Leaders and User Group Leaders. Answers: Q1=A (UGL may revoke, **scoped to claims credited to the group they lead**, 404 outside), Q2=A (**no self-revoke** — a UGL cannot revoke their own cert; only a CL can), Q3=A (**scoped member search** — only members of the led group), Q4=A (**move** the CL revoke widget off Definitions into its own tab), Q5=A (label **"Revoke"**, placed last).

## Resulting tab layouts
- **CL**: Pending Verifications · Definitions · **Revoke**
- **UGL**: Pending Verifications · Catalog · My Submissions · **Revoke**
- Member: Catalog · My Submissions (unchanged)

## Key design decisions
- **Revoke gains group scoping.** Today `revoke()` trusts a CL-only gate and has no scope check. `revokeClaim` becomes a `defer-group` op (like verify): the gate confirms the role holds a `revoke member-certification` rule, and the **service** enforces the binding — CL = any group, UGL = only its led group (resolved JWT-first then Identity, **fail-closed**), 404-not-403 on anything outside it (don't reveal existence).
- **No self-revoke (Q2=A).** A UGL's own approved cert is credited to their led group, so it would pass the group scope — an explicit owner guard returns 403 ("you cannot revoke your own certification"). Harmless for a CL (they can't hold claims).
- **Scoped picker without a new index (Q3=A).** The member directory already supports `GET /members?groupId=`, so the UGL's PeoplePicker is scoped to led-group members — no new certifications GSI and no scan (respects the repo's no-scan discipline). Holdings are additionally filtered client-side to the led group; the backend 404 is the real guarantee.
  - **Known limitation (documented, not fixed):** a member who *left* the group but still holds a cert credited to it won't appear in the scoped search (they're no longer on the roster). Revoke is primarily for current members; a CL retains unrestricted revoke for that case. Recorded as a follow-up.

## Tasks

### A. Backend — services/certifications
- [x] **A1. permission_matrix.json** — add to `UserGroupLeader`: `{ "action": "revoke", "resource": "member-certification", "scope": "group" }`. (CL already has it at `global`.)
- [x] **A2. authz.py** — change `OP_AUTHZ["revokeClaim"]` from `("revoke","member-certification")` to `("revoke","member-certification","defer-group")` so both CL (global) and UGL (group, service-enforced) pass the gate; Member/Admin still denied.
- [x] **A3. revocation_service.py** — inject `identity`; `revoke(...)` gains `bearer_token: str | None = None` (optional so existing CL callers/tests are unaffected). After fetching the claim: (1) **owner guard** → 403 if `claim.memberId == principal.user_id`; (2) **UGL group scope** → resolve led group (JWT-first, Identity fallback, fail-closed), 404 if `claim.creditedGroupId != led`; CL unscoped. Then the existing Approved-check + transition + event. Mirror `verification_service._led_group`.
- [x] **A4. app.py** — construct `RevocationService(self.repo, self.events, self.identity)`; pass `bearer_token=token` in the `revokeClaim` dispatch.

### B. Contract
- [x] **B1.** Update the `revokeClaim` description: CL revokes any; UGL only certs credited to their led group (404 outside); no self-revoke. No schema change (404 already declared). Contract gate stays green (no new op/field).

### C. Frontend — frontend/src
- [x] **C1. PeoplePicker.tsx** — add optional `groupId?: string`; when set, append `&groupId=` to the `/members` typeahead query (scopes results to that group).
- [x] **C2. RevokeFlow.tsx** — accept `role?` + `ledGroupId?`. For a UGL: pass `groupId={ledGroupId}` to PeoplePicker (scoped search) and filter fetched holdings to `creditedGroupId === ledGroupId`; copy notes the group scope. CL unchanged (global picker, all holdings).
- [x] **C3. DefinitionsTable.tsx** — remove the embedded `<RevokeFlow>` + its import (revoke moves to its own tab).
- [x] **C4. CertificationsPage.tsx** — add a **"Revoke"** tab (last) to both `CLView` (Pending Verifications · Definitions · Revoke) and `UGLView` (… · Revoke), rendering `RevokeFlow` with `role`/`ledGroupId`.

### D. Tests
- [x] **D1. test_authz_matrix.py** — add `revokeClaim` to the `UserGroupLeader` allowed set (gate now passes; service enforces scope). CL already allowed.
- [x] **D2. revoke scope tests** (extend `test_lifecycle.py` or a new `test_revocation_scope.py`): UGL revokes a claim credited to their led group → 200 Revoked; UGL revokes a claim credited to another group → **404**; UGL revokes their **own** approved cert → **403**; UGL with unresolvable led group → 403/deny; CL still revokes any group's claim.
- [x] **D3.** Full `make test`, `ruff`, contract gate, `npm run build`/`tsc` — all green.

### E. Docs
- [x] **E1.** `business-rules.md` BR-R1 amended (CL global + UGL led-group scope, 404 outside, no self-revoke). `frontend-components.md` — Revoke tab for CL and UGL, revoke removed from Definitions.
- [x] **E2.** `aidlc-state.md` change-request row + `audit.md` append.

## Out of scope / not doing
- No new GSI, no scan, no IaC change (picker rides the existing `/members?groupId=`; revoke rides the existing route). No deploy in this stage.
- No change to CL revoke semantics beyond relocation. Member/Admin unaffected.

## Verification checklist
- CL: Revoke is its own tab; Definitions no longer shows it; CL can revoke any member's approved cert.
- UGL: Revoke tab present; member search shows only led-group members; can revoke a group-credited cert; gets 404 for a cert credited elsewhere; cannot revoke their own (403). All gates green.
