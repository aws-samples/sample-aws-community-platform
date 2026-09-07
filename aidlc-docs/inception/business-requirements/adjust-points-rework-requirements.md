# Requirements — Adjust Points screen rework (US-6.15)

**Date**: 2026-08-11
**Units affected**: Unit 7 (Contributions & Scoring), Unit 15 (Frontend SPA)
**Story**: US-6.15 Manually Delete/Adjust Points — amended, not replaced
**Source**: change request logged in `audit.md` 2026-08-11T12:15:00Z; decisions from `adjust-points-rework-questions.md` (all 8 answered A)

---

## 1. Intent analysis

| Aspect | Assessment |
|---|---|
| User request | Rework Contributions ▸ Approvals ▸ Adjust Point: searchable member, populated selectable group, quarter dropdown, sign-constrained point delta |
| Request type | **Enhancement** (usability rework of a shipped screen) + **Bug fix** (the screen is currently non-functional) + **Gap closure** (the unbuilt half of US-6.15) |
| Scope | **Single component** — the SPA screen only. No contract, service or infrastructure change (see DR-3, revised at Workflow Planning) |
| Complexity | **Moderate** — no new business rules, no new data, no new authorization; complexity is in the interaction design and in reusing existing services correctly |
| Requirements depth | **Standard** |
| Risk | **Low-to-moderate.** Writes land in an append-only ledger that cannot be edited or deleted (BR-J1), so a mistake made through this form is permanent and correctable only by a compensating entry. That is precisely why the guard rails below matter. |

### Why this is partly a bug fix

The shared `FormModal` component coerces only `checkbox` and `tags` field types; every other value is submitted as a JSON string. `adjustPoints` requires `delta` to be an integer (`require_int` asserts `isinstance(value, int)`). The deployed screen therefore sends `"10"` and receives **400 VALIDATION_ERROR on every attempt** — manual point adjustment has never worked through the UI. Backend tests pass `delta` as a Python `int` directly into `AdjustmentService`, which is why the suite is green and this survived to production. Requirement **FR-7** closes it and **FR-13** stops it recurring.

---

## 2. Functional requirements

### Member selection

- **FR-1** — The Member field MUST be a searchable typeahead over the member directory, not a free-text id box. The leader searches by name or email and selects a result; the internal member id MUST NOT be typed or displayed.
- **FR-2** — Search scope is role-dependent (Q1=A): a **Community Leader** searches the whole community; a **User Group Leader** searches **only members of the group they lead**, achieved by scoping the directory query itself so an out-of-scope member is never offered.
- **FR-3** — FR-2 is a usability layer only. The server-side authorization check (CL any group, UGL led group only, BR-A5) remains the control and MUST NOT be weakened or relied upon less (SECURITY-08).

### Group selection

- **FR-4** — The Group field MUST be a dropdown populated from the groups the **selected member actually belongs to**, showing group **names**, never raw `g-…` ids. It is empty and disabled until a member is chosen.
- **FR-5** — Where the member belongs to more than one group, the dropdown MUST have **no preselected value** (Q2=A); the leader picks the group deliberately. This is a deliberate friction: the group determines which total and which quarterly tier the adjustment moves.
- **FR-6** — Where the selected member belongs to **no group**, the form MUST block submission with the explanation that the member is in no user group, and MUST NOT offer a community-wide or arbitrary-group fallback (Q3=A).

### Point delta

- **FR-7** — The delta MUST be transmitted as a **JSON integer**, not a string. This is the defect fix.
- **FR-8** — The delta field MUST accept **only an explicit sign followed by digits** (Q5=A). `+10` and `-5` are valid; a bare `10` is rejected with a message asking for an explicit sign. Characters that cannot form a valid signed integer MUST NOT be enterable.
- **FR-9** — Client-side validation MUST mirror, not replace, the server rules: non-zero, within ±100000. The server remains authoritative.

### Quarter

- **FR-10** — The Quarter field MUST be a dropdown of the current quarter plus the previous 7 (BR-J4), newest first, with the **current quarter preselected and labelled "(current)"** (Q4=A), matching the pickers already on the My Contributions and Leaderboard tabs. Format stays canonical `YYYY-Qn`.

### Impact preview

- **FR-11** — Before saving, the form MUST show the member's **current total** for the chosen group and quarter and the **projected total** after the adjustment (Q6=A), so a sign error is visible before it becomes a permanent ledger entry.
- **FR-12** — The preview MUST be derived from the member's ledger entries for that group and quarter. When the total cannot be read, the form MUST say so plainly and still allow the adjustment to proceed — the preview is an aid, never a gate (graceful degradation, RESILIENCY-10).

### Reverse an existing entry (closing the US-6.15 gap)

- **FR-13** — The screen MUST let a leader browse the selected member's point history for the chosen group and **reverse a specific entry** (Q7=A), which is the "adjustor selects the specific point entry to delete" half of US-6.15. Backend support already exists, is tested and is deployed: `GET /contributions/ledger`, `POST /contributions/adjustments/reverse`.
- **FR-14** — An entry that has **already been reversed** MUST be shown as such and MUST NOT offer a reverse action. This is derivable from the same response: an entry is reversed when another entry's `reverses` field points at its id. The server's single-use guard (BR-J2, 409) remains the control.
- **FR-15** — Reversal MUST require a reason, exactly as the free adjustment does.

