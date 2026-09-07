# Frontend Components — Unit 4: Events

Derived directly from the 9 Events mockups. The current `EventsPage.tsx` / `EventDetailPage.tsx` are thin mock-era scaffolds (single generic table, `FormModal` for create, no role shaping, no manage screen); both are rebuilt to mockup fidelity, following the component conventions already shipped for Units 2, 3, and 11 (`DataTable` server mode, `useDebounced`, dedicated modals over generic `FormModal`, always-rendered page shell with a skeleton rather than a full-page loading gate).

## Route and navigation map

| Route | Component | Personas | Notes |
|---|---|---|---|
| `/events` | `EventsPage` | CL, UGL, Member | Role-shaped: table for leaders, card grid for members. Tabs: Manage/Browse Events · Content Library |
| `/events/calendar` | `EventCalendarPage` | CL, UGL, Member | Month grid; CL gets the group filter, others do not |
| `/events/:id` | `EventDetailPage` | Member (read + RSVP) | Two-column summary + RSVP/calendar panels |
| `/events/:id/manage` | `EventManagePage` | BR-A4 managers | Stat cards + 4 tabs |

Administrators get **no** Events nav item and are blocked at the route guard (BR-A1), matching every mockup.

## Component hierarchy

```
EventsPage
├── EventsTabs (Manage|Browse · Content Library)
├── LeaderEventsList              (CL, UGL)
│   ├── EventsToolbar             (search, status/type/group filters, Rows, ColumnSettings)
│   ├── DataTable (server mode, cursor pagination)
│   │   └── SeriesRow → OccurrenceRow[]   (expand/collapse, closes G20)
│   └── EventModal                (create/edit, recurrence sub-panel)
├── MemberEventsBrowser           (Member)
│   ├── StatusTabs (Upcoming|Completed|Cancelled)
│   ├── EventFilters (search, type, mode, group)
│   └── EventCard[]  + EmptyState
└── ContentLibraryTab             (all three personas)
    ├── ContentLibraryFilters (keyword, type, group, Search button)
    ├── ContentResultRow[]
    └── ContentPager (top + bottom)

EventDetailPage
├── EventSummaryCard (badges, field grid, PresentersSection, MaterialsList)
├── RsvpPanel (Going / Not going, counts, points tag)
└── AddToCalendarPanel (Download .ics)

EventManagePage
├── EventStatCards ×5
└── Tabs
    ├── AttendanceTab (table, Mark attended, Upload CSV, Mark Completed)
    ├── RsvpListTab (table + Export CSV)
    ├── MaterialsTab
    │   ├── MaterialsCard (upload file / add link / download / replace / remove)
    │   └── UploadLinksCard (create / copy / revoke / view files)
    ├── TeamsTab (review table, include toggles, Apply & Award Points, Re-fetch)
    └── DesignationsTab (presenters + organizers pickers — new, closes G17)
```

## Component specifications

### `EventsPage`
Props: `{ role: Role }`. State: `tab`, and the child list state. Renders the header actions from the mockup — `📆 Calendar view` and `＋ Create Event` (leaders only). Heading text is role-shaped: `Events` for CL/Member, `Events — <group name>` for UGL.

