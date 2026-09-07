# Change Summary — Edit Group Field Parity (2026-08-03)

**Trigger**: User report from AWS dev testing: Community Leader had no way to change/add a User Group Leader; the Edit Group window only offered Name and Description. Requirement: Edit must offer all fields used during Create Group.
**Plan**: `aidlc-docs/construction/plans/identity-access-edit-group-parity-plan.md`.

## Finding
Backend and contract were already complete: `PUT /groups/{id}` takes the same
`GroupInput` as create (name, description, approvalRequired, leaderIds; minItems 1),
and `edit_group()` (US-1.18) validates leader availability (BR-G7 one-group-per-leader),
enforces ≥1 leader, promotes newly assigned leaders, publishes `GroupUpdated`, and
audit-logs. The gap was frontend-only: both Edit entry points used the generic
`FormModal` sending only name/description.

## Changes (frontend only — no backend/contract/infra deltas)
- **Renamed**: `components/CreateGroupModal.tsx` → `components/GroupModal.tsx`, now dual-mode:
  - Create mode (no `group` prop): unchanged behavior, `POST /groups`.
  - Edit mode (`group` prop): prefills name/description/approvalRequired/leaderIds, `PUT /groups/{id}`, title "Edit User Group", `edit-group-modal` testid.
  - Edit-mode leader eligibility: this group's current leaders (pre-checked, badge "current leader", can be unchecked) + UserGroupLeaders not leading any other group. Submit disabled until ≥1 leader checked (server re-validates).
  - Approval toggle hint notes the change is not retroactive (BR-G6).
- **Modified**: `features/pages.tsx` (UserGroups list) — Edit Group now opens `GroupModal group={…}` instead of the name/description `FormModal`.
- **Modified**: `features/GroupDetailPage.tsx` — same replacement; unused `FormModal` import dropped.

## Verification
- `npm run build` — clean; diagnostics clean on all three files.
- No backend change: identity-access pytest/contract gates unaffected (not rerun for a frontend-only change).
- NOT yet redeployed — dev stack still serves the previous SPA bundle until the next deploy.
