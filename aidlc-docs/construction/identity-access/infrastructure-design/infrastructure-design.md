# Infrastructure Design — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Identity & Access
Maps logical components (`../nfr-design/logical-components.md`) to concrete AWS resources in the `-data`/`-app` CloudFormation stacks. Inherits Unit 1 foundation (VPC, Cognito, EventBridge, API edge). Companion: `deployment-architecture.md`.

## Resource inventory
| Logical component | AWS resource | Stack | Notes |
|---|---|---|---|
| Identity store + membership history + OTP + join requests | `AWS::DynamoDB::Table` (single table, pk/sk) | `-data` | PITR on; SSE (KMS-managed); `DeletionPolicy/UpdateReplacePolicy: Retain` (D6); Stream NEW_AND_OLD_IMAGES. **Add GSI1 (email), GSI2 (role/status), GSI3 (group membership history); TTL on `ttl` for OTP items** |
| Future consumer idempotency | `AWS::DynamoDB::Table` (idem) | `-data` | exists in scaffold; TTL on `ttl` |
| Compute | `AWS::Serverless::Function` (python3.12, 256MB/15s, Tracing Active) | `-app` | Handler switches from `mock_handler.handler` → `app.handler` (real) |
| Auth-path low latency | `AutoPublishAlias` + `ProvisionedConcurrencyConfig` on the function | `-app` | Sized small (e.g., 1–2) for `login`/`verifyOtp` cold-start control; cost-guarded |
| Scheduled Cognito sync | `AWS::Scheduler::Schedule` (or `AWS::Events::Rule` schedule) → same function (sync route) | `-app` | rate configurable; target = function with a `{"source":"scheduled-sync"}` detail |
| Local-admin credentials | `AWS::SecretsManager::Secret` (`identity-access-local-admin-<stage>`) | `-data` | seeded email + initial password hash at deploy (B7); GetSecretValue scoped |
| JWT signing key (local admin) | `AWS::SecretsManager::Secret` (`identity-access-jwt-<stage>`) | `-data` | random signing key; rotation optional |
| Domain events | EventBridge `PutEvents` on platform bus (Parameter `EventBusName`) | `-app` | IAM scoped to the bus ARN |
| Transactional email | Amazon SES `SendEmail` | `-app` | sender from deploy config/Settings; IAM scoped to identity ARN |
| Identity provider | Cognito User Pool (Parameters `UserPoolId`, `UserPoolClientId`) | consumed from foundation | admin actions IAM-scoped to the pool ARN |
| Token role claims (US-1.12/BR-R2) | `AWS::Cognito::UserPool.LambdaConfig.PreTokenGeneration` → `AWS::Serverless::Function` (`token_claims_handler.handler`, identity-access source) | Foundation | Injects `role`/`led_group_id`/`member_group_ids` into every ID token from the portal record (read-only DynamoDB access), so API Gateway's Cognito authorizer forwards a real role claim to `Principal.from_claims`. Lives in Foundation (not the Identity & Access `-app` stack) because the User Pool resource lives there and a cross-stack Lambda trigger reference would be circular. |
| Edge | API GW REST + Cognito authorizer (Parameters `RestApiId`, `RootResourceId`) | consumed from api-edge | `/auth` public, `/users`+`/groups`+`/membership-history` authorized |
| Observability | `AWS::CloudWatch::Alarm` (errors + p95 + throttles + security), audit `AWS::Logs::LogGroup` (12-mo retention), X-Ray | `-app` | audit group separate; app role cannot delete it |

## IAM execution role (least privilege — SECURITY-06)
Replace scaffold `DynamoDBCrudPolicy` set with explicit scoped statements:
- `dynamodb:{GetItem,PutItem,UpdateItem,DeleteItem,Query,BatchWriteItem}` on the table ARN **and its `index/*`**; same CRUD on the idempotency table.
- `events:PutEvents` on the platform bus ARN only.
- `cognito-idp:{AdminCreateUser,AdminSetUserPassword,AdminDisableUser,AdminEnableUser,AdminGetUser,ListUsers,AdminInitiateAuth}` on the **user-pool ARN** only. The pool has `AllowAdminCreateUserOnly` enabled (no public `SignUp`); self-registration (US-1.30) uses `AdminCreateUser` + `AdminSetUserPassword` after the app-layer domain allow-list check (BR-P3).
- `ses:SendEmail` / `ses:SendRawEmail` scoped to the verified sender identity ARN (Condition on `ses:FromAddress` where possible).
- `secretsmanager:GetSecretValue` on the two secret ARNs only.
- `ssm:GetParameter` (Settings values, if read via SSM) scoped to the settings path.
- CloudWatch Logs write to own log groups; **no** `logs:DeleteLogGroup` on the audit group.
- No wildcard actions/resources (no documented exception needed).

## New `-data` stack additions (over scaffold)
- GSI1: `gsi1pk`(HASH)/`gsi1sk`(RANGE) — email lookup.
- GSI2: `gsi2pk`(HASH)/`gsi2sk`(RANGE) — role/status listing.
- GSI3: `gsi3pk`(HASH)/`gsi3sk`(RANGE) — per-group membership history.
- TTL: `AttributeName: ttl, Enabled: true` on the main table (OTP items).
- 2× Secrets Manager secrets (local-admin creds, JWT key) with `Retain`.
- Outputs add: `LocalAdminSecretArn`, `JwtSecretArn`, GSI names.

## New `-app` stack additions (over scaffold)
- Parameters add: `UserPoolId`, `UserPoolClientId`, `LocalAdminSecretArn`, `JwtSecretArn`, `SesSenderAddress`, `AuthMode` (default `cognito`).
- Env vars add: `USER_POOL_ID`, `USER_POOL_CLIENT_ID`, `LOCAL_ADMIN_SECRET_ARN`, `JWT_SECRET_ARN`, `SES_SENDER`, `AUTH_MODE`, `SETTINGS_TABLE`/param path.
- Handler → `app.handler`; explicit IAM policies (above) replacing broad managed policies.
- `AWS::Scheduler::Schedule` for the sync worker.
- Alarms: add p95 latency, throttles, and metric-filter security alarms (auth failures, authZ denials, local-admin password change) on the log group.
- Provisioned concurrency alias for the auth path.

## Encryption & network (inherited)
- At rest: DynamoDB SSE + Secrets Manager (AWS-managed KMS, AC-2). In transit: TLS 1.2+ to all AWS endpoints.
- Lambda in private subnets; VPC endpoints for DynamoDB, Secrets Manager, SES, Cognito-IDP, EventBridge, CloudWatch Logs, X-Ray (SECURITY-07). NAT egress fallback.

## Cost notes
- Provisioned concurrency kept minimal (auth path only). On-demand DynamoDB (no idle capacity). SES pay-per-email. Cognito MAU-based. GSIs add storage/write cost (bounded, index-served reads justify it).

## Compliance (this stage)
- SECURITY-01/06/07 realized in IaC (KMS, scoped role, private networking). SECURITY-02 at edge (Unit 1). SECURITY-14 alarms + audit retention. RESILIENCY-08/09/12 (multi-AZ managed, concurrency ceiling, PITR/backups). **No blocking findings.** SECURITY-04 N/A.
