# NFR Requirements — Unit 5: Forums

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Forums
**Criticality**: **STANDARD** (RESILIENCY-01). No service has a synchronous runtime dependency on Forums; Contributions and Notifications consume events asynchronously. The only synchronous coupling is *outbound* (Forums → Identity `mentionSuggest`), which fails soft. Companion: `tech-stack-decisions.md`. Source answers: `aidlc-docs/construction/plans/forums-nfr-requirements-plan.md` (Q1–Q5,Q7 = A; Q6 = C). Reflects the five functional-design deviations (DV-1..5).

## 1. Workload classification & business impact (RESILIENCY-01)
| Aspect | Value |
|---|---|
| Criticality | STANDARD |
| Business impact of downtime | Members temporarily cannot browse/post/reply; community engagement paused but no auth/payment/data-integrity path blocked. Bounded, non-cascading. |
| Synchronous dependents | **None** — Contributions consumes `ForumPostCreated`/`ForumReplyCreated` async; Notifications delivers mentions/follows async. |
| Upstream dependencies (async) | Identity (`GroupHardDeleted`/`GroupSoftDeleted`/`GroupRestored`) — via EventBridge. |
| Upstream dependency (sync, non-critical) | Identity `mentionSuggest` — autocomplete lookup. **Fail-soft** to empty suggestions; post still succeeds without it. |

## 2. Availability (RESILIENCY-02)
- **Target: 99.5%** (STANDARD tier, matching Events/Announcements/Member Profiles). Nothing blocks on Forums at runtime.
- **RTO/RPO**: hours — **Backup & Restore** (project default), augmented by DynamoDB **PITR** on the forums table (§6).
- **Topology**: single-region, multi-AZ (project default; Lambda + DynamoDB are multi-AZ by default) (RESILIENCY-08).
- **Read/write independence**: browse/channel/thread reads degrade independently of post/reply writes.

## 3. Performance
| Requirement | Target | Basis |
|---|---|---|
| **NFR-FO-PERF-1** Channel post-list / thread / browse | **p95 ≤ 400 ms** | Q2=A. Single-partition DynamoDB Query (GSI); denormalized counters (no fan-out on read); pinned-first sort via composite key. |
| **NFR-FO-PERF-2** Keyword search | **p95 ≤ 800 ms** | Q2=A. Two-step: Query inverted-index GSI per term → BatchGetItem posts. Two DDB round-trips. |
| **NFR-FO-PERF-3** Writes (post/reply/react/follow) | **p95 ≤ 500 ms** | Q2=A. Single PutItem or TransactWrite (post + counter update + search-index items) + async event emission. |
| **NFR-FO-PERF-4** No per-read fan-out | invariant | All listing data is denormalized on the item (counters, author name/role, accepted flag). Thread view is a single Query — no per-reply lookup. |
| **NFR-FO-PERF-5** Bounded search write amplification | invariant | Q7=A. Title fully tokenized + body capped at ~50 unique terms/post (stop-word filtered). Write cost is predictable regardless of body length. |

## 4. Security requirements (Security Baseline — enabled)
| ID | Requirement | Rule |
|---|---|---|
| **NFR-FO-SEC-1** | **Stored-XSS defense in depth** (Q5=A): server-side **nh3** strips/rejects raw HTML embedded in Markdown at write time (raw-HTML passthrough disabled) + length bound enforced. Client renders Markdown→HTML then **DOMPurify** sanitizes before injection. Neither layer alone is trusted. | SECURITY-05 |
| **NFR-FO-SEC-2** | Fail-closed authorization from `role-permission-matrix.v1.json`: two-layer check — (a) capability (role holds action), (b) resource access via JWT-claim group membership (BR-2/BR-3). **Administrator 403 on ALL ops including reads** (BR-1). | SECURITY-08 |
| **NFR-FO-SEC-3** | **IDOR guard**: edit/delete verify `authorId` (or leader scope) before mutating; mention validate every `userId` against group-access before writing. A resource id alone never grants access. | SECURITY-08 |
| **NFR-FO-SEC-4** | Input validation: `title`+`body` required + length-bounded; `kind` enum-checked (BR-16); `tags` array bounded; unknown fields rejected → 400. | SECURITY-05 |
| **NFR-FO-SEC-5** | **Per-user rate limiting** (Q4=A): post/reply creation capped per user per hour (e.g., 10 posts/30 replies); **per-post mention cap ≤25** (bounds notification fan-out); report dedupe (one Open per reporter per target). API GW usage-plan throttling as baseline. Generic 4xx, no internal detail. | SECURITY-11 |
| **NFR-FO-SEC-6** | Least-privilege IAM: own table CRUD + inverted-index GSI queries, EventBridge `PutEvents`, scoped `execute-api:Invoke` for Identity `mentionSuggest`, idempotency table. No wildcards. | SECURITY-06 |
| **NFR-FO-SEC-7** | Structured logging with correlation id; **no body/PII content in logs**; generic client error messages. | SECURITY-03, SECURITY-15 |
| **NFR-FO-SEC-8** | Rate limiting via the **shared API Gateway throttling** on all (authenticated) routes + per-user app-level limits (NFR-FO-SEC-5). No unauthenticated surface (no public endpoints). | SECURITY-11 |
| **NFR-FO-SEC-9** | CloudWatch alarms on handler error rate, Lambda throttles, DLQ depth, cascade-sweep stall, and authZ-failure spikes. | SECURITY-14 |
| SECURITY-04 | **N/A** — service returns JSON, not HTML; response headers owned by SPA/CloudFront (Unit 1/15). | — |

