# Domain Entities — Content Library Rework

Technology-agnostic domain model. Physical DynamoDB layout decided at Infrastructure Design.

---

## Entity Map

```
+------------------+        +------------------+
|  LibraryResource |        |   TagRegistry    |
|      (E1)        |        |      (E2)        |
+------------------+        +------------------+
| id               |        | tags (string set)|
| title            |        | (singleton item) |
| description      |        +------------------+
| format           |
| topics[]         |        Referenced externally (never owned here):
| source           |        +------------------+   +------------------+
| scope            |        |  Event (E1,      |   | Contribution     |
| url              |  ----> |  Events service) |   | (Contributions   |
| s3Key            |        +------------------+   |  service)        |
| scanState        |                               +------------------+
| submittedBy      |
| submittedByName  |
| addedBy          |
| addedAt          |
| eventId          | (Path 1 only)
| eventTitle       | (Path 1 only, denormalized)
| contributionId   | (Path 2 only)
+------------------+
```

Text alternative: `LibraryResource` is the primary entity, standalone and community-wide.
`TagRegistry` is a singleton item holding the union of all distinct tags for autocomplete.
`LibraryResource` carries denormalized references to its source (`eventId`/`eventTitle` for
Path 1, `contributionId` for Path 2) but does not own those entities.

---

## E1 — LibraryResource

The primary entity. Represents a single knowledge asset in the community Library.
Exists independently of its source once created (except Path 1 auto-removal on material deletion).

| Attribute | Type | Constraints | Notes |
|---|---|---|---|
| `id` | string | `lib-<uuid>` | Primary identifier |
| `title` | string | required, 1..200 chars | Display name |
| `description` | string | required, 1..5000 chars | Primary search corpus (BR-LIB-V2) |
| `format` | enum | required | `Slides`, `PDF`, `Doc`, `Recording`, `Link` (BR-LIB-V3) |
| `topics` | string[] | optional, max 20 | Lowercase-normalized free-form tags (BR-LIB-V4) |
| `source` | enum | required, immutable | `event-material`, `member-contribution`, `curator-direct` |
| `scope` | string | always `COMMUNITY` | Community-wide — no group scoping |
| `url` | string \| null | required when `format = Link` | Must be `https://` (BR-LIB-V5) |
| `s3Key` | string \| null | present for file formats | Path in shared S3 bucket |
| `scanState` | enum | for file formats only | `PendingScan`, `Clean`, `Quarantined` |
| `submittedBy` | string | userId | Original author / member / curator |
| `submittedByName` | string | display name | Denormalized at write time (BR-LIB-X5) |
| `addedBy` | string | userId | CL/UGL who added to Library, or system for Path 1 |
| `addedAt` | timestamp | ISO-8601 UTC | Used for newest-first ordering (BR-LIB-S7) |
| `eventId` | string \| null | Path 1 only, immutable | Parent event id |
| `eventTitle` | string \| null | Path 1 only | Denormalized event title at promotion time |
| `materialId` | string \| null | Path 1 only, immutable | Source material id — used for auto-removal lookup (BR-LIB-P5) |
| `contributionId` | string \| null | Path 2 only, immutable | Source contribution id — used for idempotency (BR-LIB-P12) |
| `updatedAt` | timestamp \| null | | Set on curator edits |

### Immutable fields (may never be changed after creation)
`id`, `source`, `submittedBy`, `eventId`, `materialId`, `contributionId`, `addedBy`, `addedAt`

### Editable fields (CL/UGL via PUT /library/{id})
`title`, `description`, `format`, `topics`, `url`

### System-managed fields (not settable via API)
`scanState` (set by GuardDuty consumer), `updatedAt`

---

## E2 — TagRegistry (singleton)

A single item in the library table that holds the complete set of all distinct lowercase tags
across all LibraryResource items. Used exclusively for the autocomplete endpoint.

| Attribute | Type | Notes |
|---|---|---|
| `pk` | string | `TAGS#ALL` — singleton, there is exactly one of these |
| `tags` | string set | DynamoDB SS — union of all `topics` values across all resources |
| `updatedAt` | timestamp | Last modification timestamp |

### Maintenance rules
- **On resource create**: add all `topics` values to `tags` set (ADD operation)
- **On resource edit**: add newly added topics; removed topics are left in the set (lazy — BR-LIB-T4)
- **On resource delete**: removed topics are left in the set (lazy — BR-LIB-T4)
- The set grows over time and is never automatically pruned; manual curator reconciliation if needed

---

## Cross-service references (never owned by Library module)

| Concept | Owner | How Library uses it |
|---|---|---|
| User identity, role | Identity & Access (Unit 2) | JWT claims (`sub`, `role`) for authZ |
| Member display name | Identity & Access (Unit 2) | JWT claim `name` — denormalized at write (BR-LIB-X5) |
| Event completion + materials | Events service (Unit 4) | In-process trigger within Events Lambda (Path 1) |
| Contribution approval | Contributions service (Unit 7) | `ContributionApproved` EventBridge event (Path 2) |
| S3 file storage | Shared community bucket | File uploads + presigned GET URLs (same bucket as event materials, under `library/` prefix) |
| GuardDuty scan results | AWS GuardDuty + existing consumer | `MalwareScanConsumer` extended to trigger Path 1 promotion |
