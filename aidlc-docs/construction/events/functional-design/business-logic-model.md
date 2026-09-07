# Business Logic Model — Unit 4: Events

Technology-agnostic behaviour model for the Events service. Physical storage, IAM, and AWS resource choices are deliberately absent (NFR Design / Infrastructure Design own those).

## Decisions carried in from the plan (all confirmed 2026-08-05)

| # | Decision | Consequence |
|---|---|---|
| D1 | MS Teams via a **provider interface with a stub adapter** | Review → match → include/exclude → apply is fully real and testable; only the raw fetch is stubbed. Real Graph adapter is a later change request. |
| D2 | Events **renders the .ics and schedules**; Notifications delivers | No SES in this service. `GET /events/{id}/ics` works today. |
| D3 | Point values via **read-time fan-out** to Contributions | Events stores no point values; a scoring outage hides the tag rather than failing the page. |
| D4 | Recurring occurrences **materialised at create**, cap 104 | Every occurrence has real identity for RSVP/cancel/attendance. |
| D5 | Materials upload **direct-to-S3 in-browser** via presigned PUT | Bytes never traverse Lambda; metadata stamped by an S3 consumer. |
| D6 | US-2.21 built **as the story specifies** — public token endpoint, write-only, 7/14/30/90-day expiry | Deviates from Settings' US-8.13 slot model; resolves mockup gap G8 in favour of write-only. |
| D7 | Attendance import **CSV-only** | Consistent with Identity & Access; avoids the vulnerable xlsx dependency. |
| D8 | Group membership from **JWT claims** | No synchronous Identity dependency on the read path. |
| D9 | **Designations panel added** to the manage screen, organizers included | Closes gaps G17 and G9. |
| D10 | Content Library on a **materials GSI + fetch-until-full page loop** | Same pattern already proven for Member Directory and File Share. |
| D11 | Announcement toggle is **event-published**, not a REST call | No coupling to the still-mocked Announcements service. |
| D12 | **Close mockup gaps G12/G16/G19/G20** | Server-side pagination + filters, cancel confirmations, empty states, real series expand/collapse. |

---

## Logical components

```
+---------------------------------------------------------------+
|                     app router (OPERATIONS)                   |
|   HTTP proxy branch  |  EventBridge branch  |  S3-event branch |
|                      |  scheduler branch    |  public branch   |
+------+--------+------+----------+-----------+--------+---------+
       |        |                 |                    |
       v        v                 v                    v
+------------+ +--------------+ +----------------+ +-----------------+
|EventService| | RsvpService  | |AttendanceSvc   | |MaterialService  |
|(CRUD,      | |(respond,     | |(manual, csv,   | |(add/replace/    |
| series,    | | list, export,| | teams review,  | | remove, presign,|
| calendar,  | | counters)    | | apply, points) | | content library)|
| complete,  | +--------------+ +----------------+ +-----------------+
| cancel)    |
+------------+ +--------------+ +----------------+ +-----------------+
               |DesignationSvc| |UploadLinkSvc   | |IcsRenderer      |
               |(presenters,  | |(create, revoke,| |(.ics render for |
               | organizers,  | | public mint,   | | invites, US-2.8)|
               | eligibility) | | uploaded files)| +-----------------+
               +--------------+ +----------------+
                          |
+---------------------------------------------------------------+
|  EventRepository (single-table)  |  FanOutClient  |  Storage    |
|  IdempotencyStore | EventPublisher | TeamsProvider | Settings   |
+---------------------------------------------------------------+
```

Text alternative: a single router dispatches five input kinds (HTTP proxy, EventBridge domain events, S3 object events, scheduled sweep, unauthenticated public upload) to seven domain services, all sharing a repository, a cross-service fan-out client, an S3 broker, an idempotency store, an event publisher, a Teams provider, and a settings cache.

## Component responsibilities

**EventService** — create (single + series), edit, cancel, complete, get, list, calendar. Owns lifecycle transitions (BR-L1..L7), scope filtering (BR-S2), and series materialisation (BR-R3..R7). Enriches responses with point values via FanOutClient (BR-P1).

**RsvpService** — record/change RSVP with transactional counters (BR-C3), list RSVPs for managers, CSV export, and publishing invite/cancellation intents (BR-C4).

**AttendanceService** — manual marking, CSV bulk import with a per-row report (BR-T7), Teams fetch → review batch → apply (BR-T4/T5), point-award publication (BR-P4/P6), and automatic completion (BR-L3).

**MaterialService** — material CRUD, presigned PUT/GET minting with type and size validation (BR-M4), S3-consumer stamping (BR-M6), post-event notification (BR-M5), and the Content Library query (BR-CL1..CL6).

**DesignationService** — set/replace presenters and organizers, compute `pointsEligible` from the designee's role (BR-P3), and surface ineligibility reasons.

**UploadLinkService** — create/revoke event-scoped links (BR-U1..U8), mint per-upload presigned PUTs for the unauthenticated public endpoint, and list uploaded files for managers.

