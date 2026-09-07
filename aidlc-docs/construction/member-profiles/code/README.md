# Code Generation Summary — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → Code Generation · **Unit**: Member Profiles & Directory
Executed plan: `../../plans/member-profiles-code-generation-plan.md`. Second real
service (Identity & Access was first). 8 stories: US-3.1, 3.2, 3.3, 3.4, 3.5, 3.6,
3.7, 3.10 (US-3.8/3.9 reassigned to Identity & Access during Functional Design).

## Contract changes
- `contracts/services/member-profiles/openapi.yaml`: removed `/admin/members` +
  `adminMemberList` (BR-15 reassignment); extended `Member` schema additively
  (`groups`, `city`, `country`, `professionalRole`, `awsProject`, `bio`, `skills`,
  `avatar`, `rollup`, `tiers`, `activitySummary` — all optional, backward-compatible,
  no `vN+1` needed per `contracts/README.md`); added optional query params to
  `browseDirectory` (`q`/`role`/`groupId`/`certId`/`limit`/`cursor`) and
  `memberActivity` (`from`/`to`) plus response fields (`memberActivity.points`).
- `contracts/services/member-profiles/published-events/member-events.v1.json`
  (new) — `MemberProfileUpserted` schema.
- `infra/api-edge.yaml` regenerated via `infra/tools/gen_api_edge.py` — the
  `/admin` and `/admin/{proxy+}` routes were dropped (no active caller, verified
  by grep against the frontend before the change).

## Application code created (`services/member-profiles/src/`)
| File | Purpose |
|---|---|
| `app.py` | Real Lambda handler — HTTP route dispatch (5 operations across 4 paths) + EventBridge-rule branch for the 6 consumed Identity events |
| `models.py` | Constants + serializers (`profile_public`, `directory_row_public`, `activity_summary_public`) |
| `repository.py` | Single-table DynamoDB access; scan+filter directory query (no GSI yet) |
| `fan_out_client.py` | **Defining component** — parallel, per-call-timeout cross-service reads with per-container short-circuit; forwards the caller's bearer token |
| `event_consumer.py` | Idempotent consumption of Identity & Access's 6 events; sole write path for identity/role/status/groups fields |
| `profile_service.py` | `getOwnProfile` / `updateOwnProfile` / `getMember` |
| `activity_service.py` | `memberActivity` (leader-only, date-range, points) |
| `directory_service.py` | `browseDirectory` (search delegation + keyword fallback, filters, pagination) |
| `providers.py` | `EventPublisher` (publishes `MemberProfileUpserted`), `SettingsCache` |
| `_conventions/*.py` | Copied verbatim from `services/identity-access/src/_conventions/` (FQ1 reference convention) |

## Tests created (`services/member-profiles/tests/`) — 51 tests, all passing
| File | Focus |
|---|---|
| `conftest.py` | moto DynamoDB fixture + `FakeFanOut`/`FakeEvents` test doubles |
| `test_repository.py` | Scan+filter directory access, deactivated-members-remain-searchable (BR-8) |
| `test_fan_out_client.py` | Parallelism, per-call fault isolation, short-circuit, bearer-token forwarding |
| `test_event_consumer.py` | All 6 consumed event types, idempotent redelivery, rejoin overwrite (BR-G5) |
| `test_profile_service.py` | US-3.1/3.2/3.3 + the mandatory degrade-path scenario (NFR-MP-MAINT-1) + identity-field-immutability (BR-2) |
| `test_activity_service.py` | US-3.10 scoping (BR-4 Admin 403, BR-13 Member 403 + UGL own-group-only) + degrade-path |
| `test_directory_service.py` | US-3.4/3.5 filters, semantic delegation, keyword fallback (BR-6b), CL cert-filter omission (BR-6) |
| `test_app_routes.py` | Route dispatch, 401/403 authz, EventBridge branch routing |

```
$ python3 -m pytest services/member-profiles/tests -q
51 passed
```

## Infrastructure changes
- `infra/services/service-member-profiles-app.yaml`: `Handler` → `app.handler`;
  new `ApiBaseUrl` Parameter; scoped IAM (`TableCrud` limited to own table with no
  GSI actions, `FanOutInvoke` for `execute-api:Invoke` on 5 sibling services'
  GET methods, `PublishDomainEvents`); new `IdentityEventRule` (`AWS::Events::Rule`
  subscribing to the 6 Identity events) + invoke permission; new
  `P95LatencyAlarm`, `ThrottleAlarm`, `FanOutFailureMetricFilter`/`FanOutFailureAlarm`.
  No `ProvisionedConcurrencyConfig` (not needed — no interactive path).
- `infra/services/service-member-profiles-data.yaml`: **unchanged** — no new
  GSI, per the accepted Infrastructure Design deferral.
- `infra/root-template.yaml`: `MemberProfilesApp` now passes `ApiBaseUrl` from
  `ApiEdge.Outputs.ApiEndpoint`.

## Frontend integration (user-requested)
- `frontend/src/features/pages.tsx` (`DirectoryPage`): added role/group filter
  dropdowns (fetches `/groups` for the group list), semantic-search query param
  wiring (`q`/`role`/`groupId`), inactive-member badge, per-group join-date
  column.
