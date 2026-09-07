# Content Library Rework — Execution Plan

## Detailed Analysis Summary

### Transformation Scope
- **Transformation Type**: Feature rework within existing service boundary
- **Primary Changes**:
  - Drop existing GSI3 index and related code from Events service
  - Add new `library` module to Events service (new table, new handlers, new API routes)
  - Extend Events service: mandatory description enforcement on Complete operation
  - Extend Contributions service: Library opt-in at contribution approval
  - Frontend: remove Content Library tab from Events pages; add standalone `/content-library` page
- **Related Components**: Events service, Contributions service, Frontend SPA, API edge config

### Change Impact Assessment
- **User-facing changes**: Yes — removes Events tab, adds top-level nav item `/content-library`
- **Structural changes**: Yes — new DynamoDB table, new API routes, new service module
- **Data model changes**: Yes — new `RESOURCE#<id>` item type in new `library-${Stage}` table; GSI3 removed from Events table
- **API changes**: Yes — `GET /events/content-library` removed; new `GET /library`, `POST /library`, `PUT /library/{id}`, `DELETE /library/{id}` routes added
- **NFR impact**: Yes — PITR on new table; file scan gate reused; presigned URL pattern reused

### Component Relationships
- **Primary**: `services/events/src/library_service.py` (new module)
- **Modified**: `services/events/src/app.py` (new routes), `services/events/src/repository.py` (GSI3 removal, new library repository), `services/events/src/material_service.py` (Path 1 auto-promote hook), `services/events/src/event_service.py` (mandatory description on complete)
- **Modified**: `services/contributions/src/` (Path 2 opt-in at approval)
- **Infrastructure**: `infra/services/service-events-data.yaml` (new library table, GSI3 removal), `infra/services/service-events-app.yaml` (new routes/IAM)
- **Frontend**: `frontend/src/features/EventsPage.tsx` (remove tab), `frontend/src/features/ContentLibraryPage.tsx` (new), `frontend/src/App.tsx` (new route)
- **Contract**: `contracts/services/events/openapi.yaml` (remove contentLibrary op, add library ops)

### Risk Assessment
- **Risk Level**: Medium
- **Rollback Complexity**: Moderate — table drop/recreate is clean; GSI3 removal is a schema change
- **Testing Complexity**: Moderate — three entry paths, cross-service integration (Path 2)
- **Schema migration**: None needed — user confirmed no live data to preserve

---

## Workflow Visualization

```
INCEPTION PHASE
  [x] Workspace Detection       COMPLETED
  [x] Reverse Engineering       SKIPPED (artifacts current)
  [x] Requirements Analysis     COMPLETED
  [ ] User Stories              SKIP
  [x] Workflow Planning         IN PROGRESS
  [ ] Application Design        SKIP
  [ ] Units Generation          SKIP

CONSTRUCTION PHASE — 1 Unit: "Content Library Rework"
  [ ] Functional Design         EXECUTE
  [ ] NFR Requirements          SKIP
  [ ] NFR Design                SKIP
  [ ] Infrastructure Design     EXECUTE
  [ ] Code Generation           EXECUTE (always)
  [ ] Build and Test            EXECUTE (always)

OPERATIONS PHASE
  [ ] Operations                PLACEHOLDER
```

---

## Phase Decisions

### INCEPTION PHASE

| Stage | Decision | Rationale |
|---|---|---|
| Workspace Detection | COMPLETED | Done |
| Reverse Engineering | SKIPPED | Artifacts current; codebase well-understood |
| Requirements Analysis | COMPLETED | Done |
| User Stories | **SKIP** | No new user personas; change is a feature rework, not a new product capability requiring story-level acceptance criteria. Existing stories cover the contribution approval flow. |
| Workflow Planning | IN PROGRESS | This document |
| Application Design | **SKIP** | No new services or cross-service component topology changes. The Library module lives within the Events service boundary. Component methods are well-understood from the requirements. |
| Units Generation | **SKIP** | Single unit of work — the entire Content Library rework is one cohesive change across Events service + Contributions service + frontend. No decomposition needed. |

### CONSTRUCTION PHASE — Unit: "content-library-rework"

| Stage | Decision | Rationale |
|---|---|---|
| Functional Design | **EXECUTE** | New `library_service.py` module with three entry paths, new data model, tag normalization, search logic, and cross-service Path 2 integration. Business logic needs explicit design before code. |
| NFR Requirements | **SKIP** | Existing NFR decisions (Security=Yes, Resiliency=Yes) apply. Scan gate, PITR, presigned URLs, and search-first pattern are already established patterns in this codebase. No new NFR decisions needed. |
| NFR Design | **SKIP** | NFR patterns are reused verbatim from Events service (scan gate, presigned URLs, PITR). No new patterns to design. |
| Infrastructure Design | **EXECUTE** | New DynamoDB table, GSI removal from Events table, new IAM permissions, new API routes, EventBridge integration for Path 2. Infrastructure has enough new surface to warrant explicit design. |
| Code Generation | **EXECUTE** | Always executes |
| Build and Test | **EXECUTE** | Always executes |

---

## Module Change Sequence

Given cross-service dependency (Path 2 requires Contributions to notify Library), the recommended
sequence within Code Generation is:

1. **Events service — Library module** (library_service.py, library_repository.py, app.py routes, GSI3 removal, description enforcement on complete)
2. **Contributions service** (approval opt-in, EventBridge publish or direct API call — resolved in Functional Design D3)
3. **Frontend** (ContentLibraryPage, remove Events tab, nav wiring)
4. **Infrastructure** (new table, IAM, routes, contract)
5. **Tests** (unit + contract for all three paths)

---

## Success Criteria

- `GET /library?q=serverless` returns matching resources across all three sources
- Event completion auto-promotes all clean materials (Path 1); empty description blocks completion
- CL/UGL contribution approval shows Library opt-in; opted-in resources appear in Library (Path 2)
- CL/UGL direct add form creates resource immediately (Path 3)
- Quarantined files not downloadable; Clean files get presigned GET URL
- `/content-library` nav item visible to Member, UGL, CL; hidden from Administrator
- Events page Content Library tab removed
- All existing Events service tests continue to pass
- GSI3 attributes absent from all new material writes

---

## Open Design Decisions (to resolve in Functional Design)

| # | Decision |
|---|---|
| D3 | Path 2 integration: EventBridge (Contributions publishes `ContributionAddedToLibrary`) vs direct API call from approval UI to Library API |
| D4 | Topics autocomplete: dedicated `TAGS#` singleton item updated on each write vs GSI on library table scanning distinct `topics` values |
