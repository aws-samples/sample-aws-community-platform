# NFR Requirements — Unit 9: Announcements

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Announcements
**Criticality**: **STANDARD** (RESILIENCY-01). No service has a synchronous runtime dependency on Announcements; the recipient panel degrades gracefully and non-cascadingly if the service is down. Companion: `tech-stack-decisions.md`. Source answers: `aidlc-docs/construction/plans/announcements-nfr-requirements-plan.md` (all Q1–Q6 = A). Reflects the two functional-design deviations (mandatory expiry; UI-only dismissal).

## 1. Workload classification & business impact (RESILIENCY-01)
| Aspect | Value |
|---|---|
| Criticality | STANDARD |
| Business impact of downtime | Leaders temporarily cannot post/see broadcasts; members see no panel (or a "couldn't load" state). Bounded, non-cascading; no auth/payment/data-integrity path. |
| Synchronous dependents | **None** — Notifications consumes `AnnouncementPublished` asynchronously. |
| Upstream dependencies (async) | Events (`EventCreated`), Identity (`GroupSoftDeleted`/`GroupRestored`) — via EventBridge. |
| Upstream dependency (sync, create-time only) | Member Profiles / Identity directory read for author/group name denormalization — **fail-closed**, non-blocking (BR-8). |

## 2. Availability (RESILIENCY-02)
- **Target: 99.5%** (STANDARD tier, matching Member Profiles/Events). Nothing blocks on Announcements at runtime.
- **RTO/RPO**: hours — **Backup & Restore** (project default), augmented by DynamoDB **PITR** on the announcements table (§6, Q4=A).
- **Topology**: single-region, multi-AZ (project default; Lambda + DynamoDB are multi-AZ by default) (RESILIENCY-08).