### `LeaderEventsList`
- Columns: **Event**, **Type**, **Scope** (CL only — UGL's mockup omits it), **Date**, **RSVP / Attended**, **Status**, actions.
- Status badges: `Upcoming` blue, `Recurring` purple, `Completed` green, `Cancelled` red.
- Row actions by row type: upcoming → `Edit` · `Manage`; series → `Edit series`; occurrence → `Edit` · `Manage` · `Cancel`; completed → `View`; cancelled → none.
- Series rows are collapsible with a real `▾`/`▸` control; occurrences load with the page and indent under their parent (G20).
- `Cancel` and `Cancel Event` both raise a confirmation dialog stating that RSVPs are notified and the event stays visible as Cancelled (G16).
- Toolbar adds what the mockup lacks (G12): debounced keyword search, status/type/group selects, `Rows` page size, and cursor `Prev`/`Next` via `DataTable` server mode. `Showing X–Y of …` reflects the real page, not a hard-coded string (G1).
- `EmptyState` for both "no events yet" and "no events match your filters" (G19).

### `EventModal` (create + edit, replaces generic `FormModal`)
Fields, in mockup order: Title (required), Description, Event type (8 options), Delivery mode (3), Date & time, Duration (min) default 90, Location / virtual link, Scope, Recurring? (toggle revealing the recurrence panel), Presenters / facilitators (**member picker**, not free text), Also post an announcement (2 toggles).

- **Scope** is a select for CL (`Community-wide (all groups)` + groups) and a **readonly** field showing `<group> (your group)` for UGL, with the mockup's hint.
- Recurrence panel: Frequency (required), Repeats on, Start date (required), End date (required), plus the hint. Client-side validation mirrors BR-R1 and warns before the server's 104-occurrence rejection.
- Presenter picker shows an inline `no delivery points (leader)` note beside any non-Member designee (BR-P3, closing G9).
- Edit mode prefills every field and labels the scope of the edit — `Editing this occurrence` vs `Editing the whole series` (G20).

### `MemberEventsBrowser`
Card grid per the mockup: type badge + delivery badge, title, `📅 date · time (duration)`, `👥 group` or `🌐 Community-wide` with `🎤 presenter`, and a footer with either the RSVP action or the `✓ You RSVP'd` badge plus the `+N pts to attend` tag. The points tag is **omitted entirely** when the value is unavailable (BR-P1). Status tabs drive a server-side `status` filter rather than pre-rendered panels; search is debounced and server-side. Cancelled cards are non-navigable and show `Cancelled by organizer · attendees notified`. Event type label unified to `AMA / Fireside Chat` everywhere (G3).

### `EventDetailPage`
Badge row (type, delivery, status, group), title, description, field grid (`DATE & TIME`, `DURATION`, `DELIVERY`, `ORGANIZER`), presenters section with role badges and eligibility notes, and a materials list. Materials offer `Download` for files and `Open` for links, plus `View online` for previewable types so the detail page matches the Content Library's affordances (G6). Unavailable post-event material shows `Pending`. Status badge colour unified with the list (`Upcoming` = blue, G2).

`RsvpPanel`: `✓ Going` / `Not going`, Yes/No counters, points-to-attend tag, and the note that points follow confirmed attendance. `AddToCalendarPanel`: `Download .ics` calling `GET /events/{id}/ics`.

### `EventManagePage`
Five stat cards — RSVP'd Yes, Attended (with turnout percentage), Presenters, Organizers, Points Awarded — in a 5-column grid (fixing the mockup's `cols-4` holding five cards, G11). Header actions `Edit` and `Cancel Event` (confirmed).

- **AttendanceTab** — Member / RSVP / Attended / Points columns; `Mark attended` per row; `⬆ Upload CSV` opens `AttendanceImportModal` (CSV-only per BR-T7, with a downloadable template and a per-row matched/unmatched result report, mirroring `BulkImportModal` from Unit 2); `Mark Completed` confirms and is disabled for future-dated events (BR-L2).
- **RsvpListTab** — Member / Response with `Export CSV`.
- **MaterialsTab** — materials table (Material / Type / Size / Added / Actions) with a unified action set for both leader roles — `View` · `Download` · `Replace` · `Remove` (resolving G5) — plus `⬆ Upload file` (direct-to-S3 with progress) and `🔗 Add link`. Below it, `UploadLinksCard`: Upload folder / Expires / Created / Status / Actions, `🔗 Create upload link` modal (readonly folder, expiry 7/14/30/90, optional max size, note), one-time token display with copy, `Revoke` with the mockup's confirmation, and a files view for uploaded content. Revoke consistently flips the status badge to `Revoked` for both personas (G10).
- **TeamsTab** — review table (Teams participant / Email / Join / Leave / Duration / Matched member / Include / action), matched-vs-unmatched summary badges, `Match member…` picker for unmatched rows, `✓ Apply & Award Points`, `Re-fetch from Teams`, `Export CSV`. Hidden entirely when the integration is disabled (BR-T1).
- **DesignationsTab** *(new)* — presenter and organizer member pickers with per-designee eligibility notes; editable until completion (G17).

