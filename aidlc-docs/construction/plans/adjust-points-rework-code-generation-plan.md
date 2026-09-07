# Code Generation Plan — Adjust Points screen rework (US-6.15)

**Unit**: Unit 15 (Frontend SPA). Unit 7 (Contributions & Scoring) is an unmodified dependency.
**Date**: 2026-08-11
**Requirements**: `aidlc-docs/inception/business-requirements/adjust-points-rework-requirements.md` (approved)
**Execution plan**: `aidlc-docs/inception/plans/adjust-points-rework-execution-plan.md` (approved)

**This plan is the single source of truth for Code Generation. Part 2 executes these steps in order and marks each `[x]` on completion. No work outside these steps.**

**STATUS: all 8 steps COMPLETE (2026-08-11).** One deviation, recorded in Step 3's note and in `aidlc-docs/construction/contributions-scoring/code/adjust-points-rework.md`: the plan assumed the member's group ids were already available, but `PeoplePicker` discards them, so the picker now carries them through in an optional field rather than the screen making a `GET /members/{id}` call that would trigger a 4-way cross-service fan-out.

---

## Unit context

| Aspect | Detail |
|---|---|
| Story | US-6.15 Manually Delete/Adjust Points (CL + UGL) |
| Code location | `frontend/src/` — workspace root. **Nothing** under `services/`, `contracts/`, `infra/`, `platform/` |
| Dependency units | Unit 7 (contributions-scoring), Unit 2 (identity-access), Unit 3 (member-profiles) — all `complete` mode, all **read-only consumed, none modified** |
| Contract changes | **None** (DR-3 revised at Workflow Planning) |
| Entities owned | None. The ledger entry written is the shape already written today |
| Business rules obeyed | BR-A5 (scoping), BR-J1 (append-only), BR-J2 (single-use reversal), BR-J3 (no floor), BR-J4 (8-quarter window) — all unchanged and enforced server-side |

### Endpoints consumed (all existing, all already routed)

| Call | Purpose | Requirement |
|---|---|---|
| `GET /members?q=&limit=10[&groupId=]` | Member typeahead; `groupId` scopes a UGL | FR-1, FR-2 |
| `GET /groups` | Resolve group ids to names | FR-4 |
| `GET /contributions/ledger?memberId=&groupId=` | History for the reverse list; source of the current-total sum | FR-11, FR-13 |
| `POST /contributions/adjustments` | The free ± adjustment | FR-7, FR-8 |
| `POST /contributions/adjustments/reverse` | Reverse a specific entry | FR-13, FR-15 |

### Conventions being followed (not invented)

- Single-select `PeoplePicker` with `groupId` scoping — exactly as `certifications/RevokeFlow.tsx` already does it
- Quarter `<select>` sourced from `trailingQuarters(8)` with the first option labelled `" (current)"` — as the My Contributions and Leaderboard tabs already do
- 300 ms debounce via the existing `useDebounced`
- Tests colocated as `src/**/*.test.ts`, pure modules only (jsdom environment, no component-testing library installed — see Step 9 note)
- `data-testid` on every interactive element, named `{component}-{role}`

---

## Steps

### Step 1 — Extract the pure logic into a testable module
- [x] Create `frontend/src/features/contributions/adjustPoints.ts` containing **no React**, so every rule is unit-testable without a DOM library:
  - `parseSignedDelta(raw)` → `{ ok: true, value: number } | { ok: false, reason: string }`. Requires an explicit leading `+` or `-` (FR-8, Q5=A), digits only after it, rejects a bare number with a message naming the missing sign, rejects `0`/`+0`/`-0` as non-zero (FR-9), rejects outside ±100000 (FR-9). Returns a **number**, which is what fixes the defect (FR-7).
  - `sanitizeDeltaInput(raw)` → strips anything that cannot form a signed integer, so unenterable characters never reach state (FR-8)
  - `groupOptionsFor({ memberGroups, allGroups, role, ledGroupId })` → `{ value, label }[]` using group **names** (FR-4, NFR-6), and for a UGL narrowed to their led group only (**DR-1**)
  - `quarterTotal(entries, groupId, quarter)` → sum of `points` (FR-11, **DR-2**)
  - `reversedIdsOf(entries)` → set of ids that already have a reversing entry, derived from each entry's `reverses` field (FR-14)
