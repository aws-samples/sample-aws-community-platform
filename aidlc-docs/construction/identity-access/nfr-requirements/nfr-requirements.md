# NFR Requirements — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Identity & Access
Platform-wide NFRs (Unit 1 `nfr-requirements.md`) are **inherited**. This document records identity-specific requirements and deltas. Companion: `tech-stack-decisions.md`.

## Workload criticality (RESILIENCY-01)
- **Criticality: CRITICAL.** Identity & Access gates authentication and authorization for the entire portal. If unavailable, no user can sign in and no authZ decision can be made — full portal outage. It is the first real service (auth never mocked).
- **Upstream deps**: Cognito user pool, SES (OTP + reset email), Secrets Manager (local-admin), Settings (OTP interval, session lifetime, allowed domains, audit toggle).
- **Downstream consumers**: all services (via `UserProvisioned`/`UserRoleChanged`/`UserDeactivated`/group + membership events).

## Availability & recovery (RESILIENCY-02/08 — inherited)
- **NFR-IA-AVAIL-1**: Single-region, multi-AZ on managed services (Cognito, Lambda, DynamoDB, EventBridge, SES). Target **99.9%** for the auth API.
- **NFR-IA-AVAIL-2**: DR = **Backup & Restore** (RTO/RPO hours). DynamoDB PITR + on-demand backups on the identity table and membership-event history. Cognito user pool is the identity system of record (its own managed durability); portal records are reconstructable via sync from Cognito for community users. Local-admin secret backed up with Secrets Manager.
- **NFR-IA-AVAIL-3**: Loss of the membership-event history is **not** acceptable silently (drives analytics US-7.2/7.3) → PITR mandatory; `DeletionPolicy: Retain` (D6).

## Performance (inherited targets + deltas)
- **NFR-IA-PERF-1**: p95 **< 400 ms** for reads (`listGroups`, `getGroup`, `listUsers`, `membershipHistory`) and **< 800 ms** for writes, **excluding** the Cognito `initiate_auth`/`sign_up` round-trip on `login`/`selfRegister` (external dependency latency reported separately).
- **NFR-IA-PERF-2**: `login` and `verifyOtp` are interactive/latency-sensitive → candidates for **provisioned concurrency** (cost-controlled per NFR-PERF-2) to bound cold-start on the auth path.
- **NFR-IA-PERF-3**: `bulkImport` is asynchronous-tolerant (batch); may run to the Lambda 15s timeout ceiling for moderate files; very large files are chunked (design in NFR Design).

## Scalability (inherited)
- **NFR-IA-SCALE-1**: DynamoDB **on-demand**; access patterns keyed to avoid hot partitions (per-user/per-group partitions, GSIs for email/role/group-history).
- **NFR-IA-SCALE-2**: Lambda concurrency auto-scales; set a **reserved concurrency floor** on the auth function is unnecessary (single function per service) but a **concurrency ceiling** protects Cognito/SES from runaway load (RESILIENCY-09). SES send rate is a quota to monitor.
- **NFR-IA-SCALE-3**: Scheduled Cognito sync paginates `list_users`; idempotent (BR-P2) so re-runs are safe.

## Security (highest sensitivity — Security Baseline)
- **NFR-IA-SEC-1 (SECURITY-12)**: Password policy enforced by Cognito for community users; **portal-enforced policy for the local admin** (min 8, reject common/breached passwords, adaptive hash — PBKDF2-HMAC-SHA256 with high iteration count or bcrypt). No hardcoded credentials — local-admin secret in Secrets Manager, seeded at deploy.
- **NFR-IA-SEC-2 (SECURITY-12)**: **Brute-force protection** — OTP challenge caps attempts + short expiry + issuance rate-limit (BR-A5); Cognito advanced security / threat protection for community logins; API Gateway throttling on `/auth/*`.
- **NFR-IA-SEC-3 (SECURITY-12)**: **OTP re-verification** as a possession factor (US-1.32); email OTP acknowledged as not phishing-resistant (stronger factors for Admin/CL deferred, documented). Sessions have server-side expiry (Settings), invalidated on logout (US-1.3).
- **NFR-IA-SEC-4 (SECURITY-08)**: **Fail-closed in-service authZ** from the permission matrix on every mutating/reading handler; object-level (own) IDOR guard + group-scope checks; CORS restricted to the SPA origin; JWT validated server-side each request (Cognito authorizer + in-service claim parse).
- **NFR-IA-SEC-5 (SECURITY-05)**: Validate all inputs (email format, string lengths, enum roles, CSV/XLSX schema on import); reject HTML/script; cap body size; no query concatenation (DynamoDB parameterized).
- **NFR-IA-SEC-6 (SECURITY-06)**: Per-Lambda execution role scoped to: this service's DynamoDB tables (+ GSIs), its EventBridge bus (PutEvents), Cognito user-pool admin actions (scoped to the pool ARN), SES send (scoped identity), Secrets Manager GetSecretValue (local-admin secret ARN only), Settings read. No wildcards.
- **NFR-IA-SEC-7 (SECURITY-03/14)**: Structured JSON logs, correlation IDs, **never log passwords/OTP/tokens** (logger redaction). **Alerting** on repeated auth failures, authZ denials, local-admin password changes (auth-security events). Audit log (US-1.13) append-only to CloudWatch, 12-month retention; app role cannot delete its own audit log group.
- **NFR-IA-SEC-8 (SECURITY-15)**: Global fail-closed error handler; generic error messages; explicit error handling + resource cleanup on all external calls (Cognito/SES/Secrets/DynamoDB).
- **NFR-IA-SEC-9 (SECURITY-01)**: Identity + idempotency tables encrypted at rest (AWS-managed KMS); TLS 1.2+ to all AWS APIs. No PII in event payloads beyond what consumers require (email/name minimized).

