# Build and Test — Adjust Points screen rework (US-6.15)

**Executed**: 2026-08-11 · **Scope**: Unit 15 (Frontend SPA) only
**Change**: `aidlc-docs/construction/contributions-scoring/code/adjust-points-rework.md`

This is a change-scoped run. The project-wide instruction files in this directory
(`build-instructions.md`, `unit-test-instructions.md`, `integration-test-instructions.md`,
`performance-test-instructions.md`, `contract-test-instructions.md`,
`security-test-instructions.md`, `e2e-test-instructions.md`) apply unchanged — this change
adds no build step, no service, no dependency and no infrastructure, so none of them needed
editing. They were deliberately **not** overwritten.

---

## Build

| Gate | Command | Result |
|---|---|---|
| TypeScript | `cd frontend && npx tsc -b` | **Clean** |
| SPA build | `cd frontend && npm run build` | **Success** — 182 modules, 632.25 kB raw / 196.11 kB gzip, 627 ms |
| Backend build | not run | **N/A** — no Python, no CloudFormation, no dependency touched |

Vite's >500 kB chunk advisory appears, as it does on every build of this SPA. Pre-existing,
not introduced here.

### Bundle delta

| | Raw | Gzip |
|---|---|---|
| Before (recorded at the What's New increment) | 604.41 kB | 188.21 kB |
| After | 632.25 kB | 196.11 kB |
| **Delta** | **+27.84 kB** | **+7.90 kB** |

The increase covers the new modal, the ledger panel and the rules module. No test code
leaked into the bundle — `*.test.ts` files are excluded by Vite's entry graph, and the
`adjustPoints.ts` module is imported only by the two new components.

---

## Unit tests

| Suite | Tests | Result |
|---|---|---|
| `frontend` (vitest) | **118** | **pass** (was 71 — **+47**) |
| `platform` + 8 service suites (`make test`) | unchanged | **pass, no regression** |

`make test` was run end to end from the repository root and exited **0**.

### What the 47 new tests cover

| Area | Cases | Why it matters |
|---|---|---|
| `parseSignedDelta` | 24 | The explicit-sign rule (FR-8) and the **defect regression pin** |
| `sanitizeDeltaInput` | 6 | Invalid characters cannot reach state; magnitude deliberately not clamped |
| `groupOptionsFor` | 8 | DR-1 UGL narrowing, the no-group case, no id ever used as a label |
| `quarterTotal` | 5 | The impact preview's arithmetic, including a negative total (BR-J3) |
| `reversedIdsOf` | 5 | FR-14, including a reversal that was itself reversed |

The single most valuable assertion is in `parseSignedDelta`: it checks not only
`typeof value === "number"` but that `JSON.stringify({delta: value})` produces
`{"delta":10}`. The defect lived exactly at the serialisation boundary, and the backend
tests never cross it — they hand `AdjustmentService.adjust` a Python `int` directly. A type
assertion alone would have guarded the wrong thing.

---

## Contract tests

Run for completeness, **not because this change could affect them**:

```
analytics 5/5 · announcements 4/4 · certifications 13/13 · contributions-scoring 18/23
events 30/30 · forums 24/24 · help-assistant 1/1 · identity-access 29/30
member-profiles 5/5 · notifications 4/4 · search 1/1 · settings 12/12
```

**The two sub-100% results are not from this change.** `git status` confirms this change
modified nothing under `contracts/` or `services/` — its entire footprint is
`frontend/src/features/contributions/` (new), `frontend/src/features/ContributionsPage.tsx`,
`frontend/src/components/PeoplePicker.tsx`, and documentation. The working tree also carries
uncommitted identity-access and settings work from a prior session, which is where the
identity-access delta comes from; contributions-scoring 18/23 was already confirmed
pre-existing at HEAD by stashing during that session.

---

## Integration / performance / E2E

**Not run.** Unchanged from the project-wide position: no automated integration, performance
or E2E suite exists in this repository. This change introduces no cross-service coupling and
no new endpoint, so it adds no new integration surface — it consumes five endpoints that
were already live and already exercised.

---

## Security

| Check | Result |
|---|---|
| `ruff` | **N/A** — no Python touched |
| `cfn-lint` | **N/A** — no template touched |
| SECURITY-05 input validation | **Compliant** — client validation added; server validation unchanged and still authoritative |
| SECURITY-08 access control | **Compliant** — no authorization change. UI scoping is usability; the server still returns 403 for an out-of-scope group (BR-A5) |
| SECURITY-15 fail-safe | **Compliant** — the ledger read has explicit error handling and degrades the preview and reverse list without blocking the primary action |
| Dependency scan / SBOM / bandit | **Not run** — pre-existing project-level gaps, unchanged by this SPA-only change (no dependency added) |

No new dependency was installed. `package.json` is untouched.

---

## Manual test procedure — REQUIRED before this is called verified

No test renders the modal (no component-testing library in the repo), so the following need
a human pass on a deployed build. Each maps to a requirement that automation does not cover.

### As a Community Leader

1. Contributions → Approvals → **± Adjust points**
2. Type a partial name in Member. **Expect** a typeahead list; pick someone. → FR-1
3. **Expect** the Group dropdown to enable, list only that member's groups **by name**, and have **nothing preselected**. → FR-4, FR-5, NFR-6
4. Pick a group. **Expect** the current total for the current quarter, and the point history below it. → FR-11, FR-13
5. Type `10` in Point change. **Expect** rejection asking for an explicit sign, and Save disabled. → FR-8
6. Type `+10`. **Expect** the projected total = current + 10. → FR-11
7. Type letters and symbols. **Expect** they cannot be entered. → FR-8
8. Enter a reason and save. **Expect success — this is the case that has always returned 400.** → FR-7
9. Reopen for the same member and group. **Expect** the new entry in the history, and the total increased by 10.
10. Reverse that entry with a reason. **Expect** an opposite entry, and the original now showing a **Reversed** badge with no action. → FR-13, FR-14
11. Try to reverse the same original again — it should offer no button. If two browser tabs race it, **expect** "already reversed", not a raw error. → BR-J2
12. Pick a member in no group. **Expect** an explanatory block and Save disabled. → FR-6
13. Enter `-99999999`. **Expect** a message about the limit, with the number left as typed. → FR-9
14. Confirm no `m-…` or `g-…` id appears anywhere on the screen. → NFR-6

### As a User Group Leader

15. Repeat step 2. **Expect** only members of the group you lead to be findable. → FR-2
16. Pick a member who is in your group **and others**. **Expect** the dropdown to offer **only the group you lead**. → DR-1
17. Complete an adjustment. **Expect** success.
18. Confirm the quarter dropdown offers 8 quarters, newest first, current marked `(current)`. → FR-10

### Degradation

19. With the browser devtools blocking `GET /contributions/ledger`, select a member and group. **Expect** the preview to say the total is unavailable, the reverse list to explain it is unavailable, and **the adjustment to still be possible**. → FR-12, NFR-4

---

## Status

| | |
|---|---|
| Build | **Success** |
| Unit tests | **Pass** — 118 frontend, `make test` green repo-wide |
| Contract gate | **Unaffected** — no contract or service file touched |
| Integration / performance / E2E | **Not run** — no suites exist (unchanged) |
| Security | **Compliant** on the three applicable rules; project-level scan gaps unchanged |
| Manual verification | **OUTSTANDING** — 19 steps above |
| Deployed | **No** |

**Honest reading**: everything automatable about this change is automated and green, and the
rules that carry the behaviour are covered by 47 focused tests. What is not covered is the
wiring between those rules and the rendered form. Until someone walks the 19 steps on a
deployed build — step 8 in particular, which is the case that has never worked — this is
"built and gated", not "verified".
