# Functional Design Plan — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Identity & Access (28 stories)
**Contract (frozen)**: `contracts/services/identity-access/openapi.yaml` · **Permission spec**: `contracts/platform/permissions/role-permission-matrix.v1.json`

## Scope (from unit-of-work.md + story-map)
Stories US-1.2–1.21, 1.26, 1.27, 1.28, 1.30, 1.31, 1.32, 1.33, 1.34 (28). Paths `/auth`, `/users`, `/groups`, `/membership-history`.

## Steps
- [x] 1. Analyze unit context (unit-of-work.md, story-map, use case 01, Role-and-Permission-Mapping.md)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (see below — all resolved from requirements; recorded as design decisions, no open blockers)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (N/A — no open questions; decisions documented)
- [x] 6. Generate functional design artifacts (business-logic-model.md, business-rules.md, domain-entities.md)
- [x] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update state

## Questions analysis → resolved from existing artifacts (no blocking questions)

| # | Area | Resolution source | Decision |
|---|---|---|---|
| Q1 | How is community-user auth performed? | requirements US-1.2/1.4/1.30/1.31 | **Cognito only** for community users (`CognitoAuthProvider`: boto3 `admin_initiate_auth`/`sign_up`/`admin_*`/`list_users`). Cognito is the system of record for identity/credentials. No local auth abstraction (per user direction 2026-07-31). Tests exercise the real provider against a mocked Cognito (moto). |
| Q2 | OTP re-verification mechanism (US-1.32) | US-1.32 impl note ("mechanism deferred to design") | **In-service OTP challenge**: OTP code + expiry + attempt-count persisted in the service table; delivered via SES. `lastVerifiedAt` tracked per user; challenge issued at login when `now - lastVerifiedAt >= interval`. Interval/session lifetime read from Settings (US-8.3). |
| Q3 | Built-in local Administrator credential storage (US-1.27/1.28) | US-1.27/1.28; NFR Secrets Manager | Local-admin credential (email + PBKDF2/bcrypt hash) in **Secrets Manager**; seeded at deploy. Portal-local login + portal-local reset via SES. Cannot be disabled/deleted/role-changed. |
| Q4 | JIT provisioning + Cognito sync reconciliation key (US-1.4/1.15/1.31) | US-1.4 | Portal record keyed on Cognito `sub` (email = unique business key). JIT is no-op if record exists. Scheduled sync = idempotent match-and-update (EventBridge Scheduler → sync handler). |
| Q5 | Group membership as append-only history (US-1.34) | US-1.34 | Membership-event log is the source of truth; current membership + join date **derived** (latest start event with no later end). Events: `joined`/`approved`/`left`/`removed`. |
| Q6 | RBAC enforcement point | FQ3a; authz.py convention | AuthN at Cognito authorizer (edge); **authZ in-service, fail-closed** via `Authorizer` + `role-permission-matrix.v1.json`; object-level (own) + group-scope (group) checks. 403 on deny (US-1.12). |
| Q7 | Audit logging (US-1.13/1.14) | US-1.13/1.14 | Structured audit events to CloudWatch Logs (dedicated audit logger); toggle flag read from Settings; toggle-change always logged. No in-portal UI. |

**Design decisions above are flagged for user review at the stage gate — override any and I will revise.**
