# Domain Entities & Schemas — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Identity & Access
Technology-agnostic entity model for the service's owned data. Persisted in the service's single DynamoDB table (`identity-access-<stage>`, pk/sk) plus the idempotency table. Companions: `business-logic-model.md`, `business-rules.md`. Shapes conform to `contracts/services/identity-access/openapi.yaml`.

---

## E1 — PortalUser (the portal record)
The local projection of a user. Identity fields (name, email) are **Cognito-owned/read-only** for community users; the built-in local Administrator is portal-managed. Keyed on Cognito `sub` (email = unique business key).

| Field | Type | Notes |
|---|---|---|
| `id` | string | Cognito `sub` for community users; `local-admin` for the built-in account |
| `email` | string | unique business key (lowercased); Cognito-owned for community users |
| `firstName` | string | Cognito-owned (community); editable only via Cognito |
| `lastName` | string | Cognito-owned (community) |
| `role` | enum | `Administrator` \| `CommunityLeader` \| `UserGroupLeader` \| `Member` (exactly one — BR-U3) |
| `status` | enum | `Active` \| `Inactive` (US-1.6/1.19) |
| `accountType` | enum | `cognito` \| `local-admin` (drives login path + reset-link visibility, US-1.28) |
| `city`, `country`, `professionalRole`, `awsProject`, `timeZone` | profile | editable via Edit User (US-1.26) / self (US-3.2); `awsProject` boolean |
| `ledGroupId` | string? | for UserGroupLeader — the single led group (BR-G7) |
| `lastVerifiedAt` | ISO-8601? | last successful OTP re-verification (US-1.32) |
| `createdAt`, `updatedAt` | ISO-8601 | audit timestamps |

- **Key**: `pk=USER#<id>`, `sk=PROFILE`.
- **GSI1 (email lookup)**: `gsi1pk=EMAIL#<email>`, `gsi1sk=USER` — dedup + login resolution.
- **GSI2 (role/status listing)**: `gsi2pk=ROLE#<role>`, `gsi2sk=USER#<id>` — admin user list, last-leader checks.

## E2 — Group (user group)
| Field | Type | Notes |
|---|---|---|
| `id` | string | `g-<uuid>` |
| `name` | string | required, 1–100 |
| `description` | string | 0–500 |
| `approvalRequired` | boolean | default `false` (US-1.7); not retroactive (US-1.18) |
| `leaderIds` | array<string> | ≥1 at all times (BR-G1); each leader leads exactly one group (BR-G7) |
| `status` | enum | `Active` \| `SoftDeleted` (US-1.11) |
| `deletedAt` | ISO-8601? | soft-delete time; permanent purge after 2 weeks (BR-G9) |
| `createdAt`, `createdBy` | | creator = a Community Leader (not auto-leader, US-1.7) |
| `memberCount` | integer (derived) | count of active memberships (from E4) |

- **Key**: `pk=GROUP#<id>`, `sk=META`.

## E3 — JoinRequest (approval-required groups only)
| Field | Type | Notes |
|---|---|---|
| `id` | string | `jr-<uuid>` |
| `groupId` | string | target group |
| `memberId` | string | requesting user |
| `message` | string? | optional requester note (US-1.21) |
| `status` | enum | `Pending` \| `Approved` \| `Rejected` \| `Withdrawn` |
| `decisionReason` | string? | required on reject (US-1.21) |
| `requestedAt`, `decidedAt`, `decidedBy` | | oldest-first sort by `requestedAt` |

- **Key**: `pk=GROUP#<groupId>`, `sk=JOINREQ#<requestedAt>#<id>`.
- Constraint: at most one `Pending` per (memberId, groupId) — BR-G4.

## E4 — MembershipEvent (append-only history — US-1.34)
Immutable log; current membership + join date are **derived** from it (BR-M1).
| Field | Type | Notes |
|---|---|---|
| `id` | string | `me-<uuid>` |
| `memberId` | string | |
| `groupId` | string | |
| `type` | enum | `joined` \| `approved` \| `left` \| `removed` (start = joined/approved; end = left/removed) |
| `at` | ISO-8601 | event time; approval sets join date at approval moment (BR-G5) |

- **Key**: `pk=MEMBER#<memberId>`, `sk=MEVENT#<at>#<id>`.
- **GSI3 (per-group history)**: `gsi3pk=GROUP#<groupId>`, `gsi3sk=MEVENT#<at>` — group member list + analytics feed (US-7.2/7.3).
- Derived current membership: latest start event for (member, group) with no later end event.

## E5 — OtpChallenge (in-service OTP — US-1.32)
| Field | Type | Notes |
|---|---|---|
| `challengeId` | string | issued at login when re-verification due |
| `userId` | string | |
| `codeHash` | string | hashed OTP (never store plaintext code) |
| `expiresAt` | epoch (TTL) | short expiry (BR-A5) |
| `attempts` | integer | capped (BR-A5); lockout on exceed |
| `ttl` | epoch | DynamoDB TTL auto-purge |

- **Key**: `pk=OTP#<challengeId>`, `sk=CHALLENGE`. No user enumeration on failure (BR-A6).

## E6 — LocalAdminCredential (Secrets Manager — US-1.27)
Not in DynamoDB. Secret JSON: `{ "email": "...", "passwordHash": "<pbkdf2>", "resetToken": "<hash>?", "resetExpiresAt": "?" }`. Seeded at deploy (email + initial password). Cannot be disabled/deleted (BR-A8).

## E7 — Published Event payloads (`contracts/services/identity-access/published-events/*.v1.json`)
Wrapped in the platform envelope (E1 of Unit 1). Emitted to EventBridge (BR-EV1):
`UserProvisioned`, `UserRoleChanged`, `UserDeactivated`, `UserReactivated`, `GroupCreated`, `GroupUpdated`, `GroupSoftDeleted`, `GroupRestored`, `GroupHardDeleted`, `MemberJoinedGroup`, `MemberLeftGroup`, `MemberRemoved`.

| Event | Key payload fields |
|---|---|
| `UserProvisioned` | `userId, email, role, source(jit\|import\|sync)` |
| `UserRoleChanged` | `userId, oldRole, newRole` |
| `UserDeactivated` / `UserReactivated` | `userId` |
| `GroupCreated`/`GroupUpdated` | `groupId, name, approvalRequired, leaderIds` |
| `GroupSoftDeleted`/`GroupRestored` | `groupId, effectiveAt` |
| `GroupHardDeleted` | `groupId` (triggers downstream purge — Forums/Contributions/Search) |
| `MemberJoinedGroup` | `memberId, groupId, at` |
| `MemberLeftGroup`/`MemberRemoved` | `memberId, groupId, at` |

## Consistency notes
- Response shapes (`User`, `Group`, `GroupList`, `JoinRequest`, `History`, `Session`) map 1:1 to OpenAPI `components.schemas`.
- `role`/`scope` semantics ↔ `role-permission-matrix.v1.json` (E3 of Unit 1) — enforced by `authz.py`.
- Derived `memberCount` / join date come only from E4 (no denormalized membership rows as source of truth).
