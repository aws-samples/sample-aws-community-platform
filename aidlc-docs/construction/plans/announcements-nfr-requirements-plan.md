# NFR Requirements Plan — Unit 9: Announcements

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Announcements
**Extensions enabled**: Security Baseline (Yes), Resiliency Baseline (Yes), Property-Based Testing (No). Inputs: the approved functional design (`aidlc-docs/construction/announcements/functional-design/`), the two requirement deviations (mandatory expiry; UI-only dismissal), and the project-level decisions already locked in `aidlc-state.md`.

## Project-level decisions already fixed (reused, NOT re-asked)
These were answered at Requirements Analysis and applied to every prior unit; they carry forward unchanged:
- **RTO/RPO = hours → Backup & Restore** DR strategy (RESILIENCY-02/11).
- **Single-region, multi-AZ** (RESILIENCY-08). Serverless (Lambda + DynamoDB) is multi-AZ by default.
- **Change management exempt** (RESILIENCY-03); **CI/CD = per-service CodePipeline**, contract-test gated (RESILIENCY-04); **rollback = redeploy previous Lambda version**; **deployment = direct/in-place** (matches STANDARD criticality).
- **Incident response = lightweight IR + COE** (RESILIENCY-15).
- **Resiliency testing deferred to Operations** (RESILIENCY-14).
- Backend **Python on Lambda**; **REST via shared API Gateway** with Cognito authorizer (authN at edge, authZ in-service, fail-closed).

## Proposed classification (RESILIENCY-01)
**STANDARD criticality** (same tier as Member Profiles and Events, not CRITICAL like Identity). Rationale: **no other service has a synchronous runtime dependency on Announcements.** Notifications consumes `AnnouncementPublished` asynchronously; the recipient panel is a supplementary landing-page widget — if Announcements is unavailable, the SPA shows no panel (or a "couldn't load" state) and every other journey is unaffected. There is no auth, payment, or data-integrity path here. Business impact of downtime: leaders can't post/see broadcasts temporarily; bounded and non-cascading.

## Steps
- [x] 1. Analyze functional design artifacts
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (below, `[Answer]:` tags)
- [x] 4. Store plan (this file)
- [x] 5. Collect + analyze answers (all A; Q5/Q6 confirmed after explanation — no ambiguity)
- [x] 6. Generate artifacts (`nfr-requirements.md`, `tech-stack-decisions.md`)
- [x] 7. Present completion message
- [x] 8. Await explicit approval (approved 2026-08-07)
- [x] 9. Record approval + update aidlc-state.md

## Security baseline applicability (pre-assessment — confirmed at the gate)
| Rule | Applicability to Announcements |
|---|---|
| SECURITY-01 Encryption at rest/in transit | Applies — DynamoDB SSE + TLS (platform default). Compliant. |
| SECURITY-04 HTTP security headers | **N/A to this service** — it serves JSON, not HTML; headers are owned by the SPA/CloudFront (Unit 1/15). |
| SECURITY-05 Input validation + **XSS sanitization** | **Key rule here** — rich-text body must be sanitized server-side on write (BR-14). Drives Q5 (sanitizer choice). |
| SECURITY-06 Least privilege | Applies — scoped IAM (own table, EventBridge put, directory read). Detailed at Infra Design. |
| SECURITY-08 App-level access control | Applies — fail-closed authz from the permission matrix (BR-1..4), Administrator denied incl. reads, author/CL delete rules. IDOR guard on edit/delete by `authorId`. |
| SECURITY-10 Supply chain | Applies — the HTML sanitizer is the one new runtime dependency (Q5); must be pinned + maintained. |
| SECURITY-11 Rate limiting / abuse | Applies — but **all endpoints are Cognito-authenticated** (no public/unauthenticated surface, unlike Events' upload token). Shared API GW throttling covers it → Q3. |
| SECURITY-14 Alerting | Applies — CloudWatch alarms on error rate/throttles (STANDARD set). |
| SECURITY-15 Fail-safe defaults | Applies — fail-closed authz, generic errors, denormalization fail-closed to id/email. |
| SECURITY-02/03/07/09/12/13 | Inherited from platform (API GW access logs, structured logging, VPC config, no default creds, no auth here, event integrity) — no unit-specific gap. |

No blocking security findings anticipated. Confirmed after answers.

## Resiliency baseline applicability
| Rule | Applicability |
|---|---|
| RESILIENCY-02/11 DR | Backup & Restore (project default). **Q4**: DynamoDB PITR on the announcements table? Content is author-created and not event-reconstructible (unlike Member Profiles), but short-lived (≤90d) and low-criticality. |
| RESILIENCY-08 Multi-AZ | Compliant by default (Lambda + DynamoDB). Single-region (project default). |
| RESILIENCY-09 Auto-scaling / quotas | Lambda concurrency + DynamoDB on-demand; identify the EventBridge/DynamoDB quotas touched by the auto-post consumer. |
| RESILIENCY-10 Dependency isolation | Applies — the create-time directory lookup (author/group name) needs a timeout + fail-closed (already in BR-8); Notifications/EventBridge are async (no synchronous coupling). **Q2** sets the timeout budget. |
| RESILIENCY-05/06/07 Observability | STANDARD alarm set + a shallow health path. |
| RESILIENCY-12 Backup | Tied to Q4 (PITR) + the project Backup & Restore posture. |
| RESILIENCY-03/04/14/15 | Project-level answers reused (above). |

No blocking resiliency findings anticipated.

---

## Questions

Recommended option marked **(recommended)**. Answer after each `[Answer]:` tag.

## Question 1
**Criticality classification (RESILIENCY-01).** Do you agree Announcements is **STANDARD** criticality?

A) **(recommended)** STANDARD — no synchronous runtime dependents; panel-down degrades gracefully; non-cascading.

