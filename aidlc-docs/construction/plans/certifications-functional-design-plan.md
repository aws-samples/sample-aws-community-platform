# Unit 6 — Certifications: Functional Design Plan

**Stage**: CONSTRUCTION → Per-Unit Loop → Functional Design (Part 1 — Planning)
**Unit**: Unit 6 — Certifications (`/certifications`, service `services/certifications/`)
**Stories (10)**: US-5.1–5.10 (definitions, claims, credited-group verification, expiry job, revoke, badges, catalog)
**Status**: ROUND 1 ANSWERED — Q2/Q3/Q4/Q8/Q11 locked (A/A/A/B/A), Q6 = real badge-image upload. Round-2 follow-ups for Q1/Q5/Q7/Q8-edge/Q9/Q10 in `certifications-functional-design-clarification-questions.md` — AWAITING CLARIFICATIONS.

---

## Context loaded (analysis complete)

- Use case `requirements/usecases/05-certifications.md` + stories US-5.1–5.10 — 1:1 coverage, no gaps between them.
- Frozen contract `contracts/services/certifications/openapi.yaml` v1.0.0 — **scaffold-thin** (9 ops). Missing vs stories: definition fields (description/badgeImage/category/expiry), claim evidence file upload/notes/dates/reasons, `Withdrawn` status, queue filters + oldest-first, pending-count for the nav badge, badges-for-profile read, and the **`GET /certifications/claims` collection route that member-profiles' shipped FanOutClient already calls** (`memberId=&countOnly=true`, `certId=&status=Approved`, date range + `decidedAt`). Contract work will be additive where possible, corrective where already-consumed.
- Mockups: `leader/certifications.html` (Pending Verifications + Definitions tabs, define modal incl. B1 "Points awarded on approval", revoke widget), `ugl/verifications.html` (credited-group scope, C3 wording), `member/certifications.html` (Catalog cards + My Submissions + claim modal), `member/profile.html` (Verified Badges card).
- Permission matrix rows: CL create/edit/deactivate/revoke/verify (global); UGL verify (group); Member submit/view-own/display-badge (own); **Administrator holds ONLY `browse certification-catalog`** — everything else denied.
- Events to publish (reserved in contracts/README): `CertificationApproved`, `CertificationRevoked`, `CertificationExpired`. To consume: Identity's `MembershipChanged` (`MemberLeftGroup`/`MemberRemoved`, payload `{memberId, groupId, at}`) → auto-reject pending claims (US-5.4).
- Reference implementations: identity-access (OP_AUTHZ declarative map — best fit for this unit's per-op matrix rows), events (sparse-GSI mark-before-emit sweep — the shape for the daily expiry job; EventPublisher; presigned-PUT + GuardDuty evidence-upload precedent).
- Prior decisions honored: gap-analysis B1 (per-cert points field), C2 (no flat cert value in framework), C3 (credited-group wording), Option 2A (bell count read-only, not a notification).

---

## Clarifying Questions

## Question 1 — Claim status vocabulary
Stories/mockups say **"Verified"**; the frozen contract decision enum, seed fixtures, shipped CertificationsPage AND member-profiles' fan-out filter (`status=Approved`) all say **"Approved"**. Which wins on the wire?

A) Keep **"Approved"** on the wire (no breakage to member-profiles' deployed fan-out or fixtures); the UI renders it as "Verified" per the mockups. (Recommended — display-label mapping is frontend-trivial; renaming the wire value touches a deployed service.)

B) Rename the wire status to **"Verified"** everywhere and update member-profiles (directory cert filter + activity mapping), fixtures, and contract in the same change.

C) Other (please describe after [Answer]: tag below)

[Answer]: Ths issue is not clear

## Question 2 — Holding model (what IS a "member certification"?)
US-5.8 revoke and US-5.1 expiry act on a member's earned certification. Because the duplicate check is community-wide (a member can hold a given certification only once, US-5.4), `(certId, memberId)` uniquely identifies a holding.

A) **Single Claim entity with a full lifecycle**: Pending → Approved | Rejected | Withdrawn; Approved → Revoked | Expired. The "holding"/badge IS the claim in Approved state — badges, revoke, expiry, and the duplicate check all read one item. (Recommended — one source of truth, no approval-time copy to drift.)

