# NFR Requirements Plan — Unit 4: Events

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Events (21 stories)
**Inputs**: `aidlc-docs/construction/events/functional-design/` (4 artifacts, approved 2026-08-05) · platform NFRs (Unit 1) · Security Baseline SECURITY-01..15 · Resiliency Baseline RESILIENCY-01..15
**Precedent**: Unit 2 (CRITICAL tier), Unit 3 (STANDARD tier), Unit 11 (Settings, S3 broker + presigned URLs)

## Steps
- [x] 1. Analyze functional design (business-logic-model, business-rules, domain-entities, frontend-components)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (Q1–Q6 below; 14 further items resolved from existing artifacts — see the resolution table)
- [x] 4. Store plan
- [x] 5. Collect and analyze answers — user replied "proceed" (2026-08-05) accepting the recommendations; all 6 = A. Q1=A means GuardDuty Malware Protection for S3 is now a required infrastructure resource (cost-bearing) and materials carry a scan state. No ambiguity, no clarification round
- [x] 6. Generate NFR artifacts (`nfr-requirements.md`, `tech-stack-decisions.md`)
- [x] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update `aidlc-state.md`

## Inherited without re-asking (platform decisions already made)
The Resiliency Baseline defers eight decisions to the user. All eight were settled at platform level (Unit 1) and apply unchanged here, so they are **not** re-asked: RTO/RPO = **Backup & Restore** (hours), change management = **exempt** with documented rationale, CI/CD = **CodePipeline** (one pipeline per service), rollback = **redeploy previous version**, deployment style = **direct**, topology = **single-region multi-AZ**, resiliency testing = **deferred to Operations** with scenarios captured now, incident response = **lightweight IR + COE**. Also inherited: Python 3.12 on Lambda, DynamoDB on-demand with PITR, EventBridge, API Gateway REST + Cognito authorizer, CloudWatch/X-Ray, pinned dependencies with scan + SBOM, Schemathesis + pytest as the contract gate, no WAF (AC-1), no customer-managed KMS keys (AC-2), no provisioned concurrency by default (AC-3).

## Resolved from existing artifacts (no question needed)

| # | Concern | Resolution |
|---|---|---|
| R1 | Workload criticality (RESILIENCY-01) | **STANDARD**, same tier as Member Profiles. Nothing blocks on Events at runtime: Contributions consumes its events asynchronously, Member Profiles' activity fan-out degrades per-section, and login/forums/certifications have no dependency on it. Not CRITICAL like Identity & Access. |
| R2 | Dependency map | Upstream: Identity (`GroupSoftDeleted` event; JWT claims), Settings (Teams enablement via cache), Contributions (read-time point values), MS Teams (stubbed). Downstream: Contributions (attendance/delivery/organize/completed), Notifications (reminders/invites/materials), Announcements (`EventCreated`), Analytics, Member Profiles (activity counts by REST). |
| R3 | Graceful-degradation pattern | Already established by Unit 3's `FanOutClient`: parallel calls, per-call timeout, individual fault isolation, per-warm-container short-circuit. Reused unchanged for the Contributions point-value read (BR-P1). |
| R4 | Idempotent event consumption | Shared `IdempotencyStore` dedup by event id, as in Units 2 and 3 (BR-X4). |
| R5 | S3 presigned-URL brokering | Settings' `FileShareStorage` pattern: private bucket, fresh short-lived URLs minted on demand, never stored, fail-closed on error (BR-M4/M8, BR-U5). |
| R6 | S3 object-created consumer | Settings' `file_share_event_consumer` pattern via EventBridge on the default bus (not a direct S3 notification, which would create a circular dependency with the Foundation-owned bucket). Reused for material and uploaded-file stamping (BR-M6). |
| R7 | Cursor pagination | Opaque base64 cursor, fetch-until-full page loop, `limit` 1..200, invalid cursor → 400 — as shipped for Admin Users, Member Directory, and File Share (BR-V7). |
| R8 | CSV parsing | Hand-written parser (`parseCsv` on the frontend, stdlib `csv` server-side). **No xlsx** — SheetJS carries unpatched high-severity CVEs and was deliberately removed from this repo (BR-T7). |
| R9 | Authorization enforcement | `Principal.from_claims` + `Authorizer` against the frozen permission matrix, fail-closed, with the creator-ownership branch layered on top (BR-A4/A5). |
| R10 | Encryption (SECURITY-01) | DynamoDB table and the community S3 bucket encrypted at rest with AWS-managed keys; TLS 1.2+ everywhere, including presigned URL traffic. |
| R11 | Security headers (SECURITY-04) | **N/A** — this service serves JSON only. The SPA is served by CloudFront (Unit 1). |
| R12 | Credential management (SECURITY-12) | **N/A** — Events holds no credentials. Teams credentials, when the real adapter lands, live in Settings/Secrets Manager, not here. |
| R13 | DynamoDB transaction limit | `TransactWriteItems` caps at **100 items**, so the 104-occurrence recurrence cap (BR-R3) cannot be one transaction. Series creation uses batched writes with the series record written last, so a partial failure leaves orphaned occurrences rather than a series pointing at nothing. Flagged for NFR Design. |
| R14 | Log retention + alerting (SECURITY-14) | 90-day minimum retention, inherited. Unit-specific alarms proposed in NFR Design: point-value fan-out failure rate, reminder-sweep failures, public-upload 4xx rate, S3-consumer lag. |