B) HIGH — treat the panel as a higher-availability surface.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 2
**Panel read performance + degrade budget (the hot path — every landing page load).** Target and mechanism?

A) **(recommended)** p95 ≤ 500 ms for the panel read, achieved via a **warm-container cache of the active-announcement set** (30s TTL, same as Settings); the create-time directory name lookup gets a **1.5 s timeout, fail-closed** (store id/email, matching the tuned Events value). Cache miss = one bounded query.

B) No caching — query the table on every panel load (simpler, more read units, still small at this volume).

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 3
**Authoring abuse / rate limiting (SECURITY-11).** All announcement endpoints are Cognito-authenticated (no public surface). How should abuse be bounded?

A) **(recommended)** Rely on the **shared API Gateway throttling** (already applied to all authenticated routes) + in-service authz (only CL/UGL can create). No dedicated usage plan — there is no unauthenticated surface here (unlike Events' public upload token).

B) Add a per-author create throttle / daily cap in-service.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 4
**Data protection for the announcements table (RESILIENCY-12).** Announcement content is author-created and **not** reconstructible by event replay (there is no upstream source of truth for the text). It is also short-lived (mandatory expiry ≤90 days) and STANDARD criticality. Enable DynamoDB Point-in-Time Recovery?

A) **(recommended)** **Enable PITR** on the announcements table — cheap insurance for non-reconstructible author content; consistent with Events (also non-reconstructible). Backup & Restore posture otherwise unchanged.

B) No PITR — rely on the project Backup & Restore default only; accept that a table-level loss between backups loses recent announcements (which self-expire anyway).

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 5
**Rich-text HTML sanitizer (SECURITY-05 / SECURITY-10 — the one new runtime dependency).** The body must be sanitized server-side on write to a safe HTML subset. Which approach?

A) **(recommended)** Use **`nh3`** (maintained Python binding to the Rust `ammonia` sanitizer) with a tight allow-list (formatting tags + safe `http(s)` links, `rel=noopener`), pinned version. Actively maintained, fast, no known CVEs. (Note: `bleach`, the old default, is **deprecated** — avoid, same reasoning as the xlsx/SheetJS avoidance elsewhere in this repo.)

B) Hand-written allow-list sanitizer (no third-party dep) — zero supply-chain surface, but security-sensitive code we must get exactly right.

C) Store Markdown instead; render to sanitized HTML on the client.

X) Other (describe after `[Answer]:`)

[Answer]: A (confirmed after explanation — nh3; bleach deprecated, hand-rolled sanitizer rejected as a fragile security boundary)

## Question 6
**Defense-in-depth on render (SECURITY-11 layering).** Server-side sanitization is authoritative (BR-14). Do you also want client-side sanitization when the SPA renders the body HTML?

A) **(recommended)** Yes — also run **DOMPurify** on the client before `dangerouslySetInnerHTML`, as a second layer (cheap, standard React practice). Server remains the source of truth.

B) No — trust the server-sanitized HTML only; render directly.

X) Other (describe after `[Answer]:`)

[Answer]: A (confirmed after explanation — DOMPurify as defense-in-depth; server sanitization remains authoritative)
