# NFR Requirements — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Platform & Delivery
**Enabled baselines**: Security Baseline (SECURITY-01..15) + Resiliency Baseline. These NFRs are platform-wide defaults inherited by all service units. Companion: `tech-stack-decisions.md`.

## Scalability
- **NFR-SCALE-1**: DynamoDB **on-demand** capacity (auto-scales with load); no manual capacity planning in Phase 1 (Q12).
- **NFR-SCALE-2**: Lambda concurrency scales per service; API Gateway default account-level throttling as the shared ceiling; per-method throttling where a service needs a tighter bound.
- **NFR-SCALE-3**: Event-driven components (EventBridge/SQS) absorb spikes; consumers scale independently.

## Performance (Q4)
- **NFR-PERF-1**: p95 latency target **< 400 ms** typical reads, **< 800 ms** writes (excluding cold starts).
- **NFR-PERF-2**: Python cold-start mitigation — right-sized memory, minimal dependency footprint, **provisioned concurrency only on latency-sensitive/interactive functions** (cost-controlled).
- **NFR-PERF-3**: Semantic-search paths (when enabled) have their own budget refined in Search/AI unit NFRs.

## Availability (Q3)
- **NFR-AVAIL-1**: **Single region, multi-AZ**, relying on managed-service AZ redundancy (API GW, Lambda, DynamoDB, Cognito, EventBridge).
- **NFR-AVAIL-2**: Target **99.9%** for the API tier.
- **NFR-AVAIL-3**: DR posture = **Backup & Restore** (no multi-region in Phase 1); DynamoDB PITR + on-demand backups.

## Security (Security Baseline — mapped to SECURITY rules)
- **NFR-SEC-1 (SECURITY-01)**: Encrypt at rest everywhere (DynamoDB, S3, SQS, CloudWatch Logs) using **AWS-managed KMS keys** (Q5=C — no customer-CMK option in Phase 1); enforce **TLS 1.2+** in transit; S3 rejects non-TLS via bucket policy.
- **NFR-SEC-2 (SECURITY-02)**: Access logging on **API Gateway** (execution + access logs) and **CloudFront** (standard logging) to CloudWatch/S3. *(Retained independently of the WAF decision.)*
- **NFR-SEC-3 (SECURITY-03/14)**: Structured JSON app logging with correlation IDs to CloudWatch; no secrets/PII in logs; audit logs append-only, app roles cannot delete their own log groups; **audit retention 12 months** (US-1.13), app-log retention default 30 days; alerts on auth failures / authorization violations.
- **NFR-SEC-4 (SECURITY-04)**: HTTP security headers on all HTML/SPA responses (`Content-Security-Policy default-src 'self'`, `Strict-Transport-Security max-age=31536000; includeSubDomains`, `X-Content-Type-Options nosniff`, `X-Frame-Options DENY`, `Referrer-Policy strict-origin-when-cross-origin`) set at CloudFront/app.
- **NFR-SEC-5 (SECURITY-06)**: **Per-Lambda execution roles** and **per-service pipeline deploy roles**, scoped to that service's own resources; no wildcard actions/resources without a documented exception (Q7).
- **NFR-SEC-6 (SECURITY-07)**: Deny-by-default networking; Lambdas in **private subnets**; egress via **NAT**; **VPC endpoints** for AWS-service access; no inbound `0.0.0.0/0` except public CloudFront/API on 443.
- **NFR-SEC-7 (SECURITY-08)**: AuthN at edge (Cognito authorizer); **authZ in-service** fail-closed with object-level (IDOR) + function-level checks from the permission spec; **CORS restricted** to the SPA origin (no wildcard on authenticated endpoints); JWT validated server-side every request.
- **NFR-SEC-8 (SECURITY-11)**: **Rate limiting via API Gateway throttling + usage plans** on public endpoints (satisfies SECURITY-11 in lieu of WAF — Q6); security-critical logic isolated (auth/authz modules).
- **NFR-SEC-9 (SECURITY-12)**: Cognito strong password policy (min 8 + breached-password check), email verification, advanced security/threat protection (Q8=A), MFA supported for admin; sessions server-side expiry + invalidated on logout; secure/httpOnly/sameSite cookies where cookies used; **no hardcoded secrets** (Secrets Manager for local-admin creds).
- **NFR-SEC-10 (SECURITY-09/15)**: Hardening — no default creds; generic production error messages (no internals); S3 public access blocked; global fail-closed error handler; explicit error handling + resource cleanup on all external calls.
- **NFR-SEC-11 (SECURITY-10/13)**: Dependency pinning + lock file; vulnerability scan + SBOM in CI; pinned tool/base-image versions; SRI on any external CDN scripts; CI/CD pipeline definitions access-controlled and auditable.

