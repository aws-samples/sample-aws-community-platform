# Unit 2 — Edit Group Field Parity (Change Request Plan)

**Origin**: User report (2026-08-03, testing on AWS dev): "There is no option for Community Leader to Change/add User Group leader. The Edit Group Window only allow to Change Name and Description. Need all the fields used during create group."
**Stories affected**: US-1.18 (edit group), US-1.10 (assign leader), US-1.9 (create group — field set reference).
**Finding**: Backend + contract already complete — `PUT /groups/{id}` takes `GroupInput` (name, description, approvalRequired, leaderIds; minItems 1) and `edit_group()` validates leader availability (BR-G7), enforces ≥1 leader, and promotes new leaders. The gap is frontend-only: both Edit Group entry points (`pages.tsx` groups list, `GroupDetailPage.tsx`) use the generic `FormModal` sending only name/description.

## Approach
Make the existing `CreateGroupModal` dual-mode (create/edit) rather than duplicating its leader-picker UI:
- Optional `group` prop → edit mode: prefill name/description/approvalRequired/leaderIds; `PUT /groups/{id}`; title/button/testids adjusted (`edit-group-modal`).
- Leader eligibility in edit mode: UGLs not leading any OTHER group (a person leads one group, BR-G7) PLUS this group's current leaders (always listed, pre-checked, so they can be kept or unchecked). Current leaders included regardless of role edge cases. UI enforces ≥1 leader (server re-validates).
- Rename component file `CreateGroupModal.tsx` → `GroupModal.tsx` (purpose broadened); imports auto-updated.
- Replace both `FormModal` edit usages with the dual-mode modal.
- No backend, contract, or infra changes.

## Steps
- [x] Step 1 — Rename `CreateGroupModal.tsx` → `GroupModal.tsx`; add `group` prop, edit-mode prefill/PUT/labels, edit-mode leader eligibility.
- [x] Step 2 — `pages.tsx` (UserGroups): replace the Edit Group `FormModal` with `<GroupModal group={editing} …/>`.
- [x] Step 3 — `GroupDetailPage.tsx`: same replacement; drop the now-unused `FormModal` import.
- [x] Step 4 — Verify: `npm run build`, diagnostics clean; backend untouched (no pytest/contract deltas expected).
- [x] Step 5 — Docs: code summary under `aidlc-docs/construction/identity-access/code/`; aidlc-state.md; audit entries.

## Extension compliance (Security + Resiliency baselines)
- SECURITY-08 (fail-closed authZ): compliant — edit stays CL-gated in UI; server-side authZ unchanged.
- Other rules: N/A — no new endpoints, data, secrets, or infra.
