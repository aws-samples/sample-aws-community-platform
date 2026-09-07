# Infrastructure Design — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Platform & Delivery
Maps the NFR logical components to concrete AWS resources + CloudFormation/SAM. Companion: `deployment-architecture.md`, shared `../../shared-infrastructure.md`.

## Stacks owned by this unit
| Stack | Resources | Lifecycle |
|---|---|---|
| `infra/foundation.yaml` | VPC/subnets/NAT, gateway VPC endpoints (S3,DynamoDB), Cognito pool, EventBridge bus, KMS usage, observability baseline + alarm SNS topic | deployed once per env |
| `infra/api-edge.yaml` | API Gateway (REST) + Cognito authorizer + throttling/usage plans; CloudFront + S3 (SPA) | deployed once per env |
| `infra/root-template.yaml` | nests foundation → api-edge → 15 service stacks → frontend → seed; `EnableSemanticSearch` condition | customer entry point |
| `infra/seed.yaml` | install-time custom resources (seeder, bootstrap admin, SPA deployer) | customer install |
| `infra/pipelines/pipeline-<svc>.yaml` | per-service CodePipeline (from reusable template) | one per service |

## Compute
- **AWS Lambda**, Python 3.12; in **private subnets**; **no provisioned concurrency** (AC-3); memory right-sized per function (deferred per function); reserved concurrency only where a downstream needs protection.

## Storage (Q7=A)
- **DynamoDB** per service: on-demand, **PITR on**, `DeletionPolicy/UpdateReplacePolicy: Retain`, SSE (AWS-managed KMS). Single-table-per-service (composite PK/SK) where it fits.
- **Idempotency table** per consuming service: PK=`eventId`, **TTL** attribute (7-day expiry) — backs P-IDEMPOTENCY.
- **S3**: materials/file-share/exports + SPA assets; public access blocked (SECURITY-09); `Retain`.

## Messaging / eventing
- **EventBridge** single bus (foundation); **rule per consumer** (filter by `type`) created in each service `-app` stack; each rule target → **SQS queue + DLQ** (P-RETRY-DLQ); DLQ depth alarm → SNS.
- **DynamoDB Streams** per table for CDC (rollups/projections).

## Networking (Q3=A, Q4=C)
- VPC, 2 AZs, private subnets for Lambda, single NAT (dev; `NatPerAz` param for prod).
- **Gateway endpoints**: S3, DynamoDB. **All other AWS + third-party egress via NAT** over TLS (AC-4).
- Deny-by-default security groups; no inbound `0.0.0.0/0` except CloudFront/API on 443.

## Edge (Q5=A)
- Single **API Gateway REST**, stage per env, Lambda proxy; per-service routes registered on the imported `RestApiId`/`RootResourceId`; **serialized `create-deployment`** step publishes changes; access + execution logging.
- **CloudFront + S3** for SPA; security headers; throttling/usage plans for rate limiting.

## Identity
- **Cognito** user pool (foundation) with custom-auth trigger **hooks reserved**; token/session lifetimes set by Identity unit; MFA for admin.

## Semantic Search (conditional)
- `EnableSemanticSearch` condition gates **OpenSearch Serverless** (vector) + **Bedrock** access (Units 13/14). When off, dependent features hidden/skipped (Q10 matrix). Bedrock region availability = install prerequisite when on.

## Monitoring (Q6=A)
- **X-Ray** tracing; structured JSON logs; **CloudWatch alarms** (error rate, p95 latency, DLQ depth, throttles) → **SNS topic** (`OpsEmail` param). **Audit logs 12 months** (immutable, app role cannot delete); **app logs 30 days** (param).

## CI/CD (Q2=A)
- **AWS CodePipeline** per service (own CFN stack); **source = CodeStar Connection to GitLab** (`github.com`), path-filtered per service.
- Stages: source → build (SAM, vendored deps) → unit tests → **dep-scan / bandit / cfn-lint+cfn_nag** → **contract tests (gate)** → deploy `-data` → deploy `-app` → **create-deployment** → smoke → update `service-mode`.
- Least-privilege pipeline roles; dev auto-deploy; manual approval only for the customer release build.

## Packaging / artifacts (Q8=A)
- **SAM-managed** deployment buckets (`sam deploy --resolve-s3`) per account; customer's `sam deploy` provisions its own (D4). Prebuilt dependency-complete artifacts in `dist/`.

## Tagging (Q9=A)
- `Project=community-portal`, `Unit=<unit>`, `Stage=<env>`, `ManagedBy=sam`; cost-allocation tags on.

## Security Compliance Summary (Infrastructure Design)
| Rule | Status | Note |
|---|---|---|
| SECURITY-01 | Compliant | SSE AWS-managed KMS + TLS |
| SECURITY-02 | Compliant | API GW access/exec logs + CloudFront logging |
| SECURITY-06 | Compliant | per-Lambda + per-pipeline least-privilege roles |
| SECURITY-07 | **Compliant w/ documented exception (AC-4)** | private subnets, NAT-not-IGW, deny-by-default, gateway endpoints for S3/DynamoDB; other AWS calls via NAT (TLS) — interface endpoints deferred |
| SECURITY-09 | Compliant | S3 public access blocked; no defaults |
| SECURITY-10/13 | Compliant | pinned deps, scans, SBOM, access-controlled pipelines |
| SECURITY-11 | Compliant | API GW throttling (WAF omitted AC-1) |
| SECURITY-14 | Compliant | alarms→SNS; audit 12mo immutable |
| Others (03,04,05,08,12,15) | Inherited/deferred-to-service | enforced in service code + contract tests |

**No blocking findings.** Accepted: AC-1 (no WAF), AC-2 (no CMK), AC-3 (no provisioned concurrency), AC-4 (NAT-only endpoints). Residual risk RR-1 (no staging account).

## Deferred to Code Generation
- Concrete CIDR values, subnet sizing, exact SG rules.
- Per-function memory/timeout; API throttling numbers; alarm thresholds.
- CloudFormation resource names/logical IDs.
