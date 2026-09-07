# NFR Requirements — Unit 6: Certifications

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Certifications
Platform-wide NFRs (Unit 1) are **inherited**. This document records certifications-specific requirements and deltas. Companion: `tech-stack-decisions.md`. Plan: `../../plans/certifications-nfr-requirements-plan.md` (N1=A, N2=5 MB per file, N3=B, N4=A).

## Workload criticality (RESILIENCY-01)
- **Criticality: STANDARD.** Nothing blocks at runtime on Certifications: login/events/forums proceed without it; member-profiles degrades its certification sections per its BR-9; Contributions consumes `CertificationApproved` asynchronously (events buffer, points arrive late rather than never).
- **BUT claim data is NOT reconstructible by replay** (Events-unit precedent, unlike Units 3/11): claims are original member-submitted records (evidence refs, dateEarned, decisions, reasons). **PITR is mandatory, not prudent.** Evidence/badge S3 objects share the same property.
- **Upstream deps**: Identity & Access (REST membership check at submission — the only sync dependency on the write path; `MembershipChanged` events for auto-reject), GuardDuty scan verdicts (S3 events), EventBridge Scheduler (daily sweep).
- **Downstream consumers**: Contributions (Approved event → auto-award, US-6.5), member-profiles (deployed REST fan-out on `listClaims`), Notifications (later; 5 event types), Analytics (later), Frontend SPA.

## Availability & recovery
- **NFR-CT-AVAIL-1 (N1=A)**: **99.5%** monthly for the certifications API (STANDARD tier, matches Units 3/4).
- **NFR-CT-AVAIL-2**: DR = Backup & Restore (inherited); **DynamoDB PITR + on-demand backups mandatory** (non-replayable data). S3 evidence/badge objects: versioning on the upload prefixes; DynamoDB/S3 restore-point skew documented in runbooks (Events precedent).
- **NFR-CT-AVAIL-3**: The daily expiry sweep is **self-healing across missed runs**: the due-window query (`expiresAt ≤ now+14d`) naturally includes overdue items, so a failed/missed run is fully caught up by the next successful one. A sweep failure must be visible (NFR-CT-REL-5), not silent.

## Performance
- **NFR-CT-PERF-1**: p95 targets — `browseCatalog` / `myClaims` / `listClaims` / `verificationQueue` **< 400 ms**; `decideClaim` / `revokeClaim` / `withdrawClaim` **< 600 ms** (conditional write + post-commit publish); `submitClaim` **< 1.5 s** (bounded by the sync Identity membership read — cross-service reads measured 490–760 ms live in the Events deployment; its 1.5 s timeout precedent applies); upload-grant ops **< 300 ms** (pure signing, no I/O beyond a pointer write).
- **NFR-CT-PERF-2**: Badge images render as **static CloudFront assets (N3=B)** — zero per-render API or signing cost on the hottest image path. Evidence files remain per-request presigned GETs (rare, private).
- **NFR-CT-PERF-3**: Every listing is an **index-bounded query — no table scans** (the lesson already paid for three times: Member Directory, File Share, My Group). Queue, my-claims, member-badges, holder-lookup, and the expiry window each get a query path sized to their result set.
- **NFR-CT-PERF-4**: No provisioned concurrency (not on the auth-critical interactive path — Unit 3 precedent).

