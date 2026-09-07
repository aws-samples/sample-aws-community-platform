# Domain Entities — Unit 4: Events

Technology-agnostic domain model. Physical single-table layout (pk/sk/GSI) is decided at NFR Design / Infrastructure Design, not here.

## Entity map

```
                        +---------------------+
                        |    EventSeries      |  (E2, recurrence rule only)
                        +----------+----------+
                                   | 1
                                   | materialises N occurrences (BR-R4)
                                   v N
+--------------+  N   +---------------------+  1   N  +------------------+
|     Rsvp     |<-----|       Event         |-------->|     Material     |
|     (E3)     |  1   |        (E1)         |         |       (E4)       |
+--------------+      +----------+----------+         +------------------+
                            |         |
                    1       |         |  1        N
      +---------------------+         +---------------> +------------------+
      v N                                              |   UploadLink     |
+------------------+                                   |      (E5)        |
|   Designation    |                                   +--------+---------+
|      (E6)        |                                            | 1
+------------------+                                            v N
                                                       +------------------+
+------------------+                                   |  UploadedFile    |
| TeamsReviewBatch |  (E7, transient, 1 per fetch)      |      (E8)        |
+------------------+                                   +------------------+
+------------------+
+------------------+
```

Text alternative: `EventSeries` (1) materialises many `Event` occurrences. Each `Event` has many `Rsvp`, many `Material`, many `UploadLink`, and many `Designation` rows. Each `UploadLink` accumulates many `UploadedFile` rows. `TeamsReviewBatch` is a transient per-fetch review set belonging to one `Event`.

---

## E1 — Event
The aggregate root. Owns its own lifecycle and is the authorization anchor for every child entity.

| Attribute | Type | Notes |
|---|---|---|
| `id` | string | `ev-<uuid>` |
| `title` | string | required, 1..200 |
| `description` | string | 0..5000; searchable by the Content Library (BR-CL2) |
| `type` | enum | Meetup · Workshop · Hackathon · Webinar · AMA / Fireside Chat · Conference · Presentation · Social (BR-V1) |
| `deliveryMode` | enum | Virtual · In-Person · Hybrid |
| `startsAt` | timestamp | ISO-8601 UTC, required |
| `durationMinutes` | integer | 1..1440, default 90 |
| `location` | string | physical address or virtual join URL (BR-V3) |
| `groupId` | string \| null | `null` ⇒ community-wide (BR-S1). Never the literal string "Community-wide" |
| `status` | enum | Upcoming · Completed · Cancelled (BR-L1) |
| `seriesId` | string \| null | set on occurrences of a recurring series |
| `seriesModified` | boolean | true once an occurrence is individually edited — excludes it from series-wide updates (BR-R6) |
| `createdBy` | string | Cognito `sub` of the creator. **Immutable** — carries edit/cancel rights across role changes (BR-A4) |
| `createdByRole` | enum | role at creation time, for audit only |
| `announceOnCreate` | boolean | "also post an announcement" (BR-X1) |
| `announceByEmail` | boolean | second toggle in the create modal |
| `teamsMeetingId` | string \| null | present only when the virtual join link is a Teams meeting |
| `rsvpYesCount` / `rsvpNoCount` | integer | denormalised counters, maintained transactionally with RSVP writes (BR-C3) |
| `attendedCount` | integer | denormalised, maintained on attendance apply |
| `completedAt` / `cancelledAt` | timestamp \| null | |
| `pointsAwarded` | integer \| null | total committed at completion; `null` until then (display-only, BR-P5) |
| `createdAt` / `updatedAt` | timestamp | |

**Not stored on Event**: per-event-type point values. Those are owned by Contributions & Scoring and read at request time (BR-P1).

## E2 — EventSeries
Holds the recurrence rule so occurrences stay independently editable.

| Attribute | Type | Notes |
|---|---|---|
| `id` | string | `evs-<uuid>` |
| `title`, `type`, `deliveryMode`, `durationMinutes`, `location`, `groupId` | — | template values applied to generated occurrences |
| `frequency` | enum | Daily · Weekly · Bi-weekly · Monthly (BR-R1) |
| `repeatsOn` | enum \| null | Mon..Sun; advisory for Weekly/Bi-weekly |
| `startDate` / `endDate` | date | both mandatory (BR-R1) |
| `occurrenceCount` | integer | materialised count, ≤ 104 (BR-R3) |
| `createdBy` | string | immutable |
| `status` | enum | Active · Ended |

A series is **not** an event: it never appears on the calendar, never accepts RSVPs, and shows `—` for RSVP/Attended in the list.

## E3 — Rsvp
One row per (event, member). Identity is the pair, so a re-RSVP updates in place.

