# NFR Requirements Plan — Unit 5: Forums

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Forums · Extensions enabled: **Security Baseline (SECURITY-01..15)**, **Resiliency Baseline (RESILIENCY-01..15)**.
Inputs: `construction/forums/functional-design/*` (business-logic-model, business-rules BR-1..30, domain-entities E1..E7, frontend-components).

## Preliminary classification — STANDARD
Forums has **no synchronous runtime dependents**: Contributions/Notifications consume its events asynchronously; the only synchronous coupling is *outbound* (Forums → Identity `mentionSuggest`), which fails soft. Nothing in the portal blocks on Forums at runtime. → **STANDARD** (same as Events/Announcements/Member Profiles), not CRITICAL like Identity. Proposed availability target **99.5%**.

## Inherited decisions (locked at Requirements phase — referenced, not re-asked)
| Area | Inherited value |
|---|---|
| Regional topology (RESILIENCY-08) | Single-region, multi-AZ (serverless multi-AZ by default). |
| RTO/RPO + DR (RESILIENCY-02/11) | Backup & Restore, RTO/RPO in hours. |
| Change management (RESILIENCY-03) | Exempt (documented at Requirements). |
| CI/CD + deploy + rollback (RESILIENCY-04) | AWS CodePipeline per service; rollback = redeploy previous Lambda version; direct deploy. |
| Incident response (RESILIENCY-15) | Lightweight IR + COE (proposed at Requirements). |
| Resiliency testing (RESILIENCY-14) | Deferred to Operations (capture scenarios now). |
| Backend runtime | Python on Lambda; TS/React frontend. |

## Steps
- [x] 1. Analyze functional design
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (below)
- [x] 4. Store plan
- [x] 5. Collect + analyze answers (resolve ambiguity before proceeding) — Q1–Q5,Q7=A; Q6=C (nightly sweep). Brainstormed one-by-one 2026-08-13. No ambiguity.
- [x] 6. Generate artifacts (`nfr-requirements.md`, `tech-stack-decisions.md`)
- [x] 7. Present completion message
- [x] 8. Await approval — user approved 2026-08-13
- [x] 9. Record approval + update aidlc-state.md

---

## Proposed decisions (resolved from precedent + baselines — flagged for review; override any)
| Ref | Area | Proposed decision |
|---|---|---|
| P1 | Availability | 99.5% (STANDARD). Reads (browse/channel/thread) degrade independently of writes. |
| P2 | Data protection (RESILIENCY-12) | Forum content (posts/replies) is **not reconstructible by event replay** (unlike Identity's derived caches) → **PITR mandatory** on the Forums table, + SSE-at-rest (SECURITY-01), + on-demand backups. Same reasoning Events/Announcements applied. |
| P3 | Authorization (SECURITY-08) | Fail-closed, two-layer (capability + JWT-claim group access), Administrator denied on all ops incl. reads, IDOR guard on every id-referenced resource. Test suite: authorization matrix + IDOR. |
| P4 | Logging/observability (SECURITY-03/14, RESILIENCY-05) | Structured logs w/ correlation id, no PII/body content in logs; CloudWatch; alarms for authZ-failure spikes + throttles + DLQ depth + cascade-worker failures. |
| P5 | Degrade (RESILIENCY-10) | `mentionSuggest` Identity call has a short timeout, **fail-soft** to empty suggestions (post still succeeds). Event emission is async/buffered; Forums never blocks on Contributions/Notifications. |
| P6 | Supply chain (SECURITY-10) | Pin any new deps (client markdown renderer + DOMPurify already in repo; server-side markdown/HTML sanitizer). Lock files + scan. |

---

## Questions

Recommended option marked **(recommended)**. Answer after each `[Answer]:`.

## Question 1
**Availability target + criticality.** Confirm Forums is **STANDARD / 99.5%** (reads degrade independently; nothing blocks on Forums synchronously)?

A) **(recommended)** Yes — STANDARD, 99.5%.

B) Higher (99.9%+) — treat forums as business-critical.

C) Lower — best-effort.

X) Other.

[Answer]: 

