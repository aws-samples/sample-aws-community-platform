# Infrastructure Design Plan — Unit 4: Events

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Events
**Inputs**: `events/functional-design/` + `events/nfr-requirements/` + `events/nfr-design/` (all approved) · existing `infra/services/service-events-{data,app}.yaml` (mock) · `infra/foundation.yaml` · `infra/api-edge.yaml` + `infra/tools/gen_api_edge.py` · `infra/root-template.yaml`

## Steps
- [x] 1. Analyze design artifacts (4 functional + 2 NFR requirements + 2 NFR design)
- [x] 1b. Inspect the live infrastructure baseline: current events data/app stacks, Foundation's community bucket, the generated API edge and its generator, root-template wiring, and the closest real analogue stacks (settings, member-profiles)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions — all 7 mandatory categories evaluated; **3 blocking conflicts found** (F1–F3) and tabled below with recommendations
- [x] 4. Store plan
- [x] 5. Collect and analyze answers — recommendations applied in the artifacts, each flagged at the gate for override
- [x] 6. Generate infrastructure design artifacts (+ update `shared-infrastructure.md`)
- [x] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update `aidlc-state.md`

## Mandatory category evaluation

| Category | Applicable? | Outcome |
|---|---|---|
| **Deployment environment** | Yes | AWS, single region, CloudFormation + SAM, nested stacks under `infra/root-template.yaml`, one pipeline per service. Inherited unchanged. |
| **Compute** | Yes | One Lambda (`events-<stage>`), python3.12, on-demand. Memory raised 256 → **512 MB** and timeout 15 → **60 s** to cover a 104-occurrence series create and a 1000-row attendance apply. No provisioned concurrency (AC-3). |
| **Storage** | Yes | Existing `events-<stage>` table gains **GSI1–GSI4**; idempotency table unchanged; materials and uploads go under `events/` prefixes in Foundation's existing community bucket rather than a new bucket. **See F2 — the GSIs cannot be added in one deployment.** |
| **Messaging** | Yes | EventBridge platform bus for the 9 published events; a rule for `GroupSoftDeleted`; a rule for S3 object events; a rule for GuardDuty scan results; one EventBridge Scheduler schedule for the reminder sweep. No SQS. **See F3 — the S3 rule overlaps Settings'.** |
| **Networking** | Yes | Shared API Gateway. `/events` is already routed and authenticated. **See F1 — the public upload route cannot live under `/public` as the functional design assumed.** |
| **Monitoring** | Yes | Six unit-specific alarms per P-OBS-1 plus the existing error alarm, all to the Foundation ops topic. X-Ray already on. |
| **Shared infrastructure** | Yes | Events becomes the **second consumer** of Foundation's community bucket (Settings is the first) and the **first consumer** of GuardDuty malware scanning on it. `aidlc-docs/construction/shared-infrastructure.md` updated accordingly. |

---

## Blocking conflicts found (F1–F3)

### F1 — The public upload route cannot live under `/public` (blocking)
The functional design specified `POST /public/event-uploads/{token}`. That is not deployable as written.

`infra/tools/gen_api_edge.py` maps the **first URL segment** to exactly one service and **hard-fails** on a collision:

```python
if base in mapping and mapping[base] != svc:
    raise SystemExit(f"base-path collision: /{base} claimed by {mapping[base]} and {svc}")
```

`/public` is already claimed by **Settings** (`GET /public/settings`, the pre-login read). Adding `/public/event-uploads` to the Events contract would abort the generator. Nor can the route hide under `/events`, because the generator applies the Cognito authorizer at the base-path level and hand-editing generated routes is explicitly forbidden.

**Options**
- **A (recommended)** — Events claims its own public base path: `POST /event-uploads/{token}`, with `event-uploads` added to the generator's `PUBLIC_BASES` set. One line in `gen_api_edge.py`, then regenerate `api-edge.yaml`. Ownership stays correct, no authorizer, no collision.
- B — Route it through Settings' Lambda (wrong service owns the event's data).
- C — Keep `/public` and make the generator support multi-service base paths (a structural change to Unit 1 tooling for one route).

