# Infrastructure Design — Unit 6: Certifications

Maps `nfr-design/logical-components.md` to AWS resources in `service-certifications-{data,app}.yaml` (+ 2 cross-unit template edits). All facts below verified against the repo's current IaC. Companion: `deployment-architecture.md`.

## Resource inventory

### `service-certifications-data.yaml` (delta to existing scaffold)
Current: single-table pk/sk, PITR on, SSE, Stream, idempotency table with TTL — **zero GSIs**.

| Add | Definition | Serves |
|---|---|---|
| **GSI1 `member-claims`** | pk `gsi1pk` = `MEMBER#<memberId>`, sk `gsi1sk` = `submittedAt` | myClaims, listClaims?memberId (member-profiles fan-out), badges |
| **GSI2 `pending-queue`** (sparse, J2) | pk `gsi2pk` = `PENDING`, sk `gsi2sk` = `submittedAt` — attrs present only while Pending | verification queue (oldest-first free), countOnly |
| **GSI3 `sweep`** (sparse, shared, J3) | pk `gsi3pk` ∈ {`EXPIRY`, `SCANWATCH`}, sk `gsi3sk` = expiresAt \| uploadedAt | daily expiry window + 15-min scan watchdog |

Holder lookup (`listClaims?certId&status=Approved`) rides the **CLAIMSLOT item collection** (`pk=CERT#<certId>`, sk=`SLOT#<memberId>`, written transactionally with the claim) — no fourth GSI; the slot exists exactly for live (Pending/Approved) claims, and the query filters `status=Approved` within a bounded read.

**F-C staging rule**: 3 GSIs = 3 sequential `-data` deployments (DynamoDB allows ONE GSI change per UpdateTable). Poll `DescribeTable` until ACTIVE between steps (`infra/tools/wait_for_gsi.sh` exists); **stack UPDATE_COMPLETE is not the readiness signal**. Mitigation: the mock never writes to DynamoDB, so the deployed table is empty — creations run minutes, not hours (Events measured 60–354 s on empty). Extend `infra/tools/stage_events_gsis.py` → generalized or sibling `stage_certifications_gsis.py`.

### `service-certifications-app.yaml` (rewrite of the mock scaffold)
| Resource | Config | Why |
|---|---|---|
| `Fn` | handler → `app.handler`; **python3.12, 256 MB / 15 s retained** (no large-batch ops; sweep is continuation-bounded) | tech-stack decision |
| Env vars | + `FILE_SHARE_BUCKET`, `SPA_BUCKET`, `API_BASE_URL` (Identity membership read), `PERMISSION_MATRIX_PATH` (bundled copy) | providers |
| IAM: DynamoDB | CRUD on own table + idempotency table (as today) | |
| IAM: EventBridge | `events:PutEvents` on the shared bus (5 detail-types) | D10 |
| IAM: S3 scanned bucket | `s3:PutObject/GetObject/DeleteObject` on `${FileShareBucketArn}/certifications/*` **only** + `ListBucket` conditioned `s3:prefix: certifications/*` | prefix isolation (Settings holds `/*` delete — the F3 IAM rationale verbatim) |
| IAM: SPA bucket | `s3:PutObject` on `arn:.../${SpaBucket}/badges/*` **only** — the unit's single cross-stack write | N3=B; NFR-CT-SEC-6 |
| IAM: Identity REST | `execute-api:Invoke` on `GET /groups*` + `GET /users/*` (led-group fallback) — member-profiles' FanOutInvoke precedent, narrower | D3/D4 |
| **New param** | `SpaBucketName` (+Arn) from ApiEdge outputs via root-template | badge copy target |
| `MembershipRule` | EventBridge rule: source `identity-access`, detail-types `MemberLeftGroup`, `MemberRemoved` → Fn (+ permission) | BR-S1 |
| `MalwareScanRule` | source `aws.guardduty`, detail-type `GuardDuty Malware Protection Object Scan Result`, **`detail.s3ObjectDetails.objectKey` prefix-filtered `certifications/`** | F-B; J5 |
| `ExpirySweepSchedule` | Scheduler, `cron(0 6 * * ? *)` UTC daily → Fn, input `{"source":"aws.scheduler","job":"expiry"}` + scoped invoke role | BR-X; J4 |
| `ScanWatchdogSchedule` | Scheduler, `rate(15 minutes)` → Fn, input `{"source":"aws.scheduler","job":"scanwatch"}` (same role) | N4; J4 |
| Alarms (6) | existing Lambda-errors alarm kept + 5 new on custom metrics namespace `certifications/${Stage}`: `SweepMissed` (no `SweepRunOutcome` success in 26 h, TreatMissingData=breaching), `PendingScanAge` > 30 (N4), `EventPublishFailure` ≥ 1, `AuthzDeniedSpike`, API 5xx-rate | every metric has a shipped emitter (Events lesson) |
| `ApiInvokePermission` | unchanged | |

