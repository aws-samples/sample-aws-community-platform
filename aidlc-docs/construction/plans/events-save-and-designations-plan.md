# Unit 4 Events — Event Save Fix + Presenter/Organizer Pickers (Change Request Plan)

**Status**: IMPLEMENTED — all gates green; awaiting user review (deployment separate)
**Date**: 2026-08-06
**Scope**: Unit 4 (Events service + contract) and Unit 15 (SPA). No IaC change expected.

## What was reported

1. As a CL or UGL, saving an Event fails.
2. Presenters / facilitators should be a searchable multi-select of members + UGLs + CLs,
   PLUS an external-presenter free-text entry. External presenters earn no points.
3. Organizers should be a searchable multi-select of members + UGLs + CLs.

## Diagnosis (verified, not assumed)

### D-1: UGL save failure — REPRODUCED, frontend defect
`EventsPage.tsx` renders `EventModal` with `groups={[]}` and never passes `ledGroupId`.
The modal therefore submits `groupId: null`, and the backend correctly returns
403 "User Group Leaders can only create events for the group they lead" (BR-A2/A3).
Reproduced through the real router with the byte-exact frontend payload:
UGL + `groupId=null` → 403 every time; UGL + led group id → 201. The UGL literally
cannot save an event from this UI.

### D-2: CL save — service layer ACCEPTS the same payload (201)
Same byte-exact payload as a CommunityLeader returns 201 locally, and the deployed
IAM policy (`service-events-app.yaml`) covers the whole create path
(PutItem, UpdateItem for the scope registry, events:PutEvents). The CL-side failure
is therefore NOT the service rejecting the write. Likely candidates:
(a) the Scope dropdown is also fed `groups={[]}`, so a CL cannot create a
group-scoped event at all — only "Community-wide"; (b) "startsAt must be in the
future" when picking a near/past time. Exact error message requested in the
questions file; the fix for (a) is in scope regardless.

### D-3: BR-P3 is silently not enforced (found during diagnosis)
`app.py` wires `DesignationService` WITHOUT a `role_lookup`, so the default
`lambda user_id: "Member"` marks EVERY designee — including leaders — as
points-eligible. The designation rework must carry a real role source or the
"external presenters don't earn points / leaders don't earn" rules are fiction.

## Design decisions (see questions file)

- **Q1**: exact CL error message (to confirm D-2 is fully covered).
- **Q2**: contract shape for external presenters (recommended: additive
  `externalPresenters: string[]` alongside the existing `presenters: string[]`,
  so nothing existing breaks and the mock/contract gate stays additive).
- **Q3**: where the designee's role comes from (recommended: server-side read-time
  lookup, not a client-supplied role — a client-supplied role would let any leader
  mark anyone points-eligible).

## Execution checklist

### A. Fix the save path (SPA)
- [x] A1. `EventsPage`/`EventManagePage`: pass `ledGroupId` (already on the session
      since the My Group change) into `EventModal`; UGL create pre-fills and locks
      scope to the led group.
- [x] A2. Feed the CL Scope dropdown real groups (`GET /groups`, already live) —
      replaces the hardcoded `groups={[]}`.
- [x] A3. Edit mode: same wiring so a UGL edit doesn't null the scope.

### B. Contract (additive, v2.x)
- [x] B1. `EventInput`/`RecurringEventInput`/`setDesignations` body gain
      `externalPresenters: string[]` (names). `presenters`/`organizers` stay
      arrays of user ids (per Q2 recommendation).
- [x] B2. `Designation` schema gains `displayName` (so the UI can render people,
      not ids) and `external: boolean`.
- [x] B3. Regenerate the events mock; contract gate must stay green for all 12
      services. No new base path → no api-edge regen.

### C. Events service
- [x] C1. `DesignationService`: accept external presenter names —
      stored as designation rows with `external=true`, `pointsEligible=false`,
      `ineligibleReason="External presenters do not earn points."` External
      entries are presenter-only (organizers are portal users per the request).
- [x] C2. Wire a REAL `role_lookup` per Q3 decision; `pointsEligible` computed
      from the looked-up role (BR-P3), never from client input.
- [x] C3. Store `displayName` on designation rows at designation time
      (denormalised, same pattern as RSVP rows) so reads stay fan-out-free.
- [x] C4. Validation: reject empty/whitespace external names; cap list sizes
      (25 designees per kind — matches the designation counts pattern).
- [x] C5. Tests: external-presenter never eligible; leader designee never eligible
      once C2 lands (this flips the current default-Member behavior — existing
      tests asserting eligibility for unlooked-up users get updated deliberately);
      authorization matrix untouched.

### D. Pickers (SPA)
- [x] D1. New `PeoplePicker` component: debounced typeahead against
      `GET /members?q=&limit=10` (directory already includes Members, UGLs, CLs
      and returns role), multi-select chips, keyboard accessible.
- [x] D2. `EventModal`: replace both comma-separated-ID inputs with `PeoplePicker`;
      presenters panel gains "Add external presenter" text box → chips marked
      "External — no points". Non-Member picks show a "no points (leader)" hint
      at selection time (closes the G9 gap properly).
- [x] D3. `EventManagePage` Designations tab: same components, same payload;
      renders `displayName` instead of raw ids.
- [x] D4. Edit/manage flows prefill pickers from `listDesignations`.

### E. Verification gate (all must pass before completion is claimed)
- [x] E1. events pytest suite (incl. new designation tests) green; repo-wide
      `make test` green, no regressions.
- [x] E2. Contract gate 12/12; ruff, cfn-lint, tsc, `npm run build` clean.
- [x] E3. Reproduction payloads: UGL create → 201 (was 403); CL group-scoped
      create → 201.

### F. Docs/state
- [x] F1. aidlc-state.md row + audit.md entries; functional-design
      business-rules note for the external-presenter rule (BR-P3 extension).

**Deployment**: NOT part of this plan (Events is live on dev; a redeploy of
service-events-app + SPA republish is needed after approval of the completed work).
