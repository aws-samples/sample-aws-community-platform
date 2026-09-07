# NFR Design Patterns — Unit 6: Certifications

Maps every NFR-CT-* requirement to a concrete pattern. Companion: `logical-components.md`. Judgement calls J1–J5 recorded in the plan.

## Security patterns

### 3-layer authorization (NFR-CT-SEC-1)
1. **Edge**: Cognito authorizer (platform) — no unauthenticated route exists in this unit.
2. **Boundary**: role gate before routing — `Administrator` → 403 on every operation (D7); the permission-matrix row removal ships with this unit so matrix and code agree.
3. **Per-op**: declarative `OP_AUTHZ` map → matrix `(action, resource, scope)`; `own` scope binds to the token subject (BR-A5, 404-not-403 on foreign claim ids); `group` scope binds to `ledGroupId` (JWT-first, Identity-REST fallback, **unresolvable → deny**, BR-A4). Matrix load failure → deny-all (fail closed).

### Storage-door upload enforcement (J1; NFR-CT-SEC-3/N2)
Presigned **POST** with a policy carrying `content-length-range: [1, 5 MB]` + exact `Content-Type` + exact system-generated key (BR-C7) — S3 itself rejects oversized/mistyped uploads; the service never trusts the client and never needs a post-hoc size audit. Extension/type whitelist applied at grant time (no SVG). Grant ops write nothing except the signed policy; the FileKeyPointer is written at claim-submit/definition-save, so ungranted junk keys have no owner and are lifecycle-cleaned.

### Scan-gated trust promotion (NFR-CT-SEC-4/5, D5/D6)
All uploads are untrusted until the GuardDuty verdict:
- **Evidence**: `scanStatus` on the claim (`PendingScan → Clean | Quarantined`); reviewability (BR-V3) and evidence-URL minting (BR-P2) both key off `Clean`.
- **Badges**: the verdict consumer **copies Clean images to the SPA public bucket** (N3=B) and only then stamps `badgeImageStatus=Clean` + the public URL; the public bucket never receives an unscanned byte, and because keys are unique per upload, a re-upload is a new URL — no CloudFront invalidation path exists or is needed.
- **Quarantined**: never served, flagged to the owner (claim) or leader (definition), object lifecycle-deleted.

### Privacy projection (NFR-CT-SEC-7, BR-P1/P2)
Two serializers, chosen by caller identity — `owner_claim()` (full) vs `public_claim()` (Approved-only badge fields). The queue serializer is a third shape (reviewer fields per US-5.6). List payloads never contain evidence URLs; `GET /claims/{id}/evidence-url` mints per request, TTL ≤ 5 min.

## Resilience patterns

### Conditional-write state machine (NFR-CT-REL-2)
Every transition is `UpdateItem` with a `ConditionExpression` on the expected current state (+ scanStatus for decisions). Concurrent decide/withdraw/revoke/expire races resolve to exactly one winner; losers get 409 with the actual state. The Events `cancel()` lesson is codified: transitions **mutate and validate in one write** — no validate-only helpers that callers can mistake for mutators.

### Duplicate-claim guard without scans (BR-C2)
Live-claim uniqueness for `(certId, memberId)` via a **claim-slot item** (`CLAIMSLOT#<certId>#<memberId>`) written with `attribute_not_exists` in the same transaction as the claim; the slot is deleted on terminal transitions (Rejected/Withdrawn/Revoked/Expired). Mirrors Identity's conditional-counter discipline: a race of two submits cannot double-claim, and no query-then-write window exists. (NULL-attribute trap from Events noted: the slot is presence-based, never a nullable attribute.)

### Fail-closed sync dependency (NFR-CT-REL-1)
`submitClaim`'s Identity membership read: 1.5 s timeout, no retry storm (one retry max), failure → 503 with a retriable error shape. Deliberately NOT wrapped in a fallback — accepting an unverifiable `creditedGroupId` corrupts routing and points attribution. All read paths are Identity-independent.

### Idempotent consumers (NFR-CT-REL-3)
MembershipChanged + scan-verdict consumers run through the run-once idempotency store keyed on envelope/event id (house pattern); payload reads use ONLY documented fields (the Events envelope-id-as-groupId defect class); malformed → log + drop.

### Mark-before-emit sweep (BR-X2/X3; NFR-CT-AVAIL-3)
Expiry sweep per item: conditional flip first (`expiringNoticeSent` or `Approved→Expired`), publish second. Two concurrent sweeps cannot double-fire; a crash loses at most one notification and never a state change. The due-window query (`≤ now+14d`) self-heals missed runs. Batch bound per run with continuation into the next run (no 15-min-timeout risk).

