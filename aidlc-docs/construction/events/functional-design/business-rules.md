# Business Rules — Unit 4: Events

Prefixed by area: **A**uthorization · **S**cope/visibility · **L**ifecycle · **V**alidation · **R**ecurrence · **C**RSVP · **T**attendance · **P**oints · **M**aterials · **U**pload links · **CL** Content Library · **N**otifications · **X** cross-service. Every rule is enforced server-side and fails closed; UI enforcement is a convenience only.

## Authorization (A)

| # | Rule | Source |
|---|---|---|
| BR-A1 | **Administrators have no event permissions.** Every `/events*` operation returns `403` for role `Administrator` — including read/browse. The only Administrator involvement is configuring the MS Teams integration, which lives in Settings, not here. | Permission matrix (no event entries under Administrator); US-2.1/2.6/2.9/2.13/2.15/2.20 |
| BR-A2 | Community Leaders may create events for **any** group and community-wide (`create event` scope=global). | US-2.1 |
| BR-A3 | User Group Leaders may create events **only** for their led group (`scope=group`). A UGL create with `groupId != led_group_id`, or with `groupId = null` (community-wide), is `403`. | US-2.1 |
| BR-A4 | **Manage rights are the union of creator-ownership and group-leadership**, evaluated per event for edit, cancel, complete, materials, RSVP list, attendance, designations, and upload links: permitted if `principal.sub == event.createdBy` **OR** (`principal.role == UserGroupLeader` AND `event.groupId == principal.led_group_id`). | US-2.4/2.5/2.15/2.21 |
| BR-A5 | **Creator rights survive role change, including demotion to Member.** Because BR-A4's first branch keys on the immutable `createdBy`, a demoted creator retains edit/cancel/manage on events they created. This is the one place a Member-role principal passes a leader-only check. | US-2.4 explicit; US-1.4 role-change semantics |
| BR-A6 | Members, Community Leaders, and User Group Leaders may RSVP. Administrators may not. | US-2.6 |
| BR-A7 | Any principal who can **view** an event can download/open its materials. RSVP is not a precondition. | US-2.15/2.14 |
| BR-A8 | Authorization is evaluated **after** the event is loaded, and a principal who cannot view an event receives `404`, not `403`, so event existence is not disclosed outside its scope. | SECURITY-08 fail-closed; IDOR guard |

## Scope and visibility (S)

| # | Rule |
|---|---|
| BR-S1 | `groupId = null` means community-wide. The string "Community-wide" is a display label only and is never persisted. |
| BR-S2 | **Visibility**: Community Leader sees all events. User Group Leader sees `groupId == led_group_id` plus community-wide. Member sees `groupId ∈ member_group_ids` plus community-wide. Administrator sees none (BR-A1). |
| BR-S3 | Group membership comes from the **JWT claims** (`member_group_ids`, `led_group_id`). A membership change takes effect on the caller's next token refresh — accepted staleness, consistent with every other real service. |
| BR-S4 | Visibility filtering is applied in the data query, not after serialisation, so pagination counts and cursors are correct for the caller. |
| BR-S5 | The calendar, the events list, and the Content Library all apply the identical BR-S2 scope. There is no view that widens visibility. |

## Lifecycle (L)

| # | Rule |
|---|---|
| BR-L1 | Only two transitions exist: `Upcoming → Completed` and `Upcoming → Cancelled`. Every other transition is `409`, including Completed → Cancelled, Cancelled → Completed, and any transition out of a terminal state. |
| BR-L2 | An event may be marked Completed **only after `startsAt` has passed**. A future-dated complete is `400`. |
| BR-L3 | Any applied attendance action (manual mark, CSV import, Teams apply) transitions the event to Completed automatically if it is still Upcoming. |
| BR-L4 | Completion may occur with **zero** attendance recorded. |
| BR-L5 | Cancellation never deletes. Cancelled events remain visible under the Cancelled filter with a Cancelled badge, and keep their RSVP history. |
| BR-L6 | Editing is permitted only while `status == Upcoming` and `startsAt` is in the future. Editing a Completed or Cancelled event is `409`. |
| BR-L7 | Cancelling an event bumps `icsSequence` and publishes `EventCancelled`, which drives the `METHOD:CANCEL` invite to `yes` RSVPs (BR-N5). |

