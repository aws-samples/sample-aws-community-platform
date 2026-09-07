# NFR Requirements Plan — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Identity & Access
**Enabled baselines**: Security (SECURITY-01..15) + Resiliency. Platform-wide NFRs (Unit 1) are inherited; this stage records identity-specific deltas.

## Steps
- [x] 1. Analyze functional design
- [x] 2. Create this plan
- [x] 3. Generate questions (resolved — see below)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (N/A — inherited platform decisions)
- [x] 6. Generate artifacts (nfr-requirements.md, tech-stack-decisions.md)
- [x] 7. Present completion
- [ ] 8/9. Approval + state update

## Questions → resolved from platform NFRs (Unit 1) + requirements
| Area | Resolution |
|---|---|
| Scalability / capacity | Inherit: DynamoDB on-demand, Lambda per-service concurrency, API GW throttling. Identity is auth-critical → add reserved/provisioned concurrency consideration for `login`/`verifyOtp` (interactive). |
| Performance | Inherit p95 <400ms reads / <800ms writes. Login excludes Cognito round-trip latency. |
| Availability | Inherit single-region multi-AZ, 99.9%, Backup & Restore (RESILIENCY-02/08 already answered). Identity is **Critical** (RESILIENCY-01) — auth gates the whole portal. |
| Security | Auth service = highest sensitivity: SECURITY-12 (brute-force, password policy, MFA/OTP, no hardcoded creds), SECURITY-08 (fail-closed authZ), SECURITY-05 (input validation), SECURITY-14 (auth-failure alerting). No new accepted exceptions beyond AC-1/AC-2. |
| Tech stack | Inherit Python 3.12 + Powertools + boto3 + SAM. Add: Cognito IDP, SES, Secrets Manager, EventBridge Scheduler, password hashing lib. |
| Reliability | Inherit SQS+DLQ (n/a — Identity is a producer, not a durable consumer), idempotent consumers, PITR. Scheduled sync must be idempotent (BR-P2). |
| DR | Inherit Backup & Restore; DynamoDB PITR + on-demand backups; Secrets Manager + Cognito are managed/replicable. |
