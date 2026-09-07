# Code Generation Plan — Unit 9: Announcements

**Stage**: CONSTRUCTION → Code Generation (Part 1 — Planning) · **Unit**: Announcements
**This plan is the single source of truth for Part 2 generation.** Greenfield, microservices layout: backend in `services/announcements/`, frontend in `frontend/`, IaC in `infra/`, contracts in `contracts/`. Fifth→ sixth real service (after Identity, Members, Settings, Events).

## Unit context
- **Stories**: US-10.1 (create), US-10.2 (target), US-10.3 (manage edit/delete), US-10.4 (view panel), US-10.5 (dismiss — client-side).
- **Owns**: `announcements-<stage>` table + idempotency table. Publishes `AnnouncementPublished`. Consumes `EventCreated` (Events), `GroupSoftDeleted`/`GroupRestored` (Identity).
- **Dependencies**: Cognito authorizer (Unit 1, edge); Members/Groups read APIs (Unit 2/3, JWT-forwarded, fail-closed); EventBridge bus (Unit 1). No synchronous dependents.
- **Design inputs**: `functional-design/` (business-logic-model, business-rules BR-1..17, domain-entities E1..E4, frontend-components), `nfr-*` (patterns + logical components + infra). Two requirement deviations: mandatory expiry (default 2d/max 90d); UI-only dismissal (no server op/table).
- **Reference services**: Member Profiles (event_consumer, directory fan-out, repository) and Events (consumers, DirectoryClient, models) — mirror their module conventions and `_conventions/` shared copies.

## Backend module map (`services/announcements/src/`)
`app.py` (router + EventBridge branch) · `models.py` (item↔API shapes, target, derived status) · `announcement_service.py` (create/edit/delete/list, expiry default+clamp, denormalize, publish) · `panel_query.py` (view=panel targeting + active-set filter) · `sanitizer.py` (`nh3` allow-list) · `active_set_cache.py` (30s warm cache) · `directory_client.py` (author/group name, 1.5s fail-closed) · `consumers.py` (EventCreated auto-post; GroupSoftDeleted/GroupRestored) · `events_publisher.py` (AnnouncementPublished via `_conventions/envelope`) · `repository.py` (single table + idempotency + TTL) · `_conventions/*` (already present; take the superset incl. `ConflictError`).

---

## Steps

### Project structure / contract
- [ ] **Step 1 — Contract v2.0.0**: amend `contracts/services/announcements/openapi.yaml` — extended `Announcement` schema; structured `target{scope,groupIds}`; `body`, mandatory-server-defaulted `expiresAt`, `emailOptIn` on create; `title/body/target/expiresAt` on edit; `view`(panel|mine)+`scope`(all) query params on `listAnnouncements`; **remove `dismissAnnouncement`**. Add `contracts/services/announcements/published-events/AnnouncementPublished.v1.json`. *(US-10.1–10.5)*
- [ ] **Step 2 — Models** (`models.py`): announcement item ↔ `Announcement` API shape; `target` (in)/`source`+`audience` (out); derived `status` (Active/Expired); expiry default(+2d)/clamp(+90d) helpers; TTL epoch. *(US-10.1/10.2/10.3)*

### Business logic
- [ ] **Step 3 — Sanitizer** (`sanitizer.py`): `nh3` wrapper, tight allow-list (formatting + `http(s)` anchors forced `rel=noopener noreferrer`; strip scripts/handlers/`javascript:`/`data:`). *(NFR-AN-SEC-1)*
- [ ] **Step 4 — Repository** (`repository.py`): single-table CRUD; bounded Scan for active set; query-by-`authorId` (in-memory filter, no GSI); group hide/restore update; idempotency check-then-write; TTL attribute write. *(US-10.3/10.4, NFR-AN-DATA)*
- [ ] **Step 5 — DirectoryClient** (`directory_client.py`): `GET /members/{id}` + `GET /groups/{id}`, JWT-forwarded, 1.5s timeout, fail-closed to email/id / raw group id. *(NFR-AN-REL-1)*
- [ ] **Step 6 — ActiveSetCache** (`active_set_cache.py`): per-warm-container 30s TTL cache of the active set; miss → repository scan. *(NFR-AN-PERF-1)*
- [ ] **Step 7 — AnnouncementService** (`announcement_service.py`): create (authz CL/UGL, UGL target forced to ledGroupId, sanitize, expiry default/clamp, denormalize via DirectoryClient, persist, publish), edit (author-only, re-sanitize/clamp), delete (author or CL-moderation), list (view=mine / scope=all). *(US-10.1/10.2/10.3)*
- [ ] **Step 8 — PanelQuery** (`panel_query.py`): view=panel — resolve audience from claims (community + memberGroupIds + ledGroupId + CL-authored), filter active set by expiry + groupHidden, newest-first. *(US-10.4)*
- [ ] **Step 9 — EventsPublisher** (`events_publisher.py`): wrap+PutEvents `AnnouncementPublished`. *(BR-10)*
- [ ] **Step 10 — Consumers** (`consumers.py`): `EventCreated announce=true` → auto-post via AnnouncementService (idempotent on envelope id); `GroupSoftDeleted`/`GroupRestored` → set/clear groupHidden. *(BR-13/17)*
- [ ] **Step 11 — Router** (`app.py`): API GW proxy routing (list/create/edit/delete; **dismiss → 404/gone**) + EventBridge-rule branch to consumers; build Principal; fail-closed global handler; IDOR guard on edit/delete. *(all US; NFR-AN-SEC-3/4/7)*

