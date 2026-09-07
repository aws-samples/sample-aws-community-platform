# Tech Stack Decisions — Unit 5: Forums

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Forums
Technology choices for the unit, derived from the project-level stack (already fixed) plus the NFR answers (Q1–Q5,Q7 = A; Q6 = C). Companion: `nfr-requirements.md`.

## Inherited from the project (not re-decided)
| Area | Decision |
|---|---|
| Backend runtime | **Python on AWS Lambda** (single function, router pattern — matches Identity/Members/Events/Settings/Announcements/Contributions). |
| Data store | **DynamoDB single table** (`forums-<stage>`) + idempotency table; on-demand capacity; SSE + `Retain`. |
| API | **REST via shared API Gateway**, Cognito authorizer at the edge; in-service fail-closed authZ. Routes under the already-registered `/forums` base path (no `gen_api_edge`/api-edge regen). |
| Async | **EventBridge** for publish (`ForumPostCreated`, `ForumReplyCreated`, `MemberMentioned`, `PostReported`, `PostDeleted`, `ForumChannelDeleted`) and consume (`GroupHardDeleted`/`GroupSoftDeleted`/`GroupRestored`). |
| Frontend | **TypeScript + React + Vite** SPA (Unit 15). |
| IaC / CI-CD | CloudFormation + SAM; per-service CodePipeline, contract-test gated; `-data`/`-app` split. |
| DR | Backup & Restore (hours) + PITR on the forums table. |

## Unit-specific decisions (from NFR answers)

### D-FO-1 — Markdown body: defense-in-depth sanitization (Q5=A)
- **Server (write-time)**: **nh3** (already in repo from Announcements) strips/rejects any raw HTML embedded in the Markdown before storage. Markdown's raw-HTML passthrough is disabled — `<script>`, `<img>`, `<iframe>`, event handlers, `javascript:` URIs are treated as literal text. Length bound enforced.
- **Client (render-time)**: A **markdown renderer** (e.g., `markdown-it` with `html:false`, already used by Announcements) converts stored Markdown→HTML, then **DOMPurify** (already in repo) sanitizes before injection.
- **Rationale**: Forums is the highest-risk XSS surface (every member authors content rendered in every other member's browser). Neither layer alone is trusted; a bypass in one is caught by the other.
- **Rejected**: client-only sanitization (no server defense if DOMPurify is bypassed); server-rendered HTML (lossy for edit round-trips).

### D-FO-2 — Keyword search via inverted-index GSI (Q7=A, DV-2)
- **Choice**: tokenize post `title` fully + `body` capped at **~50 unique terms** (stop-word filtered, lowercased, basic normalization) → write a term-item per term per post to a **sparse GSI** (PK=`TERM#<normalized_term>`, SK=`<postId>`).
- **Search**: Query the GSI per query term → intersect result sets → BatchGetItem matching posts → access-scope filter → return.
- **Write amplification**: bounded at ~58 items/post (8 title terms + 50 body terms). At community scale (~10k posts) → ~580k index items, well within DDB partition limits.
- **Rejected**: title-only indexing (body content not searchable — poor UX); full-body unbounded (unpredictable write cost); OpenSearch (always-on cost, Unit 13 is the optional upgrade path).

### D-FO-3 — Per-user rate limiting (Q4=A)
- **Choice**: app-level per-user rate check via a **TTL counter item** in the forums table (or idempotency table) keyed on `RATE#<memberId>#<action>#<window>`. On post/reply create, check count < limit (10 posts/hr, 30 replies/hr) or reject 429.
- **Mention cap**: server validates `len(mentions) <= 25` before writing; exceeding → 400.
- **Report dedupe**: Query for existing Open report by `(reporterId, targetId)` before insert; duplicate → 409 or no-op.
- **Cost**: one additional conditional read per write on the hot path; negligible at community scale.
- **Rejected**: no rate limiting (SECURITY-11 non-compliant); external rate-limiting service (over-engineered for this scale).

### D-FO-4 — Nightly purge sweep for GroupHardDeleted (Q6=C)
- **Choice**: on `GroupHardDeleted`, immediately mark that group's forums as `status=PURGING` (content invisible to all reads). A **nightly scheduled Lambda** queries for PURGING items and deletes underlying rows (channels/posts/replies/reactions/follows/reports/search-index-items) in idempotent batches of 25. Alarm if PURGING items remain after a run.
- **Rationale**: simpler than a self-continuing worker; at community scale the largest group (~5k posts + descendants) is completable in one sweep pass. Content is invisible immediately; physical deletion is eventual.
- **Rejected**: single-pass synchronous (timeout risk on large groups); self-continuing worker (more complex, marginal benefit at this scale).

### D-FO-5 — Identity mentionSuggest call: fail-soft with timeout (P5, NFR-FO-REL-1)
- **Choice**: `GET /members?q=<prefix>&groupId=<groupId>` forwarding the caller's JWT. **1.5s timeout, fail-soft** → empty suggestions on failure/timeout. The member can still post without @mentions.
- **Pattern**: same as Events' DirectoryClient and Announcements' directory lookup.
- **Rejected**: caching mention candidates (stale membership data); making mention a required step (blocks posting).

### D-FO-6 — No new infrastructure beyond established patterns
- No SQS (events via EventBridge; no fan-out queue needed at community scale).
- No Step Functions (nightly sweep is a single Lambda invocation).
- No ElastiCache/DAX (denormalized counters + keyed queries meet p95 targets without caching).
- No WAF (authenticated-only surface; API GW throttling + per-user limits suffice).
- No S3 bucket (DV-4, no image uploads).
- **Deliberately minimal**: Forums adds no new AWS service type beyond what's already deployed (DynamoDB, Lambda, EventBridge, EventBridge Scheduler, CloudWatch).

## Dependency inventory (new to this unit)
### Backend (Python)
| Dependency | Purpose | Pinned | Notes |
|---|---|---|---|
| `nh3` | Server-side HTML stripping from Markdown bodies at write (NFR-FO-SEC-1) | exact version | Already in repo (Announcements); reused, not added. Native wheel. |

### Frontend (TypeScript)
| Dependency | Purpose | Pinned | Notes |
|---|---|---|---|
| `markdown-it` | Render Markdown→HTML with `html:false` | exact version | Already in repo (Announcements); reused. |
| `dompurify` | Sanitize rendered HTML before DOM injection | exact version | Already in repo (Announcements); reused. |

**Net new dependencies: ZERO.** All three are already present in the repo from Unit 9 (Announcements). Forums reuses them with the same configuration. No supply-chain expansion (SECURITY-10 compliant; no new registry sources; existing lockfile pins cover them).
