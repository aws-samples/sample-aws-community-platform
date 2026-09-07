# Tech Stack Decisions — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Platform & Delivery
Platform-wide technology choices inherited by all service units. Companion: `nfr-requirements.md`.

## Backend runtime (Q1)
| Choice | Decision | Rationale |
|---|---|---|
| Language | **Python 3.12** on AWS Lambda | Confirmed D8 (all services Python); 3.12 is current supported managed runtime |
| Lambda toolkit | **AWS Lambda Powertools for Python** | Structured logging + correlation IDs, tracing, metrics out-of-the-box (NFR-SEC-3, NFR-OBS-1) |
| AWS SDK | **boto3** | Standard |
| Packaging | **AWS SAM** (`sam build`/`sam deploy`); dependency-complete zips vendored into `dist/` (D4) | Prebuilt default install; no customer toolchain needed |

## Platform tooling (Q2)
| Concern | Choice | Rationale |
|---|---|---|
| Mock factory + scaffold generator | **Python** | Same language as services; generates mock Lambdas + `-data`/`-app`/pipeline scaffolds from OpenAPI |
| Contract tests (the gate) | **Schemathesis** (OpenAPI-driven) + **pytest** | Property/example tests derived from the contract; run vs mock AND real (BR-19/20) |
| Event-schema validation | **jsonschema** | Validate event payloads against versioned JSON Schema |
| SPA API layer | **openapi-typescript** (types) + generated fetch client | Q9 — SPA types generated from contracts; kept in lockstep |
| IaC | **CloudFormation + AWS SAM** | Confirmed; root template nests per-service stacks (D1) |
| IaC scanning | **cfn-lint** + **cfn_nag** | NFR-MAINT-1 |
| Python SAST | **bandit** | NFR-MAINT-1 |
| Dependency scan / SBOM | vulnerability scanner + SBOM generation in CI | SECURITY-10 |

## Edge / API
| Choice | Decision |
|---|---|
| API | **Amazon API Gateway (REST)** — single shared API; per-service routes |
| AuthN | **Amazon Cognito** authorizer (JWT) |
| Rate limiting | **API Gateway throttling + usage plans** (SECURITY-11; WAF omitted — AC-1) |
| CDN / SPA hosting | **CloudFront + S3** (+ security headers, SECURITY-04) |
| WAF | **Omitted (AC-1)** — accepted design choice |

## Data / integration
| Choice | Decision |
|---|---|
| Database | **DynamoDB**, table-per-service, **on-demand**, **PITR** + on-demand backups, `Retain` (D6) |
| CDC | **DynamoDB Streams** |
| Eventing | **Amazon EventBridge** (domain events) |
| Durable async | **Amazon SQS + DLQ** |
| Object storage | **Amazon S3** (materials, file-share, exports, SPA assets), public access blocked |
| Email | **Amazon SES** |
| Secrets | **AWS Secrets Manager** (local-admin creds) |
| Scheduling | **EventBridge Scheduler** |

## Semantic Search capability (Q10) — conditional
| Choice | Decision |
|---|---|
| Toggle | Single CloudFormation condition **`EnableSemanticSearch`** (Units 13 Search + 14 AI Gateway together) |
| Vector store | **Amazon OpenSearch Serverless** (vector) — deployed only when enabled |
| AI | **Amazon Bedrock** (embeddings, dup detection, reporting, insights, help) — deployed only when enabled |
| Region note | Bedrock model availability is an install prerequisite when enabled |

## Encryption / keys (Q5=C)
| Choice | Decision |
|---|---|
| At rest | **AWS-managed KMS keys** for DynamoDB/S3/SQS/Logs (no customer-CMK option — AC-2) |
| In transit | **TLS 1.2+** everywhere |

## Security posture (Q7/Q8)
| Choice | Decision |
|---|---|
| IAM | Per-Lambda execution roles + per-service pipeline deploy roles; least privilege (SECURITY-06) |
| Cognito | Strong password policy, email verification, advanced security/threat protection, MFA for admin, custom-auth trigger hooks reserved (logic wired by Identity unit) |
| Networking | Lambdas in private subnets; NAT egress; VPC endpoints (SECURITY-07) |

## CI/CD (Q11)
| Choice | Decision |
|---|---|
| Orchestration | **AWS CodePipeline**, one pipeline per service (each its own CFN stack) — D5 |
| Pipeline stages | source → build → unit tests → **dep-scan / bandit / cfn-lint+cfn_nag** → **contract tests (gate)** → deploy `-data` → deploy `-app` → API `create-deployment` → smoke test → update `service-mode` |
| Approvals | Dev auto-deploy; **manual approval only for the customer release build** |

## Availability / performance targets (Q3/Q4)
- Single region, multi-AZ; 99.9% API tier; Backup & Restore DR.
- p95 < 400 ms reads / < 800 ms writes (excl. cold starts); provisioned concurrency on interactive functions only.

## Open items deferred to Infrastructure Design
- Concrete VPC CIDR/subnet layout, NAT count (cost vs AZ-resilience), and the exact VPC-endpoint set.
- API Gateway throttling limits (per-method vs account) and usage-plan definitions.
- Provisioned-concurrency sizing per interactive function.
- Analytics read-model store choice (Analytics unit).
