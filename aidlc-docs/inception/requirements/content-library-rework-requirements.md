# Content Library Rework — Requirements

**Feature**: Community Knowledge Hub (Content Library v2)
**Request Type**: Rework of existing feature
**Scope**: Multi-component (Events service, Contributions service, new Library service/module, frontend)
**Complexity**: Moderate-to-complex
**Date**: 2026-08-18

---

## Intent Analysis

The current Content Library is event-scoped — it automatically indexes clean materials from completed
events via a sparse DynamoDB GSI. The user wants to repurpose it as a curated, standalone community
knowledge hub (analogous to Amazon Highspot) where:
- Event materials flow in automatically
- Member-produced content (blogs, case studies, templates) can be highlighted via curator approval
- CL/UGL can add content directly

The existing implementation is to be **dropped and replaced** with a clean model.

---

## Functional Requirements

### FR-CL-1: Standalone Page
The Content Library shall be accessible as a standalone top-level page at `/content-library`,
visible in the main navigation for all authenticated non-Administrator users.

### FR-CL-2: Three Entry Paths

#### FR-CL-2a: Event Material Auto-Promotion (Path 1)
When an event is marked Completed, all Clean materials attached to that event shall automatically
be added to the Content Library as resources.
- `title` = material name
- `description` = auto-copied from the parent event's description
- `source` = `event-material`
- No curator action required

#### FR-CL-2b: Member Contribution Opt-In (Path 2)
When a CL or UGL approves a member contribution in the Contributions service, they shall see an
option "Add to Content Library". If selected, the contribution is added to the Library.
- Contribution points are awarded at the contribution approval step (existing behavior, unchanged)
- No additional points are awarded for Library entry
- `source` = `member-contribution`
- `submittedBy` = the member who submitted the contribution

#### FR-CL-2c: Curator Direct Add (Path 3)
A CL or UGL may add a resource directly to the Library without a submission or approval workflow.
- `source` = `curator-direct`
- `addedBy` = the CL/UGL who added it

### FR-CL-3: Mandatory Description
Every resource in the Library must have a `description` field. This field is mandatory across all
three entry paths and is the primary corpus for keyword search.
- For Path 1 (event material), description is auto-populated from the event description.
  Event description is now **mandatory** — an event cannot be marked Completed without a description.
  This is enforced at the Events service level (validation on the complete operation).
- For Path 2 and 3, the description must be entered by the curator at the time of adding

### FR-CL-4: Resource Data Model
Each resource in the Library shall carry the following fields:

| Field | Description |
|---|---|
| `id` | Unique resource identifier |
| `title` | Display name (material name / contribution title / curator-entered) |
| `description` | Mandatory. Primary search corpus. |
| `format` | Enum: PPT, Video, Link, Word |
| `topics` | Array of free-form tags (lowercase-normalized on write) |
| `source` | Enum: event-material, member-contribution, curator-direct |
| `scope` | Always COMMUNITY (community-wide; no group scoping) |
| `url` | For Link-type resources — the external URL |
| `s3Key` | For file-type resources (PPT, Video, Word) — S3 object key |
| `scanState` | PendingScan, Clean, Quarantined — for uploaded files only |
| `submittedBy` | userId of the original author/member (for attribution display) |
| `submittedByName` | Display name of the original author (denormalized at write) |
| `addedBy` | userId of the CL/UGL who added it to the Library |
| `addedAt` | ISO 8601 timestamp of Library entry |
| `eventId` | Parent event id (Path 1 only; null otherwise) |
| `eventTitle` | Parent event title (Path 1 only; denormalized) |

### FR-CL-5: Search and Filtering
The Content Library search page shall be search-first: no results are shown until the user
submits at least one keyword or filter.

**Supported filters** (all independent and combinable):
- **Keyword** (`q`): free-text search across `title` + `description` (case-insensitive substring)
- **Format** (`format`): PPT, Video, Link, Word
- **Topic** (`topic`): a single tag value (autocomplete input; matches exact lowercase tag)
- **Source** (`source`): event-material, member-contribution, curator-direct

Results are paginated with cursor-based pagination, page size 10.

