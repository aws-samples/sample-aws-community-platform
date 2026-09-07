# NFR Design Plan — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Member Profiles & Directory
Translates `nfr-requirements.md`/`tech-stack-decisions.md` into concrete patterns and logical components, following the same resolved-from-context approach used at Functional Design and NFR Requirements (no blocking open questions — the NFR Requirements stage already made the key calls; this stage makes them concrete).

## Steps
- [x] 1. Analyze NFR requirements (criticality STANDARD, parallel fan-out + per-call timeout as the defining pattern, no Cognito/SES/Secrets footprint, degrade-path contract-test requirement)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (resolved from context below — no blocking open questions)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (N/A — no open questions)
- [x] 6. Generate NFR design artifacts (nfr-design-patterns.md, logical-components.md)
- [x] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update state

## Questions analysis → resolved from existing artifacts (no blocking questions)

| # | Area | Resolution source | Decision |
|---|---|---|---|
| Q1 | Fan-out orchestration shape | NFR-MP-PERF-2/3 (parallel, per-call timeout); tech-stack-decisions.md (`ThreadPoolExecutor` + `urllib3`) | A single `FanOutClient` component issues all downstream calls for a given request via `ThreadPoolExecutor.map` with a per-call timeout; each call wrapped in try/except returning `None`/empty on any failure (timeout, 5xx, connection error) rather than raising. The calling domain service (`ProfileService`/`ActivityService`) merges whatever came back — never blocks on a single failed call beyond its own timeout. |
| Q2 | Circuit-breaker scope | NFR-MP-SEC-6 (alert on elevated fan-out failure rate); tech-stack-decisions.md ("skip-on-recent-failure guard, not a full library") | **In-process, per-warm-container, per-downstream-service short-circuit**: after N consecutive failures to a given downstream service within a warm Lambda container, skip calling it for a short cool-down window (returns empty immediately instead of waiting out another timeout). This is a lightweight optimization (avoids wasting the per-call timeout budget repeatedly during a known outage), not a distributed circuit breaker — state resets on cold start, which is acceptable since it's an optimization, not a correctness requirement. |
| Q3 | Event-consumer idempotency mechanics | NFR-MP-REL-3; Identity & Access precedent (idempotency table, dedup by `eventId`) | Reused verbatim: `member-profiles-idem-<stage>` table, hash key `eventId`, TTL cleanup, same `IdempotencyStore` convention module as Identity & Access. Each of the 6 consumed event types checks-then-writes the idempotency record before applying its mutation to the profile record. |
| Q4 | Search delegation + degrade implementation | NFR requirements Q4 (Scale) + BR-6b (keyword fallback) | `DirectoryQuery` component branches on a `SETTINGS_ENABLE_SEMANTIC_SEARCH` flag (read from Settings, cached per warm container with a short TTL to avoid a Settings call on every request): **on** → delegate `q` to Search service via the same `FanOutClient` pattern (still time-boxed; on failure, falls back to keyword match rather than erroring); **off** → keyword match directly, no Search call attempted. |
| Q5 | Consumer-lag observability | NFR-MP-SEC-6 (alert on sustained lag) | Each consumed event's processing timestamp is compared against the event's own timestamp (from the platform envelope); the delta is emitted as a CloudWatch EMF metric (`EventConsumerLagSeconds`) per event type. An alarm on p99 lag exceeding a threshold (e.g. 15 minutes, per NFR) signals a stuck consumer — operational signal, not a correctness gate (profile data is stale, not wrong, during lag). |
| Q6 | Health check scope | NFR-MP-REL-2 (shallow + deep DynamoDB-only, no Cognito/SES) | Deep health check verifies only this service's own DynamoDB table reachability (`describe_table` or a cheap `GetItem` on a sentinel key) — deliberately does **not** deep-check downstream services (Contributions/Events/Forums/Certifications/Search), since those are expected-to-degrade dependencies, not hard requirements for this service to report itself healthy. |
| Q7 | Data access pattern (no GSI yet) | domain-entities.md E1 (scan+filter, GSI deferred); NFR-MP-SCALE-1 | `browseDirectory` implemented as a `Scan` with `FilterExpression` on `role`/`status`/`groupId` membership (array-contains-style check on `groups[].groupId`) for the no-`q` path. This is explicitly documented as the Infrastructure Design's first-look-at item if load testing regresses — not re-litigated here, just carried forward as a known, accepted tech-debt item. |

**Design decisions above are flagged for user review at the stage gate — override any and I will revise.**
