# Infrastructure Design Plan — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Identity & Access

## Steps
- [x] 1. Analyze functional + NFR design
- [x] 2. Create this plan
- [x] 3. Generate questions (resolved from inherited infra decisions — below)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (N/A)
- [x] 6. Generate artifacts (infrastructure-design.md, deployment-architecture.md)
- [x] 7. Present completion
- [ ] 8/9. Approval + state update

## Questions → resolved
| Category | Resolution |
|---|---|
| Deployment env | Inherited: AWS single region, multi-AZ; CloudFormation + SAM; `-data`/`-app` split (D9); root template nests stacks (D1); Parameters not Fn::ImportValue. |
| Compute | Lambda python3.12, 256MB/15s (existing Globals); add provisioned concurrency on auth path (alias). |
| Storage | DynamoDB single table (pk/sk) + GSI1/2/3 + OTP TTL; idempotency table; PITR + Retain + KMS (existing -data extended). |
| Messaging | EventBridge platform bus (PutEvents); EventBridge Scheduler for sync. No SQS (producer). |
| Networking | Inherited: Lambda in private subnets, VPC endpoints (DDB/Secrets/SES/Cognito/EventBridge/Logs), deny-by-default. |
| Monitoring | CloudWatch alarms (errors/p95/throttles + security alarms), X-Ray, dedicated audit log group, dashboard. |
| Shared infra | Cognito user pool + API GW + authorizer owned by Unit 1 (foundation/api-edge); this unit consumes via Parameters. Secrets Manager secrets owned by this unit's -app/-data. |
