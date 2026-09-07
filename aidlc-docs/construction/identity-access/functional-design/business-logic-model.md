# Business Logic Model — Unit 2: Identity & Access

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Identity & Access
Technology-agnostic business logic for the 28 stories. Maps each contract operation to its logic, rules, and emitted events. Companions: `business-rules.md`, `domain-entities.md`.

## Component archetype (in-service, no shared lib — FQ1)
```
handler (API GW proxy)  → validation → authz (Principal + matrix) → domain service → repository (DynamoDB)
                                                                          ↘ auth provider (Cognito | local)
                                                                          ↘ event publisher (EventBridge)
                                                                          ↘ audit logger (CloudWatch)
                                                                          ↘ email (SES)
```
Cross-cutting modules (`_conventions/`: logger, errors, authz, validation, envelope, idempotency, config) are copied per-service by the scaffold generator.

## Credential paths (per requirement)
Community users authenticate **only via Cognito** (`CognitoAuthProvider`: `admin_initiate_auth`, `sign_up`, `admin_create_user`, `admin_disable/enable_user`, `admin_get_user`, `list_users`). Cognito is the system of record for community-user identity and credentials (US-1.2/1.4/1.30/1.31). The built-in local Administrator resolves through the portal-local path (Secrets Manager + PBKDF2 + portal-signed JWT), independent of Cognito (US-1.27/1.28). No local/dev auth abstraction — tests run the real provider against a mocked Cognito.

---

## Auth flows

### `login` (POST /auth/login) — US-1.2, 1.27, 1.32
1. Validate email + password.
2. If email == local-admin email → verify against Secrets Manager hash → issue session (role Administrator, accountType local-admin). **No OTP** (BR-A4/A8). Audit login.
3. Else community user → `AuthProvider.initiate_auth`. On bad creds → generic error (BR-A6).
4. Resolve/JIT-provision portal record (BR-P1); if `Inactive` → deny (BR-P6).
5. Determine OTP due (BR-A3). If due → create OtpChallenge, send OTP via SES, return `{ otpRequired: true, challengeId }` (no token yet). Else → issue session `{ token, role, otpRequired: false }`. Audit.

### `verifyOtp` (POST /auth/otp) — US-1.32
1. Validate code + challengeId. Load challenge; check expiry + attempts (BR-A5).
2. On match → set `lastVerifiedAt=now`, issue session, delete challenge. On mismatch → increment attempts, generic error (BR-A6). Audit success/failure.

### `selfRegister` (POST /auth/register) — US-1.30
1. Validate email/firstName/lastName/password. Enforce allowed-domain (Settings); empty list ⇒ block (BR-P3).
2. `AuthProvider.sign_up` (Cognito owns identity/creds; email verification Cognito-managed). Portal record created on first login via JIT (Member). Return `User` (201). Audit.

### `resetPassword` / `confirmResetPassword` (POST /auth/reset, /auth/reset/confirm) — US-1.20
Two-step Cognito hosted forgot-password flow, used by every user including the bootstrap Administrator (US-1.27) — there is no separate local-admin credential store (US-1.28 tombstoned).
1. `resetPassword`: validate email format; call `AuthProvider.forgot_password` (Cognito `ForgotPassword`, emails a verification code). Always returns the same generic message regardless of whether the account exists (BR-A6). Audit `user.reset_requested`.
2. `confirmResetPassword`: validate email/code/newPassword; call `AuthProvider.confirm_forgot_password` (Cognito `ConfirmForgotPassword`). Cognito enforces password policy and code expiry/attempt limits; bad code or unknown account map to a generic error (BR-A6). Audit `user.reset_confirmed`.

### `logout` — US-1.3
Session invalidated client + server (token deny/short TTL); redirect to login. (No dedicated contract path; handled at edge/session — audited.)

## User management

### `listUsers` (GET /users) — US-1.4, 1.8 (Admin only)
authz `list admin-member-list global` (Administrator). Return portal records (role, status, groups, profile). Source reconciled from Cognito sync. 403 otherwise.

### `editUser` (PUT /users/{id}) — US-1.5, 1.26
1. authz `edit user global` (Administrator).
2. Apply role + groupIds + profile fields; identity read-only (BR-R4).
3. Enforce role/membership rules (BR-R6), one-role (BR-R1), last-leader + last-CL safeguards (BR-G12), UGL-leads-one-group (BR-G7).
4. Role change → apply suspend/restore semantics (BR-R5); append membership-end/start events as needed (BR-M1). Publish `UserRoleChanged` (+ membership events). Audit.

### `disableUser` / `enableUser` (POST /users/{id}/disable|enable) — US-1.33, 1.6, 1.19
authz `disable-enable user global`. Block for local admin (BR-A8). Disable → `AuthProvider.admin_disable_user`, mark Inactive, safeguards (BR-G12), publish `UserDeactivated`, membership-end events, email. Enable → re-enable + Active + restore role, publish `UserReactivated`. Audit.

### `bulkImport` (POST /users/import) — US-1.31
authz `bulk-import user global`. Parse CSV/XLSX (header validated); per-row: validate → domain check → within-file dup → Cognito existence → create in Cognito + portal record (Member) or categorize (Created/Skipped/Rejected...). Return counts report. Publish `UserProvisioned` per created. Audit (who, file, counts).

