# Unit 6 — Certifications: Business Logic Model

**Stage**: CONSTRUCTION → Functional Design. Technology-agnostic business logic. Companions: `business-rules.md` (BR-x), `domain-entities.md` (E-x + contract deltas), `frontend-components.md`.

## Confirmed design decisions (from the approved plan + clarifications)
| # | Decision |
|---|---|
| D1 | Wire status for an approved claim is **"Approved"**; the UI renders it as **"Verified"** (mockup wording). No change to the deployed member-profiles fan-out. |
| D2 | **Single Claim entity with a full lifecycle** — the "holding"/badge IS the claim in `Approved` state. No separate MemberCertification entity. |
| D3 | Membership validated at submission by **read-time REST to Identity & Access** (caller's own JWT forwarded). `MembershipChanged` events consumed ONLY for the auto-reject rule. |
| D4 | UGL scoping reads **`ledGroupId` from JWT claims when present, REST fallback to Identity, fail closed**. |
| D5 | Evidence files go to the **GuardDuty-scanned upload bucket** under a certifications prefix; the system assigns a **unique physical filename** (original name kept as display metadata); a claim with a file is **not reviewable until the scan verdict is Clean**. |
| D6 | **Real badge-image upload** by the leader (same scanned-bucket + unique-name rules); mockup emoji tiles are placeholder art. |
| D7 | **Blanket Administrator 403 on the entire service.** The permission matrix's `Administrator: browse certification-catalog` row is removed as an error (matrix file edit in this unit's scope). |
| D8 | Expiry anchored on the **member-supplied `dateEarned`** (structured claim field, required when the chosen certification has an expiry period, not-in-future) + the definition's expiry period, **frozen into `expiresAt` at approval**; fallback anchor = approval date if `dateEarned` absent. **Already-expired claims are blocked at submission.** |
| D9 | Revoke is **claim-addressed**: `POST /certifications/claims/{claimId}/revoke`; the definition-scoped revoke route is retired (breaking contract change → v2.0.0). |
| D10 | **Five published events**: `CertificationApproved`, `CertificationRejected`, `CertificationRevoked`, `CertificationExpiringSoon`, `CertificationExpired`. |
| D11 | **Full frontend rebuild** of the certifications screens + profile badges in this unit. |

---

## 1. Claim lifecycle (the core state machine)

```
                     submitClaim (member)
                            |
                            v
         +-----------[ Pending ]------------------------------+
         |                |         \                          \
         |  (file only)   |          \ withdrawClaim (owner)    \ MembershipChanged
         |  scanStatus:    |           v                          consumer (system)
         |  PendingScan -> |      [ Withdrawn ]                    v
         |  Clean |        |                                  [ Rejected ]
         |  Quarantined    |                                  (system reason)
         |                 v
         |        decideClaim (CL / led-group UGL)
         |            /             \
         |           v               v
         |     [ Approved ]     [ Rejected ] (reason required)
         |          |    \
         |          |     \ revokeClaim (CL, reason required)
         |          |      v
         |          |   [ Revoked ]
         |          v
         |    daily expiry sweep (system, only when expiresAt set)
         |          |-- T-14: expiringNoticeSent + CertificationExpiringSoon
         |          v
         |      [ Expired ]
```

