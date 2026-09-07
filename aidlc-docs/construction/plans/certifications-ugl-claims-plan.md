# Certifications — UGL Claims Change Request: Implementation Plan

**Unit**: 6 Certifications (deployed real service) · **Type**: change request · **Date**: 2026-08-07

## Requirement (as confirmed)
A User Group Leader (UGL) can browse the Certificate Catalog like Members **and claim a certificate**. A UGL can never approve their own claim — only a Community Leader (CL) can. The Certifications page for a UGL has **three tabs**: Pending Verifications, Catalog, My Submissions.

## Confirmed answers → design decisions
| Q | Answer | Decision |
|---|---|---|
| Q1 credited group | **A** | A UGL's claim is credited to the **group they lead** (BR-C3's "must be a member" relaxed for UGLs — leadership is the credit basis). Auto-selected, not a picker. |
| Q2 self-approval | **B** | The UGL's own claim **stays visible** in their Pending Verifications queue but Approve/Reject are **disabled** for them. Backend already blocks self-decision (BR-V5); we add a server-computed `own` flag so the UI can disable + explain. Only a CL can decide it. |
| Q3 points | **B** | A UGL's approved claim earns **zero points**. Eligibility (`pointsEligible = role == Member`) is frozen on the claim at submission; approval awards `definition.points` only if eligible, else 0. Event carries `points: 0` so scoring credits nothing. |
| Q4 badges | **A** | Approved certs show as badges on the UGL profile. `VerifiedBadgesCard` is already role-agnostic (`/certifications/claims/me`); no change needed once UGLs can hold Approved claims. |
| Q5 My Submissions | **A** | Full parity: submit (URL/file evidence), withdraw pending, resubmit after terminal, see rejection reasons. Reuse the Member components. |
| Q6 default tab | **A** | UGL lands on **Pending Verifications**. |

## Key design notes / edge cases
- **Routing is unchanged (BR-V1)**: the UGL's own claim, credited to their led group, naturally lands in their own group queue (visible per Q2=B) and the CL all-groups view (decidable by CL). No new routing.
- **Self-decision** is already enforced server-side (`decide()` → 403 when `claim.memberId == principal.user_id`). This change only adds the UI affordance; the API guard stays as defense-in-depth.
- **Fail-closed led group**: if a UGL's led group can't be resolved at submit time (JWT claim absent + Identity unreachable), submission is refused (same 503 fail-closed posture as verification scope + BR-C3). A UGL with no led group cannot claim.
- **Duplicate rule (BR-C2)** and evidence/date rules apply to UGL claims unchanged.
- **Pending count badge**: the UGL's own claim is Pending in their group, so it counts in their Pending Verifications badge (consistent with what the queue table shows per Q2=B). Left as-is deliberately.

---

## Tasks

### A. Backend — services/certifications
- [x] **A1. permission_matrix.json** — add to the `UserGroupLeader` block (mirroring Member): `submit certification-claim (own)`, `view own-certification-submission (own)`, `display badge (own)`. This unlocks submitClaim, myClaims, withdrawClaim, and grantEvidenceUpload for UGL (all route through those two matrix rows; `check()` already passes `owner_id=principal.user_id`).
- [x] **A2. claim_service.submit** — branch on role: for `ROLE_UGL`, credit the **led group** (resolve `principal.led_group_id` → Identity `led_group_id()` fallback → fail-closed 503), skip the member-group check; for Member keep the existing member-group validation. Stamp `pointsEligible = (principal.role == ROLE_MEMBER)` on the claim row.
- [x] **A3. verification_service._approve** — award `points = int(definition.get("points", 0)) if claim.get("pointsEligible", True) else 0`. Default `True` preserves existing member claims with no field. `CertificationApproved` event then carries the eligibility-gated points.
- [x] **A4. verification_service.queue** — mark each queue row with a server-computed `own = (c.get("memberId") == principal.user_id)` so the UI can disable actions on the caller's own claim (only the UGL ever sees an own row).
- [x] **A5. models.py** — decided to set `own` directly in `queue()` after projection (always present, simpler) rather than touch the static `queue_claim` serializer; `pointsEligible` persists via `create_claim` (stores all non-None fields) and is documented in the submit comment. No models.py edit needed.

