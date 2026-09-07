# Business Rules — Content Library Rework

Prefixed by area: **A**uthorization · **V**alidation · **P**ath (entry paths) · **S**earch · **T**ag · **C**uration · **X** cross-service.
All rules enforced server-side. UI enforcement is a convenience only.

---

## Authorization (A)

| # | Rule |
|---|---|
| BR-LIB-A1 | **Administrators have no Library permissions.** Every `/library*` operation returns `403` for role `Administrator`. |
| BR-LIB-A2 | **Members may only read** — browse, search, download. Any write operation (POST, PUT, DELETE) by a Member returns `403`. |
| BR-LIB-A3 | **CL and UGL have full curation rights** — add (Path 3), edit, and delete any resource regardless of source or originating group. The Library is community-wide; curation authority is not group-scoped. |
| BR-LIB-A4 | **Path 1 and Path 2 promotions are system-initiated**, not user-initiated. They execute under service identity, not a user principal, and are not subject to BR-LIB-A2/A3 role checks. |

---

## Validation (V)

| # | Rule |
|---|---|
| BR-LIB-V1 | `title` is required, 1..200 chars after trim. |
| BR-LIB-V2 | `description` is **mandatory on all write paths** (Path 1, 2, 3 and edits). A blank or absent description is `400`. Exception: Path 1 inherits the event description which is guaranteed non-empty by BR-L2-DESC (event description mandatory on complete). |
| BR-LIB-V3 | `format` must be one of `Slides`, `PDF`, `Doc`, `Recording`, `Link`. Unknown values are `400`. |
| BR-LIB-V4 | `topics` is optional. Each tag is a non-empty string, max 50 chars, stored **lowercase-normalized** (`tag.strip().lower()`). Duplicate tags within one resource are silently deduplicated. Max 20 tags per resource. |
| BR-LIB-V5 | For `format = Link`, a `url` field is required and must start with `https://`. |
| BR-LIB-V6 | For file formats (`Slides`, `PDF`, `Doc`, `Recording`), an `s3Key` must be present and the file must pass the scan gate (BR-LIB-P4) before the resource is downloadable. |
| BR-LIB-V7 | `title` uniqueness is **not** enforced — duplicate titles are permitted (two events can both have "Slides from meetup"). |

---

## Entry Paths (P)

### Path 1 — Event material auto-promotion

| # | Rule |
|---|---|
| BR-LIB-P1 | **Trigger**: a material transitions to `scanState = Clean` AND its parent event has `status = Completed`. This condition is evaluated by the `MalwareScanConsumer` (for files) and by `MaterialService.add()` / `event_service.complete()` (for links and at completion time). |
| BR-LIB-P2 | **At event completion**: all materials on the event with `scanState = Clean` and `uploaded = true` (for files) or `kind = link` are promoted immediately. Materials still `PendingScan` are not promoted at completion — they are promoted when scanning clears (BR-LIB-P1). |
| BR-LIB-P3 | **Post-completion adds**: a material added to a Completed event follows the same trigger — promoted when clean (BR-LIB-P1). There is no timing distinction between materials present at completion and those added later. |
| BR-LIB-P4 | **Scan gate**: `Quarantined` materials are **never** promoted. `PendingScan` materials are not promoted until cleared. Only `Clean` materials enter the Library. |
| BR-LIB-P5 | **Auto-removal**: when a material is deleted from an event (BR-M7), its corresponding Library resource (if any, identified by `eventId + materialId`) is **automatically deleted**. The Library stays in sync with the source. |
| BR-LIB-P6 | Path 1 resource fields: `title` = material name, `description` = event description (copied at promotion time), `format` = material contentType, `source` = `event-material`, `scope` = `COMMUNITY`, `eventId` + `eventTitle` denormalized, `submittedBy` = event `createdBy`, `addedBy` = system, `addedAt` = promotion timestamp. |

### Path 2 — Member contribution opt-in

| # | Rule |
|---|---|
| BR-LIB-P7 | **Trigger**: `ContributionApproved` EventBridge event with `addToLibrary: true` in the payload. The Library module consumes this event. |
| BR-LIB-P8 | The `ContributionApproved` payload must carry: `contributionId`, `memberId`, `memberName`, `addToLibrary` (bool), and when `addToLibrary = true`: `title`, `description`, `format`, `topics[]`, and either `url` or `s3Key`. |
| BR-LIB-P9 | `description`, `format`, and `title` in the `ContributionApproved` payload are the curator-entered values from the approval modal, **not** the raw contribution fields. The curator edits them at approval time. |
| BR-LIB-P10 | Contribution **points are awarded by the existing Contributions flow**, independent of Library opt-in. Library entry never awards points. |
| BR-LIB-P11 | Path 2 resource fields: `source` = `member-contribution`, `submittedBy` = member userId, `submittedByName` = member display name, `addedBy` = approving curator userId, `addedAt` = event consumption timestamp. |
| BR-LIB-P12 | Consumer is idempotent on `contributionId` — a redelivered `ContributionApproved` event does not create a duplicate Library resource. |

### Path 3 — Curator direct add

| # | Rule |
|---|---|
| BR-LIB-P13 | CL or UGL may add a resource directly via `POST /library`. All fields (title, description, format, topics, url or file) must be provided per BR-LIB-V1..V6. |
| BR-LIB-P14 | Path 3 file resources enter `scanState = PendingScan` and are not downloadable until GuardDuty clears them (same scan gate as event materials). |
| BR-LIB-P15 | Path 3 link resources (`format = Link`) are immediately available — no scan needed. |
| BR-LIB-P16 | Path 3 resource fields: `source` = `curator-direct`, `submittedBy` = curator userId, `submittedByName` = curator display name, `addedBy` = curator userId, `addedAt` = creation timestamp. |

