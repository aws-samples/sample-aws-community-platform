# Unit 6 — Certifications: Infrastructure Design Plan

**Stage**: CONSTRUCTION → Infrastructure Design (per-unit)
**Inputs**: approved functional design (D1–D11), NFR requirements (N1–N4), NFR design (J1–J5); **verified against the actual IaC** (`service-certifications-{data,app}.yaml`, `foundation.yaml`, `api-edge.yaml`, `service-{settings,events}-app.yaml`, `platform/seed/spa_deploy_handler.py`) rather than assumed — the Unit 4 lesson.

## Checklist
- [x] Analyze functional + NFR design artifacts
- [x] Verify current scaffold stacks + shared-infra facts in the repo (not from memory)
- [x] Evaluate ALL 7 question categories (below) — **no open user questions**; all categories platform-fixed or already user-decided (N3=B was the one real infra decision and it was taken at NFR Requirements)
- [x] Generate `infrastructure-design.md` + `deployment-architecture.md`
- [x] Update `shared-infrastructure.md` (new prefixes + scan-rule mirror rule)
- [ ] Approval gate

## Category evaluation (Step 3 justification)
| Category | Outcome |
|---|---|
| Deployment environment | Fixed: dev account, Stage param, root-template nesting (D1/D9) |
| Compute | Fixed: single Lambda python3.12; 256 MB/15 s retained (no large-batch ops — tech-stack decision confirmed against Events' 512/60 rationale) |
| Storage | Fixed: existing table (Retain) + 3 new GSIs (J2/J3 consequence); FileShareBucket prefixes; SPA bucket `badges/` (N3=B, user-decided) |
| Messaging | Fixed: EventBridge bus + 2 consumer rules + 2 Scheduler schedules (J4) |
| Networking | Fixed: shared API GW; all new routes under `/certifications` `{proxy+}` → **no api-edge regen** |
| Monitoring | Fixed: house alarm/SNS pattern; 6 alarms, every custom metric with a shipped emitter |
| Shared infra | Deltas documented in shared-infrastructure.md (prefix ownership + scan-rule mirror) |

## Findings (verified, cross-unit — the review focus)
- **F-A (Settings stack edit required)**: `service-settings-app.yaml`'s S3 object rule excludes only `events/` (`anything-but: {prefix: "events/"}`). The moment certifications writes `certifications/evidence/…`, **Settings' consumer receives every certifications object event** and burns an idempotency record each — the exact F3 failure recurring. Fix: exclusion list becomes `["events/", "certifications/"]`.
- **F-B (Events stack edit required)**: GuardDuty scan-result rules are **not prefix-filtered anywhere today** — `events-malware-scan-*` matches ALL verdicts on the bucket, so certifications' uploads would feed Events' scan consumer (and vice versa). Certifications' new scan rule filters `detail.s3ObjectDetails.objectKey` on `certifications/`; Events' rule gains the mirror `events/` filter. Same F3 class, new surface.
- **F-C (staged GSI deployments)**: the deployed certifications table has **zero GSIs** (verified in `-data.yaml`); 3 new GSIs = **3 sequential deployments** (one GSI per UpdateTable), polling DescribeTable for ACTIVE — stack UPDATE_COMPLETE is NOT the readiness signal. Mitigating fact: mocks never write to DynamoDB, so the dev table is empty → creations are fast (Events measured 1–6 min on empty).
- **F-D (positive — no work needed)**: `spa_deploy_handler.py` is **upload-only on Create/Update** (never prunes the bucket), so runtime-written `badges/*` objects survive SPA redeploys; CloudFront OAI policy (`/*` GetObject) already serves the prefix; the deploy-time `/*` invalidation is harmless because badge keys are unique per upload. N3=B needs zero api-edge/seed changes.