### Accepted design choices (recorded)
- **AC-1 (Q6)**: **AWS WAF omitted.** Rate limiting provided by API Gateway throttling (SECURITY-11 satisfied). Trade-off: no WAF managed rule sets (common-exploit/known-bad-inputs L7 filtering). Accepted for cost/simplicity; can be added later without architectural change.
- **AC-2 (Q5)**: **No customer-managed KMS key option.** AWS-managed keys only (SECURITY-01 satisfied). Trade-off: customers cannot bring their own CMK; revisit if an enterprise customer requires it.

## Reliability / Resiliency (Resiliency Baseline — Q9)
- **NFR-REL-1**: **SQS + DLQ** for all durable async consumers; retry with exponential backoff.
- **NFR-REL-2**: **Explicit timeouts + graceful degradation** on external calls (Bedrock, SES, MS Teams, OpenSearch).
- **NFR-REL-3**: **Idempotent event consumers** keyed on the envelope `id` (protects the points ledger under at-least-once delivery).
- **NFR-REL-4**: **DynamoDB PITR** + on-demand backups; `Retain` policies (D6); last-write-wins concurrency.

## Observability (Q10)
- **NFR-OBS-1**: Structured JSON logs + correlation IDs; **X-Ray** tracing API→Lambda→downstream.
- **NFR-OBS-2**: CloudWatch metrics + **alarms** (error rate, p95 latency, DLQ depth, throttles) + per-unit dashboards.

## Maintainability (Q11/CI-CD)
- **NFR-MAINT-1**: CI stages before the contract-test gate — dependency vuln scan, **bandit** (SAST), **cfn-lint/cfn_nag** (IaC scan); dev auto-deploy; **manual approval only for the customer release build**.
- **NFR-MAINT-2**: Contracts-as-source-of-truth; generated mocks/clients; no hand-duplicated contract shapes.

## Compliance / scope (Q12)
- **NFR-COMP-1**: No specific regulated regime (HIPAA/PCI) in Phase 1; single-region data residency (customer's chosen region); Bedrock region availability documented as an install prerequisite when `EnableSemanticSearch`=on.

## Security Compliance Summary (this stage)
| Rule | Status | Note |
|---|---|---|
| SECURITY-01 Encryption | Compliant | AWS-managed keys + TLS (Q5=C; managed keys allowed by the rule) |
| SECURITY-02 Access logging | Compliant | API GW + CloudFront logging (independent of WAF) |
| SECURITY-03 App logging | Compliant | JSON + correlation IDs, no secrets/PII |
| SECURITY-04 Security headers | Compliant | Set at CloudFront/app |
| SECURITY-05 Input validation | Deferred-to-service | Enforced per endpoint in each service (contract-test asserts) |
| SECURITY-06 Least privilege | Compliant | Per-Lambda + per-pipeline roles |
| SECURITY-07 Network | Compliant | Private subnets, NAT, VPC endpoints, deny-by-default |
| SECURITY-08 Access control | Compliant | Cognito authN + in-service authZ, restricted CORS |
| SECURITY-09 Hardening | Compliant | No defaults, generic errors, S3 public-access blocked |
| SECURITY-10 Supply chain | Compliant | Pinning + scan + SBOM in CI |
| SECURITY-11 Secure design / rate limit | Compliant | API Gateway throttling (WAF omitted — AC-1) |
| SECURITY-12 Auth & credentials | Compliant | Cognito policy/MFA/sessions; Secrets Manager |
| SECURITY-13 Integrity | Compliant | SRI, access-controlled auditable pipelines |
| SECURITY-14 Alerting/monitoring | Compliant | Alarms + append-only audit + 12-month retention |
| SECURITY-15 Exception handling | Compliant | Global fail-closed handler, generic errors |

**No blocking security findings.** AC-1 (no WAF) and AC-2 (no CMK) are recorded accepted design choices, both baseline-compliant.