### Scheduled Cognito sync — US-1.4 (EventBridge Scheduler, not an API path)
`list_users` from Cognito → idempotent match-and-update by `sub`/email; deleted-in-Cognito ⇒ Inactive; re-added ⇒ Active; local admin exempt (BR-P2). Publish `UserProvisioned`/`UserDeactivated`/`UserReactivated` on transitions.

## Groups

### `listGroups` (GET /groups) — US-1.16
Return active groups with derived memberCount + leaders (name+email). Visibility per role (BR-G10).

### `createGroup` (POST /groups) — US-1.7
authz `create user-group global` (CommunityLeader). Require name + ≥1 leader (BR-G1); creator not auto-leader; approvalRequired default off. Assign UGL role to leaders (BR-G7). Publish `GroupCreated`. Audit. 403 for others.

### `getGroup` (GET /groups/{id}) — US-1.16
Return group + member list (Community Leader any; UGL own led group). 404 if not found/soft-deleted-to-others.

### `editGroup` (PUT /groups/{id}) — US-1.18
authz `edit user-group global` (CommunityLeader only). Edit name/description/approvalRequired/leaders; approval change not retroactive (BR-G6); last-leader rule (BR-G1); UGL-one-group (BR-G7). Publish `GroupUpdated`. Audit.

### `deleteGroup` (DELETE /groups/{id}) — US-1.11
authz `delete user-group global` (CommunityLeader). Soft-delete (BR-G9): hide, remove members (end events), auto-reject group submissions + cancel events (via `GroupSoftDeleted`). Schedule permanent purge (2 weeks) → `GroupHardDeleted`. Audit.

### `joinGroup` (POST /groups/{id}/join) — US-1.8
authz `join user-group global` (Member/UGL per rules; Admin/CL blocked BR-R3). Open ⇒ append `joined`, publish `MemberJoinedGroup`. Approval-required ⇒ create Pending JoinRequest (BR-G3/G4). Audit.

### `leaveGroup` (POST /groups/{id}/leave) — US-1.9
Remove membership (append `left`); block last-leader (BR-G1). Publish `MemberLeftGroup`. Forum access ends; posts retained. Audit.

### `listJoinRequests` (GET /groups/{id}/requests) — US-1.21
authz group-scoped (UGL of group or any CL). Return Pending sorted oldest-first with member, group, date, message.

### Approve/Reject join request — US-1.21
(Contract exposes `listJoinRequests`; approve/reject actions handled via join-request decision — mapped to POST on request within `/groups/{id}` family / handled through the same handler.) Approve → membership start (join date = now), publish `MemberJoinedGroup`, notify. Reject → reason required, notify. First actor wins (BR-G8). Withdraw pending on requester deactivation.

### `listGroupMembers` (GET /groups/{id}/members) — US-1.16
Derived active members from membership history (BR-M1). Visibility per BR-G10.

### `assignLeader` (POST /groups/{id}/leaders) — US-1.10
authz `assign user-group-leader global` (CommunityLeader). Reject if member already leads another group (BR-G7); set UGL role; publish `GroupUpdated`/`UserRoleChanged`. Audit.

### `removeMember` (DELETE /groups/{id}/members/{memberId}) — US-1.17
authz `remove group-member` (CL global / UGL group-scope). Append `removed`, publish `MemberRemoved`, notify. 403 out of scope.

### `membershipHistory` (GET /membership-history) — US-1.34
Return append-only events (filterable by member/group) — analytics data source (US-7.2/7.3).

## Access control & audit (cross-cutting)
- **RBAC (US-1.12)**: every handler calls `Authorizer.authorize(principal, action, resource, owner_id?, resource_group_id?)`; deny ⇒ 403 (BR-R2).
- **Audit (US-1.13/1.14)**: dedicated audit logger emits structured records for create/update/delete + login/logout when enabled; toggle read from Settings; toggle-change always logged (BR-AU1/AU2).

## Traceability (stories → operations)
| Story | Operation(s) |
|---|---|
| US-1.2/1.32 | login, verifyOtp |
| US-1.3 | logout (session) |
| US-1.4 | scheduled sync |
| US-1.5/1.26 | editUser |
| US-1.6/1.19/1.33 | disableUser, enableUser |
| US-1.7/1.18/1.11 | createGroup, editGroup, deleteGroup |
| US-1.8/1.9 | joinGroup, leaveGroup |
| US-1.10 | assignLeader |
| US-1.12 | authz (all) |
| US-1.13/1.14 | audit logger (all) |
| US-1.15 | JIT in login |
| US-1.16 | listGroups, getGroup, listGroupMembers |
| US-1.17 | removeMember |
| US-1.20 | resetPassword, confirmResetPassword |
| US-1.21 | listJoinRequests, approve/reject |
| US-1.27 | local-admin login (Secrets Manager) |
| US-1.30 | selfRegister |
| US-1.31 | bulkImport |
| US-1.34 | membershipHistory |

All 28 stories covered.
