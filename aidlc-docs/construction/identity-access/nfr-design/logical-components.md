# Logical Components — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Identity & Access
Logical decomposition of the service (technology-agnostic component roles → concrete Python modules in Code Generation). Companion: `nfr-design-patterns.md`.

## Component map
```
API Gateway (Cognito authorizer)                EventBridge Scheduler
        │ proxy event                                   │ cron
        ▼                                               ▼
┌──────────────────────────┐                  ┌────────────────────┐
│ handler (router)         │                  │ sync_worker        │
│  global_handler wrapper  │                  │ (Cognito → portal) │
└───────────┬──────────────┘                  └─────────┬──────────┘
            │                                            │
   ┌────────┼───────────────────────────────────────────┘
   ▼        ▼          ▼            ▼             ▼
validation  authz   AuthService  GroupService  UserService  (domain services)
                       │             │             │
                       ├── AuthProvider (Cognito | Local)
                       ├── OtpService ── SES adapter
                       ├── SecretsAdapter (local-admin creds + JWT key)
                       ▼
                    Repository (single-table DynamoDB) ── membership-history queries
                       │
                    EventPublisher (EventBridge)   AuditLogger (CloudWatch)
```

## Components
| Component | Responsibility | Realizes NFR |
|---|---|---|
| `handler` (router) | Match API GW route → operation; build `Principal`; wrap in `global_handler` (fail-closed) | SECURITY-08/15 |
| `validation` (`_conventions/validation.py`) | Type/length/email/enum checks; body cap; HTML rejection | SECURITY-05 |
| `authz` (`_conventions/authz.py`) | Load matrix; `authorize()` global/own/group; deny→403 | SECURITY-08 |
| `AuthService` | login/verifyOtp/selfRegister/resetPassword/logout orchestration; JIT provisioning | US-1.2/1.15/1.20/1.30/1.32 |
| `AuthProvider` (Cognito \| Local) | Strategy for credential ops; selected by `AUTH_MODE` | Local testability; US-1.2/1.4/1.31/1.33 |
| `OtpService` | Issue/verify OTP challenge (hash+TTL+attempt cap+rate-limit) | US-1.32; SECURITY-12 |
| `UserService` | listUsers/editUser/disable/enable/bulkImport; role + suspend/restore semantics; last-leader/last-CL safeguards | US-1.4/1.5/1.6/1.19/1.26/1.31/1.33 |
| `GroupService` | group CRUD; join/leave; leaders; join-request approve/reject; soft-delete/restore/purge; membership-event derivation | US-1.7–1.11/1.16–1.18/1.21/1.34 |
| `Repository` | Single-table DynamoDB access (pk/sk + GSI1/2/3); parameterized expressions; membership-history append + derive current | NFR-IA-SCALE-1; SECURITY-05 |
| `EventPublisher` (`_conventions/envelope.py` + events client) | Wrap payload in platform envelope; PutEvents after commit; retry/log | BR-EV1; RESILIENCY-10 |
| `AuditLogger` (`_conventions/logger.py` + audit group) | Structured audit records; toggle-aware; redaction | US-1.13/1.14; SECURITY-03/14 |
| `SesAdapter` | Send OTP + local-admin reset email; timeouts; retryable errors | US-1.28/1.32; RESILIENCY-10 |
| `SecretsAdapter` (`_conventions/config.py`) | Fetch local-admin creds + JWT signing key; cached warm | SECURITY-12 |
| `sync_worker` | Scheduled Cognito reconciliation (idempotent, paginated) | US-1.4 |
| `health` | Shallow + deep health checks | RESILIENCY-06 |

## Infrastructure logical components (mapped to AWS in Infrastructure Design)
| Logical | AWS resource |
|---|---|
| Identity store + membership history | DynamoDB `identity-access-<stage>` (pk/sk, GSI1/2/3), PITR, Retain, KMS |
| OTP/idempotency store | DynamoDB (OTP items with TTL in main table; `identity-access-idem-<stage>` for future consumer idempotency) |
| Identity provider | Cognito User Pool (+ app client, password policy, email verification, forgot-password) |
| Local-admin creds + JWT key | Secrets Manager (2 secrets) |
| Transactional email | SES (verified sender identity) |
| Domain events | EventBridge (platform bus) |
| Scheduled sync | EventBridge Scheduler → Lambda |
| Compute | Lambda (python3.12, provisioned concurrency on auth path) |
| Edge | API Gateway REST + Cognito authorizer (Unit 1) |
| Observability | CloudWatch logs/metrics/alarms + X-Ray + audit log group |

## Data access patterns (single-table)
| Pattern | Keys |
|---|---|
| Get user by id | `pk=USER#<id>, sk=PROFILE` |
| Get user by email | GSI1 `gsi1pk=EMAIL#<email>` |
| List users by role/status | GSI2 `gsi2pk=ROLE#<role>` |
| Get group | `pk=GROUP#<id>, sk=META` |
| List join requests for group | `pk=GROUP#<id>, sk begins_with JOINREQ#` |
| Member's membership events | `pk=MEMBER#<id>, sk begins_with MEVENT#` |
| Group's membership events (analytics) | GSI3 `gsi3pk=GROUP#<id>` |
| OTP challenge | `pk=OTP#<challengeId>, sk=CHALLENGE` (TTL) |

**No blocking findings.**
