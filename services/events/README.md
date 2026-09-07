# Events Service (Unit 4)

Real Python service for the Events & Meetups bounded context. Owns events, RSVPs,
attendance, materials metadata, designations and event-scoped external upload
links. Fourth real service, after Identity & Access, Member Profiles and Settings.

**Stories**: US-2.1 – US-2.21 (all 21). **Paths**: `/events`, plus the
unauthenticated `/event-uploads/{token}`. **Contract**:
`contracts/services/events/openapi.yaml` v2.0.0 (28 operations).

## Layout

| Module | Responsibility |
|---|---|
| `app.py` | Router. Four dispatch branches: authenticated HTTP, public upload mint, `GroupSoftDeleted`, S3/GuardDuty object events |
| `models.py` | Enums, transitions, serializers, and the three authorization predicates (`can_view`, `can_manage`, `visible_scopes`) |
| `recurrence.py` | Frequency expansion with month-end clamping and the 104 cap |
| `ics.py` | RFC 5545 renderer (escaping, 75-octet folding, REQUEST/CANCEL) |
| `repository.py` | Single-table access, GSI queries, scope partition walk, sparse index maintenance |
| `providers.py` | `EventPublisher`, `S3Storage`, `ContributionsClient`, `TeamsProvider`, `SettingsCache` |
| `event_service.py` | Create/edit/cancel/complete, listing, calendar, two-phase series creation |
| `rsvp_service.py` | RSVP with transactional counters, invite intents, .ics |
| `attendance_service.py` | Manual, CSV import, Teams review-then-apply, award publication |
| `material_service.py` | Materials, presigned URLs, scan-state gate, Content Library |
| `designation_service.py` | Presenters/organizers and completion-time awards |
| `upload_link_service.py` | Token-gated external upload links |
| `consumers.py` | Group soft-delete, S3 objects, GuardDuty scan results |

## Behaviour worth knowing before changing anything

**Administrators are denied on every operation, including reads.** The permission
matrix has zero event entries for that role and no mockup shows them an Events
nav item. Enforced once at the router boundary so a new operation cannot leak.

**A creator keeps edit/cancel rights after being demoted to Member.** Rights key
on the immutable `createdBy` (`models.can_manage`), which US-2.4 requires. It is
the only place a Member-role principal passes a leader-only check. Pinned by
`tests/test_authz.py::test_demoted_creator_retains_edit_rights`.

**Events outside your scope return 404, not 403**, so scope boundaries do not
disclose that an event exists.

**Point values are never stored.** They are read from Contributions per request,
cached 60 s per warm container, and **omitted** from the response when
unavailable. Absence is the degrade signal — emitting `0` would render "+0 pts".

**A Teams fetch awards nothing.** It writes a reviewable batch; awards happen only
on apply, and apply is guarded by a conditional update so two managers clicking
Apply cannot both award.

**Materials are invisible until scanned clean.** `PendingScan → Clean |
Quarantined`, driven by GuardDuty results on the shared bucket. Only `Clean`
materials are listed to members, downloadable, or indexed in the Content Library.

**Series creation is two-phase and not atomic.** `TransactWriteItems` caps at 100
items and the recurrence cap is 104, so the series row is written first as
`Provisioning`, then the occurrences, then flipped to `Active`. An interrupted
create is legible and resumable rather than leaving unexplained orphans.

**Every listing is an index query — never a Scan.** Treated as a hard rule
because it has already cost this repo twice (the Member Directory scan rework and
the File Share query against a non-existent index).

## Local development

```bash
python3 -m pytest services/events -q        # 243 unit tests
make contract-tests SVC=events              # the deploy gate (28/28)
ruff check services/events
```

Tests run in their own pytest process: services deliberately share top-level
module names (`app`, `models`, `repository`), so collecting two services in one
interpreter poisons imports.

`tests/conftest.py` creates the moto table **with all four GSIs**, matching
`infra/services/service-events-data.yaml`. Keep them in sync — the Settings
file-share defect (a live 500) happened precisely because the test table had an
index the deployed table did not.

## Deployment notes

Adding the four GSIs takes **four sequential stack updates** (one GSI change per
`UpdateTable`), and `UPDATE_COMPLETE` is **not** the readiness signal: a new index
is still backfilling at that point and a Query against it fails. GSI3 also needs a
one-off backfill for materials already attached to completed events. Full runbook:
`aidlc-docs/construction/events/infrastructure-design/deployment-architecture.md`.