- [x] Story: US-6.15

### Step 2 — Business logic unit tests (the load-bearing step)
- [x] Create `frontend/src/features/contributions/adjustPoints.test.ts`:
  - `parseSignedDelta`: `+10` → `10`; `-5` → `-5`; **`10` rejected** (explicit-sign rule); `0`, `+0`, `-0` rejected; `+100001` rejected; `+`, `-`, `""`, `+1.5`, `+1e3`, `++1`, `1-` rejected
  - **`typeof value === "number"`** asserted explicitly — this is the regression pin for the live defect (FR-7, NFR-7)
  - `sanitizeDeltaInput`: letters/symbols dropped, sign kept only in first position
  - `groupOptionsFor`: CL sees all of the member's groups; **UGL sees only their led group** even when the member has several (DR-1); a member with no groups yields `[]` (feeds FR-6); labels are names, never `g-…` ids
  - `quarterTotal`: sums only the matching group and quarter; negative entries included; empty → 0
  - `reversedIdsOf`: an entry with a reversing entry is included; an unreversed entry is not; a reversal of a reversal handled
- [x] Story: US-6.15

### Step 3 — The AdjustPointsModal component
- [x] Create `frontend/src/features/contributions/AdjustPointsModal.tsx`, props `{ role, ledGroupId, onClose, onSaved }`:
  - **Member** — `PeoplePicker` single-select, `groupId={isUGL ? ledGroupId : undefined}` (FR-1, FR-2), hint wording distinguishing the two scopes
  - **Group** — `<select>` from `groupOptionsFor`, disabled until a member is picked, **no preselection** (FR-4, FR-5, DR-1). When the picked member has no groups, render the FR-6 block message and disable Save
  - **Quarter** — `<select>` of `trailingQuarters(8)`, current preselected and labelled `(current)` (FR-10)
  - **Point delta** — text input filtered through `sanitizeDeltaInput`, validated by `parseSignedDelta`, inline error text (FR-8, FR-9, NFR-5)
  - **Reason** — required textarea, max 1000 (mirrors the server)
  - **Impact preview** — current total for the chosen group+quarter and the projected total (FR-11); when the ledger read failed, show that the preview is unavailable and **still allow Save** (FR-12, NFR-4)
  - **Guidance note** — permanent/append-only, member notified in-portal, may go below zero (FR-16)
  - Submit posts `{ memberId, memberName, groupId, quarter, delta: <number>, reason }`; Save disabled unless member + group + valid delta + reason are all present
  - `data-testid`: `adjust-modal`, `adjust-member`, `adjust-group`, `adjust-quarter`, `adjust-delta`, `adjust-reason`, `adjust-submit`, `adjust-preview`, `adjust-no-groups`
- [x] Stories: US-6.15 (FR-1..12, FR-16)

### Step 4 — Member point history + reverse action
- [x] Create `frontend/src/features/contributions/MemberLedgerPanel.tsx`, rendered inside the modal once member and group are chosen:
  - Loads `GET /contributions/ledger?memberId=&groupId=` **once per member/group selection**, not per render (NFR-1)
  - `DataTable` of date, activity, points, source, quarter, reason
  - **Reverse** action per row; rows in `reversedIdsOf` render a "Reversed" badge and **no action** (FR-14)
  - Reverse prompts for a reason (FR-15) and posts `{ memberId, ledgerId, earnedDate, reason }`, mapping the row's `id` → `ledgerId`
  - A 409 from the server surfaces as "already reversed" and refreshes the list (BR-J2 remains the control)
  - Read failure disables this panel with an explanation and never blocks the free adjustment (FR-12, NFR-4)
  - The same fetched rows feed the Step 3 preview — **one read serves both** (DR-2)
  - `data-testid`: `adjust-ledger`, `adjust-reverse-{id}`
