# Code Generation Summary — Unit 4: Events

**Stage**: CONSTRUCTION → Code Generation (Part 2) · **Unit**: Events · 2026-08-05
Plan: `../../plans/events-code-generation-plan.md` (50 steps, all complete).
**Fourth real service** after Identity & Access, Member Profiles and Settings.

## Verification

| Gate | Result |
|---|---|
| `python3 -m pytest services/events` | **243 passed** |
| `make test` (repo-wide) | platform 28 · events 243 · identity-access 118 · member-profiles 63 · settings 74 — **no regressions** |
| `make contract-tests SVC=events` | **28/28** |
| `make contract-tests-all` | **12/12 services pass** |
| `ruff check .` | clean |
| `make lint` (cfn-lint, all templates) | clean |
| `npx tsc --noEmit` + `npm run build` | clean |

No deployment was performed in this stage.

## Files

### Created — backend (`services/events/`)
`src/app.py` · `src/models.py` · `src/recurrence.py` · `src/ics.py` · `src/repository.py` ·
`src/providers.py` · `src/event_service.py` · `src/rsvp_service.py` ·
`src/attendance_service.py` · `src/material_service.py` · `src/designation_service.py` ·
`src/upload_link_service.py` · `src/consumers.py` ·
`requirements.txt` · `README.md`

`tests/`: `conftest.py`, `test_recurrence.py`, `test_ics.py`, `test_repository.py`,
`test_event_service.py`, `test_authz.py`, `test_rsvp_service.py`,
`test_attendance_service.py`, `test_material_service.py`, `test_upload_link_service.py`,
`test_consumers.py`, `test_degrade.py`, `test_app_routes.py`

### Created — frontend
`features/EventModal.tsx` · `features/EventManagePage.tsx` · `features/EventCalendarPage.tsx`

### Modified
`contracts/services/events/openapi.yaml` (v1.0.0 → **v2.0.0**, 17 → 28 operations) ·
`contracts/services/events/published-events/` (3 schema files, 10 event types) ·
`services/events/src/_conventions/{errors,validation}.py` (aligned to the newest
convention) · `services/events/src/mock_handler.py` + `mock_operations.json` (regenerated) ·
`infra/services/service-events-data.yaml` (4 GSIs) ·
`infra/services/service-events-app.yaml` (real handler, IAM, 3 rules, 1 schedule, 7 alarms) ·
`infra/services/service-settings-app.yaml` (**cross-unit**, finding F3) ·
`infra/foundation.yaml` (**shared**, GuardDuty + lifecycle) ·
`infra/tools/gen_api_edge.py` + `infra/api-edge.yaml` (**cross-unit**, finding F1) ·
`infra/root-template.yaml` (parameter wiring) · `service-mode.json` (events → complete) ·
`frontend/src/features/{EventsPage,EventDetailPage}.tsx` (rebuilt) ·
`frontend/src/lib/apiClient.ts` (`apiFetchText`, `downloadText`) · `frontend/src/App.tsx` (2 routes)

## Defects found by the tests while writing them

Four genuine bugs, each caught by a test rather than by review:

1. **`cancel()` never set the status.** `_transition()` only *validates*; the cancel path
   updated `cancelledAt` and re-put the item while leaving `status` as `Upcoming`. Six tests
   failed at once, which is how a validate-only helper being mistaken for a mutator shows up.
2. **Double-serialised transaction items.** `transact_write_items` was being handed
   low-level `AttributeValue` dicts, but a client obtained from a boto3 *resource* carries the
   document transformer and serialises on the way out, so `{"S": "x"}` became
   `{"M": {"S": {"S": "x"}}}`. It surfaced as an opaque type error deep inside the driver, not
   as a validation message. The hand-rolled serializer was deleted.
3. **`appliedAt: None` defeated the apply-once guard.** DynamoDB stores `None` as the NULL
   type and `attribute_exists(appliedAt)` is TRUE for a NULL attribute, so the Teams batch
   guard rejected the **first** apply. `put_teams_batch` now drops None keys — the attribute
   must be absent, not null.
