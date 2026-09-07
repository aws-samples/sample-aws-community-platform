# NFR Design Patterns — Unit 4: Events

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Events
Patterns that realise the approved NFRs. Companion: `logical-components.md`. Plan: `../../plans/events-nfr-design-plan.md`.

## Security patterns

### P-SEC-1 — Three-layer authorization (NFR-EV-SEC-1, SECURITY-08)
Every mutating and reading handler passes through three checks in a fixed order, and the order matters:

1. **Role check** against the frozen permission matrix (`Authorizer.authorize`). Administrators fail here on every `/events` operation.
2. **Load the resource**, then **visibility check**. If the event is outside the caller's scope (BR-S2), return `404` — not `403`. Existence is not disclosed across scope boundaries.
3. **Manage check** for mutations: `principal.sub == event.createdBy` **OR** (`role == UserGroupLeader` AND `event.groupId == principal.led_group_id`).

The manage check is deliberately *not* expressible in the permission matrix alone, because it is per-resource. It lives in one function (`require_manage(event, principal)`) called by every mutating operation, so there is exactly one place to audit — and exactly one place where the demoted-creator rule (BR-A5) is implemented.

### P-SEC-2 — Token authorization for the public write path (NFR-EV-SEC-2, N3)
The public upload endpoint carries no identity. Its entire authorization surface is:

```
token (32 random bytes, URL-safe)
  → sha256 → pointer item lookup  (O(1), no scan)
  → constant-time compare (hmac.compare_digest)
  → expiry check   → revoked check   → per-link upload-count check
  → mint ONE presigned PUT for ONE key under events/<eventId>/uploads/
```

Unknown, expired, and revoked tokens all return the same opaque `404`. The endpoint has no read, list, or delete capability, so a leaked token grants only the ability to add objects to one folder, bounded by expiry, revocation, the upload cap, and per-token throttling.

### P-SEC-3 — Malware-scan gate as a state machine (N1, J3, SECURITY-13)
```
upload  →  PendingScan  ──GuardDuty clean──▶  Clean      (listed, downloadable, indexed)
              │
              └──────────GuardDuty threat──▶  Quarantined (hidden from members,
                                              flagged to managers, not downloadable,
                                              excluded from the Content Library)
```
Three states, not a boolean, so "not yet scanned" (transient, shows *Scanning…*) is distinguishable from "failed scanning" (terminal, needs an operator signal). Only the `Clean` transition writes the Content Library index key (P-SCALE-3).

### P-SEC-4 — Presigned-URL brokering, never stored (NFR-EV-SEC-7)
Every upload and download URL is minted per request with a short TTL and returned directly to the caller. No URL is ever persisted. This is not stylistic: a presigned URL signed with a Lambda role's temporary credentials dies when the session token expires regardless of its stated expiry, and a stored URL cannot be revoked. Both were learned the hard way during the Settings rework and are avoided here by construction.

### P-SEC-5 — Fail-closed destructive ordering (NFR-EV-SEC-11)
Material removal deletes the S3 object **before** the metadata row and aborts the row delete if the object delete fails. The failure mode this prevents — an object with no owning record, invisible to the portal but still billable and still reachable by anyone holding an old URL — is worse than a row whose object is already gone, which the `uploaded` flag already models safely.

## Resilience patterns

### P-REL-1 — Parallel, timeout-bounded, individually-isolated fan-out (NFR-EV-REL-1)
Reused verbatim from Unit 3: `ThreadPoolExecutor`, per-call timeout of 300 ms, every call wrapped so it returns `None` rather than raising, plus a per-warm-container short-circuit after three consecutive failures with a 30-second cooldown. Events' only fan-out target is Contributions (point values), so the parallelism matters less than the isolation: a scoring outage must omit a field, never fail a page.

### P-REL-2 — Point-value cache (N6)
A per-warm-container dict keyed by event type with a 60-second TTL, wrapping the fan-out. A 25-row list renders from at most one downstream call. Staleness is bounded at a minute for values that change perhaps monthly. Cache misses degrade to P-REL-1's omit-the-field behaviour, so an outage during a cold start looks identical to an outage during a warm one.

### P-REL-3 — Two-phase series creation (J1, supersedes NFR-EV-REL-6's ordering)
`TransactWriteItems` caps at 100 items; the recurrence cap is 104. Atomicity is therefore impossible, so the design makes partial failure *legible* instead:

```
1. write SERIES record  status = Provisioning
2. write occurrences in batches of 25   (each a complete, valid Event)
3. update SERIES         status = Active, occurrenceCount = N
```
A crash between 1 and 3 leaves a `Provisioning` series with some occurrences. Occurrences are individually valid and independently visible, so nothing is lost or hidden; the series row renders as incomplete and offers retry or discard. This is strictly better than the originally-approved "occurrences first, series last", where the same crash produced orphans with no record explaining them.

### P-REL-4 — Idempotency everywhere a retry is possible
| Path | Guard |
|---|---|
| Consumed domain events (`GroupSoftDeleted`) | dedup by event id in the idempotency table |
| S3 object created/deleted | dedup by event id; stale events dropped by comparing timestamps |
| RSVP | identity is (event, user), so re-submitting the same response is a no-op |
| Attendance | `attended` already true ⇒ no re-award |
| Teams batch | `appliedAt != null` ⇒ `409` |
| Published point awards | stable key `eventId + userId + kind` so a consumer retry cannot double-award |