## Scalability
- **NFR-CT-SCALE-1**: Sizing envelope: 13k+ members × a handful of certifications each → low-tens-of-thousands of claims, tens of definitions. DynamoDB on-demand absorbs this trivially; the design constraint is access-pattern shape (NFR-CT-PERF-3), not throughput.
- **NFR-CT-SCALE-2**: The expiry sweep's work set is proportional to holdings expiring within 14 days (sparse index), not to total claims; a pathological backlog (mass import) still processes in bounded batches across successive daily runs.
- **NFR-CT-SCALE-3**: Auto-reject consumer volume is bounded by membership-change volume (already handled at 13k scale by Identity); per-event work = one bounded query (member's Pending claims for one group) + conditional writes.

## Security (Security Baseline)
- **NFR-CT-SEC-1 (SECURITY-08)**: Fail-closed in-service authZ via the declarative OP_AUTHZ map; **blanket Administrator 403 on every operation** (D7 — includes the matrix-row removal recorded in this unit); UGL group scope fail-closed when `ledGroupId` unresolvable (BR-A4); IDOR guards return 404 on others' claim ids (BR-A5).
- **NFR-CT-SEC-2 (SECURITY-05)**: Input validation on all bodies/params — status/category enums, ISO dates (`dateEarned` not-in-future), reason length ≤ 500, notes/description caps, http(s)-only evidence URLs, extension whitelist (evidence pdf/png/jpg/jpeg; badge png/jpg/jpeg — **no SVG**, script risk), cursor/limit validation (invalid → 400).
- **NFR-CT-SEC-3 (N2)**: **5 MB cap per uploaded file** (evidence and badge alike), enforced at the storage door (upload-grant policy) or verified immediately post-upload with the object deleted before it can become servable — an oversized object must never reach a reviewer or the public bucket. One evidence file per claim.
- **NFR-CT-SEC-4 (D5/C2=A)**: All uploads land in the GuardDuty-scanned bucket under this unit's prefixes with **system-generated unique keys** (BR-C7). Files are invisible until scan-Clean: evidence gates claim reviewability (BR-V3); badge images are **copied to the public SPA bucket only after a Clean verdict** (N3=B) — the public bucket never receives an unscanned byte. Quarantined objects are never served and are lifecycle-deleted.
- **NFR-CT-SEC-5 (N3=B consequence)**: Badge images become world-readable static assets (the SPA bucket serves pre-login). Accepted and recorded: badge art is community-visible by design and carries no PII. Evidence files must NEVER take this path.
- **NFR-CT-SEC-6 (SECURITY-06)**: Execution role scoped to: own table, own EventBridge publishes + subscribed rules, S3 upload prefixes (put-grant/get-sign/delete), **write scoped to the badges/ prefix of the SPA bucket only** (the one cross-stack write this unit adds), Identity REST invoke for the membership check. No wildcards.
- **NFR-CT-SEC-7 (SECURITY-15/BR-P1/P2)**: Privacy by projection — non-owners see only Approved-claim badge data; evidence URLs minted per request, short-lived, never stored, never in list payloads; degraded dependencies produce omitted sections or fail-closed errors, never stack traces.
- **NFR-CT-SEC-8 (SECURITY-14, N4=A)**: **Alarm when any claim sits in `PendingScan` > 30 minutes** — the scan pipeline's silent-failure mode made visible. Plus alarms on authz-denial spikes (probing signal) and event-publish failures.

## Reliability / Resiliency (Resiliency Baseline)
- **NFR-CT-REL-1 (RESILIENCY-10)**: The one sync cross-service call (Identity membership check) carries an explicit timeout and **fails the submission closed** (503) — a claim credited to an unverified group would corrupt routing and points attribution. Reads never depend on Identity.
- **NFR-CT-REL-2**: All lifecycle transitions are conditional writes (illegal → 409); concurrent decision/withdraw/revoke/expire races resolve to exactly one winner.
- **NFR-CT-REL-3**: Consumers (MembershipChanged, scan verdicts) are idempotent on envelope/event id; redelivery is safe. Sweep actions are conditional + mark-before-emit (BR-X2) — the failure direction is a lost notification, never a duplicated state change.
- **NFR-CT-REL-4 (RESILIENCY-06)**: Shallow health check + deep check (own table reachability). Identity reachability is deliberately NOT in the deep check — its failure degrades one write op, not the service.
- **NFR-CT-REL-5 (RESILIENCY-05/07)**: Metrics/alarms — sweep-run success (alarm on a missed daily run), PendingScan age (N4), event-publish failure, decision/submission error rates + p95s, consumer error rate. X-Ray tracing across API → Lambda → DynamoDB/S3/Identity.
- **NFR-CT-REL-6**: Post-commit best-effort event publishing (BR-E1); a publish failure is logged + alarmed but never fails the committed write. Contributions' auto-award tolerance for a lost Approved event is Unit 7's concern (its ledger reconciliation), noted for that unit.

## Maintainability
- **NFR-CT-MAINT-1**: Contract-test gate (all ops v2.0.0) **plus three mandatory suites**: (1) **authorization matrix** incl. the counter-intuitive rules — Admin blanket 403 everywhere, Members-only submission, UGL fail-closed on unresolvable led group, owner-only 404-not-403; (2) **lifecycle transitions** — every illegal transition → 409, freeze-at-approval invariants (BR-V6/V7), duplicate rule across all six states; (3) **fail-closed/degrade paths** — Identity down → submit 503 + reads 200, scan-verdict idempotency, sweep mark-before-emit under simulated concurrent runs.
- **NFR-CT-MAINT-2**: ruff + cfn-lint + pinned deps (platform default); bandit/dependency-scan/SBOM gaps remain platform-level follow-ups (recorded at Build & Test), not unit deltas.

## Compliance / scope
- **NFR-CT-COMP-1**: No regulated regime. Evidence files may contain member names/credential IDs — treated as member-private content (BR-P1/P2 access rules; encrypted at rest; never logged, never public). Badge art is public by design (NFR-CT-SEC-5).

## Security Compliance Summary (this stage)
| Rule | Status | Note |
|---|---|---|
| SECURITY-01 Encryption | Compliant | KMS at rest (table + buckets); TLS everywhere |
| SECURITY-02 Access logging | Compliant (inherited) | API GW edge logs |
| SECURITY-03 App logging | Compliant | JSON + correlation ids; no evidence content/PII in logs |
| SECURITY-04 Security headers | N/A | No HTML served by this service |
| SECURITY-05 Input validation | Compliant | NFR-CT-SEC-2 (enums, dates, caps, URL scheme, extension whitelist, no SVG) |
| SECURITY-06 Least privilege | Compliant | NFR-CT-SEC-6 (scoped role incl. prefix-scoped SPA-bucket write) |
| SECURITY-07 Network | Compliant (inherited) | Private subnets + VPC endpoints |
| SECURITY-08 Access control | Compliant | Fail-closed OP_AUTHZ; Admin blanket 403; UGL scope; IDOR 404s |
| SECURITY-09 Hardening | Compliant | Generic errors; no credentials held |
| SECURITY-10 Supply chain | Compliant | No new runtime deps (stdlib + boto3); pinned |
| SECURITY-11 Rate limiting | Compliant (inherited) | Platform API GW throttling; uploads authenticated (no public write surface) |
| SECURITY-12 Auth & credentials | N/A | AuthN owned by Identity; this service holds no secrets |
| SECURITY-13 Integrity | Compliant (inherited) | Pipeline + safe parsing |
| SECURITY-14 Alerting | Compliant | NFR-CT-SEC-8 (PendingScan age, denial spikes, publish failures) |
| SECURITY-15 Exception handling | Compliant | Fail-closed handler; privacy projection; no leakage in degrade paths |

## Resiliency Compliance Summary (this stage)
| Rule | Status | Note |
|---|---|---|
| RESILIENCY-01 Criticality | Compliant | STANDARD; non-replayable data caveat recorded |
| RESILIENCY-02 RTO/RPO | Compliant | Backup & Restore; **PITR mandatory** + S3 versioning |
| RESILIENCY-03 Change mgmt | N/A (inherited) | Exempt per platform decision |
| RESILIENCY-04 Deploy/rollback | Compliant (inherited) | Pipeline; redeploy-previous rollback |
| RESILIENCY-05 Monitoring | Compliant | NFR-CT-REL-5 metric/alarm set |
| RESILIENCY-06 Health checks | Compliant | Shallow + deep (own table only, deliberate) |
| RESILIENCY-07 Resiliency monitoring | Compliant | Sweep-missed + PendingScan-age + publish-failure alarms |
| RESILIENCY-08 Multi-zone | Compliant (inherited) | Managed multi-AZ services |
| RESILIENCY-09 Auto-scaling | Compliant | On-demand DDB + Lambda defaults |
| RESILIENCY-10 Circuit breaking | Compliant | Timeout + fail-closed on the single sync dependency; reads independent |
| RESILIENCY-11 DR strategy | Compliant | Backup & Restore; restore-skew documented |
| RESILIENCY-12 Backup | Compliant | PITR + on-demand + S3 versioning; no hard deletes of claims |
| RESILIENCY-13 Failover procedures | Compliant (inherited) | Platform runbook |
| RESILIENCY-14 Resiliency testing | Deferred-to-Operations (inherited) | Scenarios: restore-skew, sweep double-run, verdict redelivery — captured for NFR Design |
| RESILIENCY-15 Incident response | Compliant (inherited) | Lightweight IR + COE |

**No blocking security or resiliency findings.**