## Validation (V)

| # | Rule |
|---|---|
| BR-V1 | `type` must be one of the eight enumerated event types; `deliveryMode` one of Virtual, In-Person, Hybrid. Unknown values are `400` — no silent coercion. |
| BR-V2 | `title` 1..200 chars after trim; `description` ≤ 5000; `durationMinutes` integer 1..1440. |
| BR-V3 | `location` is required and carries the join URL for Virtual/Hybrid and the address for In-Person. For Virtual/Hybrid a URL must be `https://` — `http://` and non-URL values are rejected. |
| BR-V4 | `startsAt` must parse as ISO-8601 and, on create, must be in the future. |
| BR-V5 | `groupId`, when supplied, must be a group the principal is entitled to target (BR-A2/A3). Events does not verify group existence — Identity owns that; a non-existent group simply yields an event nobody can see, and `GroupSoftDeleted` handling (BR-X3) covers the removal case. |
| BR-V6 | All free-text fields are stored as-is and **escaped at render time**, never sanitised on write (no HTML is ever generated server-side by this service). |
| BR-V7 | `limit` on any paged listing is an integer 1..200; anything else is `400`. An unparseable `cursor` is `400`, never a silent full-page reset. |

## Recurrence (R)

| # | Rule |
|---|---|
| BR-R1 | A recurring series requires **all three** of `startDate`, `endDate`, `frequency`. Any missing ⇒ `400`. `endDate` must be ≥ `startDate`. |
| BR-R2 | `frequency ∈ {Daily, Weekly, Bi-weekly, Monthly}`. `repeatsOn` is advisory for Weekly/Bi-weekly and ignored for Daily/Monthly. |
| BR-R3 | All occurrences are **materialised at create time**, capped at **104**. Exceeding the cap is `400` asking the creator to shorten the range or reduce frequency — never a silent truncation. |
| BR-R4 | Each occurrence is a full `Event` with its own id, RSVPs, materials, and attendance, linked by `seriesId`. Occurrences are individually editable and cancellable with no effect on the series or its siblings. |
| BR-R5 | The series itself accepts no RSVPs, never appears on the calendar, and reports `—` for RSVP/Attended. |
| BR-R6 | `Edit series` updates the rule and propagates to **future occurrences that have not been individually edited** (`seriesModified == false` AND `startsAt > now`). Past occurrences and individually-edited ones are never overwritten. Editing an occurrence sets `seriesModified = true`. |
| BR-R7 | Cancelling the series cancels its future un-cancelled occurrences; already-completed occurrences are untouched. |

## RSVP (C)

| # | Rule |
|---|---|
| BR-C1 | `response ∈ {yes, no}` only. No "maybe", no waitlist, no capacity limit. |
| BR-C2 | RSVP is changeable any number of times until `startsAt`; after that, and for non-Upcoming events, RSVP is `409`. |
| BR-C3 | RSVP is idempotent per member: the same response twice is a no-op success and does not double-count. Counters are updated in the same transaction as the RSVP row so they cannot drift. |
| BR-C4 | `yes → no` publishes a cancellation-invite event so the .ics `METHOD:CANCEL` removes the entry from the member's calendar. `no → yes` publishes a fresh invite. |
| BR-C5 | RSVP counts are visible to the event creator, group leaders, and attendees; the per-member RSVP **list** is restricted to BR-A4 managers. |
| BR-C6 | RSVP has no effect on points. Points require confirmed attendance (BR-P2). |

## Attendance (T)

