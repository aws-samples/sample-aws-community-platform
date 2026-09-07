# Domain Entities & Schemas — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Platform & Delivery
Technology-agnostic schemas for the platform's own artifacts. These become the concrete files under `/contracts/platform/` and the delivery tooling's data structures. Companion: `business-logic-model.md`, `business-rules.md`.

---

## E1 — Event Envelope (`/contracts/platform/event-envelope.v1.json`) — Q1
Common wrapper for every EventBridge domain event; `data` is validated by the per-event schema.
| Field | Type | Notes |
|---|---|---|
| `id` | string (uuid) | unique event id (idempotency key for consumers) |
| `type` | string | event name, e.g. `PointsAwarded` |
| `version` | integer | payload schema version (matches `*.vN.json`) — Q2 |
| `source` | string | publishing service, e.g. `contributions-scoring` |
| `time` | string (ISO-8601 UTC) | event time |
| `correlationId` | string | trace id propagated across the workflow |
| `data` | object | event-specific payload (per-event schema) |

Example:
```json
{
  "id": "b1e...-uuid",
  "type": "PointsAwarded",
  "version": 1,
  "source": "contributions-scoring",
  "time": "2026-07-22T10:15:30Z",
  "correlationId": "req-abc123",
  "data": { "memberId": "m-101", "groupId": "g-1", "quarter": "2026-Q3", "points": 10, "sourceType": "attendance" }
}
```

## E2 — Error Response (`/contracts/platform/error-response.v1.json`)
Standard error shape returned by mocks and required of real services (generic messages — SECURITY-15).
| Field | Type | Notes |
|---|---|---|
| `code` | string | stable machine code, e.g. `FORBIDDEN`, `NOT_IMPLEMENTED`, `VALIDATION_ERROR` |
| `message` | string | generic, user-safe (no internals/stack traces) |
| `correlationId` | string | for support/log correlation |
| `details` | array (optional) | field-level validation messages (safe subset) |

## E3 — Role–Permission Matrix (`/contracts/platform/permissions/role-permission-matrix.v1.json`) — Q3/FQ3a
```json
{
  "version": 1,
  "roles": ["Administrator", "CommunityLeader", "UserGroupLeader", "Member"],
  "permissions": {
    "CommunityLeader": [
      { "action": "create", "resource": "event", "scope": "global" },
      { "action": "moderate", "resource": "forum", "scope": "global" }
    ],
    "UserGroupLeader": [
      { "action": "approve", "resource": "join-request", "scope": "group" },
      { "action": "edit", "resource": "event", "scope": "group" }
    ],
    "Member": [
      { "action": "edit", "resource": "post", "scope": "own" },
      { "action": "submit", "resource": "certification-claim", "scope": "own" }
    ]
  }
}
```
- `scope`: `global` | `own` | `group` (BR-9). `accountType=local-admin` handled as an orthogonal flag, not a role.
- Illustrative entries only — the authoritative full matrix is `requirements/Role-and-Permission-Mapping.md`, transcribed into this machine-readable spec during Code Generation.

## E4 — `service-mode` manifest (`service-mode.json`) — Q6/Q7
Informational dev-tracking (D14). Array of:
| Field | Type | Notes |
|---|---|---|
| `service` | string | service name |
| `mode` | enum | `mock` \| `partial` \| `complete` |
| `implementedPaths` | array | `["POST /events", "GET /events/{id}"]` — derived from handler `implemented` flags |
| `lastUpdated` | string (ISO-8601 UTC) | last pipeline update |
| `pipelineRunId` | string | traceability to the deploy |

Example:
```json
[
  { "service": "identity-access", "mode": "complete", "implementedPaths": ["*"], "lastUpdated": "2026-07-22T10:00:00Z", "pipelineRunId": "run-42" },
  { "service": "events", "mode": "partial", "implementedPaths": ["GET /events", "GET /events/{id}"], "lastUpdated": "2026-07-22T11:00:00Z", "pipelineRunId": "run-17" },
  { "service": "analytics", "mode": "mock", "implementedPaths": [], "lastUpdated": "2026-07-22T09:00:00Z", "pipelineRunId": "run-3" }
]
```

## E5 — Fixture Dataset (`platform/fixtures/`) — Q4
One coherent seed keyed to the 4 personas; same IDs reused across services (BR-12).
| Collection | Approx volume | Notes |
|---|---|---|
| members | ~20 | includes the 4 personas (Admin, CL, UGL, Member) |
| groups | ~3 | with UGL assignments + memberships |
| events | ~10 | mix of upcoming/completed, with RSVPs/attendance |
| forums/channels/posts | ~5 forums, sample threads/replies | for forum UI |
| certifications/claims | a few defs + sample claims | catalog + verification queue |
| ledger + rollups + tiers | **precomputed** | so points/leaderboards/tiers render (BR-13) |
| announcements, notifications, settings | small samples | panels + preferences |

Loaded into each service's seeded `-data` table at bootstrap; IDs are stable and cross-referenced.

## E6 — `/contracts` layout (owned/maintained by this unit)
```
/contracts/
├── README.md                       # BR-1/BR-4/BR-5 conventions + event index
├── services/<svc>/openapi.yaml     # per-service API (owner = <svc>)
├── services/<svc>/published-events/<event>.vN.json
└── platform/
    ├── event-envelope.v1.json      # E1
    ├── error-response.v1.json      # E2
    └── permissions/role-permission-matrix.v1.json   # E3
```

## E7 — Semantic Search capability flag — Q10
- Deploy-time: single CloudFormation condition **`EnableSemanticSearch`** (governs Units 13 + 14 together).
- Runtime (mocks + services): a resolved boolean surfaced via config; endpoints branch per the Q10 matrix (BR-22–24).

---

## Consistency notes (validation)
- Envelope `version` (E1) ↔ event filename version (BR-4/BR-5): consistent.
- Permission matrix `scope` (E3) ↔ in-service object-level checks (BR-9) and contract-test 403 assertions (BR-21): consistent.
- `service-mode.implementedPaths` (E4) ↔ 501 rule (BR-17) and per-endpoint `implemented` flags (Q7): consistent.
- Fixtures (E5) precomputed derived data ↔ "no business logic in mocks" (BR-13): consistent.

## Pending propagation (from Q10 — apply at the affected units)
- US-3.5: semantic → **text** member search; Unit 3 updated accordingly.
- Unit 13 (Search): indexes **forums only** (drop member-profile indexing).
- D3 conditions renamed to single `EnableSemanticSearch` (Units 13 + 14 deploy together).
