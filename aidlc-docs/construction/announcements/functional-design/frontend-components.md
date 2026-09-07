# Frontend Components — Unit 9: Announcements

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Announcements (Unit 15 SPA surface)
Component design for the announcements UI. Companions: `business-logic-model.md`, `business-rules.md`, `domain-entities.md`. Mockup references: `requirements/mockup/{leader,ugl}/announcements.html` (authoring/management) and `requirements/mockup/{member,leader,ugl}/dashboard.html` (the panel). Existing shipped code to rebuild: `frontend/src/features/pages.tsx` → `AnnouncementsPage`.

## Component map
```
AnnouncementsPage (route /announcements — CL & UGL only; management, view=mine)
├── AnnouncementTable (DataTable server-mode; columns vary by role)
└── AnnouncementModal (create + edit)
    ├── AudiencePicker (CL: community | multi-select groups · UGL: readonly "your group")
    ├── RichTextField (constrained toolbar; maps to sanitized-HTML body)
    ├── ExpiryField (required; default +2d, max +90d)
    └── EmailOptInToggle (default off)

AnnouncementPanel (embedded on landing pages: Member Home, CL/UGL analytics dashboards)
└── AnnouncementCard[] (title, meta line, rich-text body, ✕ dismiss)
```

## AnnouncementsPage (management — US-10.1/10.2/10.3)
- **Route/visibility**: `/announcements`, leaders only (`isLeaderRole`). Members have no management page (they only see the panel). Administrators never see the nav item.
- **Data**: `GET /announcements?view=mine` (CL may toggle a "All (moderation)" view → `view=mine&scope=all`). Uses the `useApi` + DataTable server-mode + cursor pattern already established (Directory/Admin Users).
- **Columns** (from mockups — differ by role, BR-12):
  - CL: Title · Audience · Created · Expiry · Email (Sent/No) · Status (Active/Expired badge) · actions (Edit·Delete).
  - UGL: Title · Created · Expiry · Email · Status · actions (no Audience column — always their group).
  - CL moderation footnote: "you can also delete any announcement (including group ones) for moderation." UGL footnote: "reaches all members of {group}, including co-leaders."
- **Actions**: Edit (author-only rows) opens `AnnouncementModal` in edit mode; Delete (author rows, plus any row in CL moderation view) → `DELETE /announcements/{id}`, confirm dialog, row disappears.

## AnnouncementModal (create + edit — US-10.1/10.2)
- **Fields**: Title (required); Message = `RichTextField` (B/I/link/list toolbar → constrained HTML, server re-sanitizes, BR-14); Audience = `AudiencePicker`; Expiry = `ExpiryField`; "Also send as email" = `EmailOptInToggle`.
- **AudiencePicker**:
  - CL: select `Community-wide (all members)` or `Selected user group(s)` → reveals a multi-select group toggle list (fed by `GET /groups`). Maps to `target {scope, groupIds}`.
  - UGL: a **readonly** field showing "{their group} (your group)" — no choice; the server derives the target from `ledGroupId` (BR-2). `session.ledGroupId` supplies the label without a round-trip.
- **ExpiryField**: date input, **required**; prefilled to today+2 days; rejects (client-side) dates beyond today+90 days with a hint "up to 90 days maximum"; server clamps regardless (BR-5).
- **Submit**: create → `POST /announcements`; edit → `PUT /announcements/{id}` with `{title, body, target, expiresAt}`. On success, refresh the table.

## AnnouncementPanel (recipient panel — US-10.4/10.5)
- **Placement**: rendered on Member Home (`member/dashboard.html`), the CL community analytics dashboard, and the UGL group analytics dashboard. Reuses the existing `.announce-*` CSS already in `frontend/src/styles/portal.css`.
- **Data**: `GET /announcements` (default `view=panel`) — the backend returns only announcements targeted to the caller, active and non-hidden, newest-first (BR-6/BR-12/BR-13). The frontend does **not** compute targeting.
- **Collapsed by default**: a card header `▸ 📣 Announcements (N)` where N = returned count (after localStorage-dismissal filtering); click to expand.
- **AnnouncementCard** meta line = `{source} · {authorName} ({authorRoleLabel}) · {createdAt}` with ` · expires {expiresAt}` appended when set (all fields come straight from the payload — no client lookups, BR-8). Body renders the sanitized HTML. A `✕` dismiss button per card.
- **Dismissal (client-side only, BR-11)**: dismissing adds the announcement `id` to a `localStorage` set (e.g., `announce.dismissed`); the panel filters these out on render and the header count reflects the filtered length. No API call. Dismissals persist per-browser and self-heal as announcements expire (dismissed ids for expired/absent announcements are pruned opportunistically).

## Integration points (backend endpoints)
| Component | Endpoint | Notes |
|---|---|---|
| AnnouncementsPage | `GET /announcements?view=mine[&scope=all]` | management/moderation list |
| AnnouncementModal (create) | `POST /announcements` | structured `target`, required `expiresAt`, `emailOptIn` |
| AnnouncementModal (edit) | `PUT /announcements/{id}` | author-only |
| Row delete | `DELETE /announcements/{id}` | author or CL-moderation |
| AudiencePicker (CL) | `GET /groups` | group multi-select options |
| AnnouncementPanel | `GET /announcements` (`view=panel`) | targeted, active, newest-first |
| Dismiss | *(none — localStorage)* | server `dismissAnnouncement` op removed |

## Changes from the shipped mock UI (`AnnouncementsPage` in pages.tsx)
- Replace the simple `FormModal` (title/body/audience only) with `AnnouncementModal` incl. AudiencePicker (multi-group for CL / readonly for UGL), required ExpiryField, and EmailOptInToggle.
- Management table gains Created/Expiry/Email/Status columns and role-conditional Audience column; move to server-mode pagination.
- Remove the member-facing "Dismiss" button from the management table; dismissal lives only on `AnnouncementPanel`.
- Switch dismissal from `POST /announcements/{id}/dismiss` (removed) to `localStorage`.
- Add `AnnouncementPanel` to the three landing pages (currently the mock dashboards render static cards).
