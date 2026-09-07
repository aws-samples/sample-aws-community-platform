# Member Profiles & Directory Service (Unit 3)

Second real service of the AWS Community Portal. Implements the frozen contract
`contracts/services/member-profiles/openapi.yaml` behind the same API Gateway
routes the mock served (`/members`, `/members/me`, `/members/{id}`,
`/members/{id}/activity`).

## Responsibilities (8 stories: US-3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.10)
- **Own/other profile view + edit**: own profile (US-3.1/3.2), read-only view of
  another member's profile (US-3.3) — 403 for Administrator.
- **Directory browse + search**: pagination, role/group/certification filters,
  semantic search delegation to the shared Search service with a graceful
  keyword-match fallback when disabled or unavailable (US-3.4/3.5).
- **Detailed activity summary**: leader-only (`memberActivity`), points +
  date-range filter — distinct from the basic 4-stat inline block shown on any
  profile view (US-3.10).
- **Onboarding/welcome (US-3.6/3.7)**: no backend logic here — frontend
  orchestration over Identity & Access's `/groups` (US-3.6) and Notifications
  reacting to `UserProvisioned` (US-3.7).

**US-3.8 (admin member list) and US-3.9 (export member list) were reassigned to
Identity & Access** (2026-08-02) — `GET /users` already serves both via its
existing role index; this service builds no `/admin/members` endpoint.

## Layout
```
src/
  app.py               REAL Lambda handler (router + EventBridge-rule branch) — deployed entrypoint
  models.py            constants + OpenAPI serializers (profile_public, directory_row_public, ...)
  repository.py        single-table DynamoDB access (pk/sk, scan+filter — no GSI yet)
  fan_out_client.py     parallel, per-call-timeout cross-service reads (this unit's defining pattern)
  event_consumer.py     6 consumed Identity & Access events, idempotent
  profile_service.py    getOwnProfile / updateOwnProfile / getMember
  activity_service.py   memberActivity (leader-only, date-range)
  directory_service.py  browseDirectory (search + filters + pagination)
  providers.py           EventPublisher, SettingsCache
  _conventions/         logger, errors, authz, validation, envelope, idempotency, config (copied per service)
tests/                 pytest + moto unit tests (incl. degrade-path suite)
```

## Configuration (env vars — from CFN Parameters)
| Var | Purpose |
|---|---|
| `TABLE_NAME` / `IDEMPOTENCY_TABLE` | DynamoDB tables |
| `EVENT_BUS_NAME` | EventBridge domain-event bus (publish + subscribe) |
| `API_BASE_URL` | Shared API Gateway invoke URL, used by `FanOutClient` |
| `ENABLE_SEMANTIC_SEARCH` | Search delegation toggle (D3); falls back to keyword match when `false` |

## The defining architectural pattern: FanOutClient
`getOwnProfile`/`getMember` need a current-quarter rollup from Contributions &
Scoring and basic activity counts from Events/Forums/Certifications;
`memberActivity` needs a fuller version with points + date-range. Each call is
issued in parallel (`ThreadPoolExecutor`) with its own ~300ms timeout, and any
failure (timeout, 5xx, connection error) is caught individually — a slow or
unavailable dependency degrades only its own section of the response, never the
whole request (BR-9). Calls forward the calling principal's own bearer token,
so downstream services' own in-service authZ applies unchanged — no
service-to-service credential is minted.

`FanOutClient` calls Contributions/Events/Forums/Certifications through the shared
API Gateway using their published routes — those dependency services are all real,
so the fan-out reads live data from each.

## Design decisions (flagged for review)
1. Profile-extension record is an event-sourced cache, not an independent
   source of truth — created/updated only by consuming Identity & Access's
   events (`UserProvisioned`/`UserRoleChanged`/`UserDeactivated`/`UserReactivated`/
   `MemberJoinedGroup`/`MemberLeftGroup`/`MemberRemoved`) plus the member's own
   profile edits.
2. No new GSI added at this stage — `browseDirectory` uses a scan+filter, an
   explicit accepted-tech-debt deferral pending load testing (see Infra Design).
3. US-3.8/3.9 reassignment to Identity & Access (see Responsibilities above).

## Test
```
python3 -m pytest services/member-profiles/tests -q
```

## Deploy wiring note
`service-member-profiles-app.yaml` receives `RestApiId`, `EventBusName`,
`ApiBaseUrl` (from `ApiEdge.Outputs.ApiEndpoint`), and table names from the root
template. A new `AWS::Events::Rule` subscribes to Identity & Access's 6 events.
No new `-data` stack resources — see `aidlc-docs/construction/member-profiles/infrastructure-design/`.
