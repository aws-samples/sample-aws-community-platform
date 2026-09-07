# Run & Deploy

Two ways to work with the UI: run the **SPA locally** against a deployed API, or **deploy the whole app to AWS**.

## A. Run the SPA locally (against a deployed API)
Start the SPA (Vite on :5173, proxies `/api/*` → the configured API endpoint):
```bash
cd frontend && npm install   # first time
npm run dev
```
Open http://localhost:5173. The SPA reads its API endpoint and Cognito details from `/config.json`, so point it at a deployed environment (see section B). Screens: Home, Events, Forums, Certifications, Contributions (leaderboard), User Groups, Member Directory, Announcements.

Verify a path through the SPA proxy:
```bash
curl localhost:5173/api/contributions/leaderboard   # through the SPA proxy
```

## B. Deploy to AWS (requires your credentials)
`infra/root-template.yaml` is the **single entry point**. It orchestrates everything:

```
root-template.yaml
├── foundation.yaml           # VPC, NAT, VPC endpoints, Cognito, EventBridge, ops SNS
├── api-edge.yaml             # shared API Gateway + Cognito authorizer, S3 + CloudFront (SPA)
├── per service (×8):
│   ├── service-<svc>-data.yaml   # that service's own DynamoDB tables (service-owned)
│   └── service-<svc>-app.yaml    # that service's Lambda
└── seed.yaml                 # uploads SPA bundle + injects config.json (runs last)
```
Deploying the root stands up the **entire application** (shared platform + every service's
database + Lambda + SPA) in one command. `EnableSemanticSearch=false` skips the optional
Search (OpenSearch/Bedrock) stack for cost.

Prereqs: AWS SAM CLI + credentials for the target account/region; Bedrock/OpenSearch region if `EnableSemanticSearch=true`.

### One-command deploy (recommended)

```bash
cd frontend && npm run build && cd ..     # the SPA bundle must exist first
make build                                # service artifacts into dist/
./infra/tools/deploy.sh                   # stage SPA -> package -> upload -> deploy
```

`infra/tools/deploy.sh` exists because two steps below are easy to get wrong by
hand and fail *silently* rather than loudly:

1. **The SPA must be staged into the seed Lambda's payload.** `platform/seed/spa/`
   is git-ignored and is what the SPA-publisher custom resource uploads. If it is
   not refreshed from `frontend/dist/` first, the deploy reports `UPDATE_COMPLETE`
   with new Lambdas and **republishes the previous UI bundle**. (Hit on
   2026-08-06.) The script mirrors it with `rsync --delete` as step 0.
2. **Nested templates must be pre-packaged.** The root references them by flat
   filename under `${TemplateBaseUrl}`, so every nested template needs its
   `CodeUri` already rewritten to `s3://` — CloudFormation cannot resolve a
   relative path from a template it fetched from S3.

Useful variants:

```bash
TEMPLATES_ONLY=1 ./infra/tools/deploy.sh          # stage + upload, no deploy
STACK=my-stack STAGE=test ./infra/tools/deploy.sh # different stack/stage
```

After deploying a change that alters how data is read, check whether a backfill is
needed — e.g. `infra/tools/backfill_group_members.py` for the group-membership
projection. Run it **before** switching the handler where the new rows are inert
to the old code, so there is no window of wrong-looking data.

Always verify the served bundle, not the stack status:

```bash
curl -s https://<portal-domain>/ | grep -oE 'index-[A-Za-z0-9_-]+\.js'   # must match frontend/dist
```

### Manual path (what the script automates)

```bash
# 1. Validate the root template
make package

# 2. Upload ALL nested templates to one S3 prefix (this becomes TemplateBaseUrl).
#    The root references nested stacks by flat filename under ${TemplateBaseUrl}.
aws s3 cp infra/            s3://<your-artifacts-bucket>/cp/ --recursive --exclude "*" --include "*.yaml"
aws s3 cp infra/services/   s3://<your-artifacts-bucket>/cp/ --recursive --include "*.yaml"

# 3. Build the Python service artifacts (dependency-complete) that the -app stacks reference
make build

# 4. Deploy the whole app (guided the first time — set OpsEmail, AdminEmail,
#    EnableSemanticSearch, and TemplateBaseUrl=https://<your-artifacts-bucket>.s3.<region>.amazonaws.com/cp)
sam deploy -t infra/root-template.yaml --guided --stack-name community-portal-dev \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND
```
Each service deploys its real handler from `services/<svc>/src/`; `make build` produces the
dependency-complete artifacts the `-app` stacks reference.

### API routing & CORS (wired — works end to end on mocks)
The full route table is defined centrally in `infra/api-edge.yaml` and is **generated from the
frozen service contracts** by `infra/tools/gen_api_edge.py`:
- Every base path (`/events`, `/members`, `/groups`, …) is proxied (`AWS::ApiGateway` `aws_proxy`,
  ANY method + greedy `{proxy+}`) to that service's `<service>-<stage>` Lambda.
- `/auth/*` is public (login/register/reset happen before a session); all other routes require the
  Cognito authorizer.
- **CORS**: each path has a MOCK `OPTIONS` (preflight) returning CORS headers, and the service Lambda
  responses include `Access-Control-Allow-Origin` — so the CloudFront-hosted SPA can call the
  execute-api endpoint cross-origin.
- Each `service-<svc>-app.yaml` grants API Gateway permission to invoke its Lambda
  (`ApiInvokePermission`).

Because the API is centralized in the edge stack, one deployment covers all routes (no cross-stack
redeploy problem). If contracts ever change, regenerate: `python3 infra/tools/gen_api_edge.py`.
Service teams implement the same contract behind the same routes — they don't add new APIs.

> NOTE: A real AWS deploy provisions billable resources (NAT, API Gateway, DynamoDB, Cognito, optionally OpenSearch/Bedrock). Review `infra/` and the parameters before deploying. This repo does not deploy anything automatically.

## Service states
`service-mode.json` tracks each service's status. All 8 services are now real (`complete`).