## 3. Performance (the panel is the hot path)
| Requirement | Target | Basis |
|---|---|---|
| **NFR-AN-PERF-1** Panel read (`GET /announcements?view=panel`) | **p95 ≤ 500 ms** | Q2=A. Warm-container cache of the active set (30s TTL, Settings pattern); in-memory filter by claims + expiry + `groupHidden`; cache miss = one bounded query. |
| **NFR-AN-PERF-2** Create/edit/delete | p95 ≤ 800 ms | Single O(1) write; no audience fan-out (BR-7). Create also does one directory lookup (NFR-AN-REL-1). |
| **NFR-AN-PERF-3** Management list (`view=mine`) | p95 ≤ 700 ms | Query by `authorId`; bounded, paginated (CL `scope=all` moderation paginated). |
| **NFR-AN-PERF-4** No write fan-out | invariant | Posting to 13k+ recipients is still one write (the design's core property). |

## 4. Security requirements (Security Baseline — enabled)
| ID | Requirement | Rule |
|---|---|---|
| **NFR-AN-SEC-1** | *(Revised 2026-08-07 — Markdown.)* Body **stored as inert Markdown**; rendered + sanitized at the **client boundary** via `markdown-it` (`html:false`) + **DOMPurify** before injection. Server length-bounds only (no HTML sanitize, no native `nh3` dep). Non-browser consumers (email path) render/escape themselves. | SECURITY-05 |
| **NFR-AN-SEC-2** | **Defense-in-depth at render**: `markdown-it` disables raw HTML AND DOMPurify strips anything remaining before `dangerouslySetInnerHTML`. Markdown being inert at rest is the additional layer. | SECURITY-11, SECURITY-13 |
| **NFR-AN-SEC-3** | Fail-closed authorization from `role-permission-matrix.v1.json`: create CL(global)/UGL(group-own); edit author-only; delete author or any-CL(moderation); Administrator **403 on all incl. reads**. | SECURITY-08 |
| **NFR-AN-SEC-4** | **IDOR guard**: edit/delete verify `authorId` (or CL moderation right) before mutating; a resource id alone never grants access. | SECURITY-08 |
| **NFR-AN-SEC-5** | Input validation: `title` required + length-bounded; `target.groupIds` non-empty when `scope=groups`; `expiresAt` clamped (default +2d, max +90d); enum/type checks → 400. | SECURITY-05 |
| **NFR-AN-SEC-6** | Least-privilege IAM: own table (+ PITR), EventBridge `PutEvents` for `AnnouncementPublished`, scoped `execute-api:Invoke` for the directory read, idempotency table. No wildcards. (Detailed at Infra Design.) | SECURITY-06 |
| **NFR-AN-SEC-7** | Structured logging with correlation id; **no body/PII content in logs**; generic client error messages. | SECURITY-03, SECURITY-15 |
| **NFR-AN-SEC-8** | Rate limiting via the **shared API Gateway throttling** on all (authenticated) routes; no unauthenticated surface exists (Q3=A). | SECURITY-11 |
| **NFR-AN-SEC-9** | CloudWatch alarms on handler error rate, Lambda throttles, and consumer (EventBridge) failures. | SECURITY-14 |
| SECURITY-04 | **N/A** — service returns JSON, not HTML; response headers owned by SPA/CloudFront (Unit 1/15). | — |

## 5. Reliability & dependency isolation (Resiliency Baseline)
| ID | Requirement | Rule |
|---|---|---|
| **NFR-AN-REL-1** | The create-time directory lookup (author/group name) has a **1.5 s timeout and fails closed** — stores id/email / raw group id and the post still succeeds (BR-8). Never blocks authoring. | RESILIENCY-10 |
| **NFR-AN-REL-2** | No synchronous dependency on Notifications/EventBridge for the in-portal panel; `AnnouncementPublished` is at-least-once, email may lag, panel unaffected (BR-10). | RESILIENCY-10 |
| **NFR-AN-REL-3** | Consumed events (`EventCreated`, `GroupSoftDeleted`, `GroupRestored`) processed **idempotently on envelope id** (BR-15). Redelivery never double-posts/double-hides. | RESILIENCY-06 |
| **NFR-AN-REL-4** | Graceful degradation: panel filters in memory; a directory/name gap shows id/email, never a 5xx. `view=panel` never returns 5xx for a downstream issue. | RESILIENCY-10 |
| **NFR-AN-REL-5** | Shallow health path for the Lambda; STANDARD metric/alarm set (RESILIENCY-05/07). | RESILIENCY-05/06 |
| **NFR-AN-REL-6** | Service-quota awareness: EventBridge `PutEvents` (<1 MB/req, 256 KB/event) and DynamoDB on-demand limits identified for the auto-post consumer; auto-post is one small write per `EventCreated` (no batch). | RESILIENCY-09 |

## 6. Data protection (RESILIENCY-11/12)
- **NFR-AN-DATA-1** — **DynamoDB PITR enabled** on the announcements table (Q4=A): body text is author-created and **not reconstructible by event replay**, so PITR is the recovery mechanism, not merely prudent. Short-lived (≤90d) but PITR is cheap insurance. Consistent with Events (also non-reconstructible).
- **NFR-AN-DATA-2** — Encryption at rest (DynamoDB SSE) + TLS in transit (SECURITY-01). `DeletionPolicy/UpdateReplacePolicy: Retain` on the table (D6).
- **NFR-AN-DATA-3** — **TTL on `expiresAt`** reclaims expired announcements automatically; read-time expiry filter is authoritative (not the TTL sweep) (BR-5/6).
- **NFR-AN-DATA-4** — No Dismissals table (UI-only dismissal, requirement deviation) — no per-user server state to protect.

## 7. Maintainability / testability
- **NFR-AN-MAINT-1** — Mandatory test suites for Code Generation:
  1. **Authorization matrix** — CL/UGL/Member/Administrator × create/edit/delete/panel/mine; incl. Administrator-denied-on-reads, UGL-target-forced-to-led-group, author-only-edit, CL-moderation-delete-any.
  2. **Sanitization** — a battery of XSS payloads (`<script>`, `onerror=`, `javascript:`/`data:` URIs, mutation-XSS vectors) asserting they are stripped by `nh3`; safe formatting/links preserved.
  3. **Expiry** — default +2d applied when absent; clamp to +90d; `expiresAt<=now` excluded from panel/count but shown Expired in `view=mine`.
  4. **Event consumers** — `EventCreated announce=true` auto-posts once (idempotent on redelivery); `announce=false` no-op; `GroupSoftDeleted`/`GroupRestored` hide/restore.
  5. **Degrade** — directory lookup timeout → post succeeds with id/email fallback; panel never 5xx on downstream failure.
- Property-Based Testing: **disabled** (project decision) — example-based tests.

## 8. Compliance summary
**Security**: SECURITY-01 ✅, -02 ✅ (API GW/platform), -03 ✅, -04 **N/A** (JSON not HTML), -05 ✅ (NFR-AN-SEC-1/5), -06 ✅ (NFR-AN-SEC-6), -07 ✅ (platform VPC), -08 ✅ (NFR-AN-SEC-3/4), -09 ✅, -10 ✅ (nh3/DOMPurify pinned+scanned), -11 ✅ (NFR-AN-SEC-2/8), -12 ✅ (Cognito, no auth here), -13 ✅ (DOMPurify/SRI on SPA side), -14 ✅ (NFR-AN-SEC-9), -15 ✅ (NFR-AN-SEC-7). **No blocking security findings.**

**Resiliency**: RESILIENCY-01 ✅ (STANDARD), -02 ✅ (99.5%, Backup&Restore+PITR), -03 ✅ (exempt, project), -04 ✅ (CodePipeline/redeploy/direct, project), -05/06/07 ✅ (alarms+health), -08 ✅ (single-region multi-AZ), -09 ✅ (Lambda concurrency/on-demand+quota awareness), -10 ✅ (NFR-AN-REL-1/2/4), -11 ✅ (Backup&Restore), -12 ✅ (PITR+SSE+TTL), -13 ✅ (redeploy-from-IaC runbook, project), -14 ✅ (deferred to Operations, project), -15 ✅ (lightweight IR, project). **No blocking resiliency findings.**
