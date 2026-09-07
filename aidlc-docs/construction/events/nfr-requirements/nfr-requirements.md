# NFR Requirements — Unit 4: Events

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Events (21 stories)
Platform-wide NFRs (Unit 1) are **inherited**. This document records Events-specific requirements and deltas. Companion: `tech-stack-decisions.md`. Plan: `../../plans/events-nfr-requirements-plan.md`.

## Decisions taken at this stage (all confirmed 2026-08-05)
| # | Decision |
|---|---|
| N1 | Malware scanning: **GuardDuty Malware Protection for S3** on the community bucket, quarantine-on-detect; materials remain hidden until the scan passes |
| N2 | Availability target **99.5%** (STANDARD tier, matching Member Profiles) |
| N3 | Public upload endpoint protected by an **API Gateway usage plan with per-token throttling**, opaque 404s, an upload cap per link, and a 4xx alarm — no WAF (AC-1 upheld) |
| N4 | Attendance events published in **batches of 10**, soft ceiling **1000 attendees per apply**, synchronous |
| ~~N5~~ | ~~Reminders driven by a **single 5-minute sweep**~~ — **WITHDRAWN 2026-08-27**, reminders removed |
| N6 | Point values cached **per warm container, 60-second TTL** |

## Workload criticality (RESILIENCY-01)
**Criticality: STANDARD.** Events is the portal's most-used member-facing feature, but nothing blocks on it at runtime: Contributions consumes its events asynchronously, Member Profiles' activity fan-out degrades per-section, and authentication, forums, and certifications have no dependency on it. Business impact of unavailability is loss of event browsing, RSVP, and attendance recording for the duration — recoverable, no data loss, no revenue impact.

**Upstream dependencies**: Identity & Access (`GroupSoftDeleted`; JWT claims for role and group membership), Settings (MS Teams enablement, via the settings cache), Contributions & Scoring (read-time point values), MS Teams / Microsoft Graph (stubbed at this stage), S3 (materials and uploads), EventBridge.

**Downstream consumers**: Contributions & Scoring (`AttendanceRecorded`, `EventDelivered`, `EventOrganized`, `EventCompleted`), Notifications (`EventUpdated`, `EventCancelled`, `MaterialsAdded`, `CalendarInviteDue`), Announcements (`EventCreated`), Analytics, Member Profiles (activity counts by REST), Frontend SPA.

## Availability and recovery (RESILIENCY-02/08/11 — inherited tier)
- **NFR-EV-AVAIL-1**: Single-region, multi-AZ on managed services (Lambda, DynamoDB, EventBridge, S3). Target **99.5%** for this unit's API (N2).
- **NFR-EV-AVAIL-2**: DR = **Backup & Restore** (RTO/RPO hours), platform baseline. DynamoDB PITR plus on-demand backups on the events table.
- **NFR-EV-AVAIL-3**: **This unit's data is not reconstructible by replay.** Unlike Member Profiles (a derived cache) and unlike Settings (small and re-enterable), events, RSVPs, attendance, and material metadata are original records with no upstream source of truth. This is the most consequential loss profile of any unit built so far and is why PITR is non-negotiable here rather than merely prudent.
- **NFR-EV-AVAIL-4**: S3 objects (materials, external uploads) are protected by bucket versioning, so an overwrite or delete is recoverable independently of the DynamoDB restore point.
- **NFR-EV-AVAIL-5**: A DynamoDB restore and an S3 restore can land at different points in time, producing metadata rows whose objects are missing or objects with no owning row. `uploaded = false` already models the first case safely (BR-M6); the second is reconciled by the object-created consumer. Recovery runbook must state this explicitly.

