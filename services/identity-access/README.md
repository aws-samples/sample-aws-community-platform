# Identity & Access Service (Unit 2)

First real service of the AWS Community Portal (auth is never mocked). Implements the frozen contract `contracts/services/identity-access/openapi.yaml` behind the same API Gateway routes the mock served (`/auth`, `/users`, `/groups`, `/membership-history`).

**Story reassignment (2026-08-02)**: US-3.8 (admin member list) and US-3.9 (export member list) were reassigned here from Unit 3 Member Profiles during Unit 3's functional design, since `GET /users` already returns every field those stories need (role/status/city/country/professionalRole/awsProject/groups) via the existing GSI2 role index — no new endpoint required on this service, but noted here as this service is now the system of record for both stories. See `aidlc-docs/inception/application-design/unit-of-work.md` for details.

## Responsibilities (31 stories: US-1.2–1.21, 1.26–1.35, US-3.8, US-3.9; US-1.28 tombstoned)
- **Authentication**: Cognito email+password login for every user (including the bootstrap Administrator), in-service periodic email OTP re-verification (US-1.32), JIT provisioning (US-1.15), self-registration with allowed-domain check (US-1.30), Cognito hosted password reset (US-1.20).
- **Bootstrap Administrator** (US-1.27): a regular Cognito user seeded automatically at deployment time (by `infra/seed.yaml`) with role=Administrator written directly to the portal record; no separate credential store, login path, or reset path, and no exemption from sync/disable/role-change.
- **User management**: Edit User role+groups+profile (US-1.26/1.5), disable/enable (US-1.33/1.6/1.19), single Add User form (US-1.35, POST /users — a bulk-import row of one), bulk import (US-1.31), scheduled Cognito sync (US-1.4).
- **User groups**: CRUD (US-1.7/1.18/1.11), join/leave (US-1.8/1.9), leaders (US-1.10), join-request review (US-1.21), directory (US-1.16), remove member (US-1.17).
- **Membership-event history** (US-1.34): append-only; current membership + join date derived.
- **RBAC** (US-1.12): in-service fail-closed authZ from `role-permission-matrix.v1.json`.
- **Audit** (US-1.13/1.14): toggle-aware CloudWatch audit records.

## Layout
```
src/
  app.py            REAL Lambda handler (router) + scheduled-sync branch — deployed entrypoint
  models.py         constants + OpenAPI serializers
  repository.py     single-table DynamoDB access (pk/sk + GSI1 email, GSI2 role, GSI3 group-history, OTP TTL)
  providers.py      CognitoAuthProvider, SesAdapter, EventPublisher, audit, PBKDF2 (used for OTP code hashing)
  auth_service.py   login / verifyOtp / selfRegister / resetPassword / logout / JIT
  otp_service.py    in-service OTP challenge (issue/verify)
  user_service.py   list/edit/disable/enable/bulkImport/sync
  group_service.py  group CRUD + join/leave + leaders + join-requests + membership history
  permission_matrix.json   runtime copy of contracts/platform/permissions/role-permission-matrix.v1.json
  _conventions/     logger, errors, authz, validation, envelope, idempotency, config (copied per service)
tests/              pytest + moto unit tests
```

## Configuration (env vars — from CFN Parameters)
| Var | Purpose |
|---|---|
| `TABLE_NAME` / `IDEMPOTENCY_TABLE` | DynamoDB tables |
| `EVENT_BUS_NAME` | EventBridge domain-event bus |
| `USER_POOL_ID` / `USER_POOL_CLIENT_ID` | Cognito |
| `SES_SENDER` | OTP delivery sender |
| `ALLOWED_EMAIL_DOMAINS` | Self-registration allow-list (US-1.30) — fallback only; the live value is read from the Settings service (`GET /internal/settings`, private-API-only, see `SettingsClient`) |
| `API_BASE_URL` | Shared API Gateway invoke URL for the live Settings read (30s warm-container cache; falls back to env defaults if unreachable) |
| `PERMISSION_MATRIX_PATH` | authZ matrix (defaults to bundled copy) |

## Authentication
- **Every user, including the bootstrap Administrator**: Cognito only (`CognitoAuthProvider` via `boto3 cognito-idp`). Cognito is the sole system of record for identity/credentials — there is no separate local credential store (US-1.27/1.28 — the previous "built-in local Administrator" design was superseded; see tombstone in the use case).
- **Tests** exercise the real `CognitoAuthProvider` against a mocked Cognito user pool (`moto` + `joserfc`); DynamoDB is mocked with `moto`.

## Design decisions (flagged for review)
1. In-service OTP (not Cognito custom-auth triggers) — the requirement marks the mechanism as design-phase.
2. Bootstrap Administrator's portal record is written directly by the Seed stack (mirrors bulk import, US-1.31) rather than relying on JIT provisioning, which always defaults new users to Member.

## Known contract gap
US-1.21 approve/reject join request has **no route** in the frozen OpenAPI (only `GET /groups/{id}/requests`). The decision logic (`GroupService.decide_join_request`) is implemented and unit-tested; route wiring is deferred until the contract adds the endpoint (no new APIs added here).

## Test
```
python3 -m pytest services/identity-access/tests -q
```

## Deploy wiring note
`service-identity-access-app.yaml` receives `TableArn`, `UserPoolId/Arn/ClientId`, `SesSender*`, `AllowedEmailDomains` from the root template. `infra/seed.yaml` receives `IdentityAccessTableName` (from `IdentityAccessData` outputs) so it can seed the bootstrap Administrator's portal record. All params carry defaults so each stack remains independently deployable.
