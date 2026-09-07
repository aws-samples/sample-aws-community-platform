# Code Generation Plan — Unit 4: Events

**Stage**: CONSTRUCTION → Code Generation · **Unit**: Events (21 stories, US-2.1–2.21)
Single source of truth for generating the real Events service (replaces the mock). Greenfield multi-unit (microservices) → code lives in `services/events/src/` and `services/events/tests/`. Markdown summaries in `aidlc-docs/construction/events/code/`. **Fourth real service** after Identity & Access, Member Profiles, and Settings.

## Context

**Stories**: all 21 (US-2.1 … US-2.21). No reassignments, no exclusions.

**Frozen contract (to be amended additively)**: `contracts/services/events/openapi.yaml` — 17 operations exist; 8 additive operations plus new optional query parameters and response fields are added. One **path change**: the public upload route becomes `POST /event-uploads/{token}` rather than `/public/event-uploads/{token}` (finding F1 — `/public` is claimed by Settings and `gen_api_edge.py` hard-fails on base-path collision).

**Permission matrix**: reused unchanged. The events rows already cover CL/UGL/Member; Administrator deliberately has no event permissions, which is what BR-A1 enforces.

**Conventions**: `src/_conventions/` copied verbatim from `services/identity-access/src/_conventions/` (no shared library, per FQ1). The Events service already has three of them; the full set is brought in.

**Design decisions carried forward**: D1–D12 (functional design), N1–N6 (NFR requirements), J1–J4 (NFR design), F1–F3 (infrastructure design).

**Downstream services still mocked**: Contributions & Scoring (point values), Notifications (email/.ics delivery), Announcements (event announcement). All three are consumed through their existing routes or via published events, so no change is needed here when they go real.

**Dependencies satisfied**: Identity & Access is real (publishes `GroupSoftDeleted`, provides JWT claims); Foundation provides the community bucket, bus, and API Gateway; Settings is real (Teams enablement flag).

---

## Steps

### Contract and scaffolding
- [x] **Step 1** — Contract amendment: `contracts/services/events/openapi.yaml`. Add 8 operations (`getEventIcs`, `getMaterialUploadUrl`, `replaceMaterial`, `removeMaterial`, `applyTeamsAttendance`, `importAttendanceCsv`, `listUploadLinks`, `revokeUploadLink`, `listUploadedFiles`, `publicUploadMint`); add optional query params to `listEvents`/`calendar`/`contentLibrary` (`q`, `type`, `deliveryMode`, `status`, `groupId`, `from`, `to`, `limit`, `cursor`); extend `Event`, `Rsvp`, `Material` schemas additively (description, durationMinutes, location, seriesId, counters, points, scanState, designations); add `UploadLink`, `UploadedFile`, `TeamsBatch`, `ImportReport` schemas; add the `/event-uploads/{token}` path. Bump to 2.0.0.
- [x] **Step 2** — `services/events/src/_conventions/` — copy the full convention set verbatim from `services/identity-access/src/_conventions/` (logger, errors, authz, validation, envelope, idempotency, config).
- [x] **Step 3** — `services/events/tests/` — create directory and `conftest.py` (moto DynamoDB table with all 4 GSIs, moto S3 bucket, fake `ContributionsClient`/`EventPublisher`/`TeamsProvider`/`SettingsCache`, principal factories per role).

