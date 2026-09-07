# Tech Stack Decisions — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Member Profiles & Directory
Inherits all platform-wide choices (Unit 1 `tech-stack-decisions.md`). Records member-profiles-specific additions. Companion: `nfr-requirements.md`.

## Inherited (unchanged)
Python 3.12 on Lambda · AWS Lambda Powertools · boto3 · AWS SAM packaging · DynamoDB on-demand (PITR, Retain) · EventBridge (domain events) · API Gateway REST + Cognito authorizer · CloudWatch/X-Ray · pinned deps + lock + bandit/cfn-lint/cfn_nag/dep-scan/SBOM in CI · Schemathesis + pytest contract tests (the gate).

## What this unit does NOT need (vs. Identity & Access precedent)
Unlike Unit 2, this service holds no credentials and performs no authentication — so it needs none of: Cognito admin SDK calls, Secrets Manager, SES, PBKDF2/password hashing, JWT signing/verification, or CSV/XLSX import parsing. This keeps the dependency footprint smaller than Identity & Access's.

## Member-profiles-specific stack additions
| Concern | Choice | Rationale |
|---|---|---|
| Read-time cross-service fan-out | **`urllib3`** (already vendored with the Python Lambda runtime / botocore dependency — no new pinned package) issuing authenticated same-account API Gateway calls, with an explicit per-call `timeout=` and a simple in-process skip-on-recent-failure guard (lightweight circuit-breaker, not a full library) | Avoids adding a new HTTP client dependency (e.g. `requests`) purely to call sibling services; keeps the Lambda zip small; per-call timeout is the core resiliency requirement (NFR-MP-PERF-3/REL-1). |
| Fan-out concurrency | **`concurrent.futures.ThreadPoolExecutor`** (stdlib) to issue the 4-way fan-out calls in parallel within a single Lambda invocation | Bounds total added latency to the slowest call, not the sum (NFR-MP-PERF-2); no new dependency, works within a single Lambda execution environment (I/O-bound calls, GIL not a bottleneck). |
| Search delegation | Same-account REST call to Search service (`GET /search?kind=member&q=`) when `EnableSemanticSearch` is on; in-process substring match against the profile table's `firstName`/`lastName`/`email`/`skills` fields when off | Matches D3's degrade-gracefully requirement (BR-6b); no new dependency either way. |
| Event consumption | **EventBridge rule → this service's Lambda**, same idempotency-table pattern as Identity & Access (dedup by `eventId`) | Consistency with the platform's established event-consumption pattern; no new tooling. |
| Event publishing | **boto3 `events` PutEvents** on the platform bus | `MemberProfileUpserted` (E3), same as every other service. |

## Dependencies (pinned — `services/member-profiles/requirements.txt`)
| Package | Purpose |
|---|---|
| `boto3` (pinned) | AWS SDK (dynamodb, events) |
| `aws-lambda-powertools` (pinned) | logging/tracing/metrics (aligns with NFR-MP-SEC/OBS) |
| (dev) `pytest`, `schemathesis`, `moto` | unit + contract tests; `moto` mocks AWS for local unit tests; downstream-service fan-out mocked via `responses` or a local `moto`-style stub (dev-only, TBD at Code Generation) |

No `requests`, no `openpyxl`, no `PyJWT`, no Secrets Manager/SES/Cognito SDK calls — smallest dependency footprint of the services built so far, consistent with this unit's narrower responsibility (no auth, no file import, no email).

All exact-pinned; committed lock; vulnerability-scanned + SBOM in CI (SECURITY-10). No `latest` tags.

## Design-phase items deferred to NFR Design / Infrastructure Design
- Exact per-call timeout value tuning (NFR-MP-PERF-3 sets a target of ≤300ms; final value set against measured downstream p95s once those services are real, not mocks).
- Role/status GSI on the profile table — add only if load testing shows `browseDirectory` p95 regression on the no-`q` path (NFR-MP-SCALE-1).
- Concrete degrade-path contract-test fixtures (simulated 5xx/timeout per downstream service).
- Cross-service invoke IAM shape — same-account API Gateway resource-policy vs. a shared internal invoke pattern; exact mechanism decided at Infrastructure Design (must remain least-privilege, read-only, no new shared library per FQ1).
