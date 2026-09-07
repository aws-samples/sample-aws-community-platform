# Code Generation Plan — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Code Generation · **Unit**: Identity & Access
Single source of truth for generating the real Identity & Access service (replaces the mock). Greenfield multi-unit (microservices) → code lives in `services/identity-access/src/` + `services/identity-access/tests/`. Docs summaries in `aidlc-docs/construction/identity-access/code/`.

## Context
- **Frozen contract**: `contracts/services/identity-access/openapi.yaml` (24 operations). Contract tests (Schemathesis) are the deploy gate — responses must conform.
- **Permission matrix**: `contracts/platform/permissions/role-permission-matrix.v1.json` (in-service authZ).
- **Conventions reused (no shared lib; copied per service)**: `src/_conventions/{logger,errors,authz,validation,envelope,idempotency,config}.py`.
- **Stories**: 28 (US-1.2–1.21, 1.26–1.28, 1.30–1.34).
- **Design decision**: `AuthProvider` abstraction (`AUTH_MODE=cognito|local`) for local testability; in-service OTP; Secrets Manager local admin.
- **Contract gap noted**: US-1.21 approve/reject join request has no route in the frozen OpenAPI (only `GET /groups/{id}/requests`). Logic implemented + unit-tested in `GroupService`; route wiring deferred until the contract adds the endpoint (no new APIs added here).

## Steps
- [x] Step 1. Analyze unit context (done in prior stages)
- [x] Step 2. Project structure setup — `src/` domain packages + `tests/` + `requirements.txt`
- [x] Step 3. Business logic — `models.py`, `repository.py`, providers, domain services
- [x] Step 4. Business logic unit tests
- [x] Step 5. API layer — `app.py` router (real handler) + Principal + scheduled-sync branch
- [x] Step 6. API layer unit tests (route → status/schema)
- [x] Step 7. Repository layer (single-table DynamoDB) — in Step 3 module `repository.py`
- [x] Step 8. Repository unit tests (moto)
- [x] Step 9. Infrastructure artifacts — update `service-identity-access-data.yaml` (GSIs/TTL/secrets) + `service-identity-access-app.yaml` (handler→app.handler, params/env/IAM/scheduler/alarms)
- [x] Step 10. Published-event schemas — `contracts/services/identity-access/published-events/*.v1.json`
- [x] Step 11. requirements.txt (pinned) + README
- [x] Step 12. Update `service-mode.json` (identity-access → complete after tests pass)
- [x] Step 13. Run tests + fix
- [x] Step 14. Documentation summary in `aidlc-docs/construction/identity-access/code/`

## File plan (application code — workspace)
```
services/identity-access/
├── requirements.txt                 # pinned deps
├── README.md
├── src/
│   ├── app.py                        # REAL Lambda handler (router) — replaces mock as entrypoint
│   ├── models.py                     # constants, serializers (OpenAPI shapes)
│   ├── repository.py                 # single-table DynamoDB access (pk/sk + GSI1/2/3 + OTP TTL)
│   ├── providers.py                  # AuthProvider (Cognito|Local), SecretsAdapter, SesAdapter, EventPublisher, audit
│   ├── auth_service.py               # login/otp/register/reset/logout + JIT
│   ├── user_service.py               # list/edit/disable/enable/bulkImport + scheduled sync
│   ├── group_service.py              # group CRUD, join/leave, leaders, join-requests, membership history
│   ├── otp_service.py                # OTP challenge issue/verify
│   ├── mock_handler.py               # (retained; no longer the deployed entrypoint)
│   ├── mock_runtime.py / *.json      # (retained for reference/other tooling)
│   └── _conventions/                 # unchanged
└── tests/
    ├── conftest.py                   # moto fixtures (dynamodb table + secrets), sample principals
    ├── test_repository.py
    ├── test_auth_service.py
    ├── test_user_service.py
    ├── test_group_service.py
    └── test_app_routes.py
```

## Story traceability → modules
| Stories | Module |
|---|---|
| US-1.2/1.15/1.20/1.27/1.28/1.30/1.32 | auth_service.py + otp_service.py + providers.py |
| US-1.3 | auth_service.logout |
| US-1.4/1.5/1.6/1.19/1.26/1.31/1.33 | user_service.py |
| US-1.7–1.11/1.16–1.18/1.21/1.34 | group_service.py |
| US-1.12 | authz (all handlers) |
| US-1.13/1.14 | providers.audit_log (all mutations) |

## Security/Resiliency gates to satisfy in code
SECURITY-05 (validation) · -06 (scoped IAM in IaC) · -08 (fail-closed authz on every handler) · -12 (PBKDF2, OTP caps, no hardcoded creds) · -15 (global_handler, generic errors) · RESILIENCY-10 (timeouts + fail-closed) · BR-EV1 (post-commit publish).