### P-REL-5 — Mark-before-emit on the reminder sweep — **WITHDRAWN 2026-08-27**
The pattern existed only to keep the reminder sweep idempotent. Reminders were removed (US-2.2/2.10 descoped), so there is no sweep and no schedule record to mark. Retained here as a record of the reasoning: for an at-most-once email side effect, marking before emitting is the correct direction to fail, and that argument still applies to any future scheduled sender.

### P-REL-6 — Transactional counters (NFR-EV-REL-5)
`rsvpYesCount` / `rsvpNoCount` are updated in the same `TransactWriteItems` as the RSVP row, so they cannot drift. The alternative — recomputing on read — would cost a full RSVP query on every list row.

### P-REL-7 — Batched event publication with a ceiling (N4)
Attendance apply chunks `PutEvents` into groups of 10 (the API maximum) and refuses above 1000 attendees with a `400` asking for a split import. An explicit ceiling with a clear message beats an opaque Lambda timeout at an unpredictable size.

## Scalability patterns

### P-SCALE-1 — No scans, anywhere
Every listing is a GSI query. This is a hard rule for this unit rather than a preference, because the same lesson has now been paid for twice in this codebase: the Member Directory shipped on a scan and had to be reworked under load, and the File Share listing shipped a creator query against an index that did not exist, producing a live 500.

### P-SCALE-2 — Scope partition walk with fetch-until-full pagination
A member's visible events span their groups plus community-wide, so the scope index is queried once per scope in a fixed order, accumulating until the page is full, with an opaque cursor carrying `{scopeIndex, lastKey}`. Identical in shape to the role walk already shipped for Admin Users. Post-filters (keyword, type, delivery mode) are applied inside the loop so a full page is still returned when filters are selective.

### P-SCALE-3 — Sparse indexes (J2)
Two indexes carry their key attribute only while the item qualifies:

- **Content Library index** — written when a material becomes `Clean` on a `Completed` event; removed if quarantined or if the event leaves `Completed`. The index therefore holds only publishable content.

### P-SCALE-4 — Bounded write bursts
Recurrence caps at 104 occurrences written in batches of 25. Attendance apply caps at 1000. Both limits are enforced before any write begins, so the service never starts work it cannot finish inside a Lambda invocation.

## Performance patterns

### P-PERF-1 — Denormalised counters on the event record
RSVP yes/no, attended count, presenter/organizer counts, and points-awarded are stored on the event, so a list row and the manage screen's five stat cards need no child queries. Maintained transactionally (P-REL-6) or at the single point of commit (attendance apply).

### P-PERF-2 — Item-collection reads for the detail screen
All of an event's children (RSVPs, materials, designations, upload links, uploaded files, Teams batch) live in one partition under distinguishable sort-key prefixes, so the detail and manage screens assemble from a single query per section, with no cross-partition joins.

### P-PERF-3 — Bytes never traverse compute
Uploads and downloads are direct-to-S3. A 500 MB material has no effect on function duration, memory, or the API Gateway payload limit.

## Observability patterns

### P-OBS-1 — Alarms on the paths that fail silently
| Alarm | Why it matters |
|---|---|
| Public-upload 4xx rate | token guessing against the portal's only unauthenticated write path |
| Authorization-failure rate | probing, or a genuine regression in P-SEC-1 |
| Malware detections | a threat reached the community bucket |
| Point-value fan-out failure rate | degrade path is working *and* hiding a dependency outage — invisible to users by design, so it must be visible operationally |
| S3-consumer lag | materials stuck in `PendingScan`, invisible with no error |

Every one of these is a condition where the system behaves correctly from the caller's perspective while something is wrong — which is precisely why they need alarms rather than error rates.

### P-OBS-2 — Correlation propagation and tracing
`X-Correlation-Id` flows from request through fan-out, published events, and the S3 consumer's stamping. X-Ray spans API → Lambda → Contributions → DynamoDB → S3.

## Degrade matrix

| Failing dependency | Behaviour | Caller sees |
|---|---|---|
| Contributions & Scoring | point fields omitted | pages render, no points tags |
| MS Teams (or disabled) | `503` on the Teams operations only | MS Teams tab hidden; manual attendance unaffected |
| Settings | Teams treated as disabled (fail closed) | as above |
| S3 | `502` on upload/download minting; metadata reads unaffected | event pages render, file actions fail with a clear message |
| GuardDuty scan pending or delayed | materials stay `PendingScan` | uploader sees *Scanning…*; members see nothing new |
| Notifications (not yet real) | events published and accumulate | state correct, no email sent |
| Announcements (not yet real) | `EventCreated` accumulates | event created, no announcement |
| EventBridge publish | logged, primary write already committed | operation succeeds; downstream award delayed |

## Compliance re-verification at this stage
Security: SECURITY-01/03/05/06/08/09/10/11/13/14/15 **compliant** by the patterns above; SECURITY-02/07 **compliant (inherited)**; SECURITY-04/12 **N/A** (JSON-only service, holds no credentials).
Resiliency: RESILIENCY-01/05/06/07/09/10/12 **compliant** by the patterns above; RESILIENCY-02/03/04/08/11/13/15 **compliant (inherited)** or N/A per platform decision; RESILIENCY-14 **deferred to Operations** with scenarios captured below.

**DR test scenarios captured for Operations** (RESILIENCY-14): restore the events table to a point in time and reconcile against S3 (exercises the restore-skew path, NFR-EV-AVAIL-5); fail Contributions and confirm every page still renders (P-REL-1); interrupt a 104-occurrence series create and confirm the `Provisioning` series is legible and resumable (P-REL-3); revoke an upload link and confirm minting stops immediately (P-SEC-2).

**No blocking security or resiliency findings.**