### Post-commit best-effort publishing (BR-E1; NFR-CT-REL-6)
EventPublisher copy (batched PutEvents ≤ 10, never raises after commit, `published[]` test hook). Publish failures logged + alarmed. Lost-Approved-event reconciliation is Unit 7's ledger concern — recorded as a cross-unit note, not silently assumed.

## Scalability & performance patterns

### Index-per-access-pattern, no scans (NFR-CT-PERF-3; J2/J3)
| Access | Path |
|---|---|
| Definition by id / list | Item collection + small partition (tens of items) |
| My claims | Member-partitioned index (`memberId` / `submittedAt`) |
| Pending queue (CL/UGL) | **J2**: sparse single-partition index (`PENDING`/`submittedAt`) — oldest-first for free; key removed on any terminal transition; UGL filter on `creditedGroupId` within a bounded read |
| Holder lookup (`certId`+Approved) & duplicate context | Cert-partitioned index or the claim-slot collection |
| Expiry window | **J3**: shared sweep GSI, partition `EXPIRY`, sort `expiresAt` (sparse: Approved+expiring only) |
| Scan watchdog | **J3**: same GSI, partition `SCANWATCH`, sort `uploadedAt` (sparse: PendingScan only) |

Cursors: opaque base64, whitelisted attributes, invalid → 400 (house rule). Final GSI count and staging order → Infrastructure Design (F2 discipline: one GSI per UpdateTable, DescribeTable-until-ACTIVE, stack status is NOT the readiness signal).

### Hot-path statics (N3=B; NFR-CT-PERF-2)
Badge images = CloudFront static assets; catalog/badge API payloads carry stable public URLs (no signing on the hot path). Evidence = rare per-request presigned GETs.

### Catalog enrichment without N+1 (US-5.10)
`browseCatalog` = one definitions read + **one** member-claims query (caller's), joined in memory for `held`/`pendingClaim`/`heldExpiresAt` — never a per-definition lookup.

## Observability patterns (NFR-CT-REL-5, NFR-CT-SEC-8, N4)
- **Metrics (emitted, not aspirational — the Events alarms-without-metrics lesson)**: `SweepRunOutcome`, `PendingScanAgeMinutes` (watchdog max-age), `EventPublishFailure`, `AuthzDenied`, decision/submission latency + error counts.
- **Alarms**: missed daily sweep (no success metric in 26 h), PendingScan age > 30 min (N4), publish failures > 0, denial spike, 5xx rate. Every alarm has an emitting code path shipped in this unit.
- X-Ray: API → Lambda → DynamoDB/S3/Identity-REST; correlation ids end-to-end (house logger).

## Degrade matrix
| Dependency | Failure | Behavior |
|---|---|---|
| Identity REST | down/slow | `submitClaim` 503 fail-closed (only op affected); everything else unaffected |
| GuardDuty verdicts | stalled | claims sit PendingScan (not reviewable); watchdog alarms at 30 min; link-evidence claims unaffected |
| EventBridge publish | failing | writes commit, events lost → alarm; Contributions reconciliation note stands |
| Scheduler | missed run | next run self-heals (window query); 26 h alarm |
| S3 | down | uploads/evidence-viewing fail with generic error; decisions on link-evidence claims proceed |
| SPA-bucket copy | failing | badge stays `PendingScan`-served-as-placeholder; definition functional; alarm via consumer errors |

## Deliberately NOT added (with reasons)
SQS buffering (EventBridge→Lambda retry + idempotency suffice at this volume) · Step Functions (conditional writes make orchestration redundant) · image processing/thumbnails (≤ 5 MB rendered small; no parser attack surface) · separate scan/sweep Lambdas (router branches, house convention) · ElastiCache (no hot read justifies it) · WAF (platform AC-1 upheld; no public write surface).

## DR test scenarios (for Operations)
1. PITR restore + S3-version skew walkthrough (claim row vs evidence object).
2. Sweep double-run under forced concurrency (assert zero duplicate events/transitions).
3. Verdict redelivery (idempotency) + verdict-never-arrives (watchdog alarm fires).
4. Public-bucket badge copy failure mid-consumer (badge withheld, no partial trust promotion).
5. Restore-then-replay: MembershipChanged replay window vs restored claim states (auto-reject idempotency holds).
