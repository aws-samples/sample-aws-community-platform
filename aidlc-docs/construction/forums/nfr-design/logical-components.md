# Logical Components — Unit 5: Forums

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Forums
Logical decomposition (technology-agnostic roles → concrete Python modules at Code Generation). Companion: `nfr-design-patterns.md`.

## Component map
```
API Gateway (Cognito authorizer)           EventBridge rules (Group lifecycle)     EventBridge Scheduler (nightly)
        │ proxy event                              │                                      │
        ▼                                          ▼                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ handler (router) — dispatches by event source: API / EventBridge / Scheduler                     │
└───────────┬──────────────────────────────────────┬──────────────────────────────────┬────────────┘
            │ API routes                           │ event consumer                   │ sweep
   ┌────────┼─────────────┐                        ▼                                  ▼
   ▼        ▼             ▼              ┌──────────────────┐              ┌────────────────────┐
validation  authz    ForumService        │ event_consumer   │              │ sweep_handler      │
                     ChannelService      │ (idempotent)     │              │ (batched purge)    │
                     PostService         │ - GroupHardDel   │              │ - query PURGING    │
                     ReplyService        │   → mark PURGING │              │ - batch delete 25  │
                     ReactionService     │ - GroupSoftDel   │              │ - time-cap 10min   │
                     FollowService       │   → set hidden   │              │ - alarm on remain  │
                     ReportService       │ - GroupRestored  │              └────────────────────┘
                     SearchService       │   → clear hidden │
                     MentionService      └──────────────────┘
                          │
         ┌────────────────┼──────────────────────────────┐
         ▼                ▼                              ▼
    Repository     MentionClient              EventPublisher
    (single-table  (Identity mentionSuggest   (ForumPostCreated, ForumReplyCreated,
     + idem table   1.5s fail-soft)            MemberMentioned, PostReported,
     + search GSI)                             PostDeleted, ForumChannelDeleted)
         │
         ├── SearchIndexWriter (tokenize + write term-items inline)
         ├── RateLimiter (TTL counter items, per-user per-action)
         └── Sanitizer (nh3, strip raw HTML from Markdown at write)
```

## Components
| Component | Responsibility | Realizes NFR |
|---|---|---|
| `handler` (router) | Match event source → dispatch (API/EventBridge/Scheduler); build `Principal` from JWT; `global_handler` fail-closed wrapper with correlation id | SECURITY-08/15, ND-1=A |
| `validation` | `title`/`body` length-bounded, `kind` enum, `tags` array bounded, mention cap ≤25, unknown fields rejected → 400 | NFR-FO-SEC-4/5 |
| `authz` | Two-layer: capability (permission matrix) + resource access (JWT-claim group check); Administrator denied on all; IDOR guard (authorId verify on edit/delete); UGL forced to ledGroupId | NFR-FO-SEC-2/3 |
| `ForumService` | Create/edit/delete forum (+ auto-create "General" channel); group-access scoped | BR-4/6/8/11, W1 |
| `ChannelService` | Create/edit/delete channel; cascade posts on delete | BR-7/8/11, W2 |
| `PostService` | Create post (+ counter + search-index + auto-follow + mentions + event) / edit / delete (+ cascade replies/reactions/follows/reports) | BR-9/5/11/12/13, W4/W6 |
| `ReplyService` | Create reply (+ counter + mentions + event) / edit / delete; accepted-reply management | BR-10/5/15, W5/W6/W9 |
| `ReactionService` | Set/replace/clear reaction; atomic counter update (decrement old + increment new) | BR-16, W7, J2 |
| `FollowService` | Toggle follow on channel/post; list caller's follows; auto-follow on post create | BR-17/18, W10 |
| `ReportService` | Create report (dedupe check) / moderation queue / dismiss / action (→ delete content) | BR-24/25, W11 |
| `SearchService` | Keyword search: tokenize query → Query inverted-index GSI per term → intersect → BatchGetItem → access-scope filter | BR-29, W12, NFR-FO-PERF-2 |
| `MentionService` | `mentionSuggest` → call MentionClient; on submit, validate each userId against group-access (BR-21) | W8, NFR-FO-REL-1 |
| `SearchIndexWriter` | Tokenize title (full) + body (capped ~50 terms, stop-word filtered, lowercased); produce term-items for inclusion in the create TransactWrite | D-FO-2, NFR-FO-PERF-5, ND-3=A |
| `RateLimiter` | Check/increment TTL counter item (`RATE#<memberId>#<action>#<hour>`); reject 429 if over limit | D-FO-3, NFR-FO-SEC-5 |
| `Sanitizer` | `nh3` strip raw HTML from Markdown body at write; length enforcement | D-FO-1, NFR-FO-SEC-1 |
| `MentionClient` | `GET /members?q=<prefix>&groupId=<groupId>` forwarding caller's JWT; **1.5s timeout, fail-soft** → empty list on failure | NFR-FO-REL-1, J1 |
| `EventPublisher` | Wrap domain events in the platform envelope; `PutEvents` after commit; retry/log on transient failure | NFR-FO-REL-2, BR-26 |
| `event_consumer` | Handle `GroupHardDeleted` (mark PURGING), `GroupSoftDeleted` (set hidden), `GroupRestored` (clear hidden); idempotent on envelope id | BR-27/28, NFR-FO-REL-3 |
| `sweep_handler` | Query PURGING items → BatchWriteItem delete in batches of 25 → iterate until empty or 10-min cap → alarm if items remain | NFR-FO-REL-6, ND-5=A |
| `Repository` | Single-table DynamoDB access (all access patterns below); idempotency table; parameterized expressions; transactional writes | NFR-FO-PERF-1..5 |
| `health` | Shallow + deep (own DynamoDB only — no downstream deep-check) | RESILIENCY-06 |

