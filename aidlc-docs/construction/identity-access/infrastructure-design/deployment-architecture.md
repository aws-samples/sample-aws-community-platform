# Deployment Architecture — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Identity & Access
Deploy-time composition and the mock→real transition for the first real service. Companion: `infrastructure-design.md`.

## Stack composition (Parameters, not exports — D1)
```
foundation.yaml ──outputs──▶ VpcId, PrivateSubnetIds, UserPoolId, UserPoolClientId,
   │                          EventBusName, RestApiId, RootResourceId, OpsAlarmTopicArn
   ├─▶ api-edge.yaml            (routes /auth /users /groups /membership-history → identity-access-<stage> Fn)
   ├─▶ service-identity-access-data.yaml ──outputs──▶ TableName, TableArn, StreamArn,
   │        │                                          IdempotencyTableName, LocalAdminSecretArn, JwtSecretArn
   │        └─▶ service-identity-access-app.yaml  (also receives UserPoolId/ClientId, EventBusName,
   │                                               RestApiId/RootResourceId, SesSender, AuthMode)
root-template.yaml nests all of the above.
```
Route table for `/auth /users /groups /membership-history` is centralized in `api-edge.yaml` (generated from the frozen contract by `infra/tools/gen_api_edge.py`); `/auth` public, the rest Cognito-authorized. No new APIs — the real service serves the same routes the mock served.

## Mock → real transition (FQ7 — ordinary code deploy)
1. Real code lands in `services/identity-access/src/` (`app.py` handler + domain modules); `requirements.txt` pinned.
2. `-app` `Handler` changes `mock_handler.handler` → `app.handler`; env vars + scoped IAM added.
3. Pipeline runs: build (vendored deps) → unit tests → **contract tests (gate, Schemathesis vs the frozen OpenAPI)** → deploy `-data` (adds GSIs/TTL/secrets — additive, Retain) → deploy `-app` → API `create-deployment` → smoke test → `service-mode.json` identity-access → `complete`.
4. Rollback = redeploy previous Lambda version (RESILIENCY-04). No API rewiring, no data migration (same table; GSIs are additive).

## Availability & DR
- Multi-AZ via managed services (Cognito, Lambda, DynamoDB, EventBridge, SES) — RESILIENCY-08.
- Backup & Restore DR (RESILIENCY-02/11): DynamoDB PITR + on-demand backups; Secrets Manager durable; Cognito is the community-identity SoR (portal records rebuildable via sync). Restore runbook = redeploy stacks from IaC + PITR restore of the identity table.

## Deploy-time seeding (B7 — day-one operability)
- `-data` seeds the local-admin secret: `{ email, passwordHash }` from deploy parameters (initial password provided at install; hashed by a seeding custom resource or provided pre-hashed). JWT signing key generated as a random secret.
- SES sender configured at deploy so US-1.28 self-service reset + US-1.32 OTP work on first boot before any Admin logs in.
- Cognito pool created empty (no seeded users); users arrive via self-registration / bulk import.

## Observability wiring
- Function logs + audit log group (12-mo retention). Metric filters → alarms on: auth-failure spike, authZ-denial spike, local-admin password change, function errors, p95 latency, throttles → `OpsAlarmTopicArn` (SNS). X-Ray active tracing. Dashboard: login success/failure, OTP issued/verified/failed, sync processed/failed, latency.

## Text alternative (topology)
```
[SPA/CloudFront] → [API Gateway REST + Cognito authorizer]
      → /auth/*            (public)      ─┐
      → /users/*           (authorized)   ├─▶ [Lambda identity-access-<stage> (VPC, private subnets)]
      → /groups/*          (authorized)   │        ├─ DynamoDB (table + GSI1/2/3 + OTP TTL) [PITR, KMS, Retain]
      → /membership-history(authorized)  ─┘        ├─ Secrets Manager (local-admin creds, JWT key)
[EventBridge Scheduler] ── cron ──────────────────▶│        ├─ Cognito User Pool (initiate_auth/sign_up/admin_*)
                                                    │        ├─ SES (OTP + reset email)
                                                    │        └─ EventBridge (PutEvents: user/group/membership events)
                                                    └─ CloudWatch (logs/metrics/alarms/audit group) + X-Ray
```

**No blocking findings.**
