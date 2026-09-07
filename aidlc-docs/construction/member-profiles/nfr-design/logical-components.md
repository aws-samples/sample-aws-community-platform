# Logical Components — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Member Profiles & Directory
Logical decomposition of the service (technology-agnostic component roles → concrete Python modules in Code Generation). Companion: `nfr-design-patterns.md`.

## Component map
```
API Gateway (Cognito authorizer)                EventBridge rule (Identity's 6 events)
        │ proxy event                                   │
        ▼                                               ▼
┌──────────────────────────┐                  ┌────────────────────────┐
│ handler (router)         │                  │ event_consumer          │
│  global_handler wrapper  │                  │ (idempotent, per-type)  │
└───────────┬──────────────┘                  └───────────┬─────────────┘
            │                                              │
   ┌────────┼──────────────────┐                           │
   ▼        ▼                  ▼                           ▼
validation  authz         ProfileService ── ActivityService
                                │                │
                                ├── FanOutClient ─┼── Contributions/Events/Forums/Certifications (REST)
                                │                 └── Search (REST, conditional) ── keyword fallback
                                ▼
                          DirectoryQuery (browse/search)
                                │
                          Repository (single-table DynamoDB, scan+filter)
                                │
                          EventPublisher (EventBridge, MemberProfileUpserted)
```

## Components
| Component | Responsibility | Realizes NFR |
|---|---|---|
| `handler` (router) | Match API GW route → operation; build `Principal`; wrap in `global_handler` (fail-closed) | SECURITY-08/15 |
| `validation` (`_conventions/validation.py`) | Type/length/format checks on profile fields + query params; body cap; HTML rejection | SECURITY-05 |
| `authz` (`_conventions/authz.py`) | Load matrix; `authorize()` global/own scope; Admin/UGL/Member scoping on `getMember`/`memberActivity` | SECURITY-08; BR-4/13 |
| `ProfileService` | `getOwnProfile`/`updateOwnProfile`/`getMember` orchestration; merges profile record + fan-out rollup/basic-activity results | US-3.1/3.2/3.3 |
| `ActivityService` | `memberActivity` orchestration; leader-only scoping; date-range filtering; fuller fan-out (points + lifetime) | US-3.10 |
| `DirectoryQuery` | `browseDirectory`; branches on `q` presence + `EnableSemanticSearch`; applies role/group/cert filters; pagination | US-3.4/3.5; NFR-MP-SCALE-1/2 |
| `FanOutClient` | Parallel (`ThreadPoolExecutor`) per-call-timeout REST calls to Contributions/Events/Forums/Certifications/Search; per-container short-circuit on consecutive failures; never raises past its own boundary | NFR-MP-PERF-2/3; RESILIENCY-10; BR-9 |
| `event_consumer` | Handles the 6 consumed Identity event types; idempotency check-then-write; applies mutation to `MemberProfile` | US-3.1/3.3/3.4 (data freshness); NFR-MP-REL-3 |
| `Repository` | Single-table DynamoDB access (pk/sk); scan+filter for directory (no GSI yet — flagged for Infra Design); parameterized expressions | NFR-MP-SCALE-1; SECURITY-05 |
| `EventPublisher` (`_conventions/envelope.py` + events client) | Wrap `MemberProfileUpserted` in platform envelope; PutEvents after commit; retry/log | BR-7; RESILIENCY-10 |
| `SettingsCache` | Cached read of `EnableSemanticSearch` (short TTL per warm container) — avoids a 5th fan-out call on every `browseDirectory` request | NFR-MP-PERF (latency budget) |
| `health` | Shallow + deep (this service's own DynamoDB only — no downstream deep-check) | RESILIENCY-06 |

## Infrastructure logical components (mapped to AWS in Infrastructure Design)
| Logical | AWS resource |
|---|---|
| Profile store | DynamoDB `member-profiles-<stage>` (pk/sk) — no GSIs yet; candidate role/status GSI flagged for Infra Design if load testing regresses |
| Event-consumer idempotency store | DynamoDB `member-profiles-idem-<stage>` (`eventId` hash key, TTL) — same pattern as Identity & Access |
| Domain events (publish) | EventBridge (platform bus) — `MemberProfileUpserted` |
| Domain events (consume) | EventBridge rule matching Identity & Access's 6 published event types → this service's Lambda |
| Cross-service fan-out | `execute-api:Invoke` (same-account, same API Gateway) scoped to Contributions/Events/Forums/Certifications/Search resource ARNs — read-only |
| Compute | Lambda (python3.12, standard on-demand scaling — no provisioned concurrency) |
| Edge | API Gateway REST + Cognito authorizer (Unit 1, shared) |
| Observability | CloudWatch logs/metrics (fan-out failure/latency, consumer lag)/alarms + X-Ray |

## Data access patterns (single-table, no GSI yet)
| Pattern | Keys / mechanism |
|---|---|
| Get profile by id | `pk=MEMBER#<id>, sk=PROFILE` |
| Browse/search directory (no `q`) | `Scan` + `FilterExpression` on `role`/`status`/`groups[].groupId` — accepted tech-debt, GSI candidate at Infra Design |
| Browse/search directory (with `q`, semantic on) | Search service REST call for ranked IDs → batch-get / hydrate from this table |
| Browse/search directory (with `q`, semantic off) | `Scan` + `FilterExpression` with a `contains()` check against `firstName`/`lastName`/`email`/`skills` |
| Idempotency check | `pk=<eventId>` on the idempotency table (TTL) |

**No blocking findings.**