| Attribute | Type | Notes |
|---|---|---|
| `eventId` / `userId` | string | composite identity |
| `response` | enum | `yes` · `no` — no "maybe", no waitlist (BR-C1) |
| `respondedAt` | timestamp | |
| `attended` | boolean | set only by an applied attendance action (BR-T4) |
| `attendedSource` | enum \| null | manual · csv · teams |
| `attendedAt` | timestamp \| null | |
| `pointsAwarded` | integer \| null | attendance points committed for this member |

Absence of a row means "no response" — the third state the mockup never shows explicitly.

## E4 — Material
Metadata for a file in S3 or an external link. Files are never proxied through the service.

| Attribute | Type | Notes |
|---|---|---|
| `id` | string | `mat-<uuid>` |
| `eventId` | string | parent |
| `kind` | enum | `file` · `link` |
| `name` | string | display title, unique per event (BR-M3) |
| `contentType` | enum | Slides · PDF · Doc · Recording · Link (BR-CL3, drives the Content Library filter and row icon) |
| `s3Key` | string \| null | `events/<eventId>/materials/<name>` for files |
| `url` | string \| null | external URL for links |
| `sizeBytes` | integer \| null | stamped by the S3 object-created consumer, never client-supplied (BR-M6) |
| `uploaded` | boolean | false until the S3 object exists (BR-M6) |
| `addedBy` | string | |
| `addedAt` | timestamp | |
| `postEvent` | boolean | true when added after `startsAt` — triggers the RSVP notification (BR-M5) |

## E5 — UploadLink
Event-scoped, write-only, expiring external upload link (US-2.21).

| Attribute | Type | Notes |
|---|---|---|
| `id` | string | `evul-<uuid>` |
| `eventId` | string | parent — the authorization anchor |
| `token` | string | 32-byte URL-safe random, **hashed at rest** (BR-U3) |
| `folderPrefix` | string | `events/<eventId>/uploads/` — system-derived, never client-chosen (BR-U1) |
| `expiresAt` | timestamp | createdAt + 7 · 14 · 30 · 90 days (BR-U2) |
| `maxSizeBytes` | integer \| null | optional cap, enforced at mint time (BR-U5) |
| `note` | string | shown to the recipient |
| `revoked` | boolean | revocation is checked at mint time (BR-U4) |
| `createdBy` / `createdByEmail` / `createdAt` | — | audited (US-1.13) |
| `uploadCount` | integer | maintained by the S3 object-created consumer |

## E6 — Designation
Presenter or organizer designation. Separate entity because eligibility differs per row and both feed different point awards.

| Attribute | Type | Notes |
|---|---|---|
| `eventId` / `userId` | string | composite identity |
| `kind` | enum | `presenter` · `organizer` |
| `roleAtDesignation` | enum | captured to explain ineligibility in the UI |
| `pointsEligible` | boolean | true only when the designee holds the **Member** role (BR-P3) |
| `designatedBy` / `designatedAt` | — | |

## E7 — TeamsReviewBatch (transient)
The reviewable result of one Teams fetch. Never awards anything on its own.

| Attribute | Type | Notes |
|---|---|---|
| `id` / `eventId` | string | |
| `fetchedAt` | timestamp | |
| `participants[]` | list | `{displayName, email, joinTime, leaveTime, durationMinutes, matchedUserId, matchStatus: matched\|unmatched, include: boolean}` |
| `appliedAt` | timestamp \| null | non-null ⇒ points committed; re-apply is rejected (BR-T5) |

Superseded by the next fetch; only the latest un-applied batch is retained per event.

## E8 — UploadedFile
A file that arrived through an UploadLink. Distinct from Material until a leader promotes it.

| Attribute | Type | Notes |
|---|---|---|
| `id` / `uploadLinkId` / `eventId` | string | |
| `name` / `sizeBytes` / `uploadedAt` | — | stamped by the S3 consumer |
| `promotedMaterialId` | string \| null | set when surfaced as an event Material (US-2.21) |

## E9 — ReminderSchedule — **REMOVED (2026-08-27)**
Held one due-record per pending reminder send. Deleted along with the reminder feature
(US-2.2/2.10 descoped): no `SCHED#` items are written any more, and nothing reads the ones
already in the table. The entity number is retained so E1–E8 references stay stable.

---

## Cross-service references (never owned here)
| Concept | Owner | How Events uses it |
|---|---|---|
| User identity, role, group membership | Unit 2 Identity & Access | JWT claims (`sub`, `role`, `led_group_id`, `member_group_ids`) — Q8=A |
| Group existence / soft-delete | Unit 2 | `GroupSoftDeleted` event ⇒ cancel that group's upcoming events (BR-X3) |
| Event-type point values | Unit 7 Contributions & Scoring | read-time REST fan-out, degrades to omitted (BR-P1) |
| Email + .ics delivery | Unit 10 Notifications | Events publishes; Notifications sends (BR-N2) |
| Announcement creation | Unit 9 Announcements | consumes `EventCreated` when real (BR-X1) |
| MS Teams enablement + credentials | Unit 11 Settings | read via the settings cache; disabled ⇒ 503 (BR-T1) |