| # | Rule |
|---|---|
| BR-T1 | Teams attendance requires the integration to be **enabled in Settings**. Disabled ⇒ `503 NOT_CONFIGURED`, and the SPA hides the MS Teams tab. |
| BR-T2 | Teams fetch is available only for events whose delivery mode is Virtual or Hybrid and that carry a `teamsMeetingId`. |
| BR-T3 | Teams participants are matched to members **by email**, case-insensitively. Unmatched participants are reported and earn nothing. |
| BR-T4 | **A fetch never awards anything.** Attendance is committed, and points published, only when the manager applies the reviewed batch. Rows with `include == false` are excluded. |
| BR-T5 | A batch may be applied once. Re-applying the same batch is `409`; a fresh fetch supersedes the previous un-applied batch. |
| BR-T6 | Manual attendance may only mark members who **have an RSVP row** for the event, or emails resolvable to member accounts via CSV import. |
| BR-T7 | CSV import is **CSV-only** (no xlsx — the SheetJS dependency carries unpatched high-severity CVEs and was removed from this repo deliberately). Import returns a per-row report of matched and unmatched emails; unmatched rows are errors, not silent skips. |
| BR-T8 | Attendance is idempotent per member: marking an already-attended member again does not re-award points. |
| BR-T9 | Applying attendance publishes one `AttendanceRecorded` event per confirmed member, and transitions the event to Completed (BR-L3). |

## Points (P)

| # | Rule |
|---|---|
| BR-P1 | Events **never stores or computes point values.** Per-event-type attendance and delivery values are read at request time from Contributions & Scoring via a parallel, timeout-bounded fan-out. On failure or unknown value, the points field is **omitted** from the response and the UI hides the tag — a scoring outage never blocks browsing, RSVP, or attendance. |
| BR-P2 | Attendance points are awarded to members whose attendance is **confirmed and applied** — never on RSVP. |
| BR-P3 | **Only designees holding the Member role earn.** Administrators, Community Leaders, and User Group Leaders may be designated as presenters or organizers but are `pointsEligible = false`. The UI shows the ineligibility inline at designation time. **Extended 2026-08-06 (change request)**: (a) presenters may also be **external** — a free-text name, not a portal user — stored with `external = true` and **never** points-eligible; organizers cannot be external. (b) The designee's role is resolved by a **server-side lookup at designation time** (directory fan-out, caller's own JWT); if the role cannot be verified the designation is stored but marked NOT eligible ("role unverified" — fail-closed for points, since a wrong award is not revocable while a missed one is fixed by re-designating). |
| BR-P4 | Presenters earn **delivery** points (`EventDelivered`); organizers earn **organize** points (`EventOrganized`). Both are published when the event reaches Completed, by either route (attendance apply or manual complete). |
| BR-P5 | Events records `pointsAwarded` for display only. The authoritative ledger lives in Contributions & Scoring; a discrepancy is resolved in favour of Contributions. |
| BR-P6 | Point-award events are published **after** the state write commits, and carry a stable idempotency key (`eventId + userId + kind`) so a consumer retry cannot double-award. |

## Materials (M)

| # | Rule |
|---|---|
| BR-M1 | Materials may be added, replaced, or removed at any time, before or after the event, including on Completed events. Cancelled events accept no new materials. |
| BR-M2 | Managing materials follows BR-A4 exactly. Administrators cannot manage materials. |
| BR-M3 | `name` is unique per event; a duplicate is `409`. |
| BR-M4 | Files upload **direct to S3** via a short-lived presigned PUT minted per upload; bytes never pass through the service. Allowed types: PDF, PPT/PPTX, DOC/DOCX, XLS/XLSX, PNG/JPG, MP4. Max **500 MB**. Extension and declared size are validated **before** the URL is minted. |
| BR-M5 | A material added after `startsAt` is `postEvent = true` and publishes `MaterialsAdded`, which Notifications turns into an email to `yes` RSVPs. Pre-event materials do not notify. |
| BR-M6 | `uploaded`, `sizeBytes`, and `uploadedAt` are written **only** by the S3 object-created consumer, never from the client. A material whose object never arrives stays `uploaded = false` and is excluded from the Content Library. |
| BR-M7 | Removing a material deletes the S3 object first and fails closed: if the object delete fails, the metadata row remains, so no orphaned object is ever left without an owning record. |
| BR-M8 | Downloads are served as fresh short-lived presigned GET URLs, generated on demand and never stored. |

## Upload links (U)

