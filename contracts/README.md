# Contracts Registry

Single source of truth for all cross-service agreements. **Specifications only — no runtime code** (FQ1). Mocks, contract tests, the SPA API client, and each service's local types are all generated from here.

## Layout
```
contracts/
├── services/<service>/openapi.yaml            # REST API for <service> (owner = <service>)
├── services/<service>/published-events/<event>.vN.json   # event payloads (owner = publisher)
└── platform/
    ├── event-envelope.v1.json                 # common event wrapper (data validated by per-event schema)
    ├── error-response.v1.json                 # standard error shape (generic messages, SECURITY-15)
    └── permissions/role-permission-matrix.v1.json   # RBAC source of truth (in-service authZ)
```

## Ownership rule (BR-1)
The folder name **is** the owner. Only the owning service may change schemas in its folder; all other services treat them as read-only. Cross-cutting specs under `platform/` are owned by the Platform & Delivery unit.

## Versioning rule (BR-4 / BR-5)
- Event payloads are versioned by filename: `<event>.v1.json`, `<event>.v2.json`, …, and by the `version` integer in the envelope.
- A **non-backward-compatible** change requires a **new** `vN+1` file; the previous version is retained until all consumers migrate. Consumers select by version.
- **Backward-compatible** additions (new optional field) may extend the current version in place.

## Conventions
- REST: **OpenAPI 3.x** (`openapi.yaml`), one per service.
- Events: **JSON Schema** payloads; every event is wrapped in `event-envelope.v1.json`.
- All responses conform to a schema; errors use `error-response.v1.json`.
- AuthN at the edge (Cognito); authZ in-service from `permissions/role-permission-matrix.vN.json`.

## Event index (published events by owner)
| Owner | Events |
|---|---|
| identity-access | UserProvisioned, UserRoleChanged, UserDeactivated, UserReactivated, GroupCreated, GroupUpdated, GroupSoftDeleted, GroupRestored, GroupHardDeleted, MemberJoinedGroup, MemberLeftGroup, MemberRemoved |
| member-profiles | MemberProfileUpserted |
| events | AttendanceRecorded, EventDelivered, EventOrganized, EventCompleted, EventCancelled, MaterialsAdded |
| forums | ForumPostCreated, ForumReplyCreated, PostDeleted, ForumChannelDeleted, MemberMentioned, PostReported |
| certifications | CertificationApproved, CertificationRevoked, CertificationExpired |
| contributions-scoring | PointsAwarded, PointsAdjusted, TierAchieved |
| announcements | AnnouncementPublished |
| settings | SettingsChanged |

(Per-service `openapi.yaml` and `published-events/*.json` are authored by each service unit during its construction; the platform unit owns the `platform/` specs and the conventions above.)