**Note**: option A adds the portal's **second unauthenticated base path** at the edge. That is the intended design (decision D6/N3), but it is a security-visible change to a Unit-1-owned file, which is why it is flagged rather than done silently.

### F2 — Four GSIs cannot be added in one deployment (blocking, operational)
DynamoDB permits **one** global secondary index change per `UpdateTable`, and the live `events-<stage>` table currently has **no** GSIs. GSI1–GSI4 therefore require **four sequential stack updates**.

Worse, this exact failure mode has already been hit in this repo during the Settings file-share work: **the root stack reports `UPDATE_COMPLETE` while the new index is still `CREATING`/backfilling, and a Query against a backfilling index fails.** The Settings GSI took roughly four minutes to reach `ACTIVE`.

**Recommendation**: stage the rollout as four deployments in dependency order — GSI1 (listings, needed first), GSI2 (member RSVPs), GSI4 (reminder sweep), GSI3 (Content Library, the only sparse index needing a backfill of existing materials) — waiting for `ACTIVE` between each, with a documented backfill step for GSI3. The deployment runbook must state that stack completion is **not** the readiness signal.

### F3 — The Events S3 rule overlaps Settings' existing rule (blocking, cross-unit)
Foundation enables `EventBridgeConfiguration` on the community bucket, so **all** object events flow to the default bus. Settings' existing rule matches only on bucket name with **no key-prefix filter**:

```yaml
detail:
  bucket:
    name: [ !Ref FileShareBucketName ]
```

Once Events writes to `events/*` in the same bucket, **Settings' consumer will receive every Events object event**, look for a `FILEKEY` pointer that does not exist, and burn an idempotency record per event. It is functionally tolerant (the consumer drops unknown keys) but it is wasteful, it pollutes Settings' logs, and it makes the two services' failure signals indistinguishable.

**Recommendation**: add a key-prefix filter to **both** rules — Events matches `events/`, Settings matches its own folders — which means touching `service-settings-app.yaml`, a Unit 11 file. Flagged because it is a change outside this unit's boundary.

---

## Resolved without a question

| # | Item | Resolution |
|---|---|---|
| R1 | New bucket vs shared bucket | Reuse Foundation's community bucket under `events/` prefixes. A second bucket would duplicate encryption, versioning, public-access-block, lifecycle, and malware-scanning configuration for no isolation benefit — IAM is already prefix-scoped. |
| R2 | GuardDuty plan placement | On the **bucket owner** (Foundation), not the Events app stack. The bucket is shared, so scanning it protects Settings' file-share uploads too. Placing it in a consumer stack would make protection depend on which consumer deployed last. |
| R3 | Scan-result signalling | GuardDuty Malware Protection for S3 emits scan results to EventBridge; an Events rule on that detail-type drives the `PendingScan → Clean\|Quarantined` transition. No polling, no object-tag reads. |
| R4 | Sweep schedule | One EventBridge Scheduler schedule (5-minute rate) targeting the Events Lambda, per N5/J4. |
| R5 | IAM shape | Prefix-scoped S3 (`${BucketArn}/events/*`, not `/*`), `PutEvents` on the platform bus only, and `execute-api:Invoke` on the single Contributions method. No wildcards. |
| R6 | Handler switch | `mock_handler.handler` → `app.handler`, plus `service-mode.json` → `events: complete`, exactly as Units 2/3/11 did. |
| R7 | Lifecycle policy | External uploads under `events/*/uploads/` expire after 180 days; abort incomplete multipart uploads after 7 days. |
| R8 | Contract-test gate | Unchanged. The mock stays available for the frontend until the real handler passes the gate. |

**Recommendations for F1, F2, F3 are applied in the artifacts and flagged at the stage gate — reject any and I will revise.**
