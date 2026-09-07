# Domain Entities & Schemas — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Member Profiles & Directory
Technology-agnostic entity model for the service's owned data. Persisted in the service's single DynamoDB table (`member-profiles-<stage>`, pk/sk) plus the idempotency table. Companions: `business-logic-model.md`, `business-rules.md`. Shapes conform to `contracts/services/member-profiles/openapi.yaml` (to be amended with the backward-compatible additions noted below).

---

## E1 — MemberProfile (the profile-extension record)
A **denormalized, event-sourced cache** — not a second source of truth for identity, role, or group membership. Keyed on the same user id Identity & Access uses (Cognito `sub`). Identity fields are mirrored read-only from Identity's events; only profile-specific fields are ever written directly by this service.

| Field | Type | Source | Notes |
|---|---|---|---|
| `id` | string | Identity (`UserProvisioned.userId`) | Cognito `sub`; primary key |
| `firstName`, `lastName`, `email` | string | Identity (mirrored, read-only here) | Never edited via this service (BR-2) |
| `role` | enum | Identity (`UserRoleChanged`) | Mirrored for directory filtering; not authoritative |
| `status` | enum | Identity (`UserDeactivated`/`UserReactivated`) | `active` \| `inactive`; retained forever, never removed (BR-8) |
| `groups` | array<`{groupId, joinedAt}`> | Identity (`MemberJoinedGroup`/`MemberLeftGroup`/`MemberRemoved`) | Per-group join date (BR derived from Identity's E4 MembershipEvent, mirrored here for read efficiency); rejoin overwrites `joinedAt` |
| `city`, `country` | string | this service (`updateOwnProfile`) | Free-text/selectable location (US-3.2) |
| `professionalRole` | string | this service | Free-text job title — distinct from `role` (BR-2) |
| `awsProject` | boolean | this service | "Part of an AWS project" flag (US-3.2) |
| `timeZone` | string | this service (or Identity's Edit User) | Latest save wins across both paths (BR-3) |
| `bio` | string | this service | Free-text (US-3.2, mockup `member/profile.html`) |
| `skills` | array<string> | this service | Tags (US-3.2/3.5 — search field) |
| `avatar` | string (URL) | this service | Upload reference (US-3.2) |
| `createdAt`, `updatedAt` | ISO-8601 | this service | `createdAt` set on `UserProvisioned`-triggered creation — used to gate first-time onboarding (US-3.6) |

- **Key**: `pk=MEMBER#<id>`, `sk=PROFILE`.
- No GSIs planned initially for directory filtering (`role`, `groupId`) — `browseDirectory` uses a table scan with filter expressions at this unit's expected scale; revisit with a role/status GSI at Infrastructure Design if directory size or query latency warrants it (flagged, not blocking Functional Design).

## E2 — Consumed event log (idempotency)
Not a business entity — the standard idempotency table (`member-profiles-idem-<stage>`, `eventId` hash key with TTL) dedupes Identity & Access's events before they mutate E1, same pattern as Identity & Access's own idempotency table.

## E3 — Published event payload (`contracts/services/member-profiles/published-events/MemberProfileUpserted.v1.json`)
Wrapped in the platform envelope. Emitted after every profile create/update (BR-7).

| Field | Notes |
|---|---|
| `userId` | = E1.id |
| `firstName`, `lastName`, `email` | for indexing (Search embeds these + skills/bio) |
| `skills`, `bio`, `city`, `country`, `professionalRole` | embedding input fields |
| `status` | so Search can badge deactivated members (BR-8) |

## E4 — Cross-service read shapes (not owned, consumed at read time — plan Q2)
Not persisted; assembled per-request from other services' read APIs and merged into responses. Documented here for completeness since they shape `getOwnProfile`/`getMember`/`memberActivity` response schemas:

| Source | Endpoint (indicative) | Used by |
|---|---|---|
| Contributions & Scoring | `GET /contributions/me` (or per-member equivalent) | rollup + per-group tier (US-3.1/3.3) |
| Events | attendance count/list | basic activity block + `memberActivity` |
| Forums | post count/list | basic activity block + `memberActivity` |
| Contributions & Scoring | submission count/points | basic activity block + `memberActivity` |
| Certifications | earned-cert count/list | basic activity block + `memberActivity` (also feeds "verified badges") |

Each is fetched independently and merged with a per-call try/catch (BR-9) — no cross-service transaction, no shared schema (FQ1).

## Response shape notes (contract amendments, backward-compatible per contracts/README.md)
- `Member` (existing schema) gains optional fields: `groups: [{groupId, joinedAt}]`, `professionalRole`, `city`, `country`, `awsProject`, `bio`, `skills`, `avatar`, and a nested `rollup: {points, quarter}` + `tiers: [{groupId, tier}]`, plus a nested `activitySummary: {eventsAttended, forumPosts, contributions, certifications}` (the basic block, BR-12). All optional/additive — no breaking change, no `vN+1` required.
- `browseDirectory` (`GET /members`) gains optional query params: `q`, `role`, `groupId`, `certId`, `limit`, `cursor` (BR-6, BR-10).
- `memberActivity` (`GET /members/{id}/activity`) gains optional query params `from`, `to` (BR-14) and response fields `points: {currentQuarter, lifetime}` alongside the existing count fields.
- `/admin/members` (`adminMemberList`) is **removed from this service's scope** (BR-15) — not implemented, not carried forward into code generation. `contracts/services/member-profiles/openapi.yaml` will drop this path; the operation moves conceptually to `identity-access/openapi.yaml`'s existing `GET /users` (no new path needed there either, since it already exists).

## Consistency notes
- `role-permission-matrix.v1.json` scopes applicable here: `view member-profile` (global, most roles), `browse member-directory` (global), `search member` (global) — Administrator has none of these three (BR-4), consistent with the matrix already excluding Administrator from `view member-profile`/`browse member-directory`/`search member` rows... *(verify against matrix at Infrastructure Design if any role's entry needs a follow-up correction — Administrator's block in `role-permission-matrix.v1.json` currently does list `browse member-directory`/`search member`/`list admin-member-list`, which is consistent with US-3.8/3.9 now living on Identity & Access; it does not list `view member-profile`, consistent with BR-4)*.
- Derived `groups[]`/`joinedAt` mirror Identity's E4 MembershipEvent semantics exactly (BR-G5) but are a cache, not the source of truth — Identity's membership-history endpoint remains authoritative for any dispute or audit need.