### Tests (executed in Build & Test) — the 5 mandatory suites (NFR-AN-MAINT-1)
- [ ] **Step 12 — Authorization matrix** (`tests/test_authz.py`): CL/UGL/Member/Administrator × create/edit/delete/panel/mine; Administrator-denied-on-reads; UGL-target-forced; author-only-edit; CL-moderation-delete; IDOR guard.
- [ ] **Step 13 — Sanitization/XSS battery** (`tests/test_sanitizer.py`): script/handler/`javascript:`/`data:`/mXSS payloads stripped; safe formatting/links preserved.
- [ ] **Step 14 — Expiry** (`tests/test_expiry.py`): default +2d; clamp +90d; expired excluded from panel+count, shown Expired in view=mine.
- [ ] **Step 15 — Consumers** (`tests/test_consumers.py`): auto-post once + idempotent redelivery; announce=false no-op; group hide/restore.
- [ ] **Step 16 — Degrade + service/panel/repository** (`tests/test_degrade.py`, `test_announcement_service.py`, `test_panel_query.py`, `test_repository.py`): directory timeout → post succeeds fail-closed; panel targeting correctness; create/edit/delete; repository CRUD/active-set.

### Frontend (`frontend/src/`)
- [ ] **Step 17 — API + dismissal util**: extend `apiClient` usage; `lib/dismissedAnnouncements.ts` (localStorage set + prune). Add `dompurify` dep. *(US-10.5)*
- [ ] **Step 18 — AnnouncementModal + pickers** (`features/AnnouncementModal.tsx`, `AudiencePicker`, `ExpiryField`): CL community/multi-group (from `GET /groups`) / UGL readonly led-group; required expiry (default+2d, max+90d); email toggle; rich-text field. *(US-10.1/10.2)*
- [ ] **Step 19 — AnnouncementsPage rebuild** (`features/pages.tsx`): role-based management table (CL: +Audience col; UGL: no Audience), Created/Expiry/Email/Status cols, server-mode pagination, Edit(author)/Delete(author or CL-moderation), remove member dismiss button. *(US-10.3)*
- [ ] **Step 20 — AnnouncementPanel** (`components/AnnouncementPanel.tsx` + `AnnouncementCard`): collapsed card w/ active-count badge; meta `source · author (roleLabel) · date [· expires]`; DOMPurify-sanitized body render; ✕ dismiss (localStorage); embed on Member Home + CL/UGL dashboards. *(US-10.4/10.5, NFR-AN-SEC-2)*

### IaC + mock alignment + docs
- [ ] **Step 21 — `-data`**: add `TimeToLiveSpecification {AttributeName: ttl, Enabled: true}` to the main table in `service-announcements-data.yaml`. *(D-INFRA-1)*
- [ ] **Step 22 — `-app`**: handler→`app.handler`; add `ApiBaseUrl` param + env (`API_BASE_URL`, `ACTIVE_SET_CACHE_TTL_SECONDS`, `DIRECTORY_TIMEOUT_MS`); scoped IAM (own tables CRUD + events:PutEvents + execute-api:Invoke Members/Groups GET + sqs:SendMessage DLQ); `AWS::Events::Rule` (EventCreated announce=true + GroupSoftDeleted/GroupRestored) + SQS DLQ + Lambda permission; add throttle + DLQ-depth alarms. Wire `ApiBaseUrl` in `root-template.yaml`. Add `nh3` to `requirements.txt`. *(D-INFRA-2/3/4)*
- [ ] **Step 23 — Mock alignment**: update `mock_operations.json` (drop dismiss, reflect view/scope) + `fixtures.json` announcements shape so the contract-test harness passes against real shapes; `service-mode.json` → `announcements: complete`.
- [ ] **Step 24 — Docs**: `services/announcements/README.md`; markdown summary under `aidlc-docs/construction/announcements/code/`.

## Verification target (Build & Test)
`pytest` announcements suite green (5 mandatory suites) + repo-wide no regression; contract gate 12/12 (announcements ops incl. removed dismiss); ruff + cfn-lint clean; tsc + `npm run build` clean. Not deployed in this stage.

## Story traceability
US-10.1 → Steps 1,2,3,5,7,9,18,22 · US-10.2 → 1,2,7,8,18 · US-10.3 → 1,2,7,11,19 · US-10.4 → 4,6,8,11,20 · US-10.5 → 17,20 (client-side) · cross-cutting consumers/US-2.1 → 10.

## Checklist (Part 1)
- [x] Steps 1–9 (planning) of code-generation.md Part 1 executed; plan stored
- [x] Plan approved (2026-08-07)

## Part 2 — Generation: COMPLETE + APPROVED (2026-08-07)
All 24 steps executed. Summary: `../announcements/code/code-generation-summary.md`. Verification: pytest **46 passed**; ruff clean; cfn-lint clean; contract gate announcements **4/4** and all 12 services pass; `npm run build` clean (468.38 kB / 131.12 kB gzip). Not deployed.
- [x] Steps 1–2 Contract v2.0.0 + AnnouncementPublished schema + models
- [x] Steps 3–11 Backend modules (sanitizer, repository, directory_client, active_set_cache, service, panel_query, providers, consumers, app router)
- [x] Steps 12–16 Five mandatory test suites
- [x] Steps 17–20 Frontend (dismissal util + dompurify, AnnouncementModal, AnnouncementsPage rebuild, AnnouncementPanel on dashboard)
- [x] Steps 21–22 IaC (-data TTL, -app handler+EventRule+DLQ+ApiBaseUrl+IAM+alarms, root wiring)
- [x] Steps 23–24 Mock alignment + service-mode complete + README/summary
