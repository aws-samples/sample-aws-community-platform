# Logical Components — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Platform & Delivery
The logical (technology-anchored but pre-Infra) components that implement the NFR patterns. These are shared substrate + per-service building blocks the scaffold generates. Companion: `nfr-design-patterns.md`.

## A. Shared substrate components (Foundation + Edge)
| Component | Purpose | NFR pattern |
|---|---|---|
| **VPC + private subnets + NAT** | Lambda network isolation; egress for third-party (MS Teams) | P-NETWORK |
| **VPC endpoints** | Private access to DynamoDB/S3 (gateway) + EventBridge/SQS/SES/Secrets/CloudWatch/Bedrock/OpenSearch (interface) | P-NETWORK |
| **Cognito user pool** | AuthN; custom-auth trigger hooks reserved (logic in Identity) | P-AUTHZ |
| **API Gateway (REST) + authorizer** | Single shared edge; per-service routes; throttling + usage plans | P-RATE-LIMIT, P-AUTHZ |
| **Shared EventBridge bus** | Domain-event transport; rules per consumer | P-EVENT-SCALE |
| **CloudFront + S3 (SPA)** | Static hosting + asset cache + security headers | P-CACHE, SECURITY-04 |
| **Observability baseline** | Central log groups, X-Ray, dashboards, alarm topics | P-CORRELATION, P-ALARMS |
| **KMS (AWS-managed) usage** | Encrypt-at-rest across data stores | P-ENCRYPTION |

## B. Per-service building blocks (generated into each service by the scaffold)
| Component | Purpose | NFR pattern |
|---|---|---|
| **Idempotency table** (DynamoDB, TTL) | Dedupe consumers on envelope `id` | P-IDEMPOTENCY |
| **Consumer SQS queue + DLQ** | Durable async intake per consumer rule; failure isolation | P-RETRY-DLQ, P-EVENT-SCALE |
| **AuthZ middleware** | Load permission spec; enforce function/object-level checks | P-AUTHZ, P-LEAST-PRIV |
| **Structured logger + correlation** | JSON logs, correlation id from envelope | P-CORRELATION |
| **Global error handler** | Fail-closed, generic messages, cleanup | P-FAIL-CLOSED |
| **Envelope (de)serializer** | Build/parse the versioned event envelope | P-IDEMPOTENCY, contracts |
| **External-call wrapper** | Timeouts + bounded retries + graceful fallback | P-EXTERNAL-CALL |
| **Per-Lambda execution role** | Least-privilege to own resources only | P-LEAST-PRIV |

> These are **generated copies owned by each service** (P-CONVENTIONS / FQ1), not a shared library. A reference implementation lives in `/platform`.

## C. Platform/factory components (this unit's own deliverables)
| Component | Purpose |
|---|---|
| **Mock factory** | Generate Python mock Lambda per service from OpenAPI (fixture-backed; 501 for unimplemented) |
| **Fixture dataset + loader** | One coherent seed; loaded into each service's `-data` table at bootstrap |
| **Scaffold generator** | Emit `-data`/`-app`/pipeline + mock handler + per-service convention copies |
| **Contract-test harness** | Schemathesis+pytest suite (schema/401/403/501); the pipeline gate; runs vs mock AND real |
| **Reusable CodePipeline template** | Per-service pipeline (source→build→scan→contract-test→deploy→create-deployment→smoke→manifest) |
| **Root template + nested composition** | Customer one-shot install; `EnableSemanticSearch` condition; seeding custom resources |
| **Config distribution** | Stack Parameters → Lambda env vars; SSM (dev) / foundation outputs (customer); SPA `config.json` | 
| **`service-mode` manifest** | Informational dev-tracking (mock/partial/complete) |

## D. Install-time custom resources (D7)
| Component | Purpose |
|---|---|
| **Seeder** | Scoring framework, email templates, certification catalog |
| **Bootstrap admin** | Local Administrator + Secrets Manager secret |
| **SPA deployer** | Copy prebuilt SPA bundle to S3 + inject `config.json` |

## Component interaction (event path)
```
Producer service ──put(enveloped event)──▶ EventBridge bus
     ▲                                          │  (rule filters by type)
     │                                          ▼
     │                                   Consumer SQS queue ──(fail x3)──▶ DLQ ──alarm──▶ manual redrive
     │                                          │
     │                                          ▼
     └───────────── Consumer Lambda: idempotency check (id) → authZ (n/a for events) → handle → own DynamoDB
                                                │
                                                └─ external calls via wrapper (timeout+retry+fallback)
```

## Config / distribution flow (Q7)
```
foundation outputs (VpcId, SubnetIds, UserPoolId, EventBusName, RestApiId, RootResourceId)
   ├─ dev:      pipeline reads from SSM ──▶ passes as CFN Parameters
   └─ customer: root template passes foundation outputs ──▶ as CFN Parameters
        └─▶ service -app stack ──▶ Lambda env vars
SPA: deploy-time generated config.json (API URL, user-pool id)  [no secrets in env/config]
Secrets (local-admin): Secrets Manager reference at runtime
```

## Deferred to Infrastructure Design
- Concrete VPC CIDRs/subnets, NAT count, exact VPC-endpoint list.
- API Gateway throttling numbers + usage-plan definitions.
- Idempotency-table TTL final value; DLQ alarm thresholds.
- Per-service reserved-concurrency needs (if any).
- Analytics read-model store choice (Analytics unit).
