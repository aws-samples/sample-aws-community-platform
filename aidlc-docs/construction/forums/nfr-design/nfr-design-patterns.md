# NFR Design Patterns — Unit 5: Forums

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Forums
How the NFR requirements are realized as concrete patterns. Companion: `logical-components.md`. Plan: `../../plans/forums-nfr-design-plan.md`. Criticality STANDARD. Answers: ND-1..5 = A.

## Scalability patterns

- **Read-heavy, query-only access (NFR-FO-PERF-1/4, BR-29)**: every listing (browse, channel post-list, thread, search, moderation queue, follows) is a keyed DynamoDB Query on a GSI or base-table partition — **no Scan, ever**. Counters, author names, accepted flags, and pinned status are denormalized on the item so a single Query returns render-ready rows.
- **Bounded write amplification on create (NFR-FO-PERF-5, ND-3=A)**: creating a post writes the post item + counter updates + ~58 search-index term-items in **one TransactWriteItems** call (~60 items total, within the 100-item limit). All-or-nothing: if any write fails, nothing is committed. Search index is immediately consistent with the post — no orphaned index items, no eventual lag.
- **On-demand elasticity**: DynamoDB on-demand + standard Lambda concurrency absorb read spikes. At community scale (Q3=A), no partition sharding, no DAX, no provisioned concurrency needed.
- **Counter contention negligible at scale (ND-2=A)**: at single-digit writes/second per channel or post, TransactWrite conflicts are near-zero. No write-sharded counters needed.

## Performance patterns

- **Inline transactional counter updates (ND-2=A, NFR-FO-PERF-3)**: the same TransactWriteItems that creates a post/reply/reaction atomically updates the parent's counter fields. Counters are **always consistent** — no Stream consumer, no lag, no reconciliation. At community scale, contention is negligible.
  - Post create: `[Put(post) + Update(channel.postCount++) + Update(channel.lastActivityAt) + Put(~58 term-items)]`
  - Reply create: `[Put(reply) + Update(post.replyCount++) + Update(channel.lastActivityAt)]`
  - Reaction replace: `[Delete(old reaction) + Put(new reaction) + Update(target.reactionCounts.{oldKind}--) + Update(target.reactionCounts.{newKind}++)]` — 4 items max.
- **Author denormalization from JWT claims (ND-4=A)**: `authorName` and `authorRoleLabel` are extracted directly from the caller's JWT claims at write time. **Zero cross-service call on the post/reply hot path.** Fail-closed to `sub` (member id) if the display-name claim is absent. This eliminates the latency + dependency that a DirectoryClient lookup would add on every post/reply.
- **Inverted-index search within p95 (NFR-FO-PERF-2)**: keyword search is a two-step read: (1) Query the inverted-index GSI per query term (`PK=TERM#<term>`) → collect `postId` sets, (2) intersect, (3) BatchGetItem matching posts. Two DDB round-trips ≤ 800ms p95. Access-scope filter applied in-memory after fetch (bounded by page size).
- **No provisioned concurrency**: no operation is on an interactive auth-critical path; standard on-demand scaling suffices.
- **No cache layer (D-FO-6)**: with denormalized counters and keyed queries, reads are fast enough without DAX or ElastiCache. Adding a cache would introduce invalidation complexity for marginal gain at community scale.

## Resilience patterns

- **Mention autocomplete: 1.5s timeout, fail-soft (NFR-FO-REL-1, J1)**: `mentionSuggest` calls Identity's `GET /members?q=<prefix>&groupId=<groupId>` forwarding the caller's JWT. On timeout/5xx/connection error → returns empty suggestions. The member can still post without @mentions. No caching of candidates (membership changes too frequently for a stale cache to be useful; at community scale the Identity endpoint responds in <200ms typical).
- **Event emission is async/buffered (NFR-FO-REL-2)**: `ForumPostCreated`, `ForumReplyCreated`, `MemberMentioned`, `PostReported` are emitted via EventBridge `PutEvents` after the transactional write succeeds. If EventBridge is momentarily unavailable, the post is still created (data committed); events can be re-emitted from the committed data. Contributions/Notifications lag but Forums is unaffected.
- **Idempotent event consumers (NFR-FO-REL-3, BR-27/28)**: `event_consumer` checks-then-writes an idempotency record keyed on the envelope id (TTL cleanup) before acting, for all three consumed event types. Redelivery never double-marks or double-purges. Same mechanism as Identity/Members/Announcements.
- **Nightly purge sweep with alarm (NFR-FO-REL-6, ND-5=A, Q6=C)**: on `GroupHardDeleted`, the consumer immediately marks the group's forums as `status=PURGING` (content invisible to all reads in <500ms). A nightly Scheduler-triggered invocation queries PURGING items and deletes rows in batches of 25 (BatchWriteItem), iterating until empty or a 10-minute time-cap. If PURGING items remain after the cap, an alarm fires. Next nightly run resumes. At community scale (~25k items worst case), one pass is sufficient.
- **Graceful degradation matrix (NFR-FO-REL-4)**:
  | Failure | Impact | Behavior |
  |---------|--------|----------|
  | Identity mentionSuggest down | No autocomplete suggestions | Post still succeeds; user types names manually |
  | EventBridge down | Points/notifications delayed | Forum operations unaffected; events buffered |
  | DynamoDB throttle | Retries within Lambda timeout | botocore exponential backoff; alarm on sustained |
  | Search-index partially stale (rare) | Some new posts not immediately searchable | Eventually consistent on retry/next write |