---

## Search (S)

| # | Rule |
|---|---|
| BR-LIB-S1 | **Search-first**: no results are returned until the caller submits at least one of: `q` (keyword), `format`, `topic`, or `source`. An empty request returns `{"items": [], "count": 0}` — never the full corpus. |
| BR-LIB-S2 | **Keyword search** (`q`): case-insensitive substring match across `title` + `description`. No semantic search, no stemming. |
| BR-LIB-S3 | `format` filter: exact match against the resource's `format` field. |
| BR-LIB-S4 | `topic` filter: exact match against any tag in the resource's `topics[]` array (case-insensitive, since tags are stored lowercase). |
| BR-LIB-S5 | `source` filter: exact match against `event-material`, `member-contribution`, or `curator-direct`. |
| BR-LIB-S6 | All filters combine with AND semantics — a resource must satisfy all supplied filters simultaneously. |
| BR-LIB-S7 | Results are ordered **newest first** (`addedAt` descending). |
| BR-LIB-S8 | Results are **cursor-paginated**, page size default 10, max 50. An unparseable cursor is `400`. |
| BR-LIB-S9 | Only `Clean` resources (or link resources) are returned in search results. `PendingScan` and `Quarantined` resources are **never** returned to any caller, including curators, via the search endpoint. Curators see scan state in the curation management view only. |
| BR-LIB-S10 | **Administrators are excluded** — `GET /library` returns `403` for Administrator role. |

---

## Tags (T)

| # | Rule |
|---|---|
| BR-LIB-T1 | Tags are stored **lowercase-normalized** on every write (`tag.strip().lower()`). The display value is the stored lowercase string. |
| BR-LIB-T2 | A `TAGS#ALL` singleton item in the library table holds the **union of all distinct tags** across all resources as a DynamoDB string set. It is updated (add new tags / remove deleted tags) on every resource write. |
| BR-LIB-T3 | `GET /library/tags?prefix=<str>` returns all tags in `TAGS#ALL` whose value starts with the supplied lowercase prefix. If no prefix is supplied, all tags are returned (capped at 100). |
| BR-LIB-T4 | Tag removal from `TAGS#ALL` is **lazy** — when a resource is deleted, the service does not immediately scan all resources to verify whether the deleted tags are still in use. Tags persist in `TAGS#ALL` until a background reconciliation or until a curator notices stale suggestions. This is acceptable — stale suggestions cause no functional harm. |

---

## Curation (C)

| # | Rule |
|---|---|
| BR-LIB-C1 | **Edit** (PUT /library/{id}): CL or UGL may update `title`, `description`, `format`, `topics`, `url` (for link resources). `source`, `submittedBy`, `eventId` are immutable — they record provenance and may not be changed. |
| BR-LIB-C2 | **File replacement via edit is not supported.** To replace a file, the curator deletes the resource and re-adds via Path 3. This keeps the scan gate clean — no ambiguity about which file version is scanned. |
| BR-LIB-C3 | **Delete** (DELETE /library/{id}): CL or UGL may delete any resource. The Library DynamoDB item is deleted. The S3 object is **retained** (not deleted from bucket) — it may still be referenced by the source event's material row (Path 1) or kept for audit. |
| BR-LIB-C4 | Deleting a Library resource **does not** delete the source event material (Path 1) or the contribution record (Path 2). The Library entry is independent once created (except for Path 1 auto-removal on material deletion per BR-LIB-P5). |
| BR-LIB-C5 | After any resource write (add/edit/delete), the `TAGS#ALL` singleton is updated (BR-LIB-T2). |

---

## Cross-service (X)

| # | Rule |
|---|---|
| BR-LIB-X1 | The Library module consumes `ContributionApproved` from EventBridge (Path 2). It must be idempotent on `contributionId` (BR-LIB-P12). |
| BR-LIB-X2 | The Library module is triggered by the Events service internally on event completion (Path 1) and material deletion (BR-LIB-P5). These are in-process calls within the Events Lambda, not cross-service HTTP calls. |
| BR-LIB-X3 | File scan results from GuardDuty route through the existing `MalwareScanConsumer`. After updating `scanState`, the consumer calls the Library promotion logic if the material's event is Completed (BR-LIB-P1). |
| BR-LIB-X4 | The Library never calls Contributions, Identity, or any other service synchronously. All cross-service integration is event-driven (EventBridge) or JWT-claims-based. |
| BR-LIB-X5 | Member display names (`submittedByName`) are **denormalized at write time** from the JWT claims. Stale names (member renamed their profile) are accepted — the Library is a historical record. |

---

## Removed rules (from original Content Library)

The following original BR-CL rules are **retired** with this rework:

| Original Rule | Replacement |
|---|---|
| BR-CL1 (completed events only) | Replaced by BR-LIB-P1/P2 |
| BR-CL2 (keyword search corpus) | Replaced by BR-LIB-S2 |
| BR-CL3 (content type + group filter) | Replaced by BR-LIB-S3/S4/S5 (group filter removed — Library is community-wide) |
| BR-CL4 (search-first) | Replaced by BR-LIB-S1 |
| BR-CL5 (visibility mirrors event scope) | Replaced by BR-LIB-A1/A2 (community-wide, no group scoping) |
| BR-CL6 (cursor pagination, newest first) | Replaced by BR-LIB-S7/S8 |