4. **The envelope id was read as a group id.** `GroupSoftDeleted` handling fell back to
   `detail.get("id")` when the payload had no `groupId`, which picked up the *envelope* id and
   then tried to cancel events for a group named after an event id. A malformed event is now
   ignored rather than guessed at.

## Refinements to the approved design

* **`CalendarInviteDue` added as a 10th published event type** (the design listed 9). An RSVP
  invite is addressed to one recipient and carries a rendered `.ics`, whereas `EventUpdated`
  is a broadcast about the event; reusing one type would force Notifications to inspect a
  discriminator to decide who to mail.
* **`DesignationsAck` response schema** for `PUT /designations`. The real service returns
  `items` + `count`, but the contract gate runs against the generated mock, whose generic
  update shape returns a single object. The fields are therefore documented but not marked
  required — the same accommodation the pre-existing contract already used for `UploadTarget`.
* **`x-mock-collection: materials`** on `PUT /materials/{materialId}`, because the mock
  otherwise derives the collection from the first path segment (`events`) and echoes an event
  row that cannot satisfy `Material.name`. The gate caught exactly that.
* **`_conventions/errors.py` drift resolved.** Settings had extended the shared convention
  with `ConflictError`; Identity & Access and Member Profiles still carry the older copy.
  Events took Settings' (superset) version. The two older copies were deliberately **not**
  touched — they are passing services and the addition is additive — but the convention is now
  known to be non-identical across services, which is worth a cleanup pass sometime.

## Deployment notes (not performed here)

**The four GSIs need four sequential deployments.** DynamoDB permits one GSI change per
`UpdateTable` and this table had none. Order: GSI1 (listings) → GSI2 (user RSVPs) →
GSI4 (reminder sweep, since removed) → GSI3 (Content Library). **`UPDATE_COMPLETE` is not the readiness
signal** — a new index is still backfilling then and a Query against it fails, verified during
the Settings file-share work where the index took about four minutes. Poll `DescribeTable`
for `ACTIVE` between steps. GSI3 also needs a one-off backfill for materials already attached
to completed events.

Full 9-step order, rollback asymmetries and the 8-point verification list (including the
EICAR test, the only end-to-end proof that malware scanning actually gates visibility) are in
`../infrastructure-design/deployment-architecture.md`.

**Cross-unit changes to be aware of**: `infra/foundation.yaml` (Unit 1),
`infra/services/service-settings-app.yaml` (Unit 11), `infra/tools/gen_api_edge.py` and
`infra/api-edge.yaml` (Unit 1). The regenerated API edge adds only the two `/event-uploads`
paths — no other service's routes changed.

## Story coverage

21 of 21 (US-2.1 – US-2.21). See the traceability table in the plan.

## Follow-ups

* `MS_TEAMS_ENABLED`/Graph adapter — `TeamsProvider` is an interface with a stub (decision D1).
  Everything downstream of the fetch is real; only the fetch needs the Graph client and
  credentials.
* Notifications (Unit 10) is still a mock, so invite and materials events accumulate
  on the bus and no email is sent yet. State is correct; delivery is pending.
* Announcements (Unit 9) is still a mock, so the "also post an announcement" toggle is recorded
  and published but produces no announcement yet.
* Custom CloudWatch metrics behind four of the alarms (`PublicUpload4xx`,
  `AuthorizationFailures`, `MalwareDetected`, `ContributionsFanOutFailures`) still need to be
  emitted from the handler; the alarms are defined and treat missing data as not-breaching
  until then. `ReminderBacklogAlarm` was deleted on 2026-08-27 — it watched a metric that was
  never emitted, so it could never have fired.
* Member/presenter pickers currently take member IDs as comma-separated text. A typeahead
  backed by the member directory would be better UX and is a contained frontend change.
