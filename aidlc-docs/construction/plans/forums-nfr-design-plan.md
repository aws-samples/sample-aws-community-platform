# NFR Design Plan — Unit 5: Forums

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Forums · Criticality: STANDARD.
Inputs: `construction/forums/functional-design/*` (business-logic-model W1–W13, business-rules BR-1..30, domain-entities E1–E7, frontend-components) + `construction/forums/nfr-requirements/` (NFR-FO-PERF-1..5, SEC-1..9, REL-1..7, DATA-1..4, MAINT-1; tech-stack D-FO-1..6).

## Steps
- [x] 1. Analyze NFR requirements
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (below)
- [x] 4. Store plan
- [x] 5. Collect + analyze answers — ND-1..5 all = A (recommended). Brainstormed 2026-08-13. No ambiguity.
- [x] 6. Generate artifacts (`nfr-design-patterns.md`, `logical-components.md`)
- [x] 7. Present completion message
- [x] 8. Await approval — user approved 2026-08-13
- [x] 9. Record approval + update aidlc-state.md

---

## Design questions

Recommended option marked **(recommended)**. Answer after each `[Answer]:`.

### ND-1 — Lambda function topology
Forums has API routes (W1–W12), EventBridge consumers (W13 group-lifecycle), and a nightly purge sweep (Q6=C). How many Lambda functions?

A) **(recommended)** **One function, router branches** (API / EventBridge / Scheduler triggers all route to the same handler; router dispatches by event source). Matches Identity/Members/Settings/Announcements/Events. Shared code, single deployment, one cold-start surface.

B) Two functions: one for API+EventBridge, one for the nightly sweep (separate timeout/memory/IAM).

C) Three functions: API / EventBridge consumer / sweep.

[Answer]:

### ND-2 — Counter update strategy
Posts have `replyCount`, `reactionCounts`; channels have `postCount`, `lastActivityAt`. Options:

A) **(recommended)** **Inline transactional update** — the same TransactWriteItems that creates the post/reply/reaction also atomically increments/decrements the parent's counter. No Stream consumer, no eventual lag, counters always consistent. At community scale (single-digit write concurrency per target) contention is negligible.

B) Stream-maintained — a DynamoDB Streams consumer recalculates counters after the write. Eventually consistent; adds a consumer Lambda and short lag.

[Answer]:

### ND-3 — Search-index write: transactional or async?
When a post is created, ~58 term-items are written to the inverted-index GSI. These can be:

A) **(recommended)** **Inline within the create transaction** — a single TransactWriteItems (post item + counter update + up to 100 items). At ~58 terms + 2 other items = ~60, well within the 100-item TransactWrite limit. All-or-nothing: search index is immediately consistent. If a write fails, the post isn't created (no orphaned index).

B) **Post-write async** — create the post transactionally (post + counter), then write search-index items in a separate batch. Slightly faster create latency; risk of orphaned index items on failure; search eventually consistent.

C) **Hybrid** — write index items inline for titles (always ≤10 items), body terms async/batched.

[Answer]:

### ND-4 — Denormalization of author name/role
Posts and replies store `authorName` + `authorRoleLabel` (FD Q4). Source:

A) **(recommended)** **From JWT claims at write time** — `authorRoleLabel` = role claim directly; `authorName` = a display-name claim (if carried in the token). Zero cross-service call on the write path. If no display name in the token, fail-closed to `sub` (member id).

B) **One-time Identity/Members lookup at write** — call `GET /members/{id}` like Announcements' DirectoryClient (1.5s timeout, fail-closed to id). Gets a richer name (first+last) but adds latency + a dependency on every post/reply.

[Answer]:

### ND-5 — Nightly sweep scope per invocation
The sweep Lambda runs on a schedule and purges PURGING forums' content. At community scale, the largest cascade is ~5k posts + descendants (~25k items total). Approach:

A) **(recommended)** **Single invocation, batched loop** — the sweep Lambda queries all PURGING items, deletes in batches of 25 (BatchWriteItem), iterates until empty or a configurable time-cap (e.g., 10 minutes of the 15-min Lambda limit). If items remain after the cap, alarm fires + next nightly run picks up. No self-re-invoke.

B) **Paginated self-re-invoke** — process one page per invocation, re-invoke itself if more pages remain. Avoids long-running single invocation.

[Answer]:

---

## Proposed judgement calls (resolved from precedent, flagged for review)
| Ref | Call | Rationale |
|---|---|---|
| J1 | Mention autocomplete latency: 1.5s timeout mirrors other units' DirectoryClient; no caching of candidates (membership changes frequently enough that a cache would need invalidation logic). | Pattern from Events/Announcements. At community scale, the Identity endpoint responds in <200ms typical. |
| J2 | Reaction replace is a 3-item TransactWrite (remove old reaction + add new reaction + update 2 counter fields on target). Atomic, no intermediate state. | Counter integrity is transactional; no eventual-consistency window for reaction counts. |
| J3 | Follow notifications: Forums emits `ForumReplyCreated`/`ForumPostCreated` with a `followerIds[]` field (derived from a Query on follows). Notifications delivers. At community scale (~hundreds of followers max), this query + field is bounded. | Avoids a separate fan-out worker. Notifications owns the delivery fan-out. |
