# Unit 6 — Certifications: Business Rules

Numbered rule set. Enforced in-service, fail-closed (SECURITY-08). Wire status vocabulary: `Pending | Approved | Rejected | Withdrawn | Revoked | Expired` (D1: UI displays `Approved` as "Verified").

## A — Authorization (boundary + per-operation)

- **BR-A1 (Admin blanket ban, D7)**: a caller with role `Administrator` receives **403 on every operation of this service**, including catalog browse. The permission matrix's `Administrator: browse certification-catalog` row is removed in this unit (matrix version note recorded). Same boundary shape as the Events unit.
- **BR-A2 (per-op matrix)**: every operation maps to a matrix row via a declarative `OP_AUTHZ` map (identity-access pattern): create/edit/deactivate certification + revoke → CL global; verify (queue + decision) → CL global / UGL group; submit + myClaims + withdraw → Member **and UGL** own (UGL added by the change request below); catalog browse + public claim reads → any authenticated non-Admin.
- **BR-A3 (submitters, amended 2026-08-07)**: claim submitters are **Members and User Group Leaders**. Community Leaders and Administrators still cannot submit claims, hold badges, or appear as claim owners. A UGL's claim differs from a Member's in three ways: it is credited to the group the UGL **leads**, not one they belong to (see BR-C3, Q1=A); it earns **zero points** on approval while still holding the badge (BR-V6/`pointsEligible`, Q3=B); and although it appears in the UGL's own verification queue (routing is by credited group), the UGL can **never decide it** — only a CL can (BR-V5, Q2=B). Both Members and UGLs can therefore have profile badges (US-5.9).
- **BR-A4 (UGL scope, D4)**: UGL queue/decision scope = claims with `creditedGroupId == callerLedGroupId`, resolved from JWT claims first, REST to Identity as fallback; **unresolvable led group → deny (fail closed)**, never "all groups".
- **BR-A5 (owner-only)**: `myClaims`, withdraw, and evidence re-upload act only on the caller's own claims (IDOR guard: claim owner checked against the token subject, 404 on other people's claim ids — not 403, don't confirm existence).

## C — Claim eligibility & submission

- **BR-C1 (active definitions only)**: claims are accepted only for `active` certifications; deactivated ones are hidden from the submission list AND rejected server-side (409) — UI hiding is not enforcement.
- **BR-C2 (community-wide duplicate rule)**: a new claim for `(certId, memberId)` is blocked (409) while any claim for that pair is `Pending` or `Approved`, regardless of group. `Rejected`, `Withdrawn`, `Revoked`, `Expired` do not block. One badge per certification per member, ever-current.
- **BR-C3 (credit basis, D3; amended 2026-08-07)**: for a **Member**, the submitter must belong to ≥1 group (else 422 → UI "join a group first" prompt) and `creditedGroupId` must be one of the submitter's current groups (else 400), validated read-time against Identity with the caller's own JWT. For a **UGL** (Q1=A), the claim is credited to the group the UGL **leads** — resolved JWT-first then Identity, independent of membership — and the client-supplied `creditedGroupId` is overridden with the resolved led group. In both cases Identity being unreachable (or, for a UGL, an unresolvable led group) → 503, submission fails closed (a claim credited to an unverified group would corrupt routing and points attribution).
- **BR-C4 (evidence, exactly one)**: `evidenceUrl` XOR `evidenceFileKey`. URL must be http(s). File must originate from this unit's presigned-upload step (key prefix + ownership checked), pdf/png/jpg/jpeg only.
- **BR-C5 (dateEarned, D8)**: required when the chosen certification has an expiry period, optional otherwise; ISO date; must not be in the future.
- **BR-C6 (already expired at submission, C4=A)**: if `dateEarned + expiryPeriod ≤ today`, submission is rejected (422, "This certification has already expired") and never enters a queue.
- **BR-C7 (unique physical filename, D5)**: uploaded files are stored under a system-generated unique key (`certifications/evidence/{memberId}/{timestampMs}-{random}.{ext}`); the user's original filename is display metadata only, never a storage key.

## V — Verification & decisions