**IcsRenderer** (`ics.py`) — render the RFC 5545 invite body for `CalendarInviteDue` on RSVP transitions and for `GET /events/{id}/ics` (BR-N2, BR-N5, BR-N6). *`ReminderService` was removed on 2026-08-27 with US-2.2/2.10; only the .ics rendering it also owned survives.*

## Operations (17 contract operations + 8 additive)

| Operation | Method + path | Story | Authorization |
|---|---|---|---|
| `listEvents` | GET /events | 2.13 | any non-Admin; BR-S2 scope; filters `q`, `type`, `deliveryMode`, `status`, `groupId`, `from`, `to`, `limit`, `cursor` |
| `createEvent` | POST /events | 2.1, 2.2 | CL global / UGL own group (BR-A2/A3) |
| `createRecurring` | POST /events/recurring | 2.3 | as create; materialises ≤104 (BR-R3) |
| `calendar` | GET /events/calendar | 2.9 | any non-Admin; `from`/`to`/`groupId`/`type`/`deliveryMode` |
| `contentLibrary` | GET /events/content-library | 2.20 | any non-Admin; search-first (BR-CL4) |
| `getEvent` | GET /events/{id} | 2.14 | viewable by BR-S2, else 404 (BR-A8) |
| `editEvent` | PUT /events/{id} | 2.4 | BR-A4; Upcoming only (BR-L6) |
| `cancelEvent` | DELETE /events/{id} | 2.5 | BR-A4 |
| `completeEvent` | POST /events/{id}/complete | 2.19 | BR-A4; past-dated only (BR-L2) |
| `rsvpEvent` | POST /events/{id}/rsvp | 2.6, 2.8 | non-Admin viewers (BR-A6) |
| `listRsvps` | GET /events/{id}/rsvps | 2.7 | BR-A4 |
| `listMaterials` | GET /events/{id}/materials | 2.15 | any viewer (BR-A7) |
| `addMaterial` | POST /events/{id}/materials | 2.15 | BR-A4 |
| `recordAttendance` | POST /events/{id}/attendance | 2.16 | BR-A4 |
| `teamsAttendance` | GET /events/{id}/attendance/teams | 2.12 | BR-A4; 503 when disabled (BR-T1) |
| `setDesignations` | PUT /events/{id}/designations | 2.18 | BR-A4 |
| `createUploadLink` | POST /events/{id}/upload-links | 2.21 | BR-A4 |
| **+ additive** | | | |
| `getEventIcs` | GET /events/{id}/ics | 2.8 | any viewer (BR-N6) |
| `getMaterialUploadUrl` | POST /events/{id}/materials/upload-url | 2.15 | BR-A4 (BR-M4) |
| `replaceMaterial` / `removeMaterial` | PUT/DELETE /events/{id}/materials/{mid} | 2.15 | BR-A4 (BR-M7) |
| `applyTeamsAttendance` | POST /events/{id}/attendance/teams/apply | 2.12 | BR-A4 (BR-T4) |
| `importAttendanceCsv` | POST /events/{id}/attendance/import | 2.16 | BR-A4 (BR-T7) |
| `listUploadLinks` / `revokeUploadLink` | GET / DELETE /events/{id}/upload-links[/{lid}] | 2.21 | BR-A4 |
| `listUploadedFiles` | GET /events/{id}/upload-links/{lid}/files | 2.21 | BR-A4 (BR-U6) |
| `publicUploadMint` | POST /public/event-uploads/{token} | 2.21 | **unauthenticated**, token-gated, write-only (BR-U5/U8) |

All additive operations sit under existing base paths (`/events`, `/public`) already routed by `api-edge.yaml` with `{proxy+}`, so no API-edge regeneration is required. Contract amendments are additive: new operations plus new optional query parameters and response fields on existing ones.

## Key flows

**Create event (US-2.1/2.2)** — validate (BR-V1..V5) → authorize scope (BR-A2/A3) → persist Upcoming with immutable `createdBy` → publish `EventCreated` carrying the announcement intent (BR-X1) → return the event. Point values are attached on read, not stored.

**Create series (US-2.3)** — validate all three recurrence fields (BR-R1) → expand dates → reject over 104 (BR-R3) → persist the series plus every occurrence in batched writes → return the series with its occurrence count.

**RSVP (US-2.6/2.8)** — verify viewability and Upcoming (BR-C2) → upsert the RSVP row and adjust counters in one transaction (BR-C3) → publish an invite or cancellation intent on transition (BR-C4) → return updated counts.

**Record attendance (US-2.16/2.17/2.19)** — authorize (BR-A4) → resolve members (RSVP rows, or CSV emails with a per-row report, BR-T6/T7) → mark attended idempotently (BR-T8) → read the event type's point value (BR-P1) → publish one `AttendanceRecorded` per member with a stable idempotency key (BR-P6) → transition to Completed (BR-L3) → publish `EventDelivered`/`EventOrganized` for eligible designees (BR-P3/P4) → publish `EventCompleted`.