- **Terminal states**: `Withdrawn`, `Rejected`, `Revoked`, `Expired`. None are deleted — full history retained; the duplicate check and "resubmit" affordances read them.
- **The badge is the claim in `Approved` state.** Badge display (US-5.9), the catalog "Held" flag (US-5.10), the directory cert filter (member-profiles), revoke and expiry all read this one item — nothing is copied at approval (D2).
- `scanStatus` is a **sub-state of Pending, not a lifecycle state**: `None` (link evidence) | `PendingScan` | `Clean` | `Quarantined` (3-state machine + absent, mirroring the Events unit's J3 lesson — transient and terminal verdicts must be distinguishable). A Pending claim is **reviewable** only when `scanStatus ∈ {None, Clean}` (BR-V6). Quarantined claims are flagged to the owner for re-upload and never appear in a queue.
- All transitions are **conditional writes on the current state** (illegal transition → 409), the same discipline that caught the Events `cancel()` defect.

## 2. Submission flow (US-5.4)

1. **Boundary authz**: caller must be role `Member` (CL/UGL/Admin cannot submit — BR-A3).
2. **Membership check (D3)**: service calls Identity (`GET /groups?mine=true` semantics, caller's JWT forwarded). Zero groups → 422 with the "join a group first" signal the UI renders as a prompt. `creditedGroupId` not among the caller's groups → 400.
3. **Duplicate rule (BR-C2)**: any existing claim for `(certId, memberId)` in `Pending` or `Approved` — across ALL groups — blocks with 409. `Rejected/Withdrawn/Revoked/Expired` do not block.
4. **Definition gate**: certification must exist and be `active` (deactivated certs are hidden from submission and rejected server-side, BR-C1).
5. **`dateEarned` (D8)**: required when the definition has an expiry period; must not be in the future; **`dateEarned + expiryPeriod ≤ now` → 422 "This certification has already expired"** (C4=A — never enters a queue).
6. **Evidence (BR-C4)**: exactly one of `evidenceUrl` OR `evidenceFileKey` (from the presigned-upload step, §3). Optional `notes`.
7. Claim written as `Pending` (with `scanStatus=PendingScan` when a file is attached), confirmation returned. No event published on submission (nothing consumes it; the leader queue is a query, not a notification — Option 2A).

## 3. Evidence & badge-image uploads (D5/D6)

Two-step, mirroring the Events materials pattern:

1. `POST /certifications/evidence-uploads` (member) / `POST /certifications/badge-uploads` (CL): service generates a **unique object key** — `certifications/evidence/{memberId}/{timestampMs}-{random}.{ext}` (resp. `certifications/badges/...`) — satisfying the "system renames the physical file" rule, and returns a short-lived presigned PUT. The **original filename travels only as display metadata**; extension whitelist: evidence = pdf/png/jpg/jpeg, badge = png/jpg/jpeg/svg-excluded (script risk).
2. The client PUTs the file, then references `fileKey` (+ `fileName`) in `submitClaim` / `createCert`.
3. **Scan verdict consumer**: GuardDuty verdict events for this unit's prefixes stamp `scanStatus` on the owning claim/definition via a fileKey→owner pointer (same pointer-item trick as Settings' FILEKEY). `Clean` → reviewable/servable; `Quarantined` → claim flagged for re-upload (definition: image rejected, definition stays with no image until re-upload).
4. **Presigned GETs are minted per request and never stored** (reviewer opens evidence via `GET /certifications/claims/{id}/evidence-url`; badge images resolve through short-lived URLs embedded in catalog/badge responses). Mechanism details (CDN vs presign for badge render frequency) belong to NFR/Infrastructure Design.
5. Orphaned uploads (file PUT but claim never submitted) are invisible to all reads and cleaned by storage lifecycle — noted for Infrastructure Design.

## 4. Verification queue & decisions (US-5.6/5.7)

- **Queue = a query over Pending+reviewable claims**, never a stored work-list:
  - CL → all groups; UGL → `creditedGroupId == callerLedGroupId` (D4); filters by certification and (CL only) group; **oldest-first by `submittedAt`** (BR-V2).
  - **Leader-change reassignment (US-5.7 / mirrors US-6.9) falls out of the model for free**: routing is purely `creditedGroupId`-based, so a newly assigned UGL's queue query immediately returns the group's pending claims and a removed UGL loses them — nothing stored per-leader, nothing orphaned, no event consumption needed for reassignment.
- **Pending count for the nav badge**: same query with `countOnly=true` — computed on the fly, not a stored notification (Option 2A).
- **Decision** (`approve` | `reject`, reason required on reject — BR-V4):
  - Guard: claim `Pending` AND reviewable; decider passes the CL/UGL scope rule; decider must not be the claim owner (defense-in-depth: leaders can't submit anyway, but a role change mid-flight shouldn't allow self-approval — BR-V5).
  - **Approve**: compute `expiresAt` (D8: anchor `dateEarned` else `decidedAt`, + the definition's expiry period **as of approval**; if the result is already past → 409, leader rejects instead — BR-V7); stamp `decidedAt/decidedBy`, `pointsAwarded` = the definition's **current per-cert value frozen onto the claim** (the ledger-bound number must not drift if the definition is re-priced later); transition → `Approved`; publish `CertificationApproved` (Contributions auto-award, US-6.5). Member notified via the event (email + in-portal when Notifications is real).
  - **Reject**: stamp reason; → `Rejected`; publish `CertificationRejected`.

## 5. Withdraw & resubmit (US-5.5)

- **Withdraw**: owner-only, `Pending`-only (409 otherwise), UI confirmation; → `Withdrawn`; disappears from queues (query filters on Pending); no badge, no points, no rejection reason displayed; no event (US-8.15 has no withdrawn row — the member did it themselves).
- **Resubmit** is simply a new `submitClaim` — permitted by the duplicate rule after `Rejected/Withdrawn/Revoked/Expired`. The UI's "Resubmit" button pre-fills from the old claim.

## 6. Revoke (US-5.8, D9)

`POST /certifications/claims/{claimId}/revoke` — CL-only, target must be `Approved` (409 otherwise), `reason` required. → `Revoked`, stamp `revokedAt/revokedBy/revokeReason`; badge disappears (all badge reads filter `Approved`); **points NOT reversed** (this service publishes no compensating event, and `CertificationRevoked`'s schema carries a `pointsReversed: false` constant to make the contract explicit for Contributions); publish `CertificationRevoked` (member notified with reason). UI flow: member picker → that member's Approved certifications → revoke one with reason.

## 7. Auto-reject consumer (US-5.4, D3)

Consumes Identity's `MembershipChanged` envelope types **`MemberLeftGroup` and `MemberRemoved`** (payload `{memberId, groupId, at}`; `MemberJoinedGroup` ignored):
- Idempotent on the envelope id (run-once store, same pattern as every consumer in this repo).
- For each `Pending` claim of `memberId` credited to `groupId`: → `Rejected` with the **system reason "No longer a member of the credited group"**, `decidedBy = system`; publish `CertificationRejected` per claim (member must learn why their claim vanished). Member may resubmit crediting a current group.
- Reads only the documented payload fields; malformed events logged and dropped (Events-unit lesson: never fall back to envelope fields).

## 8. Daily expiry job (US-5.1, D8)

Daily scheduled sweep (EventBridge Scheduler → this service's Lambda, router branch — same single-Lambda convention as Units 3/4/11). Work is a **bounded query over a sparse expiry index** (index key exists only on `Approved` claims that have `expiresAt` — proportional to expiring holdings, not table size), window `expiresAt ≤ now + 14d`:

- **T-14 notice**: `expiringNoticeSent` unset → conditionally set it (**mark-before-emit** — the Events reminder lesson: claim the record first so two sweeps can't double-fire; losing one notice beats sending two) → publish `CertificationExpiringSoon`.
- **Expiry**: `expiresAt ≤ now` → conditional transition `Approved → Expired` → publish `CertificationExpired`. Badge disappears from profile/catalog/directory immediately (reads filter `Approved`); **points retained** (US-5.1).
- Sweep is naturally idempotent: both actions are conditional writes; a crash between mark and emit loses at most one notification, never duplicates a state change.
- Daily cadence satisfies "runs daily"; a claim revoked between notice and expiry simply drops out of the window (`Approved` filter).

## 9. Catalog, badges, and public claim reads (US-5.9/5.10 + member-profiles contract debt)

- **Catalog** (`browseCatalog`, any authenticated non-Admin): active definitions with image/name/description/category/points; per-caller enrichment: `held` (caller has an `Approved` claim) + that claim's `expiresAt` (mockup's "expires in 2y 5m" countdown) + `pendingClaim` flag (drives "you can't submit a duplicate" affordance). Inactive definitions are excluded here but still resolve for badge display (holders keep badges, US-5.3).
- **Badges on a profile** (US-5.9): `Approved` claims of the member joined with definition name/image, **ordered by date earned (newest first, anchor = `dateEarned` else `decidedAt`)**; click-through detail = name, description, date earned. Only Members have badges — leaders/admins can't hold claims by construction (BR-A3).
- **`GET /certifications/claims` collection route** — the contract debt member-profiles' deployed FanOutClient already calls:
  - `?memberId=X&countOnly=true` → count of X's **Approved** claims (activity-summary tile).
  - `?memberId=X[&from=&to=]` → X's Approved claims with `decidedAt` (activity feed + badges for the profile screen).
  - `?certId=Y&status=Approved` → holder list for the directory's cert filter.
  - **Privacy rule (BR-P1)**: when the caller is not the subject, this route serves **only the Approved (public-badge) projection** — Pending/Rejected/Withdrawn/Revoked/Expired claims, evidence, notes and reasons are never visible to anyone but the owner (owner uses `myClaims`) and, for Pending evidence, the scoped reviewer.

## 10. Published events (D10) — payload intent

All wrapped in `platform/event-envelope.v1.json`, post-commit best-effort (never fail a committed write), schemas authored under `contracts/services/certifications/published-events/`:

| Event | When | Payload (data) | Consumers |
|---|---|---|---|
| `CertificationApproved` | leader approve | `claimId, certId, certName, memberId, groupId (credited), points, dateEarned?, expiresAt?, decidedAt` | Contributions (auto-award US-6.5: per-cert `points`, credited `groupId`), Notifications (later), Analytics |
| `CertificationRejected` | leader reject or system auto-reject | `claimId, certId, certName, memberId, groupId, reason, system (bool), decidedAt` | Notifications (later) |
| `CertificationRevoked` | CL revoke | `claimId, certId, certName, memberId, groupId, reason, pointsReversed (const false), revokedAt` | Notifications (later), Analytics |
| `CertificationExpiringSoon` | sweep T-14 | `claimId, certId, certName, memberId, expiresAt` | Notifications (later) |
| `CertificationExpired` | sweep at expiry | `claimId, certId, certName, memberId, expiredAt, pointsReversed (const false)` | Notifications (later), Analytics |

## 11. Definition management (US-5.1/5.2/5.3)

- **Create** (CL): name, description, category (`AWS Certification` | `Community Badge`), **points awarded on approval** (per-cert, ≥ 0 — gap-analysis B1/C2), optional expiry period (months), optional badge image (upload flow §3). Published immediately (`active=true`).
- **Edit** (CL): all of the above. **Changes never touch existing claims** (US-5.2): `pointsAwarded` and `expiresAt` were frozen onto claims at approval; name/image changes DO reflect in badge display (display joins the definition — renaming a cert renames the badge everywhere, the natural reading of "update details").
- **Deactivate / Reactivate** (CL): `active` flag. Inactive → hidden from catalog/submission, new claims 409, **pending claims already in queues remain decidable** (the leader may still honor an in-flight claim; nothing in US-5.3 rejects them), holders keep badges.

## 12. Story traceability

| Story | Where in the model |
|---|---|
| US-5.1 | §11 create + §8 expiry job + D8 anchor + B1 per-cert points |
| US-5.2 | §11 edit (frozen-at-approval rule) |
| US-5.3 | §11 deactivate/reactivate + §9 catalog exclusion |
| US-5.4 | §2 submission (membership D3, duplicate, evidence D5, dateEarned D8) + §7 auto-reject |
| US-5.5 | §5 withdraw/resubmit + `myClaims` (statuses, reasons) |
| US-5.6 | §4 decisions (scopes, reason-on-reject, Admin never — D7) |
| US-5.7 | §4 queue (oldest-first, filters, countOnly badge, reassignment-for-free) |
| US-5.8 | §6 revoke (D9, points retained) |
| US-5.9 | §9 badges (order, click-through, Members-only) |
| US-5.10 | §9 catalog (held flag, initiate submission) |