## Question 2
**Interactive read performance targets.** Forums is read-heavy; the hot paths are channel post-list, thread (post+replies), and browse. Proposed p95 latency targets (warm):

A) **(recommended)** Channel list / thread / browse **p95 ≤ 400ms**; keyword search **p95 ≤ 800ms**; writes (post/reply/react) **p95 ≤ 500ms**. All served by keyed DynamoDB queries + denormalized counters (no Scan, no per-row fan-out).

B) Tighter (p95 ≤ 200ms reads) — implies caching (DAX) up front.

C) Looser — no explicit p95, best-effort.

X) Other.

[Answer]: 

## Question 3
**Scale assumptions** (drive GSI design, counter contention, follow fan-out, and hard-delete batch sizing). Pick the expected shape:

A) **(recommended)** Community scale — up to ~tens of groups, thousands of posts + tens of thousands of replies total, hot channels up to ~hundreds of followers, largest group up to ~a few thousand posts (bounds the hard-delete cascade). Reactions/counters see modest concurrency.

B) Large scale — 100k+ posts, channels with thousands of followers, groups with tens of thousands of posts (implies heavier fan-out infra + partition-key sharding for hot counters).

C) Small/pilot — hundreds of posts total.

X) Other.

[Answer]: 

## Question 4
**Abuse / rate limiting (SECURITY-11 — public-facing write endpoints).** Post/reply creation, reactions, reports, and `mentionSuggest` are member-driven and abusable (spam posting, report flooding, mention blasting). Controls?

A) **(recommended)** API Gateway usage-plan throttling (baseline) **+** per-user create-rate limits on post/reply, **+** a per-post **mention cap** (e.g., ≤25 mentioned users) to bound notification fan-out, **+** dedupe repeat reports (one Open report per reporter per target). Generic 4xx, no internal detail.

B) API Gateway throttling only (no per-user/app-level limits).

C) No rate limiting in Phase 1.

X) Other.

[Answer]: 

## Question 5
**Markdown body — stored-XSS defense (SECURITY-05, load-bearing here since bodies render into other members' browsers).** Bodies are Markdown (DV-4, no images). Approach?

A) **(recommended)** **Defense in depth**: on **write**, strip/reject embedded raw HTML in the Markdown (Markdown's raw-HTML passthrough disabled) + length bound; on **render**, client converts Markdown→HTML then **DOMPurify** sanitizes. Neither layer alone is trusted. New pinned deps: a client markdown renderer + DOMPurify (already used by Announcements); a small server-side HTML-stripper (e.g., nh3, already in repo from Announcements — reused, or bleach-equivalent).

B) Client-only sanitization (DOMPurify at render); store Markdown verbatim including any raw HTML.

C) Server renders Markdown→sanitized HTML and stores HTML (like Announcements' original HTML path).

X) Other.

[Answer]: 

## Question 6
**Hard-delete cascade worker (RESILIENCY-10, from FD Q10 mark-then-background).** The background purge of a large group's content must not exceed Lambda limits or leave partial state. Bounds?

A) **(recommended)** Mark forums deleted synchronously; purge underlying rows in **idempotent batches** (e.g., 25/write-batch) via a **self-continuing worker** (re-invoke/queue until done), with a checkpoint so it resumes after failure; alarm if a purge stalls. No user-visible content survives the initial mark.

B) Single-pass synchronous cascade in the event handler (simpler; risks timeout on large groups).

C) Nightly sweep reconciles orphaned rows instead of an active worker.

X) Other.

[Answer]: 

## Question 7
**Keyword-search index write cost (from FD Q6 inverted-index GSI).** Tokenizing title (+body?) into term-items adds write amplification per post. Scope?

A) **(recommended)** Index **title + a bounded set of body terms** (cap tokens/post, stop-word filtered) so write amplification is bounded and predictable; search matches title strongly + body loosely. Keeps cost proportional and avoids unbounded term explosion on long posts.

B) Index **title only** (cheapest writes; body not searchable).

C) Index full title + full body (richest matching; highest write cost + item count).

X) Other.

[Answer]: 