- [x] Stories: US-6.15 (FR-13, FR-14, FR-15)

### Step 5 — Wire it into the Approvals tab
- [x] Modify `frontend/src/features/ContributionsPage.tsx`:
  - `Approvals()` currently takes **no props** but needs the caller's role and led group — change to `Approvals({ role, ledGroupId })` and pass them from the `tab === "approvals"` branch (line ~63)
  - Replace the `FormModal` block (lines ~547–555) with `<AdjustPointsModal …>`
  - Remove the now-unused `FormModal` import **only if** nothing else in the file uses it (verify first — `MySubmissions` may)
  - Leave the pending-approvals `DataTable` and the decide flow untouched
- [x] Stories: US-6.15

### Step 6 — Requirement/story write-back
- [x] Amend `aidlc-docs/inception/user-stories/stories.md` US-6.15 in place with a dated note: the reverse-entry half is now built, and the delta defect is fixed
- [x] Amend `requirements/usecases/06-member-contribution-tracking.md` US-6.15 with the same note plus the mandatory-explicit-sign and impact-preview behaviours
- [x] Do **not** restate the story elsewhere — User Stories was deliberately skipped

### Step 7 — Documentation
- [x] Create `aidlc-docs/construction/contributions-scoring/code/adjust-points-rework.md` — what changed, the defect and why tests missed it, DR-1/DR-2/DR-3, the deviations, and what remains unverified
- [x] Update `aidlc-docs/aidlc-state.md`

### Step 8 — Verification (gates, run in this order)
- [x] `cd frontend && npx tsc -b` — clean
- [x] `cd frontend && npm test` — all pass, including the new cases
- [x] `cd frontend && npm run build` — clean; record the bundle delta
- [x] `make test` from the repo root — green repo-wide (8 service suites + frontend), proving no regression
- [x] Grep the changed files for `m-`/`g-` id leakage into rendered strings (NFR-6)
- [x] **Not run**: `ruff`/`cfn-lint` are no-ops here (no Python, no CloudFormation touched)

---

## Step 9 — Known limitation, stated up front

The repo has **no component-testing library** (`@testing-library/react` is not installed, and the What's New increment deliberately declined to add one). So Step 2 tests the extracted pure logic, which is where every rule in this change actually lives, but **no test renders the modal**. Specifically unproven by automated test: that the picker is wired to the right scope prop, that Save is correctly disabled, and that the preview renders the number it is given. These need a human pass on the deployed screen, and Step 7 records that.

I am not adding a test dependency unilaterally. Say so if you would rather I did.

---

## Story traceability

| Requirement | Step |
|---|---|
| FR-1, FR-2, FR-3 | 3 (picker + scope), 2 (scope logic) |
| FR-4, FR-5, FR-6, DR-1 | 1, 2, 3 |
| FR-7, FR-8, FR-9 | 1, 2 (incl. the defect regression pin) |
| FR-10 | 3 |
| FR-11, FR-12, DR-2 | 1, 2, 3, 4 |
| FR-13, FR-14, FR-15 | 4 |
| FR-16 | 3 |
| NFR-1 | 4 (single read per selection), 3 (debounce via PeoplePicker) |
| NFR-2, NFR-3 | No change by design — server validation and authorization untouched |
| NFR-4 | 3, 4 (degrade paths) |
| NFR-5 | 3 (labels, ARIA from PeoplePicker, text errors) |
| NFR-6 | 1 (name-based options), 8 (id-leak grep) |
| NFR-7 | 2, 8 |

**Total: 8 executable steps** (Step 9 is a stated limitation, not work). Files: 4 created, 3 modified, 1 documentation artifact.