## 5. Reliability & dependency isolation (Resiliency Baseline)
| ID | Requirement | Rule |
|---|---|---|
| **NFR-FO-REL-1** | Identity `mentionSuggest` call has a **short timeout (1.5s) and fails soft** — returns empty suggestions; post/reply creation continues without mentions. Forums never blocks on Identity. | RESILIENCY-10 |
| **NFR-FO-REL-2** | No synchronous dependency on Contributions/Notifications; events are at-least-once via EventBridge; points/emails may lag; Forums operations unaffected. | RESILIENCY-10 |
| **NFR-FO-REL-3** | Consumed events (`GroupHardDeleted`/`GroupSoftDeleted`/`GroupRestored`) processed **idempotently on envelope id** (BR-27/28). Redelivery never double-purges/double-hides. | RESILIENCY-06 |
| **NFR-FO-REL-4** | Graceful degradation: mention lookup down → empty suggestions; search index partially stale → results eventually consistent; forum reads never fail due to downstream issues. | RESILIENCY-10 |
| **NFR-FO-REL-5** | Shallow health path for the Lambda; STANDARD metric/alarm set. | RESILIENCY-05/07 |
| **NFR-FO-REL-6** | **Nightly purge sweep** (Q6=C): on `GroupHardDeleted`, mark forums as PURGING immediately (content invisible to all reads); a nightly scheduled Lambda deletes underlying rows in idempotent batches. **Alarm if PURGING items remain after a sweep run** (stale purge detection). No user-visible content survives the mark. | RESILIENCY-10 |
| **NFR-FO-REL-7** | Service-quota awareness: DynamoDB on-demand limits; EventBridge `PutEvents` (<1 MB/req, 256 KB/event); TransactWriteItems 100-item limit (search-index items batched within this). | RESILIENCY-09 |

## 6. Data protection (RESILIENCY-11/12)
- **NFR-FO-DATA-1** — **DynamoDB PITR enabled** on the forums table: post/reply content is author-created and **not reconstructible by event replay** → PITR is the recovery mechanism. Consistent with Events, Announcements, Member Profiles.
- **NFR-FO-DATA-2** — Encryption at rest (DynamoDB SSE) + TLS in transit (SECURITY-01). `DeletionPolicy/UpdateReplacePolicy: Retain` on the table.
- **NFR-FO-DATA-3** — Inverted-index GSI items are derived from post content and **can be reconstructed** by re-tokenizing existing posts → no independent backup required.
- **NFR-FO-DATA-4** — Idempotency table with TTL (event consumer dedup) — ephemeral, no backup needed.

## 7. Maintainability / testability
- **NFR-FO-MAINT-1** — Mandatory test suites for Code Generation:
  1. **Authorization matrix** — CL/UGL/Member/Administrator × all ops (browse/read/post/reply/react/pin/accept/follow/report/moderate/manage); incl. Administrator-denied-on-reads (BR-1), UGL scoped to led group, author-only-edit, IDOR guard on mention/delete.
  2. **XSS sanitization battery** — payloads (`<script>`, `onerror=`, `javascript:`/`data:` URIs, mutation-XSS, markdown raw-HTML bypass attempts) asserting server-side nh3 strips them; safe Markdown formatting/links/code preserved.
  3. **Rate limiting** — per-user post/reply cap enforcement; mention cap (>25 → rejected); report dedupe (second Open report → 409/no-op).
  4. **Event consumers** — `GroupHardDeleted` marks PURGING (content invisible); `GroupSoftDeleted` hides; `GroupRestored` unhides; all idempotent on redelivery.
  5. **Degrade** — Identity mention lookup timeout → empty suggestions, post succeeds; event emission failure → Forums operations unaffected; search-index write failure → post succeeds (search eventually consistent).
  6. **Keyword search** — tokenization correctness (stop-words excluded, case-normalized, body capped at ~50 terms); multi-term intersection; access-scoped (hidden/deleted excluded, group-access enforced).
- Property-Based Testing: **disabled** (project decision) — example-based tests.

## 8. Compliance summary
**Security**: SECURITY-01 ✅ (SSE+TLS), -02 ✅ (API GW/platform), -03 ✅ (NFR-FO-SEC-7), -04 **N/A** (JSON not HTML), -05 ✅ (NFR-FO-SEC-1/4), -06 ✅ (NFR-FO-SEC-6), -07 ✅ (platform VPC), -08 ✅ (NFR-FO-SEC-2/3), -09 ✅ (no secrets), -10 ✅ (nh3/DOMPurify/markdown-it pinned+scanned), -11 ✅ (NFR-FO-SEC-5/8), -12 ✅ (Cognito, no auth here), -13 ✅ (DOMPurify/SRI on SPA side), -14 ✅ (NFR-FO-SEC-9), -15 ✅ (NFR-FO-SEC-7). **No blocking security findings.**

**Resiliency**: RESILIENCY-01 ✅ (STANDARD), -02 ✅ (99.5%, Backup&Restore+PITR), -03 ✅ (exempt, project), -04 ✅ (CodePipeline/redeploy/direct, project), -05/06/07 ✅ (alarms+health+idempotent), -08 ✅ (single-region multi-AZ), -09 ✅ (quota awareness, TransactWrite batch bounds), -10 ✅ (NFR-FO-REL-1/2/4/6), -11 ✅ (Backup&Restore), -12 ✅ (PITR+SSE), -13 ✅ (redeploy-from-IaC runbook, project), -14 ✅ (deferred to Operations, project), -15 ✅ (lightweight IR, project). **No blocking resiliency findings.**
