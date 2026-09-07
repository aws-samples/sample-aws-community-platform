# NFR Design Patterns — Unit 9: Announcements

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Announcements
How the NFR requirements are realized as concrete patterns. Companion: `logical-components.md`. Plan: `../../plans/announcements-nfr-design-plan.md`. Criticality STANDARD.

## Scalability patterns (the defining property)
- **Fan-out-on-read on a single definition (NFR-AN-PERF-4, BR-7)**: an announcement is exactly one item. Posting to a community-wide audience of 13k+ is **one write**; edit is one write; delete is one delete (removed for everyone immediately at the data layer). There is no per-user materialization and no write amplification anywhere in the unit — the deliberate rejection of the fan-out-on-write model considered during design.
- **Bounded, cacheable read set**: everything expires (mandatory ≤90d, default 2d), so the set of *active* announcements stays small (tens). The panel read filters that small set in memory rather than scanning per reader.
- **On-demand elasticity**: DynamoDB on-demand + standard Lambda concurrency absorb read spikes (all members hitting their landing page); reads scale horizontally by partition key. TTL (NFR-AN-DATA-3) keeps the table bounded over time so read/scan cost never grows.

## Performance patterns
- **Warm-container active-set cache (NFR-AN-PERF-1, Q2=A)**: `ActiveSetCache` holds the active-announcement set per warm Lambda container with a **30s TTL** (same pattern as Settings' `SettingsClient`). The panel read (`view=panel`) resolves audience from JWT claims and filters the cached set by membership + `expiresAt>now` + `not groupHidden` **in memory** — no DynamoDB round trip on a cache hit; a miss is one bounded query. Total added latency on the hot path is near-zero on a hit → p95 ≤ 500ms.
- **No provisioned concurrency (NFR-AN-PERF-2)**: no operation is on an interactive auth-critical path (unlike Identity's login); standard on-demand scaling suffices.
- **Single O(1) write path**: create/edit/delete touch one item; the only extra work on create/edit is the `DirectoryClient` lookup, which is time-boxed and fail-closed (below).
- **`view=mine` by author (NFR-AN-PERF-3)**: query by `authorId`, paginated; CL `scope=all` moderation listing paginated. Never an unbounded return.

## Resilience patterns
- **Create-time directory lookup: 1.5s timeout, fail-closed (NFR-AN-REL-1, RESILIENCY-10)**: `DirectoryClient` resolves author display name (`GET /members/{id}`) and group name(s) (`GET /groups/{id}`) forwarding the caller's JWT, each bounded at 1.5s. On timeout/5xx/connection error it returns nothing and the service stores `authorName=email/id`, `source=raw group id` — **the announcement still posts**. Authoring never blocks on the directory. (The tuned 1.5s value comes from the Events fan-out lesson: 300ms was too tight for NAT→API GW→Lambda.)
- **No synchronous dependency for the panel (NFR-AN-REL-2)**: the in-portal panel depends only on this service's own table/cache. `AnnouncementPublished` (for email) is at-least-once via EventBridge; if EventBridge/Notifications lag, email is delayed but the panel is unaffected — the announcement is already written.
- **Idempotent event consumption (NFR-AN-REL-3, BR-15)**: `event_consumer` checks-then-writes an idempotency record keyed on the envelope id (TTL cleanup) before acting, for all three consumed types (`EventCreated`, `GroupSoftDeleted`, `GroupRestored`). Redelivery never double-posts an auto-announcement or double-hides a group's announcements. Same mechanism as Identity/Members.
- **Graceful panel degrade (NFR-AN-REL-4)**: display fields are denormalized, so a directory outage at *read* time is irrelevant (nothing is looked up on read). A cache miss during a DynamoDB blip surfaces as a normal retried read, not a 5xx. `view=panel` never returns 5xx for a downstream issue.
- **No circuit breaker / bulkhead needed**: there is a single optional downstream call (the create-time lookup), not a multi-service read fan-out — the fail-closed timeout is sufficient; a circuit breaker would be over-engineering at STANDARD criticality.

## Security patterns
- **Inert Markdown at rest + sanitize-at-render (NFR-AN-SEC-1/2, SECURITY-05/11/13 — REVISED 2026-08-07)**: the body is **stored as Markdown** (inert; the server neither sanitizes nor executes it — no native `nh3` dependency). The **render boundary** is the sanitization point: the SPA renders with `markdown-it` (`html:false`, raw HTML disabled) then runs the output through **DOMPurify** before `dangerouslySetInnerHTML` in `AnnouncementPanel`. Non-browser consumers (Notifications email `bodyPreview`) render/escape themselves — flagged for Unit 10. (Supersedes the earlier server-side `nh3` sanitize-on-write pattern; dropped to avoid a native Lambda dependency + cross-platform wheel packaging.)
- **Fail-closed in-service authZ (NFR-AN-SEC-3/4, SECURITY-08)**: same `authz.py` convention — every handler builds a `Principal` from validated JWT claims and authorizes against the permission matrix before touching data. Create: CL(global)/UGL(group; **target forced to `ledGroupId`**). Edit: **author only**. Delete: author or **any CL** (moderation); UGL only own. `Administrator` denied on **every** op including list/panel. **IDOR guard**: edit/delete load the item and verify `authorId`==caller (or CL moderation right) before mutating — a bare id never authorizes.
- **Input validation + expiry clamp (NFR-AN-SEC-5)**: `validation.py` checks `title` (required, length-capped), `target` (`scope` enum; `groupIds` non-empty when `scope=groups`), `expiresAt` (default now+2d, clamp to now+90d), `view`/`scope` enums; all DynamoDB expressions parameterized, never string-built.
- **Least-privilege IAM (NFR-AN-SEC-6)**: execution role scoped to this service's own table (+PITR) + idempotency table (DynamoDB CRUD), EventBridge `PutEvents` for `AnnouncementPublished` + rule subscription to `EventCreated`/`GroupSoftDeleted`/`GroupRestored`, and `execute-api:Invoke` scoped to the Members/Groups read resources only. No wildcards. (Detailed at Infra Design.)
- **Rate limiting (NFR-AN-SEC-8, SECURITY-11)**: shared API Gateway throttling on all (authenticated) routes; no unauthenticated surface exists in this unit. In-service authz further bounds create to CL/UGL.
- **Fail-safe + no sensitive logging (NFR-AN-SEC-7, SECURITY-15)**: global handler catches unhandled exceptions → generic error envelope; body text and PII are never logged; correlation id on every log line.

## Observability patterns (RESILIENCY-05/07)
- **Three pillars**: structured logs + correlation ids; X-Ray spans API→Lambda→(DirectoryClient lookup)/(DynamoDB); CloudWatch EMF metrics — request error rate + p95 per operation, `DirectoryLookupTimeoutCount`, `EventConsumerLagSeconds` per consumed type, `PanelCacheMissRate`, `AutoPostCount`.
- **Alarms (NFR-AN-SEC-9)**: handler error rate, Lambda throttles, EventBridge consumer failures/DLQ, sustained event-consumer lag. Directory-timeout rate is informational (degrades gracefully) but alarmed if sustained (signals an Identity/Members outage).
- **Health (RESILIENCY-06)**: shallow (process up) + deep (own DynamoDB reachability only). Deliberately does **not** deep-check Members/Groups — those are expected-to-degrade, non-blocking dependencies.

## Resiliency test scenarios (captured for Operations — RESILIENCY-14)
| Scenario | Expected behavior |
|---|---|
| Members/Groups 5xx or timeout at create | Post succeeds; `authorName`=email/id, `source`=raw group id; `DirectoryLookupTimeoutCount` increments |
| Notifications/EventBridge lag | Email delayed; in-portal panel unaffected (announcement already written) |
| Duplicate/redelivered `EventCreated` | Idempotency dedupes on envelope id; auto-announcement created exactly once |
| `GroupSoftDeleted` then `GroupRestored` | Group's announcements hidden then restored; idempotent on redelivery |
| DynamoDB throttle (own table) | botocore backoff within Lambda timeout; alarm on sustained throttles |
| Panel read during a DynamoDB blip (cache cold) | Normal retried read; never a 5xx to the SPA |
| Expiry boundary | `expiresAt<=now` excluded from panel + count the instant it passes (read-time filter); TTL reclaims later |
| Region/AZ event | Managed multi-AZ absorbs AZ loss; region loss → Backup & Restore runbook + PITR restore (content non-reconstructible) |

## Compliance deltas (this stage)
All applicable SECURITY + RESILIENCY rules realized by the patterns above. SECURITY-04 **N/A** (JSON, not HTML). SECURITY-12 **N/A** (no credentials held). RESILIENCY-14 = scenarios captured (execution deferred to Operations); the degrade + sanitization + authz scenarios are also enforced directly as mandatory contract/unit tests (NFR-AN-MAINT-1). **No blocking findings.** Judgement calls J1–J3 (see plan) flagged for gate review.
