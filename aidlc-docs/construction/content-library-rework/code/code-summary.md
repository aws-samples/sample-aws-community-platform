# Code Summary — Content Library Rework

## New Files Created (7)

### Backend
- `services/events/src/library_repository.py` — DynamoDB access for library table (GSI1/2/3, TAGS#ALL)
- `services/events/src/library_service.py` — Business logic: 3 entry paths, search, tags, curation
- `services/events/src/library_consumers.py` — ContributionApprovedConsumer (Path 2 / EventBridge)

### Frontend
- `frontend/src/features/ContentLibraryPage.tsx` — Standalone /content-library page
- `frontend/src/components/TopicTagInput.tsx` — Autocomplete tag input (multi + single mode)
- `frontend/src/components/LibraryAddResourceModal.tsx` — Path 3 curator direct add modal
- `frontend/src/components/EditResourceModal.tsx` — Curator edit resource modal

## Modified Files (13)

### Backend
- `services/events/src/app.py` — Routes, Context wiring, ContributionApproved dispatch, removed contentLibrary
- `services/events/src/event_service.py` — Mandatory description on complete, Path 1 promotion trigger, library injection
- `services/events/src/material_service.py` — Auto-removal on delete, removed content_library(), library injection
- `services/events/src/consumers.py` — library/ prefix routing, Path 1 scan-clean promotion
- `services/events/src/repository.py` — Removed GSI3 methods (_apply_content_index, refresh_content_index, query_content_page), cleaned _CURSOR_ATTRS
- `services/contributions-scoring/src/submission_service.py` — ContributionApproved event publish on approval

### Infrastructure
- `infra/services/service-events-data.yaml` — New library table + 3 GSIs, GSI3 removed from events table
- `infra/services/service-events-app.yaml` — Library params/conditions/IAM/env, ContributionApproved rule, extended prefix filters, new alarm
- `infra/root-template.yaml` — LibraryTableName/Arn passed to EventsApp

### Frontend
- `frontend/src/App.tsx` — ContentLibraryPage import + route
- `frontend/src/roles.ts` — Content Library nav item added for Member, CL, UGL
- `frontend/src/features/EventsPage.tsx` — Removed Content Library tab + ContentLibraryTab component

## New Test Files (4)

- `services/events/tests/test_library_service.py` — 40 tests: search, Path 1, Path 2, Path 3, curation, tags
- `services/events/tests/test_library_consumers.py` — 5 tests: ContributionApprovedConsumer
- `services/events/tests/test_event_complete_description.py` — 5 tests: mandatory description on complete
- `services/contributions-scoring/tests/test_submission_library_optin.py` — 5 tests: Library opt-in at approval

## Story Coverage

| Story | Status | Key files |
|---|---|---|
| US-2.19 — Mandatory description on complete | ✅ | event_service.py, test_event_complete_description.py |
| US-2.20 — Standalone Content Library browse/search | ✅ | library_service.py, ContentLibraryPage.tsx, app.py |
| US-2.22 — Path 1 auto-promotion | ✅ | library_service.py, event_service.py, consumers.py |
| US-2.23 — Path 3 curator direct add | ✅ | library_service.py, LibraryAddResourceModal.tsx |
| US-2.24 — Path 2 member contribution opt-in | ✅ | library_consumers.py, submission_service.py, EditResourceModal.tsx |
| US-2.25 — Curator edit and delete | ✅ | library_service.py, EditResourceModal.tsx |
| US-2.26 — Topics autocomplete | ✅ | library_service.py, TopicTagInput.tsx |