- **No circuit breaker needed**: the only optional outbound call is mentionSuggest (1.5s timeout is sufficient at STANDARD criticality; a circuit breaker would be over-engineering for one non-critical endpoint).

## Security patterns

- **Defense-in-depth XSS prevention (NFR-FO-SEC-1, D-FO-1, SECURITY-05)**:
  - **Server (write-time)**: `nh3` strips any raw HTML from the Markdown body before storage. Markdown's raw-HTML passthrough is disabled — `<script>`, `<img>`, `<iframe>`, event handlers, `javascript:` URIs treated as literal text. Length bound enforced.
  - **Client (render-time)**: `markdown-it` (`html:false`) renders Markdown→HTML; `DOMPurify` sanitizes before injection. Neither layer alone is trusted.
  - **Key insight**: Forums is the highest-risk XSS surface (every member authors content rendered in every other member's browser). Two independent sanitization layers means a bypass in one is caught by the other.
- **Two-layer fail-closed authZ (NFR-FO-SEC-2/3, SECURITY-08)**:
  - Layer 1 — **Capability**: role must hold the action in the permission matrix.
  - Layer 2 — **Resource access**: caller must reach the target's `groupId` via JWT claims (CL→any, UGL→ledGroupId, M→memberGroupIds, A→never).
  - Failing either → 403. Missing claim → 403. Administrator → 403 on everything including reads (BR-1).
  - **IDOR guard**: edit/delete load the item and verify `authorId`==caller (or leader scope) before mutating. Mention validates every `userId` against group-access before writing.
- **Per-user rate limiting (NFR-FO-SEC-5, D-FO-3)**:
  - TTL counter item keyed on `RATE#<memberId>#<action>#<hourWindow>`. On post/reply create, conditional check (count < limit) or reject 429.
  - Mention cap: `len(mentions) <= 25` validated server-side before write; exceeding → 400.
  - Report dedupe: Query for existing Open report by `(reporterId, targetId)`; duplicate → 409/no-op.
  - All limits return generic 4xx (no internal detail exposed).
- **Least-privilege IAM (NFR-FO-SEC-6)**: execution role scoped to own table (CRUD + PITR), inverted-index GSI queries, idempotency table, EventBridge `PutEvents`, `execute-api:Invoke` scoped to Identity mentionSuggest endpoint only. No wildcards.
- **Input validation (NFR-FO-SEC-4)**: `title` + `body` required + length-bounded; `kind` enum-checked; `tags` array bounded; all DynamoDB expressions parameterized (never string-built). Unknown fields rejected → 400.
- **No sensitive logging (NFR-FO-SEC-7, SECURITY-15)**: global handler catches unhandled exceptions → generic error envelope; post/reply body content and PII never logged; correlation id on every log line.

## Observability patterns (RESILIENCY-05/07)

- **Structured logs + correlation ids**: every request carries a `correlationId` (from API GW request id or EventBridge event id) through all log lines.
- **CloudWatch metrics**: request error rate, p95 per operation, `MentionLookupTimeoutCount`, `SearchQueryLatency`, `SweepItemsPurged`, `SweepStallAlarm`, `RateLimitRejectCount`, `EventConsumerLagSeconds`.
- **Alarms (NFR-FO-SEC-9)**: handler error rate, Lambda throttles, DLQ depth, sweep stall (PURGING items remain after run), sustained authZ-failure spike (possible brute-force), sustained mention-timeout rate (signals Identity outage).
- **Health**: shallow (process up) + deep (own DynamoDB reachability only). Does NOT deep-check Identity — it's an expected-to-degrade, non-blocking dependency.

## Resiliency test scenarios (captured for Operations — RESILIENCY-14)
| Scenario | Expected behavior |
|---|---|
| Identity mentionSuggest 5xx or timeout | Empty suggestions returned; post/reply succeeds; `MentionLookupTimeoutCount` increments |
| EventBridge down during post create | Post committed to DDB; events lost (recoverable from committed data); alarm on sustained lag |
| Duplicate/redelivered `GroupHardDeleted` | Idempotency dedupes on envelope id; PURGING mark is idempotent (already marked) |
| `GroupSoftDeleted` then `GroupRestored` | Forums hidden then restored; idempotent on redelivery |
| DynamoDB throttle on TransactWrite | botocore backoff within Lambda timeout; alarm on sustained throttles; no partial write (transactional) |
| Nightly sweep hits time-cap | Alarm fires; next run resumes from where it stopped; no user-visible impact (content already invisible) |
| TransactWrite conflict (concurrent reply on same post) | Automatic retry (TransactWrite is retryable); at community scale, conflicts resolve in <100ms |
| Search-index write failure (within transaction) | Entire transaction rolls back; post not created; user retries; no orphaned index |
| Region/AZ event | Managed multi-AZ absorbs AZ loss; region loss → Backup & Restore runbook + PITR restore (content non-reconstructible) |

## Compliance deltas (this stage)
All applicable SECURITY + RESILIENCY rules realized by the patterns above. SECURITY-04 **N/A** (JSON, not HTML). SECURITY-09 **N/A** (no secrets held by Forums). SECURITY-12 **N/A** (Cognito, no credentials held in this service). RESILIENCY-14 = scenarios captured (execution deferred to Operations). **No blocking findings.** Judgement calls J1–J3 flagged for gate review.