## Reliability / Resiliency (Resiliency Baseline)
- **NFR-IA-REL-1 (RESILIENCY-10)**: Explicit **timeouts** on all external calls (Cognito, SES, Secrets Manager, DynamoDB, EventBridge); **graceful degradation** — if SES is down, OTP/reset email failures are surfaced as retryable errors (login fails closed, never open); if EventBridge publish fails, the primary write still succeeds and the event is retried (BR-EV1).
- **NFR-IA-REL-2 (RESILIENCY-06)**: Health check endpoint (shallow) + deep check verifying DynamoDB + Cognito reachability.
- **NFR-IA-REL-3**: Scheduled sync is idempotent and safe to re-run; a failed sync run does not corrupt portal records (match-and-update only).
- **NFR-IA-REL-4 (RESILIENCY-12)**: DynamoDB PITR + on-demand backups; membership history retained indefinitely (except group hard-delete purge).
- **NFR-IA-REL-5 (RESILIENCY-05/07)**: Metrics + alarms — auth error rate, p95 latency, throttles, Cognito/SES error rate, sync-job failure, DLQ depth (if async paths added). X-Ray tracing across API→Lambda→Cognito/SES.

## Maintainability (inherited)
- **NFR-IA-MAINT-1**: Contract-test gate (Schemathesis + pytest) must pass before real code deploys; unimplemented ops return 501. bandit + cfn-lint/cfn_nag + dep scan + SBOM in CI (SECURITY-10).

## Compliance / scope
- **NFR-IA-COMP-1**: No regulated regime (Phase 1). Email/name are the only PII; minimized in logs/events. Data residency = customer's chosen single region.

## Security Compliance Summary (this stage)
| Rule | Status | Note |
|---|---|---|
| SECURITY-01 Encryption | Compliant | Tables KMS-encrypted; TLS to AWS APIs |
| SECURITY-02 Access logging | Compliant (inherited) | API GW execution/access logs at edge |
| SECURITY-03 App logging | Compliant | JSON + correlation IDs; secrets/OTP redacted |
| SECURITY-04 Security headers | N/A | No HTML served by this service (SPA/CloudFront) |
| SECURITY-05 Input validation | Compliant | validation.py + CSV/XLSX schema; body caps |
| SECURITY-06 Least privilege | Compliant | Scoped exec role (DDB/Cognito/SES/Secrets/EventBridge) |
| SECURITY-07 Network | Compliant (inherited) | Lambda in private subnets, VPC endpoints |
| SECURITY-08 Access control | Compliant | Fail-closed in-service authZ, IDOR + group scope |
| SECURITY-09 Hardening | Compliant | No default creds; generic errors; local-admin seeded via secret |
| SECURITY-10 Supply chain | Compliant | Pinned reqs + scan/SBOM in CI |
| SECURITY-11 Rate limiting | Compliant | API GW throttling on /auth/*; OTP issuance rate-limit |
| SECURITY-12 Auth & credentials | Compliant | Cognito policy/MFA-OTP; adaptive hash local admin; brute-force caps; Secrets Manager |
| SECURITY-13 Integrity | Compliant (inherited) | Auditable pipeline; safe parsing (no unsafe deserialization) |
| SECURITY-14 Alerting | Compliant | Alarms on auth failures / authZ denials / local-admin pw change; 12-mo audit retention |
| SECURITY-15 Exception handling | Compliant | Global fail-closed handler, generic messages |

## Resiliency Compliance Summary (this stage)
| Rule | Status | Note |
|---|---|---|
| RESILIENCY-01 Criticality | Compliant | Classified CRITICAL; deps mapped |
| RESILIENCY-02 RTO/RPO | Compliant (inherited) | Backup & Restore; PITR |
| RESILIENCY-03 Change mgmt | N/A (inherited) | Exempt per platform decision |
| RESILIENCY-04 Deploy/rollback | Compliant (inherited) | CodePipeline; redeploy previous version rollback |
| RESILIENCY-05 Monitoring | Compliant | Metrics/logs/traces + dashboard (NFR Design) |
| RESILIENCY-06 Health checks | Compliant | Shallow + deep (DDB/Cognito) |
| RESILIENCY-07 Resiliency monitoring | Compliant | Sync-failure + SES/Cognito error alarms |
| RESILIENCY-08 Multi-zone | Compliant (inherited) | Managed multi-AZ services |
| RESILIENCY-09 Auto-scaling | Compliant | On-demand DDB + Lambda concurrency ceiling; SES quota monitored |
| RESILIENCY-10 Circuit breaking | Compliant | Timeouts + graceful degradation (fail closed) |
| RESILIENCY-11 DR strategy | Compliant (inherited) | Backup & Restore documented |
| RESILIENCY-12 Backup | Compliant | PITR + on-demand backups; Retain |
| RESILIENCY-13 Failover procedures | Compliant (inherited) | Platform runbook; single-region restore |
| RESILIENCY-14 Resiliency testing | Deferred-to-Operations (inherited) | Capture scenarios in NFR Design |
| RESILIENCY-15 Incident response | Compliant (inherited) | Lightweight IR + COE (platform decision) |

**No blocking security or resiliency findings.**
