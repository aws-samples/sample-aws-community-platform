# Logical Components — Unit 9: Announcements

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Announcements
Logical decomposition (technology-agnostic roles → concrete Python modules at Code Generation). Companion: `nfr-design-patterns.md`.

## Component map
```
API Gateway (Cognito authorizer)              EventBridge rule (EventCreated, GroupSoftDeleted/Restored)
        │ proxy event                                  │
        ▼                                              ▼
┌──────────────────────────┐                 ┌────────────────────────────┐
│ handler (router)         │                 │ event_consumer              │
│  global_handler wrapper  │                 │ (idempotent, per-type)      │
└───────────┬──────────────┘                 └───────────┬─────────────────┘
            │                                             │
   ┌────────┼───────────────┐                            │ (auto-post reuses create)
   ▼        ▼               ▼                            ▼
validation  authz     AnnouncementService ───────────────┘
                          │        │        │
                          │        │        └── Sanitizer (nh3, sanitize-on-write)
                          │        └── DirectoryClient (author/group name, 1.5s fail-closed)
                          │
              ┌───────────┼───────────────┐
              ▼           ▼               ▼
        PanelQuery   Repository     EventPublisher
        (view=panel) (single-table  (AnnouncementPublished)
              │        + idem)
              ▼
        ActiveSetCache (30s warm-container)
```

## Components
| Component | Responsibility | Realizes NFR |
|---|---|---|
| `handler` (router) | Match route → operation; build `Principal`; `global_handler` fail-closed wrapper | SECURITY-08/15 |
| `validation` (`_conventions/validation.py`) | `title`/`target`/`expiresAt`/`view`/`scope` type-length-format-enum checks; expiry clamp (2d/90d) | NFR-AN-SEC-5 |
| `authz` (`_conventions/authz.py`) | Load matrix; `authorize()`; UGL target-forced-to-led-group; author-only edit; CL moderation delete; Administrator denied incl. reads; IDOR guard | NFR-AN-SEC-3/4 |
| `AnnouncementService` | create/edit/delete/list orchestration; expiry defaulting/clamp; denormalization; publish | US-10.1/10.2/10.3, BR-1..8 |
| `Sanitizer` | `nh3` sanitize-on-write of the body to the allow-list HTML subset | NFR-AN-SEC-1 |
| `DirectoryClient` | Author name (`GET /members/{id}`) + group name (`GET /groups/{id}`), JWT-forwarded, **1.5s timeout fail-closed** | NFR-AN-REL-1 |
| `PanelQuery` | `view=panel` — resolve caller audience from claims; filter active set by membership+expiry+`groupHidden`; newest-first | US-10.4; NFR-AN-PERF-1 |
| `ActiveSetCache` | Per-warm-container cache (30s TTL) of the active-announcement set; miss → one bounded query | NFR-AN-PERF-1 (J1) |
| `event_consumer` | `EventCreated` (announce→auto-post via create path), `GroupSoftDeleted`/`GroupRestored` (set/clear `groupHidden`); idempotent on envelope id | BR-13/15/17; NFR-AN-REL-3 |
| `EventPublisher` (`_conventions/envelope.py` + client) | Wrap `AnnouncementPublished` in the platform envelope; PutEvents after commit; retry/log | BR-10; NFR-AN-REL-2 |
| `Repository` | Single-table DynamoDB access (by audience-scope for panel, by `authorId` for `view=mine`, by group for hide/restore); idempotency table; parameterized expressions; TTL attribute | NFR-AN-PERF-3, NFR-AN-DATA-3 |
| `health` | Shallow + deep (own DynamoDB only — no downstream deep-check) | RESILIENCY-06 |

## Infrastructure logical components (mapped to AWS in Infrastructure Design)
| Logical | AWS resource |
|---|---|
| Announcement store | DynamoDB `announcements-<stage>` — **PITR enabled** (NFR-AN-DATA-1), SSE, TTL on `expiresAt`, `Retain`; index shape (audience-scope + authorId) decided at Infra Design |
| Idempotency store | DynamoDB `announcements-idem-<stage>` (`eventId` hash key, TTL) |
| Domain events (publish) | EventBridge (platform bus) — `AnnouncementPublished` |
| Domain events (consume) | EventBridge rule matching `EventCreated` (Events) + `GroupSoftDeleted`/`GroupRestored` (Identity) → this Lambda; DLQ on the consumer |
| Cross-service reads | `execute-api:Invoke` scoped to Members/Groups read resources (JWT-forwarded) |
| Compute | Lambda (python3.x, on-demand — no provisioned concurrency) |
| Edge | API Gateway REST + Cognito authorizer (Unit 1, shared); routes under `/announcements` (no api-edge regen) |
| Observability | CloudWatch logs/metrics (error rate/p95, DirectoryLookupTimeoutCount, EventConsumerLagSeconds, PanelCacheMissRate, AutoPostCount)/alarms + X-Ray |
| Client dependency | `dompurify` in the SPA (NFR-AN-SEC-2) |

## Data access patterns
| Pattern | Mechanism |
|---|---|
| Panel (`view=panel`) | Load active set (cache or bounded query by audience scope: `community` + caller's group ids); in-memory filter by expiry + `groupHidden`; newest-first |
| Management (`view=mine`) | Query by `authorId`, paginated |
| Moderation (CL `scope=all`) | Paginated listing of active announcements |
| Hide/restore on group event | Query announcements targeting `groupId`; set/clear `groupHidden` |
| Get by id (edit/delete authz) | Direct get by `id`; verify `authorId`/CL right (IDOR guard) |
| Idempotency check | `pk=<envelopeId>` on the idempotency table (TTL) |

**No blocking findings.** Judgement calls J1–J3 flagged in the plan for gate review.
