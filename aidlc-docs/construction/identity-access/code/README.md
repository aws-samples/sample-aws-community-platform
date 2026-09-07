# Code Generation Summary — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Code Generation · **Unit**: Identity & Access
Real service implementing the frozen contract (24 operations, 28 stories). Replaces the mock as the deployed Lambda entrypoint.

## Generated / modified files

### Application code (created — `services/identity-access/`)
| File | Purpose |
|---|---|
| `src/app.py` | REAL Lambda handler (router) + in-service authZ + scheduled-sync branch; `Handler: app.handler` |
| `src/models.py` | Constants + OpenAPI serializers |
| `src/repository.py` | Single-table DynamoDB access (pk/sk + GSI1 email / GSI2 role / GSI3 group-history + OTP TTL) |
| `src/providers.py` | `CognitoAuthProvider` (community auth, Cognito-only), `SecretsAdapter`, `SesAdapter`, `EventPublisher`, `audit_log`, PBKDF2 hashing (local admin + OTP) |
| `src/auth_service.py` | login / verifyOtp / selfRegister / resetPassword / logout / JIT |
| `src/otp_service.py` | In-service OTP challenge (issue/verify, expiry + attempt cap) |
| `src/user_service.py` | listUsers / editUser / disable / enable / bulkImport / scheduled sync |
| `src/group_service.py` | group CRUD + join/leave + leaders + join-requests + membership history |
| `src/permission_matrix.json` | Runtime copy of the RBAC matrix (build-synced from contracts) |
| `requirements.txt` | Pinned deps (boto3, powertools, openpyxl, PyJWT) |
| `README.md` | Service docs |
| `tests/*` | 41 pytest + moto unit tests |

### Contracts (created)
- `contracts/services/identity-access/published-events/user-events.v1.json`
- `contracts/services/identity-access/published-events/group-events.v1.json`

### Infrastructure (modified)
- `infra/services/service-identity-access-data.yaml` — added GSI1/2/3, OTP TTL, local-admin secret, JWT secret, outputs.
- `infra/services/service-identity-access-app.yaml` — `Handler: app.handler`, new Parameters/env, **least-privilege IAM** (scoped DDB/index, EventBridge, cognito-idp on pool ARN, SES on sender, Secrets on 2 ARNs), scheduled-sync rule, provisioned-concurrency alias, audit log group (365-day), auth-failure metric filter + alarm.

### Tracking (modified)
- `service-mode.json` — identity-access → `complete`.

## Verification
- **Unit tests**: `python3 -m pytest services/identity-access/tests` → **41 passed**. Full suite `platform services` → **67 passed**.
- **CFN**: `cfn-lint` on both templates → **0 findings**.
- **Lint/SAST**: `ruff` (incl. bandit-style `S`) on `src` → no bug/security findings (B/E741/F401/I/UP resolved); remaining are cosmetic `E501` line-length only.

## Story coverage (28/28)
All operations implemented and routed; RBAC enforced per operation; domain events published; audit toggle-aware. Local-admin, OTP, JIT, sync, bulk import, group lifecycle, and append-only membership history all covered and tested.

## Notes / follow-ups
1. **Contract gap** — US-1.21 approve/reject join request has no OpenAPI route; logic implemented + tested in `GroupService.decide_join_request`, route wiring deferred (no new APIs added).
2. **Root-template wiring** — new `-app` Parameters need to be passed from foundation/`-data` outputs by `infra/root-template.yaml` (Unit 1). All params default, so the stack stays independently deployable.
3. **`datetime.UTC`** avoided in favor of `timezone.utc` for 3.10 test-runtime compatibility (Lambda target is 3.12).
4. Dev-only test deps installed locally: `moto[dynamodb]`, `joserfc` (moto Cognito JWT), `PyJWT`, `ruff` (not added to service runtime requirements).
5. **Local auth abstraction removed** (per user direction 2026-07-31): community auth is Cognito-only; tests exercise the real `CognitoAuthProvider` against a mocked Cognito pool. `AUTH_MODE`/`LocalAuthProvider` deleted from code and templates.

## Update (2026-07-31) — Bootstrap Administrator is now a Cognito user (requirement change)

