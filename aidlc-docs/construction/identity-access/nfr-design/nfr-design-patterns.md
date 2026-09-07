# NFR Design Patterns — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Identity & Access
How the NFR requirements are realized as concrete patterns in the service. Companion: `logical-components.md`.

## Security patterns
- **Edge authN + in-service fail-closed authZ (SECURITY-08)**: API Gateway Cognito authorizer validates the JWT; the handler parses claims into a `Principal` and calls `Authorizer.authorize(...)` from `role-permission-matrix.v1.json` before any state access. Default = deny; `own` enforces IDOR guard; `group` enforces led/member-group scope.
- **Dual credential paths (US-1.27)**: `AuthProvider` strategy. Community → Cognito (`initiate_auth`/`sign_up`). Local admin → Secrets Manager credential + PBKDF2 verify + portal-signed JWT (signing key in Secrets Manager). `accountType` stamped on the principal; portal-local reset endpoints reject non-local-admin sessions.
- **Adaptive password hashing (SECURITY-12)**: PBKDF2-HMAC-SHA256, high iteration count, per-secret random salt; constant-time compare. No plaintext, no reversible storage.
- **OTP challenge pattern (US-1.32, SECURITY-12)**: on due login, generate a random numeric code → store only its hash + `expiresAt` (TTL) + `attempts=0`; email code via SES; verify with expiry + attempt cap + issuance rate-limit; generic responses (no enumeration, BR-A6).
- **Secret handling (SECURITY-09/12)**: all secrets via Secrets Manager (local-admin creds, JWT signing key); never in env/code; clients cached across warm invocations.
- **Input validation + injection prevention (SECURITY-05)**: `validation.py` on every handler (type/length/email/enum, HTML rejection, body-size cap); DynamoDB expressions parameterized (no string-built queries); CSV/XLSX schema validated (header + per-row).
- **Log redaction + audit (SECURITY-03/14)**: structured JSON logger auto-redacts password/otp/token/secret; dedicated audit logger writes create/update/delete + login/logout to a separate CloudWatch group (append-only; app role cannot delete it); toggle from Settings; toggle-change always logged.
- **Least-privilege IAM (SECURITY-06)**: single-purpose execution role — DynamoDB CRUD on own tables + GSIs, EventBridge PutEvents (own bus), cognito-idp scoped to the pool ARN, ses:SendEmail scoped to the verified identity, secretsmanager:GetSecretValue on the two secret ARNs. No wildcards.

## Resilience patterns
- **Timeouts + fail-closed (RESILIENCY-10, SECURITY-15)**: every external call (Cognito, SES, Secrets, DynamoDB, EventBridge) uses a bounded botocore timeout + limited retries; any auth error path denies access (never fails open). `global_handler` wraps the Lambda so no exception escapes; generic 500 on unknown.
- **Best-effort event publish (BR-EV1)**: domain events publish **after** the primary DynamoDB write commits; publish failure is logged + retried but does not roll back or fail the user response (consumers are idempotent on envelope `id`). Optional transactional-outbox via DynamoDB Streams is available as a hardening step (documented, not required Phase 1).
- **Idempotent scheduled sync (BR-P2, RESILIENCY-03/04)**: match-and-update by Cognito `sub`/email; paginated `list_users`; safe to re-run; partial failure leaves records consistent (no destructive ops).
- **Idempotent consumers (inherited)**: this service is primarily a producer; the idempotency table + `IdempotencyStore` convention is available should it consume events later.
- **Graceful degradation**: SES outage → OTP/reset emails return retryable errors and login is not granted (fail closed); EventBridge outage → primary writes still succeed, downstream eventual consistency catches up.

## Performance patterns
- **Cold-start mitigation (NFR-IA-PERF-2)**: minimal dependency footprint; module-scope boto3 client creation reused across warm invocations; **provisioned concurrency** on the interactive auth path (`login`/`verifyOtp`) sized in Infrastructure Design.
- **Single-table access design (NFR-IA-SCALE-1)**: partitions per user/group; GSI1 email lookup, GSI2 role/status listing, GSI3 per-group membership history — bounded, index-served queries; no scans on hot paths (`bulkImport`/sync may page).

## Observability patterns (RESILIENCY-05/07)
- **Three pillars**: Powertools structured logs + correlation IDs; X-Ray tracing API→Lambda→Cognito/SES/DDB; CloudWatch EMF metrics (login success/failure, OTP issued/verified/failed, authZ denials, sync processed/failed).
- **Alarms**: error rate, p95 latency, throttles, Cognito/SES error rate, sync-failure, plus **security alarms** on repeated auth failures / authZ denials / local-admin password change.
- **Health checks (RESILIENCY-06)**: shallow (process up) + deep (DynamoDB describe + Cognito reachability).

## Resiliency test scenarios (captured for Operations — RESILIENCY-14)
| Scenario | Expected behavior |
|---|---|
| Cognito unavailable | `login` returns retryable error; access denied (fail closed); alarm fires |
| SES send failure | OTP/reset email error surfaced; session not granted; retried |
| DynamoDB throttle | botocore backoff/retry; within Lambda timeout; alarm on sustained throttles |
| Scheduled sync partial failure | re-run reconciles; no duplicates; no data loss |
| EventBridge publish failure | primary write succeeds; event retried; consumers idempotent |
| Region/AZ event | managed multi-AZ absorbs AZ loss; region loss → Backup & Restore runbook (inherited) |

## Compliance deltas (this stage)
All applicable SECURITY + RESILIENCY rules realized by the patterns above; SECURITY-04 remains N/A (no HTML). RESILIENCY-14 = scenarios captured (execution deferred to Operations). **No blocking findings.**