## Performance
- **NFR-EV-PERF-1**: p95 targets — `listEvents` and `calendar` **< 500 ms**; `getEvent` **< 600 ms** (includes the point-value read); `contentLibrary` **< 700 ms** (keyword post-filter inside a page loop); `rsvpEvent` **< 400 ms** (transactional write, on the interactive path); `recordAttendance` / attendance apply **< 3 s** for up to 200 attendees.
- **NFR-EV-PERF-2**: The point-value read runs through the parallel, timeout-bounded fan-out and is cached per warm container for 60 seconds (N6), so a page of 25 events costs at most one downstream call.
- **NFR-EV-PERF-3**: Per-call fan-out timeout ≤ **300 ms**, matching Unit 3, so a slow Contributions response cannot consume this unit's own latency budget.
- **NFR-EV-PERF-4**: Series creation of up to 104 occurrences completes within the Lambda timeout using batched writes (`TransactWriteItems` caps at 100 items, so a single transaction is impossible — see NFR-EV-REL-6).
- **NFR-EV-PERF-5**: File bytes never traverse Lambda. Uploads and downloads are direct-to-S3 via presigned URLs, so a 500 MB material has no effect on function duration or memory.
- **NFR-EV-PERF-6**: No provisioned concurrency (AC-3 upheld) — Events is not on the authentication-critical path.

## Scalability
- **NFR-EV-SCALE-1**: DynamoDB **on-demand**. Every listing path is served by an index query with a fetch-until-full page loop, never a table scan — the lesson already learned and paid for twice on the Member Directory and File Share listings.
- **NFR-EV-SCALE-2**: Recurrence is capped at **104 occurrences** per series (BR-R3), bounding both write burst and list size.
- **NFR-EV-SCALE-3**: Attendance apply is capped at a soft ceiling of **1000 attendees**, published in batches of 10 (N4, EventBridge `PutEvents` maximum). Above the ceiling the request returns `400` asking for a split import rather than silently truncating or timing out.
- ~~**NFR-EV-SCALE-4**~~: **WITHDRAWN 2026-08-27** — governed the reminder sweep, which no longer exists. The no-Scans rule it was an instance of still holds platform-wide (P-SCALE-1).
- **NFR-EV-SCALE-5**: Service quotas to track (RESILIENCY-09): EventBridge `PutEvents` entries per call (10) and requests per second, Lambda concurrency, S3 request rates, DynamoDB on-demand burst, and API Gateway throttle limits on the public upload route.

## Security
- **NFR-EV-SEC-1 (SECURITY-08)**: Fail-closed in-service authorization on every handler. Three distinct checks layer: role from the permission matrix, creator-ownership or group-leadership per event (BR-A4), and the visibility filter that returns `404` rather than `403` for events outside the caller's scope (BR-A8). Administrators are denied on **every** `/events` operation including reads (BR-A1).
- **NFR-EV-SEC-2 (SECURITY-08, public route)**: The unauthenticated public upload endpoint is the portal's **first unauthenticated write path**. It is authorized solely by a 32-byte random token, stored hashed and compared in constant time (BR-U3), and grants nothing beyond a single-object presigned PUT into one event's folder. It offers no list, read, or delete (BR-U5). Unknown, expired, and revoked tokens are indistinguishable in the response.
- **NFR-EV-SEC-3 (SECURITY-05)**: Validate every input — the eight event types and three delivery modes as enums, title/description length caps, duration bounds, `https://` requirement on virtual join URLs, ISO-8601 timestamps, recurrence completeness, `limit` 1..200, cursor decodability, upload file extension and declared size, and a required `email` column in the attendance CSV. Body size limits at the gateway.
- **NFR-EV-SEC-4 (SECURITY-13)**: **Malware scanning via GuardDuty Malware Protection for S3** (N1). A material is not listed, not downloadable, and not indexed in the Content Library until its scan result is clean; an infected object is quarantined and its material row marked accordingly. This closes the highest-risk path in the unit — externally-supplied files, uploaded by parties with no portal account, served to members.
- **NFR-EV-SEC-5 (SECURITY-06)**: Execution role scoped to this service's tables, its own S3 prefixes (`events/*`) rather than the whole bucket, `PutEvents` on the platform bus, and read-only invoke on the specific Contributions method it calls. No wildcards.
- **NFR-EV-SEC-6 (SECURITY-01)**: Events table and the community bucket encrypted at rest with AWS-managed keys; TLS 1.2+ on all traffic including presigned URL transfers; bucket policy denies non-TLS requests.
- **NFR-EV-SEC-7 (SECURITY-09)**: Community bucket blocks all public access. Presigned URLs are the only access path, minted per request and never stored (the durable lesson from the Settings rework, where a stored presigned URL died with its signing session and could not be revoked).
- **NFR-EV-SEC-8 (SECURITY-11)**: Rate limiting on the public upload route via an API Gateway usage plan with per-token throttling and a per-link upload cap (N3). Abuse case addressed explicitly: a leaked upload token cannot be used to enumerate, read, or delete content, and its exposure is bounded by the link's expiry and immediate revocability.
- **NFR-EV-SEC-9 (SECURITY-14)**: Alarms on public-upload 4xx rate (token guessing), authorization-failure rate, malware detections, point-value fan-out failure rate, and S3-consumer lag.
- **NFR-EV-SEC-10 (SECURITY-13)**: Upload-link create and revoke are audited with actor, event, and link id (BR-U7); attendance applies and point awards are auditable through their published events with stable idempotency keys.
- **NFR-EV-SEC-11 (SECURITY-15)**: Global fail-closed handler. Notably, material removal deletes the S3 object **before** the metadata row and fails closed if the object delete fails, so no object is ever orphaned without an owning record (BR-M7) — the same ordering that a live 502 exposed as necessary during the Settings work.
- **NFR-EV-SEC-12 (SECURITY-04)**: **N/A** — this service returns JSON only; the SPA is served by CloudFront.
- **NFR-EV-SEC-13 (SECURITY-12)**: **N/A** — Events holds no credentials. When the real Graph adapter lands, its credentials belong in Secrets Manager via Settings, not here.

