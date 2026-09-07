# Logical Components — Unit 4: Events

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Events
Logical decomposition (component roles → concrete Python modules at Code Generation). Companion: `nfr-design-patterns.md`.

## Component map

```
API Gateway (Cognito)   API Gateway (/public, no auth)   EventBridge rule   S3 events   Scheduler
        |                        |                            |               |            |
        v                        v                            v               v            v
+---------------------------------------------------------------------------------------------+
|                              handler (router, global_handler wrapper)                        |
|   5 branches: http-authenticated | http-public | domain-event | s3-event | scheduled-sweep    |
+----+-------------+-------------+-------------+-------------+-------------+-------------------+
     |             |             |             |             |             |
     v             v             v             v             v             v
 validation      authz     EventService   RsvpService  AttendanceService  MaterialService
                              |               |               |
                              |               |               +-- ContentLibraryQuery
                              v               v               v
                       DesignationService  UploadLinkService  IcsRenderer
                              |               |
                              +-------+-------+-------+
                                      v               v
                              EventRepository    providers
                              (single table)     - S3Storage
                                                 - EventPublisher
                                                 - ContributionsClient (fan-out + cache)
                                                 - TeamsProvider (stub)
                                                 - SettingsCache
                                                 - IdempotencyStore
```

Text alternative: one router receives five kinds of input and dispatches to seven domain services. All services share one repository over a single DynamoDB table plus six providers for external concerns.

## Components

| Component | Responsibility | Realises |
|---|---|---|
| `handler` (router) | Match route → operation; build `Principal`; dispatch the five input branches; wrap everything in `global_handler` so nothing escapes | SECURITY-15, P-SEC-1 |
| `validation` | Enum, length, bound, URL-scheme, timestamp, recurrence-completeness, `limit`/`cursor`, upload type/size, CSV-shape checks | SECURITY-05, NFR-EV-SEC-3 |
| `authz` | Permission-matrix role check plus the single `require_manage()` function carrying the ownership-or-group rule and the demoted-creator rule | SECURITY-08, P-SEC-1, BR-A4/A5 |
| `EventService` | Create, edit, cancel, complete, get, list, calendar; two-phase series creation; scope filtering; lifecycle guards | BR-L*, BR-R*, BR-S*, P-REL-3, P-SCALE-2 |
| `RecurrenceExpander` | Expand (frequency, start, end) into occurrence timestamps; monthly end-of-month clamping; enforce the 104 cap | BR-R1..R3, P-SCALE-4 |
| `RsvpService` | Record/change RSVP transactionally with counters; list; CSV export; publish invite/cancellation intents | BR-C*, P-REL-6 |
| `AttendanceService` | Manual marking; CSV import with per-row report; Teams review batch and single apply; batched award publication; auto-completion | BR-T*, BR-P*, P-REL-7 |
| `MaterialService` | Material CRUD; presigned PUT/GET minting with pre-validation; scan-state transitions; post-event notification | BR-M*, P-SEC-3/4/5 |
| `ContentLibraryQuery` | Search-first keyword query over the sparse publishable-content index, scoped and cursor-paginated | BR-CL*, P-SCALE-3 |
| `DesignationService` | Set presenters/organizers; compute `pointsEligible` from role; surface ineligibility reasons | BR-P3/P4 |
| `UploadLinkService` | Create/revoke links; hash and verify tokens; enforce expiry, revocation and upload caps; mint per-file PUTs; list uploaded files | BR-U*, P-SEC-2 |
| `IcsRenderer` | RFC 5545 `VEVENT` output with `METHOD:REQUEST`/`CANCEL`, correct escaping and 75-octet line folding | BR-N2/N5/N6 |
| `EventRepository` | Single-table access; all listings as GSI queries with fetch-until-full loops; sparse index-key maintenance; parameterised expressions | P-SCALE-1/2/3 |
| `S3Storage` | Presigned PUT/GET brokering, object listing, deletion; fails closed | P-SEC-4/5 |
| `ContributionsClient` | Parallel timeout-bounded point-value read with short-circuit and a 60-second per-container cache | P-REL-1/2 |
| `TeamsProvider` | Interface plus stub adapter; real Graph adapter deferred | D1 |
| `SettingsCache` | Cached read of the Teams-enablement flag; fails closed to disabled | BR-T1 |
| `EventPublisher` | Platform-envelope wrapping, post-commit `PutEvents`, batches of 10, never raises to the caller | BR-X2, P-REL-7 |
| `IdempotencyStore` | Dedup by event id for consumed domain and S3 events | P-REL-4 |
| `group_event_consumer` | `GroupSoftDeleted` → cancel that group's Upcoming events, idempotently | BR-X3 |
| `s3_object_consumer` | Stamp `uploaded`/`sizeBytes`/`uploadedAt` and scan state; maintain the publishable-content index key; drop stale events | BR-M6, P-SEC-3 |
| `health` | Shallow, plus deep check against DynamoDB and S3 | RESILIENCY-06 |