Per user decision, the built-in local Administrator design (US-1.27/1.28) was superseded: the Administrator is now an ordinary Cognito user, seeded automatically at deployment time by `infra/seed.yaml`. This removes the separate portal-local credential store, login path, and reset path, and removes the account's exemption from Cognito sync/disable/role-change (US-1.4/1.6/1.19/1.33). Rationale: Cognito is provisioned by the same infrastructure template as the rest of the portal, so the failure mode the break-glass account protected against (Cognito unavailable/misconfigured at first boot) does not apply.

### Changes
- **Requirements**: `requirements/usecases/01-authentication-and-authorization.md` (US-1.27 rewritten, US-1.28 tombstoned, exemption clauses removed from US-1.2/1.4/1.31/1.32/1.33); `requirements/usecases/08-cross-cutting-concerns.md` and `requirements/Role-and-Permission-Mapping.md` (notification matrix, permission table, resolved-issues log updated); `aidlc-docs/inception/user-stories/stories.md` mirrored.
- **Code** (`services/identity-access/src/`): removed `LOCAL_ADMIN_ID`/`ACCOUNT_LOCAL_ADMIN` (models.py), `SecretsAdapter`/`issue_local_token` (providers.py), the local-admin branch in `AuthService.login`/`reset_password`, and the local-admin exemption checks in `UserService.edit_user`/`set_enabled`/`sync_from_cognito`. `AuthService`/`Context` no longer take a `secrets` param.
- **Infra**: `service-identity-access-data.yaml` — removed `LocalAdminSecret`/`JwtSecret` + their params. `service-identity-access-app.yaml` — removed `LocalAdminSecretArn`/`JwtSecretArn` params, env vars, and the `ReadSecrets` IAM statement. `root-template.yaml` — removed the corresponding wiring; added `IdentityAccessTableName` parameter to the `Seed` stack.
- **`infra/seed.yaml`** / **`platform/seed/seed_handler.py`**: `LocalAdminSecret` renamed `BootstrapAdminSecret` (`community-portal/bootstrap-admin-<stage>`) — now documented as an operator-retrieval record of the initial Cognito password, not a competing credential store. The seeder now also writes the Administrator's **portal record directly** (role=Administrator, mirroring bulk import US-1.31) via a new `dynamodb:PutItem`/`GetItem` grant on the Identity & Access table — this avoids relying on JIT provisioning (US-1.15), which always defaults new users to Member and would otherwise mis-provision the bootstrap account.
- **Tests**: replaced local-admin-specific tests with tests proving the bootstrap Administrator follows the same Cognito login, edit, and disable rules as any other Administrator (no exemption).
- **Frontend** (`frontend/src/features/AuthScreen.tsx`, `frontend/src/lib/apiClient.ts`, `frontend/src/App.tsx`): wired to the real `/auth/login`, `/auth/otp`, `/auth/register` endpoints (previously a fake role-switcher stub that made no network calls). Removed the local-admin reset-link footer note. Self-registration: removed the "allowed-domain" and "default role Member" helper labels; added a **Confirm password** field with client-side match validation before submit.
- **Configuration**: added `AllowedEmailDomains` root-template parameter (default `amazon.com`) → `ALLOWED_EMAIL_DOMAINS` env var, read by `Context._default_settings()` as a stop-gap until the Settings service exists.

### Verification
- `python3 -m pytest platform services` → 69 passed.
- `cfn-lint` on `root-template.yaml`, `seed.yaml`, `service-identity-access-data.yaml`, `service-identity-access-app.yaml` → 0 findings.
- `ruff` (incl. bandit-style checks) on touched source → clean.
- `npm run build` (frontend) → clean.
- End-to-end against the live deployed stack: `POST /auth/register` with `user@example.com` → 201 and a real Cognito user is created; a non-allow-listed domain → 400 `VALIDATION_ERROR`. Test user cleaned up afterward.

### Follow-ups
- The static HTML mockups under `requirements/mockup/admin/*.html` (e.g. `reset-password.html`, the `data-local-admin-only` reset link) still reflect the superseded design. They are inception-phase design references, superseded by the real frontend/backend; not updated as part of this change.
- Not yet redeployed — infra/code changes are made and verified locally/by lint; the running stack still has the old templates/secrets until the next `deploy.sh` run.