## Reliability and resiliency
- **NFR-EV-REL-1 (RESILIENCY-10)**: Explicit timeouts on every external call (Contributions, Teams provider, S3, DynamoDB). Point-value unavailability degrades to an omitted field (BR-P1) — never an error, never a blocked page.
- **NFR-EV-REL-2 (RESILIENCY-06)**: Shallow health endpoint plus a deep check verifying DynamoDB and S3 reachability.
- **NFR-EV-REL-3**: Event consumption (`GroupSoftDeleted`, S3 object-created/deleted) is idempotent by event id.
- **NFR-EV-REL-4**: Attendance and RSVP are idempotent per member (BR-C3, BR-T8); a Teams batch applies exactly once (BR-T5). Point-award events carry a stable `eventId + userId + kind` key so a consumer retry cannot double-award (BR-P6).
- **NFR-EV-REL-5**: RSVP counters are written in the same transaction as the RSVP row, so they cannot drift from the underlying rows.
- **NFR-EV-REL-6**: **Series creation is not atomic** — 104 occurrences exceed the 100-item `TransactWriteItems` limit. Occurrences are written first in batches and the series record last, so a partial failure leaves orphaned occurrences (individually valid, visible, cancellable events) rather than a series pointing at occurrences that do not exist. NFR Design must specify the reconciliation path.
- **NFR-EV-REL-7 (RESILIENCY-12)**: DynamoDB PITR plus on-demand backups; S3 versioning on the community bucket. Cancellation is a state change, never a delete (BR-L5), so the destructive-operation surface is limited to material removal and upload-link deletion.
- **NFR-EV-REL-8 (RESILIENCY-05/07)**: Metrics and alarms per NFR-EV-SEC-9, plus X-Ray tracing across API → Lambda → Contributions fan-out → S3.
- ~~**NFR-EV-REL-9**~~: **WITHDRAWN 2026-08-27** — there is no reminder sweep to double-send from.

## Maintainability
- **NFR-EV-MAINT-1**: Contract-test gate (Schemathesis + pytest) as for every prior unit, **plus** three unit-specific suites that must not regress silently:
  1. **Authorization matrix** — every operation × every role × every ownership combination, including the Administrator-denied-on-reads rule and the demoted-creator-retains-rights rule (BR-A1, BR-A5), which are the two counter-intuitive behaviours most likely to be "fixed" into a bug later.
  2. **Lifecycle transitions** — every illegal transition returns 409, including the past-date guard on completion.
  3. **Degrade path** — point-value unavailability yields a 200 with the field omitted, never a 5xx.
- **NFR-EV-MAINT-2**: ruff, bandit, cfn-lint, dependency scan, and SBOM in CI (platform default). Tests run in this service's own pytest process, since services deliberately share top-level module names.