## Single-table design

Table `events-<stage>`, keys `pk` / `sk`. One item collection per event, so the detail and manage screens read from one partition (P-PERF-2).

| Item | pk | sk |
|---|---|---|
| Event | `EVENT#<eventId>` | `META` |
| RSVP | `EVENT#<eventId>` | `RSVP#<userId>` |
| Material | `EVENT#<eventId>` | `MAT#<materialId>` |
| Designation | `EVENT#<eventId>` | `DESIG#<kind>#<userId>` |
| Upload link | `EVENT#<eventId>` | `UL#<linkId>` |
| Uploaded file | `EVENT#<eventId>` | `UF#<linkId>#<name>` |
| Teams batch | `EVENT#<eventId>` | `TEAMS#<fetchedAt>` |
| Series | `SERIES#<seriesId>` | `META` |
| Occurrence pointer | `SERIES#<seriesId>` | `OCC#<startsAt>#<eventId>` |
| Token pointer | `ULTOKEN#<sha256(token)>` | `META` |

The token pointer mirrors Settings' `FILEKEY` pointer: an O(1) lookup for a value that must never be found by scanning.

## Indexes

| Index | pk | sk | Serves | Sparse? |
|---|---|---|---|---|
| **GSI1** scope-date | `SCOPE#<groupId\|COMMUNITY>#<status>` | `startsAt` | `listEvents`, `calendar` — one query per visible scope, date-ordered (P-SCALE-2) | no |
| **GSI2** user-rsvp | `USER#<userId>` | `RSVP#<startsAt>#<eventId>` | a member's own RSVPs and attendance counts, including Member Profiles' activity fan-out | no |
| **GSI3** publishable-content | `CONTENT#<groupId\|COMMUNITY>` | `<eventStartsAt>#<materialId>` | Content Library — holds only `Clean` materials on `Completed` events | **yes** |
| ~~**GSI4** due-schedule~~ | `DUE#Pending` | `dueAt` | **UNUSED since 2026-08-27** — served the reminder sweep, which was removed. Still deployed (empty); the drop is staged as its own change. | **yes** |

Three live indexes, each earning its place: GSI1 makes every list a query, GSI2 avoids scanning for a member's own events, and GSI3 stays small by construction because its key attributes are removed the moment an item stops qualifying (P-SCALE-3, J2).

## Access patterns

| Pattern | Mechanism |
|---|---|
| Get event with children | Query `pk = EVENT#<id>`, optionally `begins_with(sk, …)` per section |
| List events for a caller | GSI1 partition walk over `[COMMUNITY, …caller's groups]` × status, fetch-until-full, opaque cursor |
| Calendar for a date range | Same as above with an `sk BETWEEN from AND to` condition |
| List a series' occurrences | Query `pk = SERIES#<id>`, `begins_with(sk, OCC#)` |
| My RSVPs / attendance counts | GSI2 query on `USER#<userId>` |
| Content Library search | GSI3 partition walk over the caller's scopes, newest first, keyword post-filter inside the page loop |
| Resolve an upload token | Get `pk = ULTOKEN#<sha256>` — never a scan |
| Idempotency check | Get by event id on the idempotency table (TTL) |

## Infrastructure logical components (mapped concretely at Infrastructure Design)

| Logical | AWS resource |
|---|---|
| Event store | DynamoDB `events-<stage>` — pk/sk + GSI1–GSI4, on-demand, PITR, Retain |
| Idempotency store | DynamoDB `events-idem-<stage>` — event id hash key, TTL |
| Materials and external uploads | S3 community bucket (Foundation-owned), prefixes `events/<eventId>/materials/` and `events/<eventId>/uploads/`, versioned, public access blocked |
| Malware scanning | GuardDuty Malware Protection for S3 on the community bucket (N1) |
| Object metadata events | EventBridge rule on S3 Object Created/Deleted → this service's Lambda (default bus, avoiding the Foundation circular dependency) |
| Domain events (publish) | EventBridge platform bus — 9 event types |
| Domain events (consume) | EventBridge rule matching `GroupSoftDeleted` |
| Cross-service read | `execute-api:Invoke` scoped to the single Contributions method, read-only |
| Compute | Lambda python3.12, on-demand, no provisioned concurrency (AC-3) |
| Edge (authenticated) | API Gateway REST + Cognito authorizer, `/events` + `{proxy+}` (already routed) |
| Edge (public) | API Gateway REST, no authorizer, `/public/event-uploads/{token}`, usage plan with per-token throttling (N3) |
| Observability | CloudWatch logs/metrics/alarms per P-OBS-1, X-Ray tracing |

## What this unit deliberately does not add
No SQS, no Step Functions, no ElastiCache, no distributed circuit breaker, no separate Lambdas for the sweep and the S3 consumer (J4), and no WAF (AC-1). Nothing in the approved NFRs at STANDARD criticality justifies them, and each would add deployment surface for a workload measured in single-digit invocations per minute.

**No blocking findings.**