## Infrastructure logical components (mapped to AWS in Infrastructure Design)
| Logical | AWS resource |
|---|---|
| Forums store | DynamoDB `forums-<stage>` — **PITR enabled** (NFR-FO-DATA-1), SSE, on-demand, `Retain`; single table with base-table + GSIs (index shape at Infra Design) |
| Inverted-index (search) | **Sparse GSI** on the same table — PK=`TERM#<normalized_term>`, SK=`<postId>`. Items written inline with post creation. Derived, reconstructible (NFR-FO-DATA-3) |
| Idempotency store | DynamoDB `forums-idem-<stage>` (`eventId` hash key, TTL) |
| Domain events (publish) | EventBridge (platform bus) — `ForumPostCreated`, `ForumReplyCreated`, `MemberMentioned`, `PostReported`, `PostDeleted`, `ForumChannelDeleted` |
| Domain events (consume) | EventBridge rule matching `GroupHardDeleted`/`GroupSoftDeleted`/`GroupRestored` (Identity) → this Lambda; DLQ on the consumer |
| Nightly sweep trigger | EventBridge Scheduler — daily cron → this Lambda (sweep branch) |
| Cross-service reads | `execute-api:Invoke` scoped to Identity's `/members` endpoint for mentionSuggest (JWT-forwarded) |
| Compute | Lambda (python3.x, on-demand, 256MB/60s — single function, router pattern; ND-1=A) |
| Edge | API Gateway REST + Cognito authorizer (Unit 1, shared); routes under `/forums` (no api-edge regen) |
| Observability | CloudWatch logs/metrics (error rate/p95, MentionLookupTimeoutCount, SearchQueryLatency, SweepItemsPurged, SweepStallAlarm, RateLimitRejectCount, EventConsumerLagSeconds)/alarms |

## Data access patterns (single-table)
| Pattern | Mechanism | Used by |
|---|---|---|
| Browse forums by group | Query by `groupId` partition, filter `hidden=false` | W1 |
| Channel post-list (newest/pinned) | Query by `channelId` partition, sort by `createdAt` desc; pinned items sorted separately by `pinnedAt` desc, shown first | W2 |
| Thread (post + replies) | Get post by `postId`; Query replies by `postId` partition, sort `createdAt` asc | W3 |
| Caller's reaction on a target | Get by `(userId, targetType, targetId)` — O(1) lookup | W7 |
| Caller's follows | Query by `userId` partition (follow items) | W10 |
| Moderation queue | Query reports by `groupId` + `status=Open` (UGL→own group; CL→all) | W11 |
| Keyword search | Query inverted-index GSI by `TERM#<term>` → collect `postId` set; intersect multi-term; BatchGetItem results | W12 |
| Mention candidates | External call: Identity `GET /members?q=&groupId=` | W8 |
| Group lifecycle (hide/mark) | Query forums by `groupId`; batch update `hidden` or `status=PURGING` | W13 |
| Nightly purge | Query items with `status=PURGING` (forums/channels/posts/replies/reactions/follows/reports); BatchWriteItem delete 25 at a time | sweep |
| Rate-limit check | Get by `RATE#<memberId>#<action>#<hourWindow>` (TTL item) | RateLimiter |
| Idempotency check | Get by `eventId` on idempotency table (TTL) | event_consumer |

## Follow notification fan-out (J3)
Forums emits `ForumReplyCreated` / `ForumPostCreated` with a `followerIds[]` field derived from a Query on the post's/channel's follow items at emit time. At community scale (~hundreds of followers max per channel), this query is bounded and fits in a single EventBridge event (<256 KB). Notifications (Unit 10) owns the delivery fan-out to individual members — Forums does not send notifications directly.

**No blocking findings.** Judgement calls J1–J3 flagged in the plan for gate review.