### `EventCalendarPage`
Month grid with `‹`/`›` navigation, Month/Week/List view switch (all three functional, G15), type-colour legend, and clickable chips that navigate to the event (G15). CL gets the group filter; UGL and Member do not, matching their mockups. Member's subtitle is corrected to match the controls actually present. Empty months show a `No events this month` state (G19).

### `ContentLibraryTab`
Search-first: renders `Enter a keyword and/or pick filters, then click Search to find content from past events.` until a search runs. Keyword input (Enter submits), content-type select (Slides/PDF/Doc/Recording/Link), group select scoped to the caller's visibility, `🔍 Search` button, and a populated result count (G13). Changing a select re-runs the search (G14). Result rows carry the file-type icon, material title, type badge, event name, group + date, event description, a link to the event, and both actions — `▶ Play online` for recordings, `🔗 Open online` for links, `👁 View online` otherwise, plus `⬇ Download`. Pagers render above and below with `Showing X–Y of N`, `‹ Prev`, `Page p of t`, `Next ›`.

## Form validation (client-side, mirroring server rules)

| Field | Rule |
|---|---|
| Title | required, ≤ 200 |
| Event type / Delivery mode | required, from the enumerated lists |
| Date & time | required; must be in the future on create |
| Duration | integer 1..1440 (numeric input, not free text — G25) |
| Location | required; `https://` URL for Virtual/Hybrid |
| Scope | required for CL; fixed for UGL |
| Recurrence | Frequency, Start date, End date all required when Recurring is on; end ≥ start; warn above 104 occurrences |
| Material name | required, unique per event |
| Upload file | allowed extension, ≤ 500 MB, checked before requesting the URL |
| Upload-link max size | numeric with a unit, parsed to bytes (G25) |
| Attendance CSV | must contain an `email` column |

## API integration

| Component | Calls |
|---|---|
| `LeaderEventsList` / `MemberEventsBrowser` | `GET /events` (filters, `limit`, `cursor`) |
| `EventModal` | `POST /events`, `POST /events/recurring`, `PUT /events/{id}` |
| Row actions | `DELETE /events/{id}`, `POST /events/{id}/complete` |
| `EventDetailPage` | `GET /events/{id}`, `GET /events/{id}/materials`, `POST /events/{id}/rsvp`, `GET /events/{id}/ics` |
| `EventManagePage` | `GET /events/{id}/rsvps`, `POST /events/{id}/attendance`, `POST /events/{id}/attendance/import`, `GET|POST /events/{id}/attendance/teams[/apply]`, `PUT /events/{id}/designations` |
| `MaterialsTab` | `POST /events/{id}/materials/upload-url`, `POST|PUT|DELETE /events/{id}/materials[/{mid}]` |
| `UploadLinksCard` | `GET|POST /events/{id}/upload-links`, `DELETE …/{lid}`, `GET …/{lid}/files` |
| `EventCalendarPage` | `GET /events/calendar` |
| `ContentLibraryTab` | `GET /events/content-library` |

## Shared components reused (no new primitives)
`DataTable` (server mode + column settings), `FormModal` (simple cases only), `Banner`, `EmptyState` / `ErrorState` / `Loading`, `Toggle`, `useApi`, `useDebounced`, `apiFetch`, `exportEndpointCsv`, `parseCsv`. New Events-specific components: `EventModal`, `EventCard`, `EventStatCards`, `SeriesRow`, `AttendanceImportModal`, `TeamsReviewTable`, `DesignationsPanel`, `UploadLinksCard`, `MemberPicker`, `CalendarGrid`, `ContentResultRow`.