---

# Questions

Six decisions genuinely need your input. Everything else is inherited or resolved above.

## Question 1
**Malware scanning of uploaded files.** Both US-2.15 and US-2.21 explicitly defer virus/malware scanning to the design phase — this is that decision. Event materials are downloaded by other members, and US-2.21 accepts uploads from **external parties with no portal account**, which is the highest-risk ingestion path in the whole portal.

A) **GuardDuty Malware Protection for S3** on the community bucket: quarantine-on-detect, materials stay hidden until the scan passes. Managed, no code, per-GB cost. Adds a scan-completion state to the material lifecycle.

B) No scanning in Phase 1 — document the accepted risk, restrict allowed types, and note it as a follow-up. Zero cost, but externally-supplied files are served to members unscanned.

C) Third-party scanning Lambda (ClamAV layer) triggered on object-created — no per-GB service cost but a container/layer to maintain and a 500 MB file to scan inside Lambda limits.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
**Availability target for this unit.** Identity & Access is 99.9% (CRITICAL); Member Profiles is 99.5% (STANDARD).

A) **99.5%**, matching Member Profiles' STANDARD tier — Events is member-facing and high-traffic but blocks nothing else.

B) 99.9%, treating Events as the portal's most-used feature and holding it to the Identity tier (implies tighter alarms and likely provisioned concurrency, reversing platform decision AC-3).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3
**Abuse controls on the unauthenticated public upload endpoint.** This is the portal's **first unauthenticated write endpoint**. The platform decided against WAF (AC-1).

A) **API Gateway usage plan with per-token throttling** plus an opaque `404` for unknown/expired/revoked tokens, a hard cap on uploads per link, and a CloudWatch alarm on elevated 4xx. No WAF, consistent with AC-1.

B) Revisit AC-1 and add WAF in front of the public route (rate-based rule + bot control) — stronger, adds monthly cost and reverses a platform decision.

C) Require a one-time email verification step before the recipient can upload (adds friction the story does not ask for).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4
**Attendance event volume.** Applying attendance publishes one `AttendanceRecorded` per confirmed member (BR-P6). A 500-person conference produces 500 events in one request, and the mockup shows a 180-RSVP event.

A) **Batch publication in chunks of 10** (EventBridge `PutEvents` maximum) inside the request, with a documented soft ceiling of **1000 attendees per apply**; above that, return `400` asking for a split import. Simple, synchronous, no new infrastructure.

B) Write the attendance rows synchronously and publish asynchronously from the table's DynamoDB stream — smoother under load, adds a stream consumer and makes point awards eventually consistent.

C) Enqueue the apply to SQS and process in the background, returning `202` — most scalable, but the manager no longer sees an immediate result.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5
**Reminder scheduling mechanism and accuracy.** Reminders must fire at `startsAt − leadTime` (BR-N1).

A) **One EventBridge Scheduler-driven sweep every 5 minutes** querying due records, giving ≤5-minute accuracy. One schedule for the whole service, cheap, and naturally idempotent via the record's status. Accuracy is ample for 1-hour-to-1-week lead times.

B) One EventBridge Scheduler schedule created per event — to-the-minute accuracy, but thousands of schedules to create, update, and delete, and a quota to manage.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6
**Point-value read caching.** Every event list, card, and detail render wants the event type's point value from Contributions (BR-P1). Eight event types, values that change rarely.

A) **Per-warm-container cache with a 60-second TTL**, exactly the pattern Identity & Access uses for the settings read. Collapses a whole page of renders into one downstream call and bounds staleness to a minute.

B) No cache — one fan-out call per request; simplest, but a list of 25 events triggers repeated downstream load for values that almost never change.

C) Consume a `ScoringFrameworkChanged` event into an Events-owned cache table (adds a new event to Unit 7's contract, and a second copy of Contributions' data).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

**Recommended answers**: Q1 **A**, Q2 **A**, Q3 **A**, Q4 **A**, Q5 **A**, Q6 **A**. Reply "all A" to accept, or answer individually.

Note on Q1: option B is the only answer that would produce a **blocking security finding** at this stage (externally-supplied files served to members without scanning, against SECURITY-13's integrity requirement). If you choose B, I will record it as an accepted-risk exception with your rationale rather than silently passing the gate.