- **BR-V1 (routing)**: a claim is routed solely by `creditedGroupId` — it appears in exactly one group's queue (plus the CL all-groups view). No per-leader assignment is ever stored, so **UGL removal/assignment reassigns queues implicitly and instantly** (US-5.7 mirror of US-6.9): CLs and co-leaders retain visibility; a new UGL inherits by definition; none orphaned.
- **BR-V2 (queue order & filters)**: pending queues sort **oldest-first by `submittedAt`**; filterable by certification (CL+UGL) and by group (CL only).
- **BR-V3 (reviewable gate, D5)**: a claim is decidable only while `Pending` AND `scanStatus ∈ {None, Clean}`. `PendingScan` claims are visible in the queue as "awaiting scan" but not decidable; `Quarantined` claims never appear in queues and are flagged to the owner for re-upload.
- **BR-V4 (decision integrity)**: `approve` or `reject`; **reason required on reject** (400 without); reason ≤ 500 chars; decisions are conditional on current state (`Pending` → else 409); decider + timestamp stamped.
- **BR-V5 (no self-decision)**: the decider must not be the claim owner (guards role-change races).
- **BR-V6 (freeze at approval)**: on approve, the claim permanently freezes `pointsAwarded` and `expiresAt` (D8 anchor + definition's current expiry period). Later definition edits never alter approved claims (US-5.2). **Points eligibility (Q3=B, 2026-08-07)**: the frozen `pointsAwarded` is the definition's per-cert value only when the claim's `pointsEligible` flag (stamped at submission = `role == Member`) is true; a UGL's claim freezes `pointsAwarded = 0` while still becoming a badge-holding `Approved` claim. The `CertificationApproved` event carries the eligibility-gated points, so downstream scoring credits nothing for a UGL. The flag defaults true for pre-change claims that lack it.
- **BR-V7 (expired-at-approval guard)**: if the frozen `expiresAt` computation yields a past date (definition's period changed since submission), the approval is refused (409) — the leader rejects with that explanation instead; a badge must never be born expired.

## W — Withdraw & resubmission

- **BR-W1**: withdraw is owner-only and `Pending`-only (409 otherwise); requires UI confirmation; → `Withdrawn`; removed from queues; no badge/points; no rejection reason shown; no event published.
- **BR-W2**: resubmission after `Rejected/Withdrawn/Revoked/Expired` is an ordinary new claim (BR-C2 permits); rejected claims keep their reason visible to the owner for context.

## R — Revoke

- **BR-R1 (D9; amended 2026-08-07)**: claim-addressed (`/claims/{claimId}/revoke`), target must be `Approved` (409 otherwise), **reason required**. Revoke is now scoped like verification: a **Community Leader** may revoke any claim; a **User Group Leader** may revoke only claims **credited to the group they lead** (led group resolved JWT-first then Identity, fail-closed; **404-not-403** outside it), and **never their own** certification (403, mirrors BR-V5). `revokeClaim` is a `defer-group` op — the gate confirms the role holds the `revoke member-certification` rule and the service enforces the group binding. Surfaced as a dedicated **Revoke** tab for both CL and UGL.
- **BR-R2 (points retained)**: revocation never reverses points (US-5.8); the published event states `pointsReversed: false` explicitly so downstream consumers cannot mis-infer.
- **BR-R3**: revocation removes the badge everywhere immediately (badge reads filter `Approved`) and notifies the member with the reason (via `CertificationRevoked`).

## X — Expiry

- **BR-X1**: only `Approved` claims with `expiresAt` participate in expiry; the daily sweep's work set is index-bounded (proportional to expiring holdings, never a table walk).
- **BR-X2 (T-14 notice)**: exactly one expiring-soon notice per holding, guaranteed by a conditional mark **before** the event is emitted (mark-before-emit; the failure direction is a lost notice, never a duplicate).
- **BR-X3 (expiry action)**: at `expiresAt ≤ now`, conditional transition `Approved → Expired` + `CertificationExpired`; badge removed; **points retained** (US-5.1).
- **BR-X4**: expiry state changes are never destructive deletes — the claim row remains as history and unblocks resubmission (BR-C2).

## S — System consumer (auto-reject)

- **BR-S1**: on `MemberLeftGroup`/`MemberRemoved` for `(memberId, groupId)`: every `Pending` claim of that member credited to that group → `Rejected`, system reason **"No longer a member of the credited group"**, `decidedBy=system`; `CertificationRejected` published per claim (`system: true`).
- **BR-S2**: consumer is idempotent on the envelope id; reads only documented payload fields; malformed events are logged and dropped, never guessed at.
- **BR-S3**: `Approved` claims are untouched by membership changes — leaving a group does not un-earn a certification.

## P — Privacy & reads

- **BR-P1 (public projection)**: to anyone but the owner, only `Approved` claims are visible (badge data: cert name/image/category, date earned, decidedAt). Pending/Rejected/Withdrawn/Revoked/Expired claims, evidence, notes, and reasons are owner-only — except that the scoped reviewer sees Pending claims' member/group/cert/evidence/date (US-5.6 fields) in the queue.
- **BR-P2 (evidence access)**: evidence file URLs are minted per request (short-lived), only for the claim owner or a reviewer in scope (BR-A4), and only while scan-Clean; never stored, never in list payloads.
- **BR-P3 (counts are queries)**: the nav pending-count and bell count are computed on the fly (Option 2A) — never stored notifications, never emailed, not part of US-8.15.

## E — Events & audit

- **BR-E1**: events publish **post-commit, best-effort** — a publish failure never fails the committed write (repo-wide convention).
- **BR-E2**: five event types (D10), schema'd under `contracts/services/certifications/published-events/`, enveloped per `platform/event-envelope.v1.json`.
- **BR-E3 (audit)**: decisions, revocations, auto-rejects, and definition writes are audit-logged (actor, action, target, reason) per the CloudWatch audit convention (US-1.13).

## Recorded deviations & cross-unit edits
| Item | Nature |
|---|---|
| Admin catalog browse removed (D7) | Deliberate deviation from the permission matrix as transcribed; matrix file edited in this unit (no other service reads that row today — verified in the context brief). Use-case prose ("no access") wins. |
| Wire "Approved" vs story "Verified" (D1) | Display-label mapping in the SPA; recorded, no requirement change. |
| Badge image upload (D6) | Honors US-5.1 "badge image" literally; mockups' emoji tiles treated as placeholder art. |
| Revoke route change (D9) | Breaking contract change (certifications v1.0.0 → v2.0.0); old `POST /certifications/{id}/revoke` retired; shipped mock UI's revoke was already wrong, rebuilt under D11. |
| `dateEarned` structured field (D8) | Upgrades US-5.4's "optional notes (e.g., date earned)" into a validated field when expiry applies; notes remain free-text. |