### B. Contract + mock
- [x] **B1.** Amended the certifications contract additively: `Claim.own: boolean`; submitClaim + `creditedGroupId` descriptions updated for UGL.
- [x] **B2.** Regenerated the mock (13 ops). Seed fixture for a UGL-owned queue claim NOT added — it only affects a mock-mode demo, not the deployed real service; recorded as a follow-up.
- [x] **B3.** Contract gate: certifications 13/13, all 12 services green.

### C. Frontend — frontend/src
- [x] **C1. App.tsx** — pass `ledGroupId={session.ledGroupId}` to `<CertificationsPage>` (route currently passes only `role`).
- [x] **C2. CertificationsPage.tsx** — give the UGL a **three-tab** view (Pending Verifications | Catalog | My Submissions), default **Pending Verifications**. Catalog is no longer `readOnly` for UGL (Submit enabled); wire `ClaimModal` + `MySubmissionsTable` for UGL exactly like the Member view. CL view unchanged (Pending Verifications | Definitions). Update the header comment.
- [x] **C3. ClaimModal.tsx** — accept `role` + `ledGroupId` (+ resolve the led group name from `/groups`). For a UGL: the "user group to credit" field is **fixed** to the led group (pre-selected, read-only), the member-groups list and the "join a group first" gate are bypassed. Member behavior unchanged.
- [x] **C4. VerificationQueue.tsx** — accept the current user's own-row signal via the server `own` flag: when `c.own`, render Approve/Reject **disabled** with a hint ("Your own claim — a Community Leader will verify it"). CL rows never have `own=true`.
- [x] **C5.** Confirmed `VerifiedBadgesCard` is role-agnostic (own profile → `/certifications/claims/me`); no change needed — a UGL's Approved claims render once they can hold them.

### D. Tests
- [x] **D1. test_authz_matrix.py** — update the expected UGL permission set to include `submitClaim`, `myClaims`, `withdrawClaim`, `grantEvidenceUpload`.
- [x] **D2. claim_service tests** (in new `test_ugl_claims.py`) — UGL submit credits the led group (not a member group); UGL with no resolvable led group → 503; `pointsEligible=False` stamped for UGL, `True` for Member.
- [x] **D3. verification tests** (in new `test_ugl_claims.py`) — UGL's own claim appears in their queue with `own=true`; UGL self-approve → 403 (BR-V5 still holds); CL can approve a UGL claim and it awards **0** points (event `points=0`), while a Member claim still awards `definition.points`.
- [x] **D4.** Full repo `make test` green (certifications 102, no sibling regressions), `ruff` clean, contract gate 12/12, `npm run build`/`tsc` clean. (cfn-lint N/A — no IaC change.)

### E. Docs
- [x] **E1.** `business-rules.md` amended: BR-A2/BR-A3 (submitters now Members + UGLs), BR-C3 (led-group credit basis for UGLs), BR-V6 (`pointsEligible` gate). `frontend-components.md` UGL tree updated to the 3-tab UI.
- [x] **E2.** `aidlc-state.md` change-request row added; `audit.md` appended.

## Out of scope / not doing
- No change to routing, revocation, expiry, or the CL/Member experiences.
- No IaC change (no new resources, GSIs, or IAM — submit/queue ride existing routes and the existing Identity fan-out).
- No deployment in this stage (code + gates only); deploy is a separate user-directed step, consistent with prior units.

## Verification checklist (definition of done)
- UGL: Catalog shows Submit; can submit a claim credited to their led group; claim appears in My Submissions and in their own Pending Verifications queue as non-decidable; a CL can approve it; approval awards 0 points but shows the badge on the UGL profile.
- Member and CL flows unchanged; all gates green.
