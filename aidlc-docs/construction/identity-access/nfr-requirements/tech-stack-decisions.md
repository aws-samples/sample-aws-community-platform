# Tech Stack Decisions — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Identity & Access
Inherits all platform-wide choices (Unit 1 `tech-stack-decisions.md`). Records identity-specific additions. Companion: `nfr-requirements.md`.

## Inherited (unchanged)
Python 3.12 on Lambda · AWS Lambda Powertools · boto3 · AWS SAM packaging · DynamoDB on-demand (PITR, Retain) · EventBridge (domain events) · API Gateway REST + Cognito authorizer · CloudWatch/X-Ray · pinned deps + lock + bandit/cfn-lint/cfn_nag/dep-scan/SBOM in CI · Schemathesis + pytest contract tests (the gate).

## Identity-specific stack additions
| Concern | Choice | Rationale |
|---|---|---|
| Identity provider | **Amazon Cognito User Pool** (portal-owned, IaC-provisioned) | System of record for community-user identity/credentials (US-1.2/1.4/1.30/1.31). App client + password policy + email verification + hosted forgot-password + custom-auth triggers reserved. |
| Cognito access | **boto3 `cognito-idp`** (`initiate_auth`, `sign_up`, `admin_create_user`, `admin_disable_user`, `admin_enable_user`, `admin_get_user`, `list_users`) | Server-side auth + admin lifecycle + sync. |
| Local-admin secret | **AWS Secrets Manager** | Built-in local Administrator credentials (US-1.27); GetSecretValue scoped to the secret ARN. |
| Password hashing (local admin) | **PBKDF2-HMAC-SHA256** (stdlib `hashlib.pbkdf2_hmac`, high iteration count) — no third-party dep | Adaptive hash (SECURITY-12); avoids adding a native-build dependency to the Lambda zip. |
| OTP + transactional email | **Amazon SES** (`send_email`) | OTP delivery (US-1.32) + local-admin reset link (US-1.28). Sender configured at deploy (B7) / overridable via Settings. |
| OTP storage | **DynamoDB (service table) with TTL** | In-service OTP challenge (design decision); short-lived, auto-expiring; code stored hashed. |
| Session token | **Cognito-issued JWT** (community) / **portal-signed short-lived JWT** (local admin) | Validated at the Cognito authorizer (community) + in-service claim parse. Local-admin token signed with a Secrets-Manager-held signing key. |
| Scheduled sync | **Amazon EventBridge Scheduler** → sync Lambda handler | US-1.4 batch reconciliation; schedule/frequency from Settings (read-only pool id/region shown in Settings). |
| CSV/XLSX parsing (bulk import) | **stdlib `csv`** + **`openpyxl`** (pinned) | US-1.31 file import; openpyxl is pure-Python (no native build). Header validated; row-level outcomes. |
| Event publishing | **boto3 `events` PutEvents** on the platform bus | Domain events (E7). |
| Community auth | **Cognito only** (`CognitoAuthProvider`) | No local auth abstraction (per user direction 2026-07-31). Cognito is the system of record; tests exercise the real provider against a mocked Cognito (moto + joserfc). |

## Dependencies (pinned — `services/identity-access/requirements.txt`)
| Package | Purpose |
|---|---|
| `boto3` (pinned) | AWS SDK (cognito-idp, ses, secretsmanager, events, dynamodb) |
| `aws-lambda-powertools` (pinned) | logging/tracing/metrics (aligns with NFR-OBS) |
| `openpyxl` (pinned) | XLSX bulk import parsing |
| `PyJWT` (pinned) | local-admin token sign/verify (community tokens verified by Cognito authorizer) |
| (dev) `pytest`, `schemathesis`, `moto` | unit + contract tests; `moto` mocks AWS for local unit tests |

All exact-pinned; committed lock; vulnerability-scanned + SBOM in CI (SECURITY-10). No `latest` tags.

## Design-phase items deferred to NFR Design / Infrastructure Design
- Provisioned-concurrency sizing for `login`/`verifyOtp`.
- Lambda concurrency ceiling value (protect Cognito/SES).
- Exact GSI projections + capacity behavior under on-demand.
- Cognito custom-auth trigger wiring vs. pure in-service OTP (chosen: in-service OTP; Cognito triggers reserved but not required for Phase 1).
- SES sending identity/domain verification prerequisite documentation.
