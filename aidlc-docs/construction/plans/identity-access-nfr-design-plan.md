# NFR Design Plan — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Identity & Access

## Steps
- [x] 1. Analyze NFR requirements
- [x] 2. Create this plan
- [x] 3. Generate questions (resolved from inherited patterns — below)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (N/A)
- [x] 6. Generate artifacts (nfr-design-patterns.md, logical-components.md)
- [x] 7. Present completion
- [ ] 8/9. Approval + state update

## Questions → resolved
| Category | Resolution |
|---|---|
| Resilience patterns | Timeouts on every external call; fail-closed on auth; best-effort event publish with retry (write succeeds independently); idempotent scheduled sync. No circuit breaker needed (Cognito/SES are AWS-managed; retries + timeouts suffice). |
| Scalability patterns | Serverless auto-scale; Lambda concurrency ceiling to protect Cognito/SES; single-table access patterns + GSIs to avoid hot partitions. |
| Performance patterns | Provisioned concurrency on login/verifyOtp; lazy boto3 client init + reuse across invocations; minimal deps. |
| Security patterns | Cognito authorizer (edge authN) + in-service fail-closed authZ; adaptive hashing; OTP challenge with expiry/attempt caps; secret-manager-held signing key + local-admin creds; log redaction; scoped IAM. |
| Logical components | Auth provider, OTP service, event publisher, audit logger, repository, Cognito/SES/Secrets adapters, scheduled-sync worker. |
| Resiliency testing (RESILIENCY-14) | Capture scenarios now, execute in Operations: Cognito unavailable → login fails closed; SES failure → OTP retryable; DDB throttle → backoff; sync partial failure → safe re-run. |
