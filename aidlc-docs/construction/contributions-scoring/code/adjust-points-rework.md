# Adjust Points screen rework — code summary (US-6.15)

**Date**: 2026-08-11
**Unit**: Unit 15 (Frontend SPA). Unit 7 consumed read/write, **not modified**.
**Plan**: `aidlc-docs/construction/plans/adjust-points-rework-code-generation-plan.md`

---

## What changed

### Created

| File | Purpose |
|---|---|
| `frontend/src/features/contributions/adjustPoints.ts` | All rules, React-free: `parseSignedDelta`, `sanitizeDeltaInput`, `groupOptionsFor`, `quarterTotal`, `reversedIdsOf` |
| `frontend/src/features/contributions/adjustPoints.test.ts` | **47 tests** over the above |
| `frontend/src/features/contributions/AdjustPointsModal.tsx` | The reworked form |
| `frontend/src/features/contributions/MemberLedgerPanel.tsx` | Point history + reverse-an-entry (FR-13/14/15) |

### Modified

| File | Change |
|---|---|
| `frontend/src/features/ContributionsPage.tsx` | `Approvals()` now takes `{ role, ledGroupId }`; the `FormModal` adjust block replaced by `AdjustPointsModal` |
| `frontend/src/components/PeoplePicker.tsx` | `PickedPerson` gained optional `groupIds`; `DirectoryHit` gained optional `memberGroupIds`; `add()` carries them through |
| `aidlc-docs/inception/user-stories/stories.md` | US-6.15 amended in place |
| `requirements/usecases/06-member-contribution-tracking.md` | US-6.15 amended in place |

`FormModal` is **still imported** in `ContributionsPage.tsx` — `MySubmissions` and `Framework` use it. The plan said to verify before removing; verified, and it stays.

---

## The defect this fixes

`FormModal` coerces only `checkbox` and `tags` field types; everything else is submitted as a string. `adjustPoints` requires `delta` to be an integer (`require_int` asserts `isinstance(value, int)`). The old screen therefore sent `"10"` and received **400 VALIDATION_ERROR on every attempt** — manual point adjustment had never worked through the UI since it shipped.

It survived because the backend tests call `AdjustmentService.adjust` directly with a Python `int`, so the serialisation boundary where the bug lived was never crossed in a test. `parseSignedDelta` now returns a number, and a test asserts both `typeof value === "number"` and that `JSON.stringify` emits `{"delta":10}` rather than `{"delta":"10"}`.

---

## Decisions taken during generation

**One deviation from the plan, and why.** The plan assumed the member's group ids were already in hand because directory rows carry `memberGroupIds`. They are — but `PeoplePicker` discards them, exposing only `{id, name, role}`. Two options: call `GET /members/{id}` after selection, or carry the field through the picker. Chose the picker, because `GET /members/{id}` runs a **4-way cross-service fan-out** (contributions, events, forums, certifications) to build a profile, which is a lot of work to learn a list of group ids. The change is three additive lines behind optional fields, so the three existing callers (`EventModal`, `EventManagePage`, `RevokeFlow`) are unaffected.

**`sanitizeDeltaInput` does not clamp magnitude.** It filters characters that cannot form a signed integer, but leaves an over-limit number intact so `parseSignedDelta` can explain the ±100000 bound. Clamping would rewrite what the leader typed without telling them.

**A reversing entry is itself reversible.** The server allows it (any ledger entry can be reversed once) and the UI does not prevent it. `reversedIdsOf` handles the chain, so reversing a reversal marks the reversal as reversed and stops there.

**Reverse uses `window.prompt` for the reason**, matching the existing approve/reject flow immediately above it in the same file rather than introducing a second confirmation idiom on one screen.

---

## Requirement coverage

FR-1..FR-16 all implemented. NFR-1 (one ledger read per member/group selection; typeahead debounced by `PeoplePicker`), NFR-4 (ledger read failure disables the preview and reverse list, never the adjustment), NFR-5 (labels bound via `htmlFor`, `aria-invalid`/`aria-describedby` on the delta field, errors as text), NFR-6 (`groupOptionsFor` emits names; an unresolvable group is labelled "Unnamed group", never an id), NFR-7 (47 tests).

NFR-2/NFR-3 are satisfied by *not* changing anything: server-side validation and authorization are untouched and remain the enforcement point. The UI scoping is usability only.

---

## Verification

- `npx tsc -b` — clean
- `npm test` — **118 passed** (was 71; +47)
- `npm run build` — clean
- `make test` — green repo-wide, no service-suite regression
- No raw `m-`/`g-` id rendered

## Not verified

**No test renders the modal.** The repo has no component-testing library, so the following are unproven by automation and need a human pass on the deployed screen:

- that the picker receives the right `groupId` scope for a UGL
- that Save is disabled in exactly the intended states
- that the preview renders the numbers it is handed
- the reverse round-trip against real data, including the 409 path

**Not deployed.** SPA-only, so deployment is `npm run build` + `aws s3 sync` (without `--delete`, excluding `config.json` — both mistakes have been made on this project before) + a CloudFront invalidation. No stack update.

**Unchanged limitation**: the in-portal notification of an adjustment (BR-N1) still is not delivered. `PointsAdjusted` is published exactly as before, but Notifications remains a mocked service.