### FR-CL-6: Topics — Free-Form Tags
Topics are free-form strings entered by curators. They are:
- Stored as lowercase (e.g., "Serverless" → stored as "serverless")
- Displayed as entered by the curator (display value stored separately or normalized on display)
- Used for filtering (exact match on the lowercase value)
- Discoverable via autocomplete — the add/edit form shows existing tags as suggestions as the
  user types

### FR-CL-7: Curation Operations (CL/UGL only)
CL and UGL roles may:
- Edit any resource in the Library (title, description, format, topics, url)
- Delete any resource from the Library
- Add resources directly (Path 3)
- Opt-in to Library during contribution approval (Path 2)

Members may view and download/open resources but may not edit or delete.

### FR-CL-8: File Handling and Scan Gate
For uploaded file resources (PPT, Video, Word):
- Files are uploaded directly to S3 via presigned PUT URL (same pattern as event materials)
- Files enter the Library in `PendingScan` state
- GuardDuty Malware Protection results transition the state to `Clean` or `Quarantined`
- Only `Clean` files are downloadable / shown with a download link
- Quarantined files remain in the Library record (visible to curators) but are not downloadable

### FR-CL-9: Attribution Display
Each resource card shall display the original author's name:
- Path 1: parent event name + event date
- Path 2: member's display name + "Community Contribution"
- Path 3: curator's display name + "Curated by"

### FR-CL-10: Administrator Exclusion
Administrators shall not have access to the Content Library (consistent with current platform
permission model). Any request from an Administrator role shall return 403.

### FR-CL-11: Remove Events Content Library Tab
The existing "Content Library" tab inside the Events detail/manage pages shall be removed.
The standalone `/content-library` page replaces this entirely.

---

## Non-Functional Requirements

### NFR-CL-PERF-1
Content Library search shall respond in p95 ≤ 1 second under normal load.
Search is keyword-filtered index query — never a DynamoDB Scan.

### NFR-CL-SEC-1
Only `Clean`-scanned files may be made available for download. Presigned GET URLs are
short-lived (same policy as event materials — DOWNLOAD_URL_SECONDS).

### NFR-CL-SEC-2
Edit and delete operations are restricted to CL and UGL roles. Member requests to these
operations return 403.

### NFR-CL-DATA-1
The Library data store shall have PITR enabled (resources are original records with no
upstream source of truth for reconstruction).

### NFR-CL-MAINT-1
The `description` field is mandatory at the data layer — not just the API layer. A missing
description is a validation error (400) on all write paths.

---

## What Is Being Removed (from existing implementation)

| Removed | Reason |
|---|---|
| GSI3 sparse index (`gsi3pk`, `gsi3sk`) on Events table | Replaced by dedicated Library index |
| `_apply_content_index()` / `refresh_content_index()` in repository.py | No longer needed |
| GuardDuty → Library auto-indexing pipeline | Replaced by GuardDuty → Library service pipeline |
| `ContentLibraryTab` component in `EventsPage.tsx` | Replaced by standalone `/content-library` page |
| `content_library()` method in `MaterialService` | Moved to new Library service |
| `GET /events/content-library` API route | Replaced by `GET /library` route |
| `contentLibrary` operationId in events OpenAPI contract | Removed |

---

## Constraints

- No changes to the Contributions points-award logic
- The existing event materials upload/scan pipeline remains intact for event-scoped materials
- Event description is now mandatory at the Events service level — enforced on the Complete
  operation. This is a breaking change to the existing Events service behavior.
- Administrators are excluded from all Library operations

---

## Open Items / Design-Phase Decisions

| # | Decision Needed |
|---|---|
| D1 | ~~New service vs. module~~ **RESOLVED**: Extend the existing Events service with a new `library` module. New DynamoDB table (existing table has all 4 GSI slots occupied). Schema can be dropped/recreated freely — no live data. |
| D2 | DynamoDB table strategy — **RESOLVED by D1**: new dedicated `library-${Stage}` table owned by the Events service data stack |
| D3 | Path 2 integration point — does the Contributions service emit an event that Library consumes, or does the approval UI call the Library API directly? |
| D4 | Topics autocomplete — served from a dedicated tags GSI on the library table, or a separate `TAGS#` item in the same table updated on each write? |
| D5 | ~~Empty description handling~~ **RESOLVED**: Event description is now mandatory. Enforced on Complete operation in Events service. |
