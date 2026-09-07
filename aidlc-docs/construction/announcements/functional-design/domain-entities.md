# Domain Entities & Schemas — Unit 9: Announcements

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Announcements
Technology-agnostic entity model for the service's owned data. Persisted in the service's single DynamoDB table (`announcements-<stage>`) plus an idempotency table. Companions: `business-logic-model.md`, `business-rules.md`, `frontend-components.md`. Shapes conform to `contracts/services/announcements/openapi.yaml` (to be amended per the additions below).

---

## E1 — Announcement (the definition — single source of truth)
One item per announcement. No per-user copies (BR-7). Denormalized display fields (BR-8) let panel reads avoid cross-service calls.

| Field | Type | Source | Notes |
|---|---|---|---|
| `id` | string | this service | Primary identifier |
| `title` | string | author (US-10.1) | Required, length-bounded (BR-16) |
| `body` | string (sanitized HTML) | author | Constrained HTML subset, sanitized on write (BR-14) |
| `target` | object `{scope: "community"｜"groups", groupIds: string[]}` | author / derived | UGL forced to `{groups,[ledGroupId]}` (BR-2); CL free choice |
| `authorId` | string | caller claim (`sub`) | Used for `view=mine` and edit/delete authz (BR-4) |
| `authorName` | string | denormalized at create (BR-8) | Directory lookup, fail-closed to email/id |
| `authorRoleLabel` | string | caller role claim | "Community Leader" / "User Group Leader" — no lookup |
| `source` | string | denormalized at create | "Community-wide" or the target group name(s) |
| `emailOptIn` | boolean | author (US-10.1) | Default false; drives `AnnouncementPublished` (BR-10) |
| `emailSent` | boolean | this service | Reflected in `view=mine` (mockup Email column); set when the publish path fires |
| `createdAt` | ISO-8601 | this service | Panel sorts newest-first |
| `expiresAt` | ISO-8601 | author / defaulted | **Mandatory** (BR-5): default `now+2d`, max `now+90d` |
| `ttl` | number (epoch s) | this service | = `expiresAt`; DynamoDB TTL attribute for storage reclaim (BR-6) |
| `groupHidden` | boolean | consumer (`GroupSoftDeleted`) | Excludes item from views; cleared on `GroupRestored` (BR-13) |
| `originEventId` | string｜null | `EventCreated` consumer | Set when auto-posted from an event (BR-17); null otherwise |

- **Status** (`Active`｜`Expired`) is **derived** (`expiresAt <= now`), never stored (US-10.3).
- **Key / access patterns** (index shape deferred to Infrastructure Design, per the Member-Profiles precedent):
  - Panel read (US-10.4): fetch active announcements by **audience scope** — `community` plus each of the caller's group ids (from claims). A community has few active announcements, so this is a small set held in a **warm-container cache**; a miss is a bounded query, never a scan.
  - Management list (US-10.3, `view=mine`): fetch by **`authorId`**.
  - Moderation (CL `scope=all`): paginated listing of all active announcements.
  - `GroupSoftDeleted`/`GroupRestored` (BR-13): fetch announcements targeting a given group id.
  - Flagged for Infrastructure Design: a GSI on audience-scope (sort `createdAt` desc) and a GSI on `authorId`; multi-group targeting representation (list attribute vs per-group index rows). Not blocking Functional Design.

## E2 — Consumed-event idempotency log
Not a business entity — the standard idempotency table (`announcements-idem-<stage>`, `eventId` hash key with TTL) dedupes `EventCreated`/`GroupSoftDeleted`/`GroupRestored` before they mutate/create E1 (BR-15). Same pattern as Identity & Access and Member Profiles.

## E3 — Published event: `AnnouncementPublished`
New schema file to add: `contracts/services/announcements/published-events/AnnouncementPublished.v1.json` (wrapped in the platform envelope). Emitted on create and on qualifying edits (BR-10).

| Field | Notes |
|---|---|
| `announcementId` | = E1.id |
| `title` | for the email subject/body |
| `bodyPreview` | short plain-text/sanitized snippet for email |
| `target` | `{scope, groupIds}` — Notifications resolves recipients from this |
| `authorName`, `source` | for email rendering |
| `emailOptIn` | Notifications sends email only if true |
| `expiresAt` | so a delayed email is suppressed if already expired |

## E4 — Consumed event shapes (not owned)
Read-only inputs; documented for the consumer logic.

| Event | Owner | Fields used | Effect |
|---|---|---|---|
| `EventCreated` | Events (Unit 4) | `eventId, title, groupId, announce, announceByEmail, createdBy, startsAt` | If `announce` → auto-post (BR-17); `originEventId=eventId` |
| `GroupSoftDeleted` | Identity (Unit 2) | `groupId` | Set `groupHidden=true` on that group's announcements (BR-13) |
| `GroupRestored` | Identity (Unit 2) | `groupId` | Clear `groupHidden` (BR-13) |

## Contract amendments (`contracts/services/announcements/openapi.yaml` → v2.0.0)
Reflecting the design; mostly additive, one removal. All under the already-routed `/announcements` base path (no `gen_api_edge`/api-edge regeneration).
- **`Announcement` schema** gains: `body, target{scope,groupIds}, authorId, authorName, authorRoleLabel, source, emailOptIn, emailSent, createdAt, expiresAt, status` (`active` retained; `status` is the derived Active/Expired label).
- **`createAnnouncement`** request body: `title` (required), `body`, `target{scope,groupIds}`, `expiresAt` (optional — server defaults/clamps), `emailOptIn`. (Replaces the flat `audience: string` with the structured `target`; `audience` kept as a read-only computed label on responses for backward-compatible display.)
- **`editAnnouncement`** request body: `title, body, target, expiresAt`.
- **`listAnnouncements`** gains query params: `view` (`panel`｜`mine`, default `panel`), and for CL moderation `scope=all`; `AnnList.items[]` uses the extended `Announcement`.
- **`dismissAnnouncement` (`POST /announcements/{id}/dismiss`) is REMOVED** — dismissal is client-side only (BR-11). It was mock-only with no real consumer; the frontend switches to `localStorage` (see frontend-components.md). Recorded as an intentional contract reduction.
- New event schema file `AnnouncementPublished.v1.json` (E3).

## Consistency notes
- Permission-matrix scopes used: CL `create/global` + `delete/global`; UGL `create/group` + `delete/own`; Member `view/global` + `dismiss/own` (the `dismiss` permission now maps to a purely client-side action — no server op — but the matrix entry is left as-is; no matrix change required). Administrator has no announcement entries → 403 everywhere (BR-3).
- `unit-of-work.md` updated 2026-08-07: Unit 9 **Owns: Announcements table** (Dismissals table removed); **Consumes** now includes `EventCreated`.
