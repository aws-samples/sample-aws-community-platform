# Code Generation Plan — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → Code Generation · **Unit**: Member Profiles & Directory
Single source of truth for generating the real Member Profiles & Directory service (replaces the mock). Greenfield multi-unit (microservices) → code lives in `services/member-profiles/src/` + `services/member-profiles/tests/`. Docs summaries in `aidlc-docs/construction/member-profiles/code/`.

## Context
- **Frozen contract (to be amended)**: `contracts/services/member-profiles/openapi.yaml` (6 operations currently; `/admin/members` removed per Amendment 2/BR-15, `browseDirectory`/`getMember`/`memberActivity`/`Member` schema extended per domain-entities.md's additive/backward-compatible notes). Contract tests (Schemathesis) are the deploy gate.
- **Permission matrix**: `contracts/platform/permissions/role-permission-matrix.v1.json` (in-service authZ) — reused unchanged, no new entries needed (existing `view member-profile`/`browse member-directory`/`search member` rows already cover this unit's roles).
- **Conventions reused (no shared lib; copied per service)**: `src/_conventions/{logger,errors,authz,validation,envelope,idempotency,config}.py` — copied verbatim from `services/identity-access/src/_conventions/` (byte-identical reference convention per FQ1; this unit adds no new convention modules).
- **Stories**: 8 (US-3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.10). US-3.8/3.9 excluded (reassigned to Identity & Access).
- **Design decisions carried forward**: event-sourced profile-extension record (E1); `FanOutClient` parallel per-call-timeout cross-service reads; two-tiered activity summary (basic inline block vs. leader-only `memberActivity`); Search delegation with keyword fallback; no new GSI (scan+filter accepted); no provisioned concurrency.
- **Downstream services still mocked**: Contributions & Scoring, Events, Forums, Certifications, Search are all still mock Lambdas (only Identity & Access is real so far). `FanOutClient` calls their existing mock-served routes through the shared API Gateway — this is correct and forward-compatible; when those units later go real, no change is needed here (same route, same shape, contract-gated).
- **Dependency note**: this is the **second** real service. It depends on Identity & Access's published events (already real) for profile-record population, and on the shared API Gateway (Unit 1, already provisioned) for the fan-out calls.

## Steps
- [x] Step 1. Analyze unit context (done in prior stages — functional/NFR/infra design)
- [x] Step 2. Project structure setup — reuse existing `services/member-profiles/src/` scaffold; add `tests/` directory (does not exist yet, unlike identity-access)
- [x] Step 3. Contract amendment — `contracts/services/member-profiles/openapi.yaml`: remove `/admin/members`+`adminMemberList`; extend `Member` schema (groups/professionalRole/city/country/awsProject/bio/skills/avatar/rollup/tiers/activitySummary, all optional/additive); add optional query params to `browseDirectory` (`q`,`role`,`groupId`,`certId`,`limit`,`cursor`) and `memberActivity` (`from`,`to`); add response fields to `memberActivity` (`points.currentQuarter`/`points.lifetime`)
- [x] Step 4. `_conventions/` — copy the 7 modules verbatim from `services/identity-access/src/_conventions/` (no changes needed; already service-agnostic)
- [x] Step 5. `models.py` — constants (no roles/statuses redefinition needed, imported conceptually but this service doesn't need its own role enum since it never assigns roles) + serializers (`profile_public`, `directory_row_public`, `activity_summary_public`) conforming to the amended contract
- [x] Step 6. `repository.py` — single-table DynamoDB access: `put_profile`/`get_profile`/`scan_directory` (filter by role/status/groupId/keyword)/idempotency-table helpers reused from `_conventions.idempotency.IdempotencyStore`
- [x] Step 7. `fan_out_client.py` — `FanOutClient`: `ThreadPoolExecutor`-based parallel caller, per-call timeout, per-container short-circuit on consecutive failures, wraps `execute-api:Invoke`-style same-account HTTP calls (via `urllib3`) forwarding the caller's own bearer token; every call individually try/except → `None` on failure
- [x] Step 8. `event_consumer.py` — handles the 6 consumed Identity & Access event types (`UserProvisioned`/`UserRoleChanged`/`UserDeactivated`/`UserReactivated`/`MemberJoinedGroup`/`MemberLeftGroup`/`MemberRemoved`); idempotent via `IdempotencyStore`; mutates the profile-extension record
- [x] Step 9. `profile_service.py` — `getOwnProfile`/`updateOwnProfile`/`getMember` orchestration; merges profile record + `FanOutClient` rollup/basic-activity results; publishes `MemberProfileUpserted`
- [x] Step 10. `activity_service.py` — `memberActivity` orchestration; leader-only scoping (BR-4/13); date-range filtering; fuller fan-out (points current-quarter + lifetime)
- [x] Step 11. `directory_service.py` — `browseDirectory`; branches on `q` + `EnableSemanticSearch` (delegates to Search's mock via `FanOutClient` when on, falls back to keyword match, or direct keyword match when off); role/group/cert filters; pagination
- [x] Step 12. `providers.py` — `EventPublisher` (reused pattern from identity-access, `source="member-profiles"`) + `SettingsCache` (cached `EnableSemanticSearch` read, short TTL)
- [x] Step 13. `app.py` — REAL Lambda handler (router): operation table for the 4 in-scope API routes (`getOwnProfile`/`updateOwnProfile`/`getMember`/`browseDirectory`/`memberActivity` — 5 operations across 4 paths) + EventBridge-rule branch for the 6 consumed events (mirrors identity-access's scheduled-sync branch pattern); `Context` wiring; fail-closed authz per BR-4/13
- [x] Step 14. Business logic unit tests — `test_repository.py`, `test_event_consumer.py`, `test_profile_service.py`, `test_activity_service.py`, `test_directory_service.py`, `test_fan_out_client.py` (incl. the degrade-path suite: simulated downstream 5xx/timeout per fan-out target → assert 200 with empty section, per NFR-MP-MAINT-1)
- [x] Step 15. API layer unit tests — `test_app_routes.py` (route → status/schema, authz 403s for Administrator/out-of-scope UGL/Member on `getMember`/`memberActivity`)
- [x] Step 16. Infrastructure artifacts — update `service-member-profiles-app.yaml` (handler→`app.handler`, new `RestApiId` Parameter for `execute-api:Invoke` ARNs, new `AWS::Events::Rule` for the 6-event subscription, scoped IAM policies replacing `DynamoDBCrudPolicy`, new alarms for fan-out-failure-rate + event-consumer-lag); `service-member-profiles-data.yaml` unchanged (no new GSI, per Infra Design Q4)
- [x] Step 17. Published-event schema — `contracts/services/member-profiles/published-events/MemberProfileUpserted.v1.json`
- [x] Step 18. `requirements.txt` (pinned: `boto3`, `aws-lambda-powertools`; dev: `pytest`, `schemathesis`, `moto`, `responses`) + `README.md`
- [x] Step 19. Regenerate `infra/api-edge.yaml` via `python3 infra/tools/gen_api_edge.py` (reflects the `/admin/members` route removal from Step 3)
- [x] Step 20. Update `service-mode.json` (member-profiles → `complete` after tests pass)
- [x] Step 21. Run tests + fix
- [x] Step 22. **Frontend integration** (user-requested 2026-08-02): update `frontend/src/features/pages.tsx` (`DirectoryPage` — role/group filters, inactive badge, per-group join dates), `frontend/src/features/singletons.tsx` (`ProfilePage` — rollup, per-group tiers, bio/skills/avatar, basic activity block, edit-profile fields for bio/skills/awsProject), `frontend/src/features/MemberDetailPage.tsx` (read-only view — same additive fields, no edit action, 403→ComingSoon-style handling for Administrator), and `frontend/src/lib/apiClient.ts`/type defs if a typed `Member` shape exists. No new pages needed — all 8 stories map onto these 3 existing screens.
- [x] Step 23. Documentation summary in `aidlc-docs/construction/member-profiles/code/`

## File plan (application code — workspace)
```
services/member-profiles/
├── requirements.txt                  # pinned deps
├── README.md
├── src/
│   ├── app.py                         # REAL Lambda handler (router) — replaces mock as entrypoint
│   ├── models.py                      # constants, serializers (OpenAPI shapes)
│   ├── repository.py                  # single-table DynamoDB access (pk/sk, scan+filter — no GSI)
│   ├── fan_out_client.py              # parallel per-call-timeout cross-service reads
│   ├── event_consumer.py              # 6 consumed Identity events, idempotent
│   ├── profile_service.py             # getOwnProfile / updateOwnProfile / getMember
│   ├── activity_service.py            # memberActivity (leader-only, date-range)
│   ├── directory_service.py           # browseDirectory (search + filters + pagination)
│   ├── providers.py                   # EventPublisher, SettingsCache
│   ├── mock_handler.py                # (retained; no longer the deployed entrypoint)
│   ├── mock_runtime.py / *.json       # (retained for reference/other tooling)
│   └── _conventions/                  # copied verbatim from identity-access (Step 4)
└── tests/
    ├── conftest.py                    # moto DynamoDB fixture + fake FanOutClient/EventPublisher
    ├── test_repository.py
    ├── test_fan_out_client.py         # incl. degrade-path scenarios
    ├── test_event_consumer.py
    ├── test_profile_service.py
    ├── test_activity_service.py
    ├── test_directory_service.py
    └── test_app_routes.py
```

## Story traceability → modules
| Stories | Module |
|---|---|
| US-3.1 | profile_service.get_own_profile |
| US-3.2 | profile_service.update_own_profile |
| US-3.3 | profile_service.get_member |
| US-3.4 | directory_service.browse (no `q`) |
| US-3.5 | directory_service.browse (with `q`) + fan_out_client Search delegation |
| US-3.6 | (no backend module — frontend orchestration over Identity's `/groups`; profile record existence check only, exposed via `getOwnProfile`'s `createdAt`) |
| US-3.7 | (no backend module — Notifications, off `UserProvisioned`) |
| US-3.10 | activity_service.get_activity |

## Security/Resiliency gates to satisfy in code
SECURITY-05 (validation) · -06 (scoped IAM in IaC) · -08 (fail-closed authz — Admin 403 BR-4, UGL/Member scoping BR-13) · -15 (global_handler, generic errors, fan-out failures caught individually) · RESILIENCY-10 (per-call timeouts + graceful per-section degrade, BR-9) · BR-7 (post-commit `MemberProfileUpserted` publish) · NFR-MP-MAINT-1 (degrade-path contract-test suite — mandatory, not optional).