### Cross-unit template edits (both F3-class, reviewed with owners' notes)
1. **`service-settings-app.yaml`** (F-A): S3 object rule exclusion `anything-but: {prefix: "events/"}` → `anything-but: {prefix: ["events/", "certifications/"]}` (EventBridge accepts a list) — otherwise Settings' consumer burns an idempotency record per certifications upload.
2. **`service-events-app.yaml`** (F-B): `events-malware-scan-*` rule gains `detail.s3ObjectDetails.objectKey: [{prefix: "events/"}]` — today it matches ALL bucket verdicts and would consume certifications' scan results. Certifications' own rule carries the mirror filter from birth.
3. **`infra/root-template.yaml`**: pass `FileShareBucketName/Arn`, `SpaBucketName`, `ApiBaseUrl` to the certifications app stack (params exist as outputs already — wiring only).

### Deliberately unchanged
- **api-edge.yaml**: all new ops live under `/certifications` `{proxy+}` — no route regen, no new base path, no public surface.
- **foundation.yaml**: GuardDuty plan already bucket-wide (Unit 4, owner-side) — certifications' prefixes are covered for free; no lifecycle rule for evidence (claims are permanent history; orphan cleanup via a 30-day `certifications/evidence/` incomplete-upload + untagged-orphan rule is **deferred to a follow-up**, recorded).
- **seed.yaml / spa_deploy_handler.py** (F-D, verified): the SPA publisher is upload-only on Create/Update — `badges/*` written at runtime survives redeploys; OAI bucket policy already serves `/*`; unique keys make the deploy-time `/*` invalidation harmless. **Zero changes needed for N3=B.**

## Security & compliance mapping (deltas only — platform inherited)
| Control | Realization |
|---|---|
| SECURITY-06 | Prefix-scoped S3 both buckets; narrowest execute-api grant yet; no wildcards |
| SECURITY-08 | Bundled permission-matrix copy (with the Admin row removed, D7) + OP_AUTHZ; fail-closed loader |
| NFR-CT-SEC-3 (5 MB door) | Presigned **POST** `content-length-range` [1, 5242880] + exact content-type + exact key (J1) |
| NFR-CT-AVAIL-2 | PITR already on (verified); S3 versioning already on (verified); restore-skew noted in deployment-architecture.md |
| RESILIENCY-05/07, N4 | 6 alarms, emitters shipped in the same change |

## Mock→real transition
Same function/routes/table (FQ7): contract v2.0.0 regenerates the mock + contract tests; handler swaps `mock_handler.handler` → `app.handler`; `service-mode.json` certifications → `complete` after the gate. Rollback = redeploy previous Lambda version; **GSIs do not roll back usefully — roll the handler back instead** (Events F2 note applies verbatim).

## Compliance summary: no blocking findings. F-A/F-B are cross-unit corrections shipped with this unit (precedent: Unit 4 edited Settings' rule for F3); F-C is a deployment-order discipline, documented in deployment-architecture.md.