## Compliance and scope
- **NFR-EV-COMP-1**: No regulated regime. Event data is community activity data. The one new PII consideration is **externally-supplied uploader identity** on US-2.21 uploads (an email address captured if provided) — minimized in logs, never published in domain events.
- **NFR-EV-COMP-2**: Accessibility — the calendar grid and the review tables are the most complex widgets in the portal so far and must be keyboard-navigable with proper table semantics and non-colour-dependent status indication (badge text carries the meaning, not just the colour).

## Security Compliance Summary
| Rule | Status | Note |
|---|---|---|
| SECURITY-01 Encryption | Compliant | Table + bucket encrypted; TLS enforced by bucket policy |
| SECURITY-02 Access logging | Compliant (inherited) | API Gateway execution/access logs |
| SECURITY-03 App logging | Compliant | Structured logs + correlation ids; uploader email minimized |
| SECURITY-04 Security headers | N/A | JSON-only service |
| SECURITY-05 Input validation | Compliant | Enums, length/size caps, URL scheme, cursor/limit, upload type+size, CSV shape |
| SECURITY-06 Least privilege | Compliant | Prefix-scoped S3, single-method cross-service invoke, no wildcards |
| SECURITY-07 Network | Compliant (inherited) | Private subnets, VPC endpoints |
| SECURITY-08 Access control | Compliant | Three-layer authZ; 404-not-403 for out-of-scope; token-only public write with no read surface |
| SECURITY-09 Hardening | Compliant | Public access blocked; generic errors; no stored presigned URLs |
| SECURITY-10 Supply chain | Compliant | Pinned deps, scan + SBOM, no xlsx (CVE-bearing) |
| SECURITY-11 Rate limiting | Compliant | Per-token throttling + per-link upload cap on the public route |
| SECURITY-12 Auth & credentials | N/A | Service holds no credentials |
| SECURITY-13 Integrity | Compliant | GuardDuty malware scanning gates material visibility; create/revoke audited |
| SECURITY-14 Alerting | Compliant | Public-upload 4xx, authZ failures, malware detections, sweep failures, consumer lag |
| SECURITY-15 Exception handling | Compliant | Global fail-closed handler; S3-delete-before-row ordering |

## Resiliency Compliance Summary
| Rule | Status | Note |
|---|---|---|
| RESILIENCY-01 Criticality | Compliant | STANDARD; dependencies mapped both directions |
| RESILIENCY-02 RTO/RPO | Compliant (inherited) | Backup & Restore; PITR mandatory here (data not replayable) |
| RESILIENCY-03 Change mgmt | N/A (inherited) | Exempt per platform decision |
| RESILIENCY-04 Deploy/rollback | Compliant (inherited) | CodePipeline; previous-version redeploy; direct deployment |
| RESILIENCY-05 Monitoring | Compliant | Metrics/alarms/tracing specified |
| RESILIENCY-06 Health checks | Compliant | Shallow + deep (DynamoDB, S3) |
| RESILIENCY-07 Resiliency monitoring | Compliant | Fan-out failure, sweep failure, consumer lag alarms |
| RESILIENCY-08 Multi-zone | Compliant (inherited) | Managed multi-AZ; single region |
| RESILIENCY-09 Auto-scaling | Compliant | On-demand DynamoDB, Lambda default scaling, quotas identified |
| RESILIENCY-10 Circuit breaking | Compliant | Per-call timeouts, short-circuit, graceful degrade |
| RESILIENCY-11 DR strategy | Compliant (inherited) | Backup & Restore, with the non-replayable caveat documented |
| RESILIENCY-12 Backup | Compliant | PITR + on-demand backups + S3 versioning |
| RESILIENCY-13 Failover procedures | Compliant (inherited) | Platform runbook + the DynamoDB/S3 restore-skew note (NFR-EV-AVAIL-5) |
| RESILIENCY-14 Resiliency testing | Deferred-to-Operations (inherited) | Scenarios captured in NFR Design |
| RESILIENCY-15 Incident response | Compliant (inherited) | Lightweight IR + COE |

**No blocking security or resiliency findings.** The one candidate — unscanned externally-supplied files — was resolved by decision N1 (GuardDuty Malware Protection for S3) rather than accepted as a risk.