### Guidance

- **FR-16** — The form MUST carry a short note (Q8=A) stating that the adjustment is permanent and append-only, that the affected member is notified in-portal, and that a negative adjustment may take a total below zero.

---

## 3. Non-functional requirements

- **NFR-1 (Performance)** — Member search MUST be debounced to avoid a request per keystroke, reusing the existing 300 ms convention. The ledger read for a member/group MUST happen once per selection, not per render.
- **NFR-2 (Security, SECURITY-05)** — Client-side validation is additive. The existing server-side validation of every field stays unchanged and remains the enforcement point.
- **NFR-3 (Security, SECURITY-08)** — No change to authorization. A UGL who somehow submits an out-of-scope group MUST still receive 403 from the server.
- **NFR-4 (Security, SECURITY-15)** — Every added API call MUST have explicit error handling and fail safe: a failed directory search shows no results rather than a broken form; a failed ledger read disables the preview and the reverse list but never blocks the primary action.
- **NFR-5 (Accessibility)** — The member typeahead MUST keep the existing ARIA combobox semantics (`role="combobox"` / `listbox` / `option`). Every control MUST have an associated label, and validation errors MUST be announced in text, not conveyed by colour alone.
- **NFR-6 (Usability)** — Raw internal ids (`m-…`, `g-…`, `led-…`) MUST NOT appear anywhere in the UI, consistent with the existing rule applied across the Directory, Approvals and File Sharing screens.
- **NFR-7 (Maintainability)** — The rework MUST be covered by frontend tests, including a case that pins the integer-typed delta so the string-delta defect cannot regress. The repo has an established vitest suite (71 tests) to extend.

---

## 4. Derived decisions

Recorded here because they follow from the answers rather than being separately asked. Raise them if you disagree.

- **DR-1 — UGL group dropdown.** Q1=A establishes the principle that a leader is never offered something they cannot act on; Q2=A establishes that the group is never preselected. Applied together, a UGL's dropdown lists **only the group they lead** (the intersection of the member's groups with their own), still with no preselection. Listing a member's other groups would offer choices that are guaranteed to return 403.
- **DR-2 — Source of the current total.** `tiersEarned` is unsuitable: it emits a row only when the points clear a tier threshold, so a member sitting below the lowest tier is indistinguishable from a member with no data, and the preview would show a confident, wrong zero. The preview therefore sums the member's ledger entries for the group and quarter — the same data the rollups are derived from, and the same call FR-13 needs, so one read serves both.
- **DR-3 — No contract change after all (revised at Workflow Planning, 2026-08-11).** This originally proposed an additive optional `quarter` parameter on `GET /contributions/ledger`. Planning showed it is not needed: FR-13 needs the member's history for the chosen **group across all quarters** (an entry is reversible regardless of which quarter it sits in), so the frontend already holds every row it needs and can derive FR-11's quarter total by filtering the same response. Adding the parameter would have bought nothing and cost a backend change plus a Lambda redeploy. **The change is therefore SPA-only**: no contract change, no service change, no infrastructure change, and rollback is a static-asset redeploy. The repository's existing `quarter` filter stays unused by this work.

---

## 5. Explicitly unchanged

No change to: authorization (BR-A5), ledger immutability (BR-J1), single-use reversal (BR-J2), below-zero adjustments (BR-J3), the 8-quarter window (BR-J4), the `PointsAdjusted` event, the API contract, any backend service, DynamoDB tables, GSIs, IAM policies, or any infrastructure template. There is no new AWS resource, no Lambda redeploy and no data migration.

Every endpoint this screen needs is already live and serving real data: `contributions-scoring`, `member-profiles` and `identity-access` are all in `complete` mode in `service-mode.json`, so the member typeahead, the group names, the ledger read and the reverse call all hit real services rather than mocks.

---

## 6. Traceability

| Requirement | Story / rule | Verification |
|---|---|---|
| FR-1, FR-2, FR-3 | US-6.15, BR-A5 | Frontend test: UGL search is group-scoped; existing backend test `test_ugl_adjust_scoped_to_led_group` |
| FR-4, FR-5, FR-6, DR-1 | US-6.15 ("applies to a specific user group") | Frontend tests: multi-group no default, no-group blocked, UGL sees only led group |
| FR-7, FR-8, FR-9 | Defect; US-6.15 ("positive or negative") | Frontend tests: integer type pinned, bare number rejected, zero rejected |
| FR-10 | BR-J4 | Frontend test: 8 options, newest first, current preselected |
| FR-11, FR-12, DR-2 | New (Q6) | Frontend tests: projected total arithmetic, degraded preview on read failure |
| FR-13, FR-14, FR-15, DR-3 | US-6.15 ("selects the specific point entry"), BR-J2 | Frontend tests: reversed entries offer no action; existing backend test `test_reverse_entry_single_use` |
| FR-16 | US-6.15, BR-J3 | Present in the rendered form |

---

## 7. Follow-up already on the record

Adjustments are supposed to notify the affected member in-portal (BR-N1, `PointsAdjusted`). Notifications is still a mocked service and re-enters the workflow at Requirements Analysis, so that notification is published as an event but not delivered. This change does not alter that, and does not depend on it.
