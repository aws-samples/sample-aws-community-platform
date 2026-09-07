# Unit 6 — Certifications: Domain Entities

Technology-agnostic entity model (persistence key design belongs to NFR/Infrastructure Design). Owner: Certifications service; single service-owned table per D9/D2 conventions.

## E1 — CertificationDefinition

| Field | Type | Notes |
|---|---|---|
| id | string | `cert-…` |
| name | string, required | e.g. "AWS Solutions Architect – Pro" |
| description | string, required | catalog + badge click-through detail |
| category | enum, required | `AWS Certification` \| `Community Badge` (mockup's two; extensible) |
| pointsAwarded | integer ≥ 0, required | per-cert value credited on approval (B1/C2; read by US-6.5 via the Approved event) |
| expiryPeriodMonths | integer > 0, optional | absent = never expires; months (mockup "3 years" = 36) |
| badgeImageKey | string, optional | unique object key (D6); absent until upload + scan Clean |
| badgeImageStatus | enum | `None` \| `PendingScan` \| `Clean` \| `Quarantined` |
| active | boolean | US-5.3 deactivate/reactivate |
| createdBy / createdAt / updatedAt | audit stamps | |

Rules: BR-C1 (claims only while active), BR-V6 (edits never touch approved claims — points/expiry frozen on claims), §11 rename/image edits DO flow into badge display.

## E2 — Claim (the single lifecycle entity, D2)

| Field | Type | Notes |
|---|---|---|
| id | string | `clm-…` |
| certId → E1 | string, required | |
| memberId | string, required | claim owner (token subject at submission) |
| creditedGroupId | string, required | routing + points attribution (US-5.4) |
| status | enum | `Pending` \| `Approved` \| `Rejected` \| `Withdrawn` \| `Revoked` \| `Expired` |
| evidenceUrl | string, conditional | XOR with evidenceFileKey (BR-C4) |
| evidenceFileKey | string, conditional | unique physical key (BR-C7) |
| evidenceFileName | string, optional | original filename, display only |
| scanStatus | enum | `None` \| `PendingScan` \| `Clean` \| `Quarantined` (BR-V3) |
| notes | string, optional | free text (e.g. context for the reviewer) |
| dateEarned | ISO date, conditional | D8/BR-C5; required when E1 has expiryPeriodMonths |
| submittedAt | ISO datetime | queue sort key (BR-V2) |
| decidedAt / decidedBy | stamps, on decision | `decidedBy=system` for auto-reject (BR-S1) |
| rejectReason | string, on Rejected | owner-visible; required for leader rejects (BR-V4) |
| pointsAwarded | integer, frozen on Approved | BR-V6 — never re-read from E1 afterwards |
| expiresAt | ISO date, frozen on Approved | D8 anchor + E1 period at approval; absent = never expires |
| expiringNoticeSent | boolean/timestamp | BR-X2 mark-before-emit flag |
| revokedAt / revokedBy / revokeReason | stamps, on Revoked | BR-R1 |

Identity: `(certId, memberId)` is unique among `{Pending, Approved}` claims (BR-C2) — enforced with a conditional write, not a scan. History rows (terminal states) are retained forever.

## E3 — Supporting records (service-internal)

- **FileKeyPointer** — `fileKey → {kind: evidence|badge, ownerId (claimId|certId)}`; lets the scan-verdict consumer stamp the owning entity in O(1) (Settings FILEKEY precedent). Written at upload-grant time, before the owning claim/definition may exist? No — evidence pointer is written at claim submission (grant step stores nothing but the signed key contract); badge pointer at definition create/edit. Orphaned uploads therefore have no pointer and are lifecycle-cleaned invisibly.
- **IdempotencyRecord** — envelope-id run-once store for the MembershipChanged and scan-verdict consumers (repo-wide pattern).
- **Expiry index** — sparse: only `Approved` claims with `expiresAt` carry the index key (removed on any terminal transition), so the daily sweep queries exactly the expiring population (BR-X1). Key design finalized in NFR/Infra Design.

## Relationships

```
CertificationDefinition 1 ----- * Claim        (certId)
Member (Identity-owned)  1 ----- * Claim        (memberId; no local member entity — D3)
Group  (Identity-owned)  1 ----- * Claim        (creditedGroupId; no local group entity)
Claim  1 ----- 0..1 EvidenceFile (S3 object)    (evidenceFileKey, unique physical name)
CertificationDefinition 1 -- 0..1 BadgeImage (S3 object)
```

No membership projection is kept (D3 — REST at submission; events only for auto-reject). No per-leader queue assignment exists (BR-V1).

---

## Contract deltas (certifications openapi v1.0.0 → v2.0.0)

**Breaking** (D9): `POST /certifications/{id}/revoke` **removed** → `POST /certifications/claims/{claimId}/revoke` (`{reason}` required). Everything else additive. All routes stay under the `/certifications` base path — **no api-edge regeneration needed**.

| Op | Change |
|---|---|
| `browseCatalog` GET /certifications | Response schema gains description/category/pointsAwarded/expiryPeriodMonths/badgeImageUrl/active + per-caller `held`, `heldExpiresAt`, `pendingClaim`. Excludes inactive definitions for non-leaders; leaders see all (Definitions tab) via `includeInactive=true`. |
| `createCert` POST /certifications | Body: name, description, category, pointsAwarded (required); expiryPeriodMonths, badgeImageKey+badgeImageFileName (optional). |
| `editCert` PUT /certifications/{id} | Same fields + `active` (deactivate/reactivate stays on PUT — matches shipped UI + story-verification adjustment #13). |
| `submitClaim` POST /certifications/claims | Body: certId, creditedGroupId (required); evidenceUrl XOR evidenceFileKey(+evidenceFileName); notes; dateEarned (conditional). 409 duplicate; 422 no-group / already-expired. |
| `myClaims` GET /certifications/claims/me | Full owner projection incl. status, rejectReason, expiresAt, evidence refs. |
| `withdrawClaim` DELETE /certifications/claims/{id} | Unchanged shape; semantics = transition to `Withdrawn` (soft), 204; 409 if not Pending. |
| `verificationQueue` GET /certifications/verifications | Adds `certId=`, `groupId=` (CL), `countOnly=true` params; response items carry member/group display names, evidence descriptor, submittedAt; oldest-first. |
| `decideClaim` POST /certifications/claims/{id}/decision | `reason` required when decision=reject (schema conditional documented; enforced in-service). |
| **NEW** `revokeClaim` POST /certifications/claims/{id}/revoke | CL-only; `{reason}` required; 409 unless Approved. |
| **NEW** `listClaims` GET /certifications/claims | The route member-profiles already calls: `memberId=`, `certId=`, `status=`, `from=`, `to=`, `countOnly=`. Serves the BR-P1 public (Approved-only) projection to non-owners. |
| **NEW** `grantEvidenceUpload` POST /certifications/evidence-uploads | Member; `{fileName}` → `{uploadUrl, fileKey}` (unique key, BR-C7). |
| **NEW** `grantBadgeUpload` POST /certifications/badge-uploads | CL; same shape. |
| **NEW** `evidenceUrl` GET /certifications/claims/{id}/evidence-url | Owner or in-scope reviewer; fresh short-lived GET URL (BR-P2); 409 while PendingScan/Quarantined. |

**Status enum on the wire**: `Pending | Approved | Rejected | Withdrawn | Revoked | Expired` (D1).

**Cross-unit contract edits in this unit's scope**:
- `contracts/platform/permissions/role-permission-matrix.v1.json`: remove `Administrator: {browse, certification-catalog}` (D7).
- `contracts/services/certifications/published-events/`: author 5 schemas (D10) — `certification-approved.v1.json`, `certification-rejected.v1.json`, `certification-revoked.v1.json`, `certification-expiring-soon.v1.json`, `certification-expired.v1.json`.
- Seed fixtures: extend certifications/claims fixtures with the new fields (statuses already "Approved" — compatible with D1).