### Business logic
- [x] **Step 4** — `models.py` — event-type and delivery-mode enums, status and scan-state enums, reminder lead-time map, id factories, `now_iso`, and serializers (`event_public`, `rsvp_public`, `material_public`, `upload_link_public`, `uploaded_file_public`, `teams_batch_public`, `listing`). US-2.1/2.13/2.14
- [x] **Step 5** — `recurrence.py` — `expand(frequency, start_date, end_date, repeats_on)` → occurrence timestamps; monthly end-of-month clamping; enforce the 104 cap with a `ValidationError`. US-2.3, BR-R1..R3
- [x] **Step 6** — `ics.py` — RFC 5545 `VEVENT` renderer with `METHOD:REQUEST`/`CANCEL`, text escaping (`,` `;` `\` newline), and 75-octet line folding. US-2.8, BR-N2/N5/N6
- [x] **Step 7** — `repository.py` — single-table access: event/RSVP/material/designation/upload-link/uploaded-file/Teams-batch/series/schedule/token-pointer CRUD; GSI1 scope-partition-walk listing with fetch-until-full and opaque cursor; GSI2 user-RSVP query; GSI3 content query; GSI4 due query; sparse index-key maintenance helpers. BR-S4, BR-V7, P-SCALE-1/2/3
- [x] **Step 8** — `providers.py` — `EventPublisher` (batches of 10, post-commit, never raises), `S3Storage` (presigned PUT/GET, list, delete, fail-closed), `ContributionsClient` (parallel timeout-bounded read + 60 s per-container cache), `TeamsProvider` (interface + stub adapter), `SettingsCache` (Teams flag, fail-closed to disabled). BR-P1, P-REL-1/2, D1, N6
- [x] **Step 9** — `event_service.py` — create, edit, cancel, complete, get, list, calendar; two-phase series creation (Provisioning → occurrences in batches of 25 → Active); scope filtering; lifecycle guards; `require_manage`. US-2.1/2.3/2.4/2.5/2.9/2.13/2.14/2.19, BR-A*/L*/R*/S*
- [x] **Step 10** — `rsvp_service.py` — record/change RSVP transactionally with counters; list; CSV export rows; invite/cancellation intents. US-2.6/2.7/2.8, BR-C*
- [x] **Step 11** — `attendance_service.py` — manual marking; CSV import with per-row report; Teams fetch → review batch → single apply; batched award publication; auto-completion. US-2.12/2.16/2.17/2.19, BR-T*/P*
- [x] **Step 12** — `material_service.py` — material CRUD; presigned PUT/GET with pre-validation; scan-state transitions; post-event notification; Content Library query. US-2.15/2.20, BR-M*/CL*
- [x] **Step 13** — `designation_service.py` — set presenters/organizers; `pointsEligible` from role; ineligibility reasons. US-2.18, BR-P3/P4
- [x] **Step 14** — `upload_link_service.py` — create/revoke; token hashing and constant-time verification; expiry, revocation and upload-count enforcement; public per-file mint; uploaded-file listing. US-2.21, BR-U*
- [x] **Step 15** — `reminder_service.py` — schedule-record write/maintain; due sweep with mark-before-emit; reminder/invite publication. US-2.2/2.10, BR-N*, P-REL-5
- [x] **Step 16** — `consumers.py` — `group_event_consumer` (`GroupSoftDeleted` → cancel that group's upcoming events) and `s3_object_consumer` (stamp `uploaded`/`sizeBytes`, scan-state transitions, sparse index-key maintenance, drop stale events). BR-X3/X4, BR-M6, P-SEC-3
- [x] **Step 17** — `app.py` — real Lambda handler: operation table for all 25 authenticated operations, plus five dispatch branches (authenticated HTTP, public HTTP, domain event, S3/GuardDuty event, scheduled sweep); `Context` wiring; fail-closed authz.

### Tests
- [x] **Step 18** — `test_recurrence.py`, `test_ics.py` — expansion including monthly clamping and the 104 cap; .ics folding, escaping, and CANCEL output.
- [x] **Step 19** — `test_repository.py` — index queries, scope partition walk, cursor round-trip, invalid cursor → 400, sparse key add/remove.
- [x] **Step 20** — `test_event_service.py` — create/edit/cancel/complete; **lifecycle-transition suite** (every illegal transition → 409, past-date guard); two-phase series creation including a simulated mid-write failure leaving a legible `Provisioning` series.
- [x] **Step 21** — `test_authz.py` — **authorization matrix suite**: every operation × every role × ownership combination, explicitly including Administrator denied on reads (BR-A1) and the demoted-creator-retains-rights rule (BR-A5), plus out-of-scope events returning 404 not 403.
- [x] **Step 22** — `test_rsvp_service.py` — yes/no, change, idempotency, counter accuracy, post-start rejection, invite/cancel intents.
- [x] **Step 23** — `test_attendance_service.py` — manual, CSV import report (matched/unmatched), Teams review-then-apply, re-apply → 409, no double-award, auto-completion, 1000-attendee ceiling.
- [x] **Step 24** — `test_material_service.py` — type/size validation before minting, scan-state gating (pending hidden, quarantined excluded), duplicate name → 409, delete-object-before-row ordering, Content Library search-first + filters + pagination.
- [x] **Step 25** — `test_upload_link_service.py` — token hashing and constant-time compare, expiry, revocation stops minting, upload cap, and the **indistinguishability test**: unknown, expired, and revoked tokens all return the same opaque 404.
- [x] **Step 26** — `test_reminder_service.py` — schedule creation, mark-before-emit ordering (no duplicate on crash), skip on cancel/disable, `dueAt` recompute on reschedule.
- [x] **Step 27** — `test_consumers.py` — `GroupSoftDeleted` cancels only upcoming events and is idempotent; S3 stamping, stale-event drop, prefix handling.
- [x] **Step 28** — `test_degrade.py` — **degrade-path suite**: Contributions 5xx/timeout → 200 with the points field omitted, never a 5xx; Teams disabled → 503 on Teams operations only; S3 failure → 502 on file operations with metadata reads unaffected.
- [x] **Step 29** — `test_app_routes.py` — route → status/schema for all operations; the five dispatch branches; public route behaviour.

### Infrastructure and artifacts
- [x] **Step 30** — `infra/services/service-events-data.yaml` — add GSI1–GSI4 with their attribute definitions. Template carries all four; the **deployment** is staged one index at a time (F2) and that is documented in the code summary, not enforced by the template.
- [x] **Step 31** — `infra/services/service-events-app.yaml` — handler → `app.handler`; memory 512, timeout 60; new parameters (`FileShareBucketName`/`Arn`, `ApiBaseUrl`, `PublicUploadBaseUrl`, `EventBusArn`, `RestApiId`); scoped IAM replacing `DynamoDBCrudPolicy`; three EventBridge rules (S3 objects prefix-filtered to `events/`, GuardDuty scan results, `GroupSoftDeleted`); one `AWS::Scheduler::Schedule`; six new alarms.
- [x] **Step 32** — `infra/foundation.yaml` — GuardDuty `MalwareProtectionPlan` + service role on the community bucket; lifecycle rules for `events/*/uploads/`.
- [x] **Step 33** — `infra/services/service-settings-app.yaml` — add the key-prefix filter to Settings' S3 rule (F3, cross-unit change).
- [x] **Step 34** — `infra/tools/gen_api_edge.py` — add `event-uploads` to `PUBLIC_BASES`; then regenerate `infra/api-edge.yaml`.
- [x] **Step 35** — `infra/root-template.yaml` — wire the new Events app-stack parameters.
- [x] **Step 36** — Published-event schemas — `contracts/services/events/published-events/`: `EventCreated`, `EventUpdated`, `EventCancelled`, `EventCompleted`, `AttendanceRecorded`, `EventDelivered`, `EventOrganized`, `EventReminderDue`, `MaterialsAdded` (9 files).
- [x] **Step 37** — `services/events/requirements.txt` (pinned `boto3`, `aws-lambda-powertools`; dev `pytest`, `schemathesis`, `moto`) + `services/events/README.md`.
- [x] **Step 38** — Regenerate the mock from the amended contract (`make generate-mocks SVC=events`) so the frontend keeps working until the real handler is deployed.
- [x] **Step 39** — `service-mode.json` → `events: complete` (only after the tests and the contract gate pass).

### Frontend
- [x] **Step 40** — `frontend/src/features/EventsPage.tsx` — rebuild: role-shaped list (leader `DataTable` in server mode with Scope column for CL only, search/status/type/group filters, series expand/collapse, confirmations, empty states) and member card grid with status tabs. Replaces the current mock-era single table. `data-testid` on every interactive element.
- [x] **Step 41** — `frontend/src/features/EventModal.tsx` (new) — create/edit with all mockup fields, CL select vs UGL readonly scope, recurrence sub-panel with client-side validation, member picker for presenters, announcement toggles, normalised reminder labels.
- [x] **Step 42** — `frontend/src/features/EventDetailPage.tsx` — rebuild to the member mockup: summary card, field grid, presenters with eligibility notes, materials with download/view, RSVP panel (Going / Not going, counts, points tag), Add-to-calendar panel.
- [x] **Step 43** — `frontend/src/features/EventManagePage.tsx` (new) — five stat cards + five tabs (Attendance, RSVP List, Materials incl. Upload Links, MS Teams, Designations).
- [x] **Step 44** — `frontend/src/features/EventCalendarPage.tsx` (new) — month grid with navigation, Month/Week/List views, type legend, clickable chips, CL-only group filter, empty month state.
- [x] **Step 45** — Supporting components — `AttendanceImportModal`, `TeamsReviewTable`, `DesignationsPanel`, `UploadLinksCard`, `MemberPicker`, `ContentLibraryTab`, `EventCard`.
- [x] **Step 46** — `frontend/src/App.tsx` + nav — add `/events/calendar` and `/events/:id/manage` routes; block Administrators from the Events section (BR-A1).
- [x] **Step 47** — `npm run build` + `tsc` clean.

### Verification and documentation
- [x] **Step 48** — Run `python3 -m pytest services/events -q` and fix; then `make test` repo-wide to confirm no regression in the other three real services.
- [x] **Step 49** — `make contract-tests SVC=events` (the deploy gate) + `ruff check .` + `cfn-lint` on every changed template.
- [x] **Step 50** — Documentation summary in `aidlc-docs/construction/events/code/README.md`, including the staged-GSI deployment runbook (F2) and the cross-unit changes (F1, F3).

**50 steps.** No deployment is performed — this stage produces code and templates only.

---

## File plan (application code)

```
services/events/
├── requirements.txt
├── README.md
├── src/
│   ├── app.py                     # REAL handler, 5 dispatch branches
│   ├── models.py
│   ├── recurrence.py
│   ├── ics.py
│   ├── repository.py
│   ├── providers.py               # EventPublisher, S3Storage, ContributionsClient, TeamsProvider, SettingsCache
│   ├── event_service.py
│   ├── rsvp_service.py
│   ├── attendance_service.py
│   ├── material_service.py
│   ├── designation_service.py
│   ├── upload_link_service.py
│   ├── reminder_service.py
│   ├── consumers.py
│   ├── mock_handler.py            # retained, no longer the entrypoint
│   ├── mock_runtime.py / *.json   # retained
│   └── _conventions/              # copied verbatim
└── tests/
    ├── conftest.py
    ├── test_recurrence.py       test_ics.py
    ├── test_repository.py       test_event_service.py
    ├── test_authz.py            test_rsvp_service.py
    ├── test_attendance_service.py
    ├── test_material_service.py test_upload_link_service.py
    ├── test_reminder_service.py test_consumers.py
    ├── test_degrade.py          test_app_routes.py
```

Frontend: `EventsPage.tsx` and `EventDetailPage.tsx` modified in place; `EventModal.tsx`, `EventManagePage.tsx`, `EventCalendarPage.tsx` and the supporting components created.

## Story traceability → modules

| Stories | Module |
|---|---|
| US-2.1, 2.4, 2.5, 2.19 | `event_service` |
| US-2.3 | `event_service` + `recurrence` |
| US-2.2, 2.10 | `reminder_service` |
| US-2.6, 2.7 | `rsvp_service` |
| US-2.8 | `ics` + `rsvp_service` + `event_service` |
| US-2.9, 2.13, 2.14 | `event_service` (calendar, list, get) |
| US-2.11 | `providers.SettingsCache` (flag owned by Settings) |
| US-2.12 | `attendance_service` + `providers.TeamsProvider` |
| US-2.15 | `material_service` + `providers.S3Storage` + `consumers.s3_object_consumer` |
| US-2.16, 2.17 | `attendance_service` + `providers.ContributionsClient` |
| US-2.18 | `designation_service` |
| US-2.20 | `material_service` (Content Library query) |
| US-2.21 | `upload_link_service` |

21 of 21 mapped.

## Gates to satisfy in code
SECURITY-05 (validation on every input) · SECURITY-06 (prefix-scoped IAM in the templates) · SECURITY-08 (three-layer fail-closed authz, single `require_manage`, 404-not-403) · SECURITY-11 (throttled public route) · SECURITY-13 (scan-state gating; audited create/revoke) · SECURITY-15 (global handler, generic errors, S3-delete-before-row) · RESILIENCY-10 (per-call timeouts, graceful degrade) · NFR-EV-MAINT-1 (the three mandatory suites: authorization matrix, lifecycle transitions, degrade path).