B) Separate MemberCertification/Badge entity created at approval, claim record kept as history.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3 — Membership validation at submission
US-5.4: submitter must belong to ≥1 group and must credit a group they belong to. Identity & Access is the membership source of truth.

A) **Read-time REST to Identity** (forward the caller's own JWT, list their groups — same pattern as member-profiles' fan-out) to validate at submission; consume `MembershipChanged` events ONLY for the auto-reject rule. (Recommended — no second membership projection to keep consistent; submission is low-frequency so a sync read is cheap.)

B) Maintain a local event-sourced membership projection (consume MemberJoined/Left/Removed) and validate locally.

C) Trust the frontend's group picker and the JWT alone (no server-side membership check).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4 — UGL queue scoping (how does the service learn the caller's led group?)
US-5.6/5.7: a UGL sees/decides only claims credited to the group they lead. The permission matrix expresses this as `verify certification-claim (scope: group)`.

A) Read the led group from the caller's **JWT claims if present** (Events unit precedent: membership/lead info from claims; Identity now returns `ledGroupId` at login), **falling back to a REST lookup to Identity** when absent. Fail closed if neither resolves. (Recommended)

B) Always resolve via REST to Identity on each queue/decision call (no reliance on token contents).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5 — Evidence file upload (US-5.4: link OR file image/PDF)
The claim modal accepts a URL or an uploaded PDF/image that reviewers will open. Events already established: direct-to-S3 presigned PUT, GuardDuty Malware Protection on the foundation bucket, file gated from viewers until the scan is Clean.

A) **Reuse the Events pattern end-to-end**: presigned PUT to a certifications prefix of the scanned foundation bucket; evidence file hidden from the reviewer (and the claim held out of "reviewable" state) until the scan verdict is Clean; link evidence needs no scan. (Recommended — externally supplied files served to leaders is exactly the threat GuardDuty was added for.)

B) Link-only in v1; file upload deferred (recorded deviation from US-5.4).

C) Presigned upload without malware gating (accept the risk).

D) Other (please describe after [Answer]: tag below)

[Answer]: Evidece file will be uploaded into a pre-configured S3 bucket. Before storing the file system must change the physical filename (may be timestamp basis) to make it unique in the S3 bucket.

## Question 6 — Badge image (US-5.1 "badge image")
Mockups render badges as an emoji/icon on a gradient tile (no real photos anywhere), yet the define modal has an "Upload image" button. Real image upload means an upload flow, storage, scanning, and a serving path (badges render on catalog + profiles at high frequency, so per-render presigned GETs are a poor fit).

A) **Icon + color visual identity in v1**: leader picks an emoji/icon and accent color at define time (exactly what every mockup actually displays); recorded deviation from "upload image", upgradeable later without model change (image ref field reserved). (Recommended)

B) Real image upload now (presigned PUT + scan + serve via the SPA's CloudFront/S3 or an API proxy) — accepted extra scope in this unit.

C) Image URL string field (leader hosts the image elsewhere).

D) Other (please describe after [Answer]: tag below)

[Answer]: Leader will upload the Certifcation badge picture. 

## Question 7 — Administrator access
Use case prose: "Administrators do not have access to certification management." Permission matrix: Administrator holds exactly one row — `browse certification-catalog (global)`. Events set a blanket Admin-403 precedent, but its matrix had NO Admin rows.

A) **Follow the matrix**: Admin may call `browseCatalog` (read-only), 403 on everything else including queues, claims, definitions writes. (Recommended — matrix is the transcribed RBAC source of truth; "management" ≠ read-only catalog.)

B) Blanket Admin 403 on the whole service, treating the matrix row as an error to be corrected in the matrix.

C) Other (please describe after [Answer]: tag below)

[Answer]: Administrators do not have access to certification management. 

## Question 8 — Expiry anchor date
US-5.1: optional expiry period (e.g., 3 years); daily job notifies at T-14 days and removes the badge at expiry. From WHEN does the period count? (US-5.2 fixes that later edits don't affect already-verified holdings, so whatever the anchor, `expiresAt` freezes at approval.)

A) **Approval date** + the definition's expiry period at the moment of approval. (Recommended — deterministic, portal-verifiable; the member's "date earned" is free-text notes we cannot trust for a scheduled destructive action.)

