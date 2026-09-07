# NFR Design Patterns — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Platform & Delivery
Concrete patterns that realize the approved NFR Requirements. Platform-wide — inherited by all service units. Companion: `logical-components.md`.

## Resilience patterns

### P-IDEMPOTENCY (Q1) — protects the append-only ledger
- Every consumer is **idempotent on the event envelope `id`**.
- Mechanism: a per-service **idempotency table** (DynamoDB) keyed on `id` with **TTL ≈ 7 days**; consumer performs a conditional put — if `id` already present, **skip** (already processed).
- Implemented via **AWS Lambda Powertools idempotency utility** (minimal custom code; consistent across the 14 Python services).
- Guarantee: at-least-once delivery (EventBridge/SQS) never causes double-award / double-side-effect (Correctness Property 6).

### P-RETRY-DLQ (Q2)
- Async consumers: **exponential backoff, max 3 attempts**, then route to a **DLQ**.
- **CloudWatch alarm on DLQ depth > 0**; **manual redrive** after fix (no auto-redrive in Phase 1).
- SES email path: 3 retries / 15 min then discard (per NFR).

### P-EXTERNAL-CALL (Q3) — Bedrock / SES / MS Teams / OpenSearch
- **Explicit timeouts** on every external call + **bounded retries (2)** with backoff.
- **Graceful degradation** (fail-safe per requirement):
  - AI insights → **stale-with-timestamp** fallback.
  - Duplicate detection → **fail closed** (reject/hold) per requirement.
  - Mention autocomplete → **no-suggestions** fallback.
  - When `EnableSemanticSearch`=off → features hidden/skipped per the Q10 matrix.
- **No circuit breaker** in Phase 1 (low call volume; timeouts + fallback sufficient). Revisit if a dependency shows sustained failure.

### P-FAIL-CLOSED (SECURITY-15)
- Global top-level error handler in every Lambda; on error → deny/halt (never fail open); generic user-facing messages; resource cleanup on error paths.

## Scalability patterns

### P-CONCURRENCY (Q4) — **no provisioned concurrency**
- **Default (unreserved) on-demand Lambda concurrency**; **NO provisioned concurrency** anywhere (cost choice).
- **Reserved concurrency** applied only where needed to protect a specific downstream (decided per service; not a platform default).
- **Accepted trade-off (AC-3)**: Python **cold-start latency is accepted** on first/idle-scaled invocations; interactive calls may occasionally exceed the steady-state p95 target on a cold start. NFR-PERF p95 targets remain defined excluding cold starts. Zero-cost cold-start mitigations retained: **right-sized memory, minimal dependency footprint, lazy imports**.

### P-EVENT-SCALE (Q6)
- **Single shared EventBridge bus**; **one rule per consumer** (filter by `type`); each rule target has its own **SQS queue + DLQ**, so a slow/failing consumer never backs up producers or other consumers.
- Consumers scale independently on their queue depth.

### P-DATA-SCALE
- DynamoDB **on-demand** (auto-scales); table-per-service isolates hot partitions per domain; Streams fan-out per service.

## Performance patterns

### P-CACHE (Q5)
- **CloudFront** caches SPA static assets (long TTL + cache-busting on deploy).
- **No API Gateway response cache** (data is dynamic/role-scoped) and **no DAX** in Phase 1.
- Reintroduce targeted caching only if a measured hot read path emerges.

## Security patterns

### P-AUTHZ (SECURITY-08, FQ3a)
- AuthN at edge (Cognito authorizer) → in-service **authZ middleware** applied to every handler; loads the permission spec (`role-permission-matrix.vN.json`); enforces function-level + object-level (`own`/`group`) checks; deny → 403 fail-closed.

### P-LEAST-PRIV (SECURITY-06)
- One execution role per Lambda scoped to its own table(s)/queue(s)/events; one deploy role per pipeline scoped to that service's stacks; no wildcard actions/resources without documented exception.

### P-NETWORK (SECURITY-07)
- Lambdas in **private subnets**; egress via **NAT**; **VPC endpoints** for AWS-service access; deny-by-default security groups.

### P-RATE-LIMIT (SECURITY-11)
- **API Gateway throttling + usage plans** as the public rate-limit ceiling (WAF omitted — AC-1).

### P-SECRETS / P-ENCRYPTION
- Secrets (local-admin) in **Secrets Manager**, referenced (never env vars). Encrypt-at-rest with **AWS-managed KMS** (AC-2), TLS 1.2+ in transit.

## Observability patterns

### P-CORRELATION
- `correlationId` originates at API edge, propagates through the **event envelope** into async consumers; present in every structured log line and X-Ray trace.

### P-ALARMS
- Per-function alarms: error rate, p95 latency, throttles; per-queue: DLQ depth; per-unit CloudWatch dashboard.

## Maintainability patterns

### P-CONVENTIONS (Q8, FQ1) — consistency without shared code
- The **scaffold generator emits a per-service copy** of the cross-cutting conventions (logger, error handler, validation, authZ middleware, idempotency wrapper, envelope (de)serialization) as **generated code owned by each service** — not a shared library.
- A **documented reference implementation** lives in `/platform`; regeneration realigns services; **contract tests** (401/403/501/schema) + lint catch drift.

## Accepted trade-offs (recorded)
- **AC-1** WAF omitted (rate limit via API GW throttling).
- **AC-2** No customer-managed KMS key (AWS-managed only).
- **AC-3** No provisioned concurrency — Python cold-start latency accepted (Q4).