**Teams attendance (US-2.12)** — check enablement (BR-T1) and mode (BR-T2) → fetch via TeamsProvider (stub for now, D1) → match by email (BR-T3) → persist a review batch, awarding nothing (BR-T4) → manager adjusts matches and include flags → apply once (BR-T5) → same commit path as manual attendance.

**Materials (US-2.15)** — for files: validate type/size then mint a presigned PUT (BR-M4) → SPA uploads directly to S3 → the S3 object-created consumer stamps `uploaded`/`sizeBytes` (BR-M6) → if post-event, publish `MaterialsAdded` (BR-M5). For links: persist immediately with `kind = link`.

**Content Library (US-2.20)** — no query, no results (BR-CL4) → query the materials index scoped by BR-S2 and restricted to Completed events with uploaded materials (BR-CL1) → apply keyword and type/group filters inside a fetch-until-full page loop (D10) → return a cursor-paginated list.

**Event-scoped upload link (US-2.21)** — manager creates a link with an expiry choice; the plaintext token is returned once (BR-U3) → the external recipient opens the public page and requests an upload URL per file → the service validates token, expiry, revocation, and size, then mints a single-object presigned PUT (BR-U5) → the S3 consumer records the uploaded file → managers view/download from the Materials tab and may promote a file to a Material.

**Group soft-delete (US-1.17 → BR-X3)** — the EventBridge branch receives `GroupSoftDeleted`, checks idempotency (BR-X4), and cancels every Upcoming event scoped to that group with full cancellation semantics.

## Error semantics

| Condition | Status | Code |
|---|---|---|
| Unauthenticated | 401 | `UNAUTHORIZED` |
| Role or scope not permitted | 403 | `FORBIDDEN` |
| Event outside caller's visibility | 404 | `NOT_FOUND` (BR-A8) |
| Validation failure, bad `limit`/`cursor`, over recurrence cap | 400 | `VALIDATION_ERROR` |
| Illegal lifecycle transition, duplicate material name, re-applied batch | 409 | `CONFLICT` |
| Teams integration disabled, storage unconfigured | 503 | `NOT_CONFIGURED` |
| S3 or downstream write failure | 502 | `STORAGE_ERROR` |
| Point value unavailable | 200 | field omitted, never an error (BR-P1) |

## Published events

| Event | When | Primary consumer |
|---|---|---|
| `EventCreated` | on create (carries announcement intent) | Announcements (9), Analytics (8) |
| `EventUpdated` | on edit | Notifications (10) |
| `EventCancelled` | on cancel | Notifications (10), Analytics (8) |
| `EventCompleted` | on completion | Contributions (7), Analytics (8) |
| `AttendanceRecorded` | per confirmed attendee | Contributions (7) |
| `EventDelivered` | per eligible presenter at completion | Contributions (7) |
| `EventOrganized` | per eligible organizer at completion | Contributions (7) |
| `MaterialsAdded` | post-event material added | Notifications (10) |

## Story coverage

| Story | Where satisfied |
|---|---|
| US-2.1 | `createEvent`; BR-A2/A3, BR-V1..V5, BR-X1 |
| ~~US-2.2~~ | **REMOVED 2026-08-27** — reminders descoped |
| US-2.3 | `createRecurring`; BR-R1..R7 |
| US-2.4 | `editEvent`; BR-A4/A5, BR-L6, BR-N5 |
| US-2.5 | `cancelEvent`; BR-L5/L7 |
| US-2.6 | `rsvpEvent`; BR-C1..C6 |
| US-2.7 | `listRsvps` + CSV export; BR-C5 |
| US-2.8 | invite publication + `getEventIcs`; BR-N2/N5/N6 |
| US-2.9 | `calendar`; BR-S2/S5 |
| ~~US-2.10~~ | **REMOVED 2026-08-27** — reminders descoped |
| US-2.11 | Settings-owned toggle read through the settings cache; BR-T1 |
| US-2.12 | `teamsAttendance` + `applyTeamsAttendance`; BR-T1..T5, D1 |
| US-2.13 | `listEvents` with filters, search, pagination; BR-S2, D12 |
| US-2.14 | `getEvent` + `listMaterials`; BR-A7/A8 |
| US-2.15 | MaterialService; BR-M1..M8 |
| US-2.16 | `recordAttendance` + `importAttendanceCsv`; BR-T6..T9 |
| US-2.17 | fan-out point values; BR-P1/P2/P5 |
| US-2.18 | `setDesignations`; BR-P3/P4, D9 |
| US-2.19 | `completeEvent`; BR-L1..L4 |
| US-2.20 | `contentLibrary`; BR-CL1..CL6, D10 |
| US-2.21 | UploadLinkService + public mint; BR-U1..U8, D6 |

21 of 21 stories mapped.