| # | Rule |
|---|---|
| BR-U1 | The folder prefix is **system-derived** (`events/<eventId>/uploads/`). The bucket is the pre-existing private community bucket; leaders never choose either. |
| BR-U2 | Expiry is one of 7, 14, 30, or 90 days and is enforced **server-side at mint time**. An expired link mints nothing. |
| BR-U3 | The token is 32 bytes of URL-safe randomness, stored **hashed**, and compared in constant time. The plaintext token is returned exactly once, at creation. |
| BR-U4 | Revocation is immediate for all future mints. Already-issued presigned URLs remain valid for their (short) remaining life — the same bounded-exposure trade-off approved for US-8.13. |
| BR-U5 | Uploads are **write-only**: the public endpoint mints single-object presigned PUTs and offers no list, read, or delete. This resolves the mockup's self-contradiction in favour of the stated security constraint. `maxSizeBytes`, when set, is enforced in the presigned policy. |
| BR-U6 | Only BR-A4 managers may view or download uploaded files, from inside the event's Materials tab. Deleting a link does not delete already-uploaded files. |
| BR-U7 | Every create and revoke is audited with the actor, event, and link id. |
| BR-U8 | The public upload endpoint is unauthenticated by design and therefore rate-limited per token, and returns an opaque `404` for unknown, expired, or revoked tokens — no distinction is leaked. |

## Content Library (CL)

| # | Rule |
|---|---|
| BR-CL1 | Only materials belonging to **Completed** events with at least one `uploaded` material appear. Upcoming, Cancelled, and material-less events never appear. |
| BR-CL2 | Search is **keyword-only** (case-insensitive substring) over material name + parent event title + parent event description. No semantic search, no media transcription. |
| BR-CL3 | Filters are content type (Slides, PDF, Doc, Recording, Link) and user group. Both are exact matches and combine with the keyword. |
| BR-CL4 | **Search-first**: no results are returned until the caller submits a query or a filter. An empty request returns an empty result set with a prompt, not the whole corpus. |
| BR-CL5 | Visibility mirrors BR-S2 exactly. Administrators are excluded (BR-A1). |
| BR-CL6 | Results are cursor-paginated, newest event first. |

## Notifications and scheduling (N)

| # | Rule |
|---|---|
| BR-N1 | ~~Reminder lead time is one of 1 hour, 24 hours, 48 hours, or 1 week.~~ **WITHDRAWN 2026-08-27** — reminders removed (US-2.2/2.10 descoped). |
| BR-N2 | **Events renders the .ics and publishes; Notifications delivers.** Events never calls SES. Until Notifications is real, published events accumulate and no email is sent — the state is correct, delivery is pending. |
| BR-N3 | ~~Reminders go to `yes` RSVPs only.~~ **WITHDRAWN 2026-08-27** — reminders removed. The `yes`-RSVP-only audience rule survives for invites and updates under BR-N5. |
| BR-N4 | ~~Cancelling an event, disabling its reminder, or moving `startsAt` marks pending schedule records Skipped.~~ **WITHDRAWN 2026-08-27** — there are no schedule records any more. Cancellation still bumps `icsSequence` and publishes a `METHOD:CANCEL` invite (BR-N5), which is what removes the entry from the member's calendar. |
| BR-N5 | An edit to a published event publishes an invite-update so an updated .ics reaches `yes` RSVPs; a cancellation publishes a `METHOD:CANCEL` invite. |
| BR-N6 | `GET /events/{id}/ics` returns the invite synchronously for the mockup's Download .ics button, subject to normal view authorization. |

## Cross-service (X)

| # | Rule |
|---|---|
| BR-X1 | `announceOnCreate` is recorded on the event and surfaced in the published `EventCreated` payload. Announcements (Unit 9) creates the announcement when it becomes real; Events makes no synchronous call. |
| BR-X2 | Every published event uses the platform event envelope with a correlation id propagated from the request. |
| BR-X3 | On `GroupSoftDeleted`, all **Upcoming** events scoped to that group are cancelled (BR-L7 semantics, including notifications). Completed and already-Cancelled events are untouched. Handling is idempotent on the event id. |
| BR-X4 | Event consumption is idempotent via the shared idempotency store: a redelivered event is acknowledged without re-processing. |
| BR-X5 | Every outbound cross-service read is individually fault-isolated with its own timeout; a downstream failure degrades that section of the response only, never the whole request. |