B) Member-supplied "date earned" (from claim notes made structured) + period; fall back to approval date when absent.

C) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 9 — Revoke addressing & UX
Contract today: `POST /certifications/{id}/revoke {memberId, reason}`. Mockup: a member-search + reason widget (no cert picker). Shipped UI wrongly revokes from the definition row with no member at all.

A) **Keep the route shape, fix the semantics**: `(certId, memberId)` uniquely identifies the holding (Q2), `reason` becomes required; UI reworked to member-picker → shows that member's Approved certs → revoke one with reason. (Recommended — additive contract change, matches the mockup widget once a cert choice is added.)

B) New claim-id-addressed op (`POST /certifications/claims/{id}/revoke`) and retire the definition-scoped route.

C) Other (please describe after [Answer]: tag below)

[Answer]: Explain more

## Question 10 — Notification-driving events beyond the reserved three
Reserved events: CertificationApproved / CertificationRevoked / CertificationExpired. But US-8.15's matrix also notifies on **rejection** and **expiring-soon (T-14)**, and Notifications (still mock, unit re-scoped) will need triggers.

A) **Publish five**: add `CertificationRejected` and `CertificationExpiringSoon` schemas now, so Notifications finds every trigger it needs when built. (Recommended — authoring the schema now costs little; retrofitting a producer later costs a deploy of THIS unit.)

B) Publish only the reserved three; rejection/expiring-soon triggers solved when Notifications is designed.

C) Other (please describe after [Answer]: tag below)

[Answer]: Explain more

## Question 11 — Frontend scope for this unit
Units 3 and 4 set the precedent: the unit's code generation includes rebuilding its SPA screens to mockup fidelity (CertificationsPage today has hardcoded cert/group selects, no evidence field, no reject reason, no filters, raw IDs instead of names, revoke misplaced on definitions, badges as raw-ID pills on the profile).

A) **Full frontend rebuild in this unit** — member catalog cards + claim modal (real groups, evidence, notes) + my-submissions (withdraw/resubmit/reason), leader Pending Verifications tab (filters, oldest-first, evidence links, reject-with-reason) + Definitions tab (full define/edit modal, deactivate/reactivate) + revoke flow, profile Verified Badges card (image/name/date, click-through), nav pending-count badges. (Recommended)

B) Backend + contract only this round; frontend as a follow-up change request.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Part 1 — Planning checklist
- [x] Read unit definition (unit-of-work.md Unit 6) + story map (US-5.1–5.10)
- [x] Read use case 05, all 4 certification mockups, permission matrix, frozen contract, seed fixtures
- [x] Read cross-unit touchpoints: member-profiles fan-out calls, Contributions US-6.5 consumption, Notifications US-8.15 rows, Identity MembershipChanged schema
- [x] Read reference implementations (identity-access OP_AUTHZ; events sweep/publisher/upload patterns)
- [x] Author clarifying questions (11)
- [x] Collect answers; resolve ambiguities/contradictions (2 clarification rounds — all 17 answers resolved; final decision set D1–D11 recorded in business-logic-model.md)
- [ ] Plan approved by user (functional-design artifacts at the approval gate)

## Part 2 — Generation checklist (executes after approval)
- [x] `aidlc-docs/construction/certifications/functional-design/business-logic-model.md` — claim lifecycle state machine, verification routing, duplicate rule, expiry job model, auto-reject consumer, catalog/badge reads, event publications
- [x] `aidlc-docs/construction/certifications/functional-design/business-rules.md` — numbered BR set (authz incl. Admin rule, claim eligibility, credited-group routing, withdraw/resubmit, points-never-reversed, reassignment inheritance, evidence gating)
- [x] `aidlc-docs/construction/certifications/functional-design/domain-entities.md` — CertificationDefinition, Claim (lifecycle per Q2), supporting records (schedule/idempotency), field-level detail incl. contract deltas
- [x] `aidlc-docs/construction/certifications/functional-design/frontend-components.md` — component tree, props/state, flows, validation, endpoint map (scope per Q11)
- [x] Map all 10 stories to model elements (traceability — business-logic-model.md §12)
- [x] Update aidlc-state.md + audit.md; present completion gate
