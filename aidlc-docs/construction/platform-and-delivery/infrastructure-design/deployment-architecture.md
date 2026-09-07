# Deployment Architecture — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Platform & Delivery
How the platform substrate and services deploy in **dev** (construction) and in the **customer** install. Companion: `infrastructure-design.md`, `../../shared-infrastructure.md`.

## Environments (Q1=B)
- **Dev account** — all per-service pipelines deploy here; release validated here (RR-1: no separate staging).
- **Customer account/region** — one-shot install of the tagged release via the root template.
- `Stage` parameter (`dev` | `prod`) differentiates.

## Stack dependency (deploy-time, via Parameters — D1)
```
foundation.yaml ──outputs──▶ (VpcId, PrivateSubnetIds, UserPoolId, EventBusName,
   │                          RestApiId, RootResourceId, OpsAlarmTopicArn, LogRetentionDays)
   │  passed as CFN Parameters (NOT Fn::ImportValue)
   ├─▶ api-edge.yaml
   ├─▶ service-<svc>-data.yaml ──outputs──▶ (TableName/Arn, StreamArn, BucketName)
   │        └─▶ service-<svc>-app.yaml   (also gets RestApiId/RootResourceId, EventBusName)
   └─▶ frontend.yaml (RestApiUrl, UserPoolId → config.json)
root-template.yaml nests all of the above for the customer (EnableSemanticSearch condition).
```

## Dev: per-service CI/CD flow (CodePipeline, GitLab source — Q2=A)
```
GitLab push (path-filtered)
  → CodeStar Connection source
  → build (SAM, vendored Python deps)
  → unit tests
  → security scans (dep-scan, bandit, cfn-lint, cfn_nag)
  → CONTRACT TESTS (gate: schema/401/403/501)
  → deploy service-<svc>-data (no-op after bootstrap)
  → deploy service-<svc>-app (mock seed → real code over time)
  → API create-deployment (serialized)
  → smoke test
  → update service-mode.json (mock|partial|complete)
```
Mock→real is an ordinary gated code deploy (FQ7); no swap.

## Customer: one-shot install (D4)
```
clone tagged repo (source + dist/ prebuilt artifacts)
  → sam deploy root-template.yaml into customer account/region
       → SAM provisions its own deployment bucket (--resolve-s3)
       → nested: foundation → api-edge → 15 service stacks (-data + -app) → frontend → seed
       → Conditions: EnableSemanticSearch (OpenSearch+Bedrock) on/off
       → seed.yaml custom resources: scoring framework, email templates, cert catalog,
         bootstrap local admin (+ Secrets Manager secret), SPA asset deploy + config.json
  → single nested operation (no create-deployment race)
```
No language toolchain required for the default install; building from source is optional.

## Network path (Q3/Q4)
```
Users ──HTTPS──▶ CloudFront (SPA, cached, security headers)
Users ──REST /api──▶ API Gateway (Cognito authorZ) ──▶ Lambda (private subnet, per-svc route)
Lambda ──gateway endpoint──▶ S3 / DynamoDB            (private)
Lambda ──NAT (TLS)──▶ EventBridge/SQS/Secrets/KMS/Logs/SES/Bedrock/OpenSearch/MS Teams   (AC-4)
Async: Lambda ──put──▶ EventBridge bus ──rule──▶ SQS(+DLQ) ──▶ consumer Lambda (idempotent)
```

## Data safety (D6)
- Tables + buckets `Retain`; `-data`/`-app` split so app redeploys never touch data.
- DR = Backup & Restore (PITR + on-demand backups); single region.

## Deferred to Code Generation
- Root/nested template wiring + logical IDs; SAM template authoring; pipeline stack authoring; custom-resource Lambdas; CIDR/SG specifics.