- `frontend/src/features/singletons.tsx` (`ProfilePage`): renders the merged
  rollup/tiers/activitySummary from the real service; extended the edit form
  with `bio`/`skills` fields; per-group join dates; bio/skills/certification-badge
  cards; activity-summary stat grid.
- `frontend/src/features/MemberDetailPage.tsx`: rewritten as a read-only view
  matching the `member/view-profile.html` mockup — location/professional-role/
  AWS-project, per-group join dates, rollup (no tier meaning), per-group tiers,
  bio/skills, activity-summary stat grid. No edit action (BR-5).
- No new routes needed — all 8 in-scope stories map onto these 3 existing screens.
- Verified: `npm run build` (tsc -b && vite build) — clean, no TypeScript errors.

## Verification performed
- `python3 -m pytest services/member-profiles/tests -q` — 51 passed.
- `python3 -m pytest services/identity-access/tests -q` — 88 passed (no regression).
- `ruff check services/member-profiles/src` — same category/volume of pre-existing
  style findings (E501/UP017) as Identity & Access's `src/` baseline (56 similar
  findings there); one S310 finding fixed (explicit `https://` scheme validation
  before any fan-out request is constructed).
- `cfn-lint` on `service-member-profiles-app.yaml`, `root-template.yaml`,
  `api-edge.yaml` — clean, no findings.
- `npm run build` (frontend) — clean.
- bandit not available in this environment (not installed); deferred to CI per
  NFR-MAINT-1 (same constraint noted for Identity & Access's local dev loop).

## Known/deferred items
- `getMember`'s 403 (BR-4) for Administrator surfaces to the frontend the same
  way a 501 does today (`ComingSoon`) rather than a distinct "forbidden" UI —
  acceptable since Administrators have no legitimate reason to navigate to
  `/directory/:id` (their own nav never links there), but noted for a future
  UX pass if desired.
- Role/status GSI on the profile table remains deferred pending load testing
  (Infrastructure Design Q4) — `browseDirectory` uses scan+filter.
- `US-3.6`/`US-3.7` (onboarding/welcome) have no backend module in this unit by
  design — they are frontend orchestration and Notifications' responsibility
  respectively; not implemented here or in Notifications yet (Unit 10 not built).


## Story-coverage verification (user-requested) + gap closure

A full story-by-story check against use case 03, the contract, backend code, and
the frontend surfaced 4 frontend gaps (backend was already complete for all 8
in-scope stories). All 4 were closed:

| Story | Gap found | Fix |
|---|---|---|
| US-3.2 Edit My Profile | Edit form was missing `awsProject` toggle and `avatar` upload; `skills` was sent as a raw comma-separated string instead of an array | Added `checkbox` and `tags` field types to `FormModal.tsx` (generic, reusable); added `avatar`/`awsProject`/`skills` (as `tags`) to `ProfilePage`'s edit form in `singletons.tsx` |
| US-3.5 Search Members | Certification-held filter dropdown was never rendered (backend/contract already supported `certId`) | Added a cert filter to `DirectoryPage` (`pages.tsx`), fetching `/certifications` for options; hidden for `CommunityLeader` (BR-6, mirrors the server-side omission) |
| US-3.6 First-Time Login Experience | No onboarding flow existed anywhere in the frontend | Added `OnboardingBanner` to `DashboardPage.tsx` — shown to Members whose profile has no group memberships yet (checked via `/members/me`); lists open groups from `/groups` with Join/Request-to-join actions (reusing the existing join endpoint), a Skip action, and a Done action; dismissal persisted in `localStorage` so it doesn't reappear once acted on |
| US-3.10 View Member Activity Summary | The leader-only `memberActivity` endpoint (points, date-range) was never called by any frontend page — `MemberDetailPage` only showed the basic inline block from `getMember` | Created `DetailedActivitySummary.tsx` (new component) — date-range inputs + a Load/Refresh action calling `GET /members/{id}/activity?from&to` directly; rendered on `MemberDetailPage` only when the viewing role is `CommunityLeader`/`UserGroupLeader` (`isLeader` gate); `App.tsx` now passes `role` through to `MemberDetailPage` |

US-3.7 (Welcome Notification) remains intentionally unimplemented — it is
Notifications' (Unit 10) responsibility and that unit does not exist yet; this
was flagged, not silently skipped, in the original code-generation summary above.

### Files touched in this pass
- `frontend/src/components/FormModal.tsx` — added `checkbox`/`tags` field types (generic, reused by any future form)
- `frontend/src/components/DetailedActivitySummary.tsx` (new)
- `frontend/src/features/singletons.tsx` (`ProfilePage` edit form)
- `frontend/src/features/pages.tsx` (`DirectoryPage` cert filter)
- `frontend/src/features/DashboardPage.tsx` (`OnboardingBanner`)
- `frontend/src/features/MemberDetailPage.tsx` (leader-gated detailed activity section)
- `frontend/src/App.tsx` (`role` prop threading to `DirectoryPage`/`MemberDetailPage`)

No backend changes were needed — every gap was a missing frontend integration
against endpoints/fields the real service already exposed.

### Verification
- `npm run build` (tsc -b && vite build) — clean, no TypeScript errors.
- `python3 -m pytest services/member-profiles/tests -q` — 51 passed (unchanged, no backend touched).
- `python3 -m pytest services/identity-access/tests -q` — 88 passed (no regression).
