# User Stories — AWS Community Portal

**Organization** (Q2 = A): by module. Each module maps to a target **bounded context / microservice** (noted per section) to guide Units Generation.
**IDs** (Q1 = A): source `US-x.y` IDs preserved 1:1; each story links to its use-case source.
**Acceptance criteria** (Q3 = A): carried over from the use cases, lightly normalized. The source file remains authoritative for any fine detail.
**Scope** (Q5 = A): all 143 active stories across 11 modules.
**Tombstones** (Q6 = A): removed stories are omitted here and listed in the Traceability Matrix as "removed — not implemented".
**Cross-cutting/NFRs** (Q7 = A): user-facing cross-cutting features are stories (US-8.x); global constraints are in the "Cross-Cutting Constraints & NFRs" section near the end — every story inherits them.

All stories follow **INVEST**. Global cross-cutting acceptance criteria (RBAC 403 on unauthorized access, input validation/sanitization, encryption, structured logging/audit, times shown in user's time zone, responsive UI, last-write-wins) are inherited from the Cross-Cutting section and not repeated per story.

Legend: **CL** = Community Leader, **UGL** = User Group Leader, **M** = Member, **A** = Administrator.

---

# Module 1 — Authentication & Authorization
**Target service/bounded context**: Identity & Access Service (Cognito integration, users, roles, user groups, membership history, audit config). Source: `requirements/usecases/01-authentication-and-authorization.md`

## Authentication

### US-1.2 — Cognito User Login (Email + Password)
**As a** user, **I want** to log in with email + password **so that** I can access the portal.
**Acceptance Criteria**
- Single sign-in method for every user, including the bootstrap Administrator, is email + password against the portal-owned Cognito user pool (no SSO/federation).
- Cognito enforces password policy; clear error on invalid credentials.
- When periodic OTP re-verification is due (US-1.32), an email OTP step precedes session grant; otherwise password alone completes sign-in.

### US-1.27 — Bootstrap Administrator Account (Cognito, Deployment-Seeded)
**As the** platform owner, **I want** a bootstrap Administrator created automatically when the stack is deployed **so that** the portal is administrable from day one (incl. assigning the first Community Leader) with no manual account-creation step.
**Acceptance Criteria**
- The Cognito user pool and the bootstrap Administrator user are provisioned in the same deployment (IaC); the Administrator email is a deployment parameter.
- The bootstrap Administrator is an ordinary Cognito user with the Administrator role, created via the same admin-create-user mechanism used elsewhere — not a separate credential store.
- Bootstrap mechanism: exists before any other user signs up; used to promote the first Community Leader via Edit User (US-1.26), following role-change data handling.
- Signs in via the same Cognito login path as every user (US-1.2), including OTP re-verification (US-1.32) and standard Cognito hosted password reset (US-1.20) — no separate portal-local login/reset.
- Cognito emails a temporary password/verification message at deployment; the Administrator sets their real password on first sign-in.
- Subject to the Cognito sync job (US-1.4) and disable/enable + last-Community-Leader safeguards (US-1.6/1.19/1.26/1.33) like any other Administrator — no exemption.
- Administrator role is not exclusive to this account — any other Cognito user can also be granted it via Edit User.
- **Accepted tradeoff:** removes the earlier "break-glass" account independent of Cognito; acceptable because Cognito is provisioned by the same infrastructure template, so the scenario that account protected against does not apply. Single bootstrap Administrator assumed for Phase 1.

### US-1.28 — (Removed) Local Administrator Password Reset (Portal-Local)
**Removed.** Superseded by US-1.27 — the bootstrap Administrator is an ordinary Cognito user and resets its password via the standard Cognito hosted forgot-password flow (US-1.20). This story number is retained as a tombstone to preserve traceability; do not reuse it.

### US-1.3 — User Logout
**As a** user, **I want** to log out **so that** my session is terminated.
**Acceptance Criteria**: Session invalidated on logout; redirect to login page.

### US-1.15 — Just-in-Time Account Provisioning (First Login)
**As a** Cognito user logging in for the first time, **I want** my portal account auto-created **so that** I can start without admin intervention.
**Acceptance Criteria**
- On first successful Cognito login with no existing portal record, auto-provision a portal account from Cognito profile (name, email); default role Member; directed to onboarding (join groups).
- No-op when a portal record already exists (e.g., created by bulk import US-1.31) — existing record used; no duplicate.
- Applies to self-registration (US-1.30) and IT-created Cognito users; subsequently reconciled by scheduled sync (US-1.4).

### US-1.30 — User Self-Registration (Allowed Email Domains)
**Amended 2026-08-11** by user instruction ("why we have self service different than admin creating user, both should be same right?"). Self-registration no longer accepts a password at sign-up; it now uses the SAME provisioning mechanism as Administrator-created users and bulk import (US-1.31), which proves mailbox control by construction. Rationale, findings and migration: `aidlc-docs/construction/identity-access/functional-design/us-1.30-unified-provisioning.md`. The original criterion "Cognito enforces email verification" was never met by the implementation — this amendment closes that gap rather than introducing a new requirement.

**As a** prospective user, **I want** to register myself **so that** I can join without waiting for IT.
**Acceptance Criteria**
- "Sign up" available on login **only when** self-registration is enabled in Settings (US-8.3); hidden by default and shown only on an explicit enabled value, so a settings outage cannot reveal it.
- Registrant provides **email, first name, last name — NO password**. Identity is created in Cognito with a system-generated PERMANENT password that is never disclosed or emailed, exactly as bulk import (BR-P4) and Administrator-created users do.
- The registrant establishes their own password via "Forgot password" (US-1.20), whose code Cognito emails to the registered address. This is what proves mailbox control; `email_verified` is never asserted by the portal.
- Administrator-defined allowed-email-domain allow-list (Admin → Settings, US-8.3); registration rejected if the domain is not allowed. An empty allow-list blocks self-registration (BR-P3).
- **Uniform response**: an address that already has an account returns the SAME response as a new one, so the endpoint cannot be used to discover who holds an account (BR-A6). No account is created or modified in that case.
- No separate admin/leader approval — an allowed-domain email plus proven mailbox control activates the account.
- First login JIT-provisions a portal record as Member (US-1.15) and routes to onboarding; cannot self-grant any role beyond Member (BR-P3).
- Because the mailbox is proven before a usable password exists, **no first-login OTP is required** (BR-A10). Periodic re-verification (US-1.32) still applies on its interval — that control detects a user who has LOST mailbox access later, which first-login proof cannot.

### US-1.32 — Periodic Email OTP Re-verification
**As the** platform owner, **I want** periodic email-OTP re-verification **so that** a user who left the org loses access without an explicit deprovision signal.
**Acceptance Criteria**
- On top of email+password, an email OTP step is required when re-verification is **due**; time-based (interval in days since last successful OTP), not login-count based.
- OTP delivered to the registered corporate email via SES; losing mailbox control ⇒ access lapses at next interval.
- Admin-configurable interval + max session/refresh-token lifetime (US-8.3); settings screen states effective access window ≈ session lifetime + interval.
- OTP enforces short expiry, limited attempts, rate limiting; no user enumeration.
- Implemented via Cognito custom-auth triggers with server-side "last verified" timestamp; applies to every Cognito user, including the bootstrap Administrator (US-1.27) — no exemption. Successes/failures audit-logged (US-1.13).

### US-1.33 — Administrator Disable / Enable a User
**As an** Administrator, **I want** to disable/re-enable a user directly **so that** I can cut off access immediately.
**Acceptance Criteria**
- Disable any Cognito community user (row action and/or Edit User): disables the Cognito account (auth + OTP both fail) and marks portal user Inactive, triggering full US-1.6 deactivation handling.
- Re-enable restores Cognito account and marks Active per US-1.19 (previous role restored; memberships must be re-joined).
- The bootstrap Administrator (US-1.27) is a regular Cognito user and can be disabled like any other Administrator, subject to the same safeguards.
- Last-Community-Leader / last-UGL safeguards apply; disabled user emailed (US-8.7); disable/enable audit-logged with actor. Complements US-1.32.

### US-1.20 — Password Reset for Cognito Users
**As a** Cognito user, **I want** to reset my password **so that** I regain access if I forget it.
**Acceptance Criteria**: Cognito hosted forgot-password flow; "Forgot Password" on login → email code → set new password; Cognito enforces policy.

## User Management

### US-1.4 — Sync Users from Cognito
**As an** Administrator, **I want** the portal to pull users from Cognito via a scheduled job **so that** the member list reflects the source of truth.
**Acceptance Criteria**
- Cognito is system of record for identity + credentials (portal never stores passwords or owns name/email; no one-by-one portal creation). Portal record (role, membership, profile, status) keys to Cognito `sub` (email as unique business key).
- Portal record created either directly by bulk import (US-1.31) or via sync/JIT (US-1.15); reconciliation is idempotent (match-and-update, never duplicate).
- Scheduled batch job syncs users; Cognito pool is portal-owned, provisioned via IaC (app clients, password policy, email verification, hosted forgot-password, custom-auth OTP triggers). Pool ID + region are read-only deployment outputs in settings; only sync schedule is admin-configurable (US-8.3). Pool created empty.
- First-seen user → created as Member; existing → matched/updated. Deleted in Cognito → next sync marks Inactive (content retained, US-1.6); re-added → Active.
- Identity (name/email) not editable in portal; only role + group membership editable (US-1.26). Synced users appear in directory automatically.

### US-1.31 — Administrator Bulk User Import
**As an** Administrator, **I want** to bulk-import users from a spreadsheet **so that** I can onboard a batch without IT.
**Acceptance Criteria**
- Always available to Administrators. For each valid row, portal creates the user in Cognito (identity/credentials Cognito-owned) and, using the returned `sub`, creates the portal record at import time as Member (no dependency on sync/JIT); sync later reconciles idempotently.
- Upload `.csv`/`.xlsx`; downloadable template; header row validated.
- Required identity columns (→ Cognito): `email` (unique, valid, allowed domain per US-1.30), `first_name`, `last_name`.
- Optional profile columns (→ portal record): `city`, `country`, `professional_role`, `aws_project` (yes/no), `time_zone`.
- No password column: the portal sets a system-generated password as permanent immediately (no Cognito invite email, no `FORCE_CHANGE_PASSWORD` state) and instead sends the new user a welcome email (via SES) directing them to "Forgot password" on the login page to set their own — the generated password is never disclosed. Role not importable (all Member); membership not set by import.
- Duplicate handling: repeated email within file rejected; email already in Cognito skipped (never overwrites); previously deleted/Inactive treated as existing → skipped (reactivation is Cognito-driven).
- Row-level validation (not all-or-nothing): each row categorized Created / Skipped (duplicate) / Rejected (domain) / Rejected (invalid data); summary + downloadable per-row report; import audit-logged (actor, file name, counts). This flow onboards Members; it is not how the bootstrap Administrator (US-1.27) is created.

### US-1.26 — Edit a User (Role & Group Membership)
**As an** Administrator, **I want** one "Edit User" action for role + group membership **so that** I manage access in one place.
**Acceptance Criteria**
- Single Edit User combines role + membership; identity (name/email) read-only.
- Also edits profile fields: city, country, professional role (free-text job title, distinct from access role), AWS-project (yes/no), time zone (same fields as US-3.2/8.14; latest save wins).
- Exactly one role at a time (mutually exclusive); role change effective on next action (no re-login).
- Membership by role: Administrator/Community Leader — no group membership (disabled); UGL — leads exactly one group, scoped strictly to it (other selections disabled); Member — one or many groups.
- Validation: every group must retain ≥1 UGL (block with affected group); a group may have multiple UGLs; changing away from the last active Community Leader is blocked.
- Role-change data handling (suspend, not destroy) mirrors US-1.6: promotion to non-Member retains memberships as inactive, keeps points/badges in ledger (no new earning), auto-rejects in-flight pending submissions, removes from future RSVPs, retains/attributes created content, preserves event edit/cancel rights (US-2.4). Demotion to Member reactivates memberships, resumes earning from current quarter (no backfill), reassigns held review queues per US-6.9. Applies to bootstrap promotion (US-1.27).
- **User-groups column (2026-08-11)**: the Admin user-management table shows a **User Groups** column listing, by name, the groups each user belongs to (Members) or leads (UGL, annotated "· leads"); Administrators and Community Leaders show "—" (BR-R6, they belong to no group). Names only — raw ids never render. The rows already carry `groupIds` from `listUsers`; this is a display-only change (no backend/contract change).

### US-1.5 — Assign a Role to a User
**As an** Administrator, **I want** to assign a single role **so that** the user has appropriate access.
**Acceptance Criteria**: Done via Edit User (US-1.26); exactly one role; block role change that would leave a group leaderless; role changes follow US-1.26 data handling.

### US-1.6 — User Deactivation (Admin-initiated or Cognito-driven)
**As the** system, **I want** a user marked Inactive on Admin disable (US-1.33) or Cognito delete/disable **so that** access reflects the source of truth.
**Acceptance Criteria**
- Inactive via (a) Admin disable or (b) Cognito delete/disable reflected by next sync; deactivated user cannot log in (auth + OTP fail).
- Emailed about deactivation (mandatory, US-8.7); removed from all groups and future RSVP lists (counts updated); pending contribution/certification submissions auto-rejected ("User deactivated").
- All content retained and attributed; profile marked Inactive but visible in directory with inactive badge; points/badges preserved; excluded from active leaderboards/tier distributions/active-contributor counts.
- If deactivation leaves a group with no UGL, or community with no active Community Leader, flag to Admins/Community Leaders for replacement.

### US-1.19 — User Reactivation (Admin-initiated or Cognito-driven)
**As the** system, **I want** to reactivate a user on Admin re-enable (US-1.33) or Cognito re-add **so that** returning users regain access.
**Acceptance Criteria**: Active via either trigger; previous role restored; groups must be re-joined manually; can log in immediately (with OTP when due); inactive badge removed.

## User Groups

### US-1.7 — Create a User Group
**As a** Community Leader, **I want** to create a user group **so that** members are organized.
**Acceptance Criteria**
- Provide name, description, assign ≥1 UGL; creator not auto-assigned as UGL.
- Optional "Approval required to join" flag (default off): off = instant join (US-1.8); on = join requires leader approval (US-1.8, US-1.21).
- Visible in group directory; cannot create without ≥1 UGL; Administrators cannot create groups.

### US-1.18 — Edit a User Group
**As a** Community Leader, **I want** one "Edit Group" screen **so that** I manage details and leaders together.
**Acceptance Criteria**
- Combines detail editing + leader management; editable: name, description, approval-required flag.
- Flag change is not retroactive (applies to future joins only; doesn't auto-approve pending or affect current members).
- Leaders section: add (block if the person already leads another group, US-1.10) / remove (block if last leader); assigning UGL updates role.
- Only Community Leaders edit groups (any); UGLs cannot edit group config; Administrators cannot. Changes reflected immediately; quick access to member list (US-1.16) and delete (US-1.11).

### US-1.8 — Join a User Group
**As a** UGL or Member, **I want** to join a user group **so that** I can participate.
**Acceptance Criteria**
- Browse groups; each listing shows UGL(s) by name + email; indicates approval requirement and user state (Join / Requested / Joined).
- Open group: single-action join, appears in member list immediately. Approval-required: single action creates a pending request (US-1.21) — not a member, no forum access, no points until approved; can cancel own pending request; only one pending request per group.
- Records per-group join timestamp (display US-3.4, quarter logic US-6.10); for approval groups, join date = approval moment.
- Every change written to append-only membership-event history (US-1.34); rejoin resets displayed join date to most recent (prior points retained). Can belong to multiple groups. Administrators cannot join; Community Leaders do not join (cross-group access without membership).

### US-1.9 — Leave a User Group
**As a** Member, **I want** to leave a group **so that** I'm no longer part of it.
**Acceptance Criteria**: Single-action leave; removed from member list immediately; block a UGL leaving if last leader (assign another first); on leave, loses forum view/post access but existing posts remain attributed and visible.

### US-1.10 — Assign a User Group Leader
**As a** Community Leader, **I want** to assign a UGL **so that** the group has management.
**Acceptance Criteria**: Assign any member as UGL; a group may have multiple UGLs; a person leads only one group (block second, validation error); assignee role updated to UGL; can remove a UGL; every group must always retain ≥1 UGL; Administrators cannot assign/remove.

### US-1.11 — Delete a User Group
**As a** Community Leader, **I want** to delete a group **so that** obsolete groups are removed.
**Acceptance Criteria**
- Community Leader only (Administrators cannot); soft-delete: group + associated data (forums, events, contributions) immediately hidden.
- Pending contribution/certification submissions scoped to group auto-rejected ("User group deleted"); upcoming group events auto-cancelled with email to RSVPs.
- Data retained 2 weeks; within grace period a Community Leader can undo (restore group + data; cancelled events restored); on restore, former members emailed they may rejoin.
- After 2 weeks, permanent deletion of group + forums/events/contributions; also removes group's contribution-ledger entries (incl. per-group slices of community-wide event points), reducing affected lifetime totals (accepted); removes group's indexed content from search index.
- All members removed on soft-delete; user warned of impact; confirmation required.

### US-1.16 — View/Manage User Group Directory
**As a** Community Leader or UGL, **I want** to view/manage the group directory **so that** I can see all groups.
**Acceptance Criteria**: Lists groups with name, description, member count, leader(s), creation date; Community Leaders see/manage all (incl. any group's full member list); UGLs see all but manage only their led group; Administrators don't manage the directory (only assign via Edit User); sortable/filterable; clicking shows member list + details (scoped by role).

### US-1.17 — Remove a Member from a User Group
**As a** Community Leader or UGL, **I want** to remove a member from a group **so that** I manage membership.
**Acceptance Criteria**: Community Leaders remove from any group; UGLs from led group only; Administrators use Edit User; removed member emailed; loses forum view/post (existing posts retained/attributed); may rejoin later.

### US-1.21 — Review Join Requests (Approval-Required Groups)
**As a** UGL or Community Leader, **I want** to review pending join requests **so that** I control who joins.
**Acceptance Criteria**
- Applies only to approval-required groups (US-1.7). Reviewed from a "Join Requests" tab: UGL on My Group (led group only); Community Leader on User Groups (all approval groups, with Group column).
- Each request shows requester name, target group, request date, optional message. A UGL of that group or any Community Leader may approve/reject — first action wins; request removed from both queues.
- Approve: member joins immediately, per-group join date = approval moment (US-1.8), member notified (email + in-portal). Reject: requires reason; member notified; may resubmit.
- Pending-count badge; UGL "Needs Your Attention" highlight links to My Group › Join Requests; sorted oldest first.
- Edge cases: group deleted → pending auto-rejected ("User group deleted"); flag turned off → pending remain (no auto-approve); UGL removed → pending visible to Community Leaders/co-leaders and inherited by new UGL (US-6.9); requester deactivated → request auto-withdrawn. Pending-request count shown as a nav badge and surfaced read-only in the notification bell (US-8.6, Option 2A) — not a stored notification.

### US-1.34 — Membership-Event History
**As the** system, **I want** an append-only history of membership changes **so that** analytics can report membership as of any period.
**Acceptance Criteria**
- Immutable events: member, group, type (`joined`/`approved`/`left`/`removed`), timestamp. Join/approve = start; leave/remove = end.
- Current membership + displayed per-group join date derived from history (latest start with no later end); rejoin appends new start and resets displayed join date (prior events retained).
- Data source for "members as of selected quarter" (US-7.2) and membership-growth chart (US-7.3).
- Deactivation (US-1.6) records end events; reactivation (US-1.19) does not auto-restore (re-join creates new start). Retention indefinite; group hard-delete (US-1.11) removes that group's history after grace period.

### US-1.35 — Admin Adds a Single User via Form
**Added 2026-08-03 by user instruction (post-deployment enhancement, Unit 2).**
**As an** Administrator, **I want** to add one user through a form **so that** I can onboard an individual without preparing a CSV bulk import.
**Acceptance Criteria**
- "Add User" action on Admin → User Management opens a form: email + first/last name (required), optional profile fields (city, country, professional role, AWS project, time zone).
- Same identity model as a bulk-import row (US-1.31): identity/credentials created in Cognito (system-generated PERMANENT password, never disclosed or emailed); portal record created directly as Member; welcome email (SES) directs the user to set their own password via "Forgot password" (US-1.20).
- Role is not settable at creation (always Member) — promotion via Edit User (US-1.26). Duplicate email rejected with a clear message.
- Domain allow-list (US-1.30/US-8.3) is enforced when configured; an empty allow-list blocks only self-registration (BR-P3), not Administrator-driven creation (mirrors bulk import).
- Administrator only (same permission class as bulk import); creation audit-logged (US-1.13); publishes `UserProvisioned` (source=import).

## Access Control

### US-1.12 — Role-Based Access Enforcement
**As the** system, **I want** to enforce RBAC **so that** users only do what their role permits.
**Acceptance Criteria**
- Administrators: manage users/settings/integrations/email templates/audit; NO community participation.
- Community Leaders: own community activities across all groups (groups, UGL assignment, all events, scoring framework, certifications, forum structure + moderation any group, announcements, community + group analytics); don't join groups; don't earn points; multiple allowed.
- UGLs: lead exactly one group, scoped strictly (forums, events, cert/contribution reviews, join-request approvals, point adjustments, group announcements, group analytics); cannot edit group config (US-1.18); no participation in other groups; don't earn/submit anywhere.
- Members: home dashboard, events (their groups + community-wide), forums (their groups), submit certifications/contributions, own points/tiers/submissions, leaderboards, join/leave, receive announcements.
- Exactly one role at a time; unauthorized actions return 403 with friendly message.

## Audit Logging

### US-1.13 — Access Audit Log
**As an** Administrator, **I want** audit logs maintained **so that** access/operations are tracked.
**Acceptance Criteria**: Records user ID, action type, timestamp, IP; logs all create/delete/update across modules + logins/logouts; written to CloudWatch Logs (Log Group name shown in settings, US-8.3); raw access via CloudWatch (no in-portal viewer); retained 12 months then auto-purged.

### US-1.14 — Toggle Audit Logging
**As an** Administrator, **I want** to turn audit logging on/off **so that** I control tracking.
**Acceptance Criteria**: Enable/disable in settings; Log Group name shown; when off no new entries; existing data preserved; the toggle change itself is always logged.

---

# Module 2 — Events & Meetups
**Target service/bounded context**: Events Service (events, RSVP, attendance, materials, Content Library as standalone community hub, event-scoped upload links). Depends on Notifications (email/.ics), Contributions (point awarding + Library opt-in at approval), MS Teams integration. Source: `requirements/usecases/02-events-and-meetups.md`
Event types: Meetup, Workshop, Hackathon, Webinar, AMA/Fireside Chat, Conference, Presentation, Social. Delivery modes: Virtual, In-Person, Hybrid (Hybrid = in-person + virtual join; Teams attendance US-2.12 applies to the virtual portion).

### US-2.1 — Create an Event
**As a** CL or UGL, **I want** to create an event **so that** members can participate.
**Acceptance Criteria**: Provide title, description, type, delivery mode, date/time, duration, location (address or virtual link); select scope (specific group or community-wide); CL creates any/community-wide, UGL only for led group; Administrators cannot; optional "also post announcement" (US-10.1) targeting the event audience; published/visible to audience immediately.

### US-2.2 — Set Event Reminder — **REMOVED (2026-08-27)**
**Descoped on request to simplify the requirement.** The reminder toggle and lead-time
selector are gone from the event form, and the platform no longer schedules or sends
reminders. US-2.8 still puts the event in the member's own calendar via an .ics invite on
RSVP, and that calendar raises the reminder — which is where a reminder belongs, since the
member controls its timing. The story ID is retained so existing traceability references
resolve; do not reuse it for new scope.

### US-2.3 — Create a Recurring Event
**As an** event creator, **I want** a recurring event **so that** regular meetups are scheduled automatically.
**Acceptance Criteria**: Mandatory start date, end date, frequency (daily/weekly/bi-weekly/monthly); each occurrence created as an individual instance; occurrences editable/cancellable independently. In the events list, a recurring series is shown as an **expandable row** that reveals its individual occurrences, each independently manageable (Manage / Edit / Cancel) without affecting the series (the calendar already renders individual occurrences).

### US-2.4 — Edit an Event
**As an** event creator, **I want** to edit an event **so that** I can update details.
**Acceptance Criteria**: All fields editable before event date; creator can edit, and a UGL can edit any event scoped to their led group (even if CL-created); creators retain edit/cancel regardless of later role change (incl. demotion to Member); RSVPs notified of changes by email; updated .ics sent automatically.

### US-2.5 — Cancel an Event
**As an** event creator, **I want** to cancel an event **so that** members know it won't happen.
**Acceptance Criteria**: Creator cancels; UGL can cancel any event for their led group; marked cancelled (not deleted); all RSVPs emailed; remains in history with "Cancelled" badge.

### US-2.15 — Attach Materials to an Event
**As an** event creator, **I want** to attach materials **so that** attendees access content.
**Acceptance Criteria**: Same scope as edit (US-2.4); materials are files (PPT/PDF/docs/recordings → S3) and/or links; add/replace/remove any time; listed on detail page with name, type, size; all who can view the event can download/open; RSVPs emailed when post-event materials added; Administrators cannot manage; file size/type limits deferred to design.

### US-2.19 — Mark Event as Completed
**As an** event creator, **I want** to mark an event completed **so that** status updates and post-event workflows trigger.
**Acceptance Criteria**: Manually mark "Completed" after event date; any attendance recording (manual/Excel/Teams) auto-transitions to Completed; can mark completed without recording attendance; only past-dated events; visible under Completed filter; transitions Upcoming→Completed or Upcoming→Cancelled only. **Event description is mandatory before an event can be marked Completed** — the Complete operation returns 400 if description is absent or blank (required for Content Library auto-promotion, US-2.22).

### US-2.6 — RSVP to an Event
**As a** CL/UGL/Member, **I want** to RSVP yes/no **so that** the organizer knows attendance intent.
**Acceptance Criteria**: Single-action yes/no; changeable before event; yes→no sends .ics cancellation; RSVP count visible to creator + attendees; Administrators cannot RSVP.

### US-2.7 — View RSVP List
**As an** event creator, **I want** to view RSVPs **so that** I can plan attendance.
**Acceptance Criteria**: List of yes/no RSVPs; exportable to CSV.

### US-2.8 — Send Calendar Invite
**As the** system, **I want** to send a calendar invite on RSVP yes **so that** the event appears in the member's calendar.
**Acceptance Criteria**: .ics emailed on RSVP yes with title, description, time, location/link; updated invites on change; cancellation notice on cancel.

### US-2.9 — Event Calendar View
**As a** CL/UGL/Member, **I want** a calendar view **so that** I see what's scheduled.
**Acceptance Criteria**: Month/week/list views; scoped by role (CL all with filter; UGL led group + community-wide; Member their groups + community-wide); switch calendar/list; color-coded by type; filter by group/type/delivery mode; Administrators cannot access; click opens detail.

### US-2.10 — Receive Event Reminder — **REMOVED (2026-08-27)**
**Descoped together with US-2.2.** The member's own calendar entry (US-2.8) carries the
reminder. The story ID is retained so existing traceability references resolve.

### US-2.11 — Configure MS Teams Integration
**As an** Administrator, **I want** to configure MS Teams **so that** attendance can be tracked automatically.
**Acceptance Criteria**: Enable/disable in settings; provide Teams API credentials/tenant config; integration status visible in admin dashboard.

### US-2.12 — Track Attendance via MS Teams
**As an** event creator, **I want** to see who attended a virtual (Teams) event **so that** I can compare RSVP vs actual.
**Acceptance Criteria**: After a Teams-linked virtual event, attendance fetched automatically (name, join/leave time, duration) on detail page; matching by email with a review screen (confirm/correct/exclude) before applying (mirrors US-2.16); points awarded only after creator applies, per event-type value; unmatched participants reported, earn nothing until resolved; exportable CSV; only when integration enabled.

### US-2.16 — Record Attendance Manually
**As an** event creator, **I want** to record attendance manually **so that** participation is tracked.
**Acceptance Criteria**: Mark individuals attended from RSVP list; upload Excel/CSV of attendee emails to bulk-record; emails matched to accounts; unmatched reported as errors; attendance triggers point awarding per event-type value.

### US-2.17 — Configure Event Points
**As an** event creator, **I want** event points determined by the scoring framework **so that** points are consistent.
**Acceptance Criteria**: Each event type has its own configurable attendance point value (US-6.1, CL-managed); creator cannot override; points awarded to confirmed attendees (manual/Excel/Teams); value shown on detail page.

### US-2.18 — Award Points for Delivering an Event
**As a** Member who delivers a session, **I want** points for presenting **so that** my contribution is recognized.
**Acceptance Criteria**: Creator designates one+ internal members as presenters/facilitators; only internal portal users eligible (external SMEs not tracked); delivery points only to presenters holding the Member role (A/CL/UGL never earn, US-6.17); delivery points configured per event type (separate from attendance); awarded when event marked completed (US-2.19). Creator can also designate one+ internal members as **event organizer(s)** (distinct from presenters) — organizers earn **organize points** automatically on completion (US-6.18); both designations are captured on the event so both awards are auto-tracked (no evidence).

### US-2.13 — Browse Events
**As a** CL/UGL/Member, **I want** to browse upcoming events **so that** I can find events.
**Acceptance Criteria**: CL sees all; UGL/Member see their groups + community-wide; Administrators cannot; default "Upcoming" (Cancelled/Completed via filter); filter by type/delivery mode/date range/group/status; keyword search within selected status + active filters; empty state on no match; sort by date (nearest first); past events under Completed.

### US-2.14 — View Event Details
**As a** Member, **I want** full event details **so that** I can decide to attend.
**Acceptance Criteria**: Shows title, description, type, delivery mode, date/time, duration, location/link, organizer, RSVP count; RSVP from detail; lists materials (US-2.15) — download files/open links for any viewable event (no RSVP required).

### US-2.20 — Content Library — Browse and Search Community Resources
**As a** Member/CL/UGL, **I want** a standalone Content Library **so that** I can discover and reuse community-produced knowledge assets.
**Acceptance Criteria**: Accessible as a top-level page `/content-library` with its own navigation item (not a tab within Events); visible to all authenticated non-Administrator users; search-first — nothing shown until at least one keyword or filter is submitted; keyword search (no semantic) across resource title and description; filters: Format (PPT, Video, Link, Word), Topic (free-form tag autocomplete), Source (event-material, member-contribution, curator-direct); results paginated (cursor-based, page size 10); each result card shows: content-type icon, title, description excerpt, format badge, topics, source label, attribution (event name + date for event-material; member name for member-contribution; curator name for curator-direct), download or open-link action; file downloads via short-lived presigned GET URL; links open in new tab; quarantined files not downloadable; graceful empty states; Administrators excluded (403).

### US-2.21 — Create an Event-Scoped External Upload Link
**As an** event creator (CL or UGL), **I want** a secure, revocable, event-scoped upload link **so that** an external party can upload files without a portal account.
**Acceptance Criteria**: From event management, same roles as materials (US-2.15); Administrators cannot; reuses external file-share model (US-8.13) scoped to the event — folder (key prefix) in the pre-existing community S3 bucket associated with the event; set expiry (7/14/30/90 days), optional max file size, note; generate shareable link with unguessable time-bound token; write-only upload (no list/view/delete) via short-lived per-upload pre-signed URLs; creator/CL (UGL within led group) can view/download uploaded files (name, size, uploader if captured, date); independently revocable + expiring (revocation immediate; deleting link doesn't delete files); create/revoke + owner audited (US-1.13); uploads can be surfaced as event materials; bucket not public; exact mechanism deferred to design.

### US-2.22 — Content Library — Auto-Promote Event Materials on Completion
**As the** system, **I want** to automatically add all clean event materials to the Content Library when an event is completed **so that** event knowledge is preserved without curator effort.
**Acceptance Criteria**: When an event transitions to Completed (US-2.19), all materials with `scanState=Clean` are automatically created as Library resources; `title` = material name; `description` = event description (guaranteed non-empty by US-2.19 mandatory description rule); `format` derived from material content type; `source` = `event-material`; `scope` = COMMUNITY; `eventId` and `eventTitle` denormalized onto the resource; no curator action required; materials added after completion that subsequently pass scanning are also promoted; quarantined materials are not promoted.

### US-2.23 — Content Library — Curator Direct Add
**As a** CL or UGL, **I want** to add a resource directly to the Content Library **so that** I can share curated content without a submission workflow.
**Acceptance Criteria**: CL and UGL can access an "Add to Library" form from the Content Library page; form fields: title (required), description (required, used for search), format (required: PPT/Video/Link/Word), topics (optional, free-form tags, autocomplete suggestions from existing tags), and either a URL (for Link format) or file upload (for PPT/Video/Word); `source` = `curator-direct`; `addedBy` = curator's userId and display name; file uploads go directly to S3 via presigned PUT (same pattern as event materials) and enter `PendingScan` state until GuardDuty clears them; link resources are immediately available; resource appears in Library once clean; Administrators cannot add.

### US-2.24 — Content Library — Member Contribution Opt-In
**As a** CL or UGL approving a member contribution, **I want** to optionally add the contribution to the Content Library **so that** noteworthy member work is discoverable by the whole community.
**Acceptance Criteria**: During contribution approval (existing Contributions flow, US-6.9), CL/UGL sees a checkbox/toggle "Add to Content Library" with required fields: description (pre-filled from contribution description if available, editable, mandatory), format (required: PPT/Video/Link/Word), topics (optional free-form tags); if opted in, a Library resource is created with `source` = `member-contribution`, `submittedBy` = member's userId and display name; contribution approval points are awarded by the existing flow regardless of Library opt-in (no double-award); if opted out, no Library record is created; the opt-in is a one-time decision at approval — post-approval, curators use US-2.25 to manage.

### US-2.25 — Content Library — Curator Edit and Delete Resources
**As a** CL or UGL, **I want** to edit or delete any resource in the Content Library **so that** I can keep the Library accurate and relevant.
**Acceptance Criteria**: CL and UGL can edit any Library resource: title, description, format, topics, URL (for link resources); file replacement not supported via edit (delete and re-add); delete removes the resource from the Library immediately (S3 object retained for audit — not deleted from bucket); Members cannot edit or delete (403); Administrators cannot edit or delete (403); changes take effect immediately with no approval step.

### US-2.26 — Content Library — Topics Autocomplete
**As a** curator adding or editing a Library resource, **I want** topic tag autocomplete suggestions **so that** tagging is consistent across resources.
**Acceptance Criteria**: When typing in the Topics field (US-2.23, US-2.24, US-2.25), the input shows existing tags as suggestions matching the typed prefix; tags are stored lowercase-normalized (e.g. "Serverless" → "serverless"); display shows the tag as entered but matches are case-insensitive; multiple tags allowed per resource; tags are free-form (no predefined list); suggestions sourced from all existing tags in the Library.

---

# Module 3 — Member Management
**Target service/bounded context**: Member Profiles & Directory Service; member/forum **semantic search delegated to a shared Search capability** (Amazon OpenSearch Serverless vector indices). Source: `requirements/usecases/03-member-management.md`

### US-3.1 — View My Profile
**As a** Member, **I want** to view my profile **so that** I see my community info.
**Acceptance Criteria**: Shows name, email, role, groups, certifications, and a **display-only contribution-score rollup** (sum of current-quarter points across the member's groups; no tier meaning, never used for tiering); location (city, country), professional role, AWS-project flag; each group listed with its own join date (most recent if rejoined); per-group current-quarter points + tier; activity summary (events attended, forum posts, contributions).

### US-3.2 — Edit My Profile
**As a** Member, **I want** to edit my profile **so that** my info is current.
**Acceptance Criteria**: Update display name, bio, avatar, skills/tags, city, country, professional role (free-text job title, not the access role), AWS-project (yes/no); email + access role not member-editable; can set time zone (Settings, US-8.14); Admin can also edit same fields via Edit User (latest save wins); changes reflected immediately.

**Bio & error rework — 2026-08-11.** Added acceptance criteria:
- Bio may be up to **2000 characters** (was an accidental 500, shared with city/country and never documented). It is **plain text** — angle brackets are still rejected (BR-17) and no markup is interpreted — and **line breaks are preserved** when the bio is displayed, on both the member's own profile and the member-detail page.
- The Bio editor shows a **live character counter** ("N of 2000 remaining") that warns as the limit nears and turns red when exceeded; **Save is blocked while over the limit**.
- Each **skill/tag** is length-bounded (≤60) and rejects angle brackets — previously skills were not validated at all.
- A failed save shows a **clear, prominent, screen-reader-announced** error naming the field and reason (e.g. "Bio: length must be 1-2000") instead of a bare "Validation failed." *(Fixes a defect where member-profiles dropped the per-field detail the server already produced.)*

### US-3.3 — View Another Member's Profile
**As a** Member/UGL/CL, **I want** to view another member's profile **so that** I learn about them.
**Acceptance Criteria**: Shows name, role, groups, certifications, display-only contribution-score rollup (no tier meaning), location, professional role, AWS-project, bio, skills, per-group tier badges, verified badges, activity summary; read-only (no Edit); all community roles can view; **Administrators cannot open this view** (they use identity-only admin list US-3.8 + Edit User); reachable by clicking a member's name anywhere.

### US-3.4 — Browse Member Directory
**As a** Member, **I want** to browse the directory **so that** I discover members.
**Acceptance Criteria**: Lists all members with name, email, role, groups, and per-group date joined (most recent if rejoined; "—" if none); contribution points NOT shown; pagination for large lists.

### US-3.5 — Search Members
**As a** Member, **I want** to search the directory **so that** I find specific people.
**Acceptance Criteria**: Semantic search by name/email/skills (intent-based, not keyword); powered by **Amazon OpenSearch Serverless vector indices**; embeddings generated on profile create/update; **no member hard-delete in Phase 1** — member embeddings never removed; deactivated members remain searchable with inactive badge; filter by role/group/certification held (Community Leader directory omits the "certification held" filter; member-facing has all three); results ranked by relevance; embedding model/pipeline deferred to design.

### US-3.6 — First-Time Login Experience
**As a** new Member, **I want** onboarding to join a group **so that** I can start participating.
**Acceptance Criteria**: On first access, presented available groups; can join one+ during onboarding; approval-required groups submit a join request (US-1.7) with pending notice; can skip and join later; then routed to home/dashboard.

### US-3.7 — Welcome Notification
**As a** new Member, **I want** a welcome notification **so that** I know how to start.
**Acceptance Criteria**: In-portal welcome on first login with links to group directory, upcoming events, community guidelines. Welcome email also sent (US-8.2/US-8.5) on first login via the admin-configurable Welcome template; subject to the admin per-type on/off switch (US-8.5), not subject to user opt-out (not a US-8.7 opt-out category).

### US-3.8 — View All Members (Admin)
**As an** Administrator, **I want** to view all members (synced from Cognito) **so that** I manage roles/groups.
**Acceptance Criteria**: List with name, email, role, city, country, status (active/inactive), groups; sourced from Cognito (no portal create/import here); join date not shown in this table; sortable by name/role/status; filter by role/status/group; Edit User (US-1.26) from the list.

### US-3.9 — Export Member List (Admin)
**As an** Administrator, **I want** to export the member list **so that** I can report/use external tools.
**Acceptance Criteria**: Export all or filtered subset to CSV; includes name, email, role, groups, status — **no contribution/points data** (Administrators don't access community data).

### US-3.10 — View Member Activity Summary
**As a** CL or UGL, **I want** a member's activity summary **so that** I understand engagement.
**Acceptance Criteria**: Shows events attended, forum posts, contributions submitted, certifications earned, points (current quarter + lifetime); shown on profile (leaders only); **Administrators cannot view**; UGLs only for their group's members; CLs any member; filter by date range.

---

# Module 4 — Forums & Discussions
**Target service/bounded context**: Forums Service (forums/channels/posts/replies, reactions, moderation); **search + LLM duplicate detection delegated** to Search + AI capabilities. Structure: `User Group → Forum(s) → Channel(s) → Posts → Replies`. Source: `requirements/usecases/04-forums-and-discussions.md`

### US-4.1 — Create a Forum
**As a** CL or UGL, **I want** to create a forum for a group **so that** members can discuss.
**Acceptance Criteria**: Provide name, description, target group; CL any group, UGL only led group; Administrators cannot; new forum gets a default "General" channel; visible to group members; a group may have multiple forums.

### US-4.2 — Create a Channel
**As a** CL or UGL, **I want** channels within a forum **so that** discussions are organized.
**Acceptance Criteria**: Provide name, description; listed under parent forum; same permissions as forum creation; all group members can post in every channel (no leader-only channels in Phase 1); examples General/Technical Q&A/Show & Tell.

### US-4.3 — Edit a Forum or Channel
**As a** CL or UGL, **I want** to edit a forum/channel **so that** I can update name/description.
**Acceptance Criteria**: Name + description editable; CL any group, UGL led group; Administrators cannot; existing posts unaffected.

### US-4.4 — Delete a Forum or Channel
**As a** CL or UGL, **I want** to delete a forum/channel **so that** unused spaces are removed.
**Acceptance Criteria**: CL any group, UGL led group; Administrators cannot; removed from navigation; warn all posts permanently deleted; confirmation required; previously earned points retained (leader may adjust, US-6.15); deleted posts/replies removed from search index (US-4.13).

### US-4.5 — Create a Post
**As a** Member (or participating leader), **I want** to create a post **so that** I can start a discussion.
**Acceptance Criteria**: Author must access the forum's group (Member belongs; CL any; UGL led group); provide title + rich-text body (formatting, code, images, links); max 5 images/post in S3; on submit, LLM duplicate analysis runs if enabled (US-6.4) — potential duplicates shown, flagged posts held for leader review; newest-first default; shows author, timestamp, reactions count, reply count.
**Deviation (Unit 5 Functional Design, 2026-08-08, user-approved — DV-1/DV-4)**: LLM **duplicate detection is out of scope for Phase 1** — no dup analysis, no held-for-review status, no Publish/Reject flow, no Duplicate-Flags queue. Every post publishes immediately on submit. Removes the AI-Gateway (Unit 14) runtime dependency for Forums. Body is stored as **Markdown** (sanitized on render). **No image uploads in Phase 1 (DV-4)** — body is text/formatting/code/links only; the "max 5 images/post in S3" clause is dropped (no S3 bucket, no malware scanning for this unit).

### US-4.6 — Reply to a Post
**As a** Member, **I want** to reply **so that** I can participate.
**Acceptance Criteria**: Threaded under original; rich text; shows author, timestamp, reactions; original author notified (email + in-portal).

### US-4.7 — Edit My Post or Reply
**As a** Member, **I want** to edit my own post/reply **so that** I can correct content.
**Acceptance Criteria**: Edit own posts/replies; "edited" indicator with timestamp; edit history not tracked (latest only).

### US-4.8 — Delete a Post or Reply
**As a** leader or author, **I want** to delete a post/reply **so that** unwanted content is removed.
**Acceptance Criteria**: Members delete own; CL any group; UGL led group; Administrators no access; permanent removal; replies to a deleted post also removed; points retained (leader may adjust, US-6.15); removed from search index (embeddings deleted, US-4.13).

### US-4.9 — @Mention a Member
**As a** Member, **I want** to @mention someone **so that** they're notified.
**Acceptance Criteria**: "@" autocomplete restricted to those who can access the post (forum group members + that group's UGL(s) + any CL) — a mention can never link a recipient to an inaccessible post; mentioned member notified (email + in-portal); rendered as clickable link to profile.

### US-4.10 — Receive Mention Notification
**As a** Member, **I want** notification when @mentioned **so that** I can respond.
**Acceptance Criteria**: Email includes who/where/link; in-portal notification with same; clicking navigates to the post.

### US-4.11 — React to a Post or Reply
**As a** Member, **I want** to react **so that** I express response without replying.
**Acceptance Criteria**: One+ reactions on any post/reply; available upvote, like, emoji set; counts displayed; can remove own reaction.
**Deviation (Unit 5 Functional Design, 2026-08-08, user-approved — DV-5)**: narrowed to **a single reaction per member per post/reply** (choosing a new kind replaces the previous; member can clear). Fixed reaction set {upvote, like, heart, celebrate, insightful}; per-kind counts displayed. Simpler UX + counts than the original "one or more."

### US-4.12 — Browse Forums and Channels
**As a** community participant, **I want** to browse forums/channels **so that** I find discussions.
**Acceptance Criteria**: Members see forums for their groups; UGLs only led group (with controls); CLs all; Administrators none; channels shown in sidebar/nav; each channel shows post count + last activity.

### US-4.18 — View a Channel (Post List)
**As a** community participant, **I want** to open a channel and see its posts **so that** I can scan and pick one.
**Acceptance Criteria**: Channel view lists posts (not a single thread); each row shows title, snippet, author, timestamp, reply/reaction counts, tags/badges (Pinned/Answered/edited); pinned at top (US-4.14); default newest-first, sort by most active/most reactions/unanswered; pagination + data-table controls (US-8.9); actions to create post + follow channel (US-4.16); channel-scoped search; click opens thread; breadcrumb Forums › Group › Channel › Post; role-scoped navigation; leaders see inline moderation controls per permissions, Members see participate-only controls.

### US-4.13 — Search Forum Posts
**As a** Member, **I want** to search forum posts **so that** I find discussions/answers.
**Acceptance Criteria**: Semantic search across post titles + bodies; **Amazon OpenSearch Serverless vector indices**; embeddings generated on post create/edit; **embeddings removed on delete** — post/reply delete (US-4.8), forum/channel delete (US-4.4), group hard-delete (US-1.11); filter by group/forum/channel/author/date range; results show title, snippet, author, channel, timestamp, ranked by relevance; deactivated users' posts remain searchable with inactive badge; embedding model/pipeline deferred to design.
**Deviation (Unit 5 Functional Design, 2026-08-08, user-approved — DV-2/DV-3)**: Semantic/vector search **downgraded to literal keyword search** in-service (title/body contains + group/forum/channel/author/date filters; no OpenSearch, embeddings, relevance ranking, or AI). Removes the Search (Unit 13) + AI-Gateway (Unit 14) dependency for Forums. **No inactive-author badge** on results (Forums does not track author active-state / does not consume UserDeactivated/UserReactivated). Result fields: title, snippet, author, channel, timestamp.

### US-4.14 — Pin a Post to Top of Channel
**As a** CL or UGL, **I want** to pin a post **so that** important info stays visible.
**Acceptance Criteria**: CL any channel, UGL own group only; pinned appear above regular posts; multiple pins allowed (order by pin date, newest first); visually distinguished; same users can unpin; pin/unpin doesn't notify.

### US-4.15 — Mark a Reply as Accepted Answer
**As a** post author or leader, **I want** to mark an accepted answer **so that** others find the resolution.
**Acceptance Criteria**: Author marks any one reply as Accepted; CL (any) and the group's UGL can mark/clear; accepted reply highlighted under original; only one at a time (new clears previous); can clear; no additional points awarded.

### US-4.16 — Follow a Channel or Post
**As a** community participant, **I want** to follow a channel/post **so that** I'm notified of activity.
**Acceptance Criteria**: Follow/unfollow a channel (new posts) or post (new replies); auto-follow own posts; in-portal notifications, email per preferences (US-8.7); can view/manage followed items; per-user, doesn't affect others.

### US-4.17 — Report a Post or Reply
**As a** Member, **I want** to report content **so that** leaders can review.
**Acceptance Criteria**: Report any post/reply with optional reason; routed to that group's UGL + CLs; moderation queue shows content, reporter, reason, date; leader can dismiss or delete (US-4.8); reporter not notified of outcome (Phase 1); reported content stays visible until a leader acts. Moderation-queue count shown as a nav badge and surfaced read-only in the notification bell (US-8.6, Option 2A) — not a stored notification.

---

# Module 5 — Certifications
**Target service/bounded context**: Certifications Service (definitions, claims, verification, expiry). Emits approval events to Contributions; uses Notifications. Source: `requirements/usecases/05-certifications.md`

### US-5.1 — Create a Certification/Badge
**As a** Community Leader, **I want** to define a certification/badge **so that** members can earn and display it.
**Acceptance Criteria**: Provide name, description, badge image, category; set **per-certification point value** awarded on claim approval (not a single flat value; auto-tracked "certification approval" reads this, US-6.5); optional expiry period; no prerequisites; daily scheduled expiry job — 2 weeks before: notify (email + in-portal); on expiry: remove badge + notify; points NOT reversed on expiry; published/available to claim.

### US-5.2 — Edit a Certification/Badge
**As a** Community Leader, **I want** to edit a certification definition **so that** I update details.
**Acceptance Criteria**: Update name, description, badge image, category, expiry period; changes don't affect already-verified member certifications.

### US-5.3 — Deactivate a Certification/Badge
**As a** Community Leader, **I want** to deactivate a certification **so that** it's not available for new claims.
**Acceptance Criteria**: Hidden from submission list; existing holders keep their badge; reactivatable any time.

### US-5.4 — Submit a Certification Claim
**As a** Member, **I want** to submit a claim with proof **so that** my achievement is recognized.
**Acceptance Criteria**: Members only; must belong to ≥1 group (else prompted to join); select a certification; select a **group to credit** (routes to that group's leaders; points credited there); block if a pending/approved claim exists for the same certification (across all groups; allowed only if prior rejected/revoked/expired/withdrawn); evidence via link or file (image/PDF); optional notes; status "Pending Verification"; if member leaves/removed from credited group before verification, claim auto-rejected ("No longer a member of the credited group"), may resubmit; confirmation on submit.

### US-5.5 — View My Certification Submissions
**As a** Member, **I want** to see my submission status **so that** I know what's pending/verified.
**Acceptance Criteria**: Members only; statuses Pending/Verified/Rejected; rejected show reason; can resubmit rejected with updated evidence; can **withdraw** only while Pending (confirmation; removed from leader queue; no badge/points); withdrawn shows no rejection reason and allows a new claim (treated like rejected for the duplicate check).

### US-5.6 — Verify a Certification Claim
**As a** CL or UGL, **I want** to review/verify claims **so that** only legitimate certifications display.
**Acceptance Criteria**: Reviewer sees member, credited group, certification, evidence, date; approve or reject with reason; Administrators cannot verify; UGLs verify only claims credited to their led group; CLs any; on approve badge added; member notified (email + in-portal).

### US-5.7 — View Pending Verifications
**As a** CL or UGL, **I want** to see pending submissions **so that** I can process them.
**Acceptance Criteria**: Sorted oldest first; UGLs see only claims credited to their led group; routed to the single credited group's queue; CLs see all; Administrators cannot; filter by certification type/group; pending-count badge in nav; leader-change reassignment mirrors US-6.9 (pending claims visible to CLs/co-leaders; new UGL inherits; none orphaned). Pending count shown as a nav badge and surfaced read-only in the notification bell (US-8.6, Option 2A) — not a stored notification.

### US-5.8 — Revoke a Certification
**As a** Community Leader, **I want** to revoke a certification **so that** expired/invalid ones are removed.
**Acceptance Criteria**: CL can revoke any verified certification; provide reason; badge removed; points NOT reversed; member notified with reason.

### US-5.9 — Display Badges on Member Profile
**As a** Member, **I want** my verified badges shown **so that** others see my achievements.
**Acceptance Criteria**: Only Members have profile badges; verified badges shown with image + name; ordered by date earned (newest first); clicking shows name, description, date earned.

### US-5.10 — Browse Certifications Catalog
**As a** Member, **I want** to browse available certifications **so that** I know what I can earn.
**Acceptance Criteria**: Catalog lists active certifications with image, name, description, category; shows which the member holds; can initiate submission directly.
**Scope note (change request 2026-08-07)**: User Group Leaders can also browse the catalog (read-only — no claim submission, no held/pending state, per BR-A3 claims remain Member-only). The permission matrix (`requirements/Role-and-Permission-Mapping.md`) always granted UGL `browse certification-catalog`; this note aligns the story and UI with it.

---

# Module 6 — Member Contribution Tracking
**Target service/bounded context**: Contributions & Scoring Service — system of record for the **append-only point ledger**; balances/tiers/leaderboards derived at runtime; DynamoDB Streams maintain rollups. Source: `requirements/usecases/06-member-contribution-tracking.md`
**Key model**: single community-wide scoring framework; **points & tiers tracked per user group**; community-wide event points distributed equally across the member's groups at earn time; certification points credited to the single selected group. Ledger entries carry member, group, activity type, pillar, points (may be negative), source (`auto`/`evidence`/`adjustment`), earned_date, quarter. Tiers computed at runtime, never snapshotted.

### US-6.1 — Configure the Scoring Framework
**As a** Community Leader, **I want** to configure the community-wide scoring framework **so that** points/tiers are defined across the community.
**Acceptance Criteria**: Add/edit/remove activity types (name, description, points, pillar, evidence-required); new/edited activities are forced evidence-required = yes (auto-tracked "no" limited to the fixed system set: event attendance, event delivery, event organizing, forum post created, forum reply created, certification approval — not UI-creatable/switchable); deactivating auto-rejects pending + notifies; per-event-type attendance & delivery values; certification-approval points come per-certification (US-5.1), framework only marks it auto-tracked; configurable quarterly tier thresholds (name, min points, label); deactivate (no new points, history preserved); delete only evidence-required activities (confirmation; pending auto-rejected + notified; history preserved); changes effective immediately (no recalculation of historical points); single framework for all groups; **seeded default framework** from `requirements/mockup/leader/scoring-framework.html` (tiers Gold/Silver/Bronze/Rising, default thresholds 75/50/25/0); seeded non-system activities default to evidence-required = yes.
> **Seed reconciliation note (gap-analysis C2):** the `scoring-framework.html` mockup pre-dates resolved issue #36, so one seed value must be reconciled: **"Complete AWS Certification"** must NOT be seeded as a flat-value activity — certification approval is auto-tracked but its points are read **per-certification** from each certification definition (US-5.1/US-6.5). The **fixed 6-activity auto-tracked system set** is: event attendance, event delivery, **event organizing** (US-6.18), forum post created, forum reply created, certification approval; only these may be seeded as auto-tracked. The seeded **"Organize an event"** activity maps to **event organizing** (auto-tracked, no evidence — the portal is the system of record for events and their designated organizers). Point values/thresholds from the mockup are otherwise usable as defaults.

### US-6.2 — View the Scoring Framework
**As a** Community Leader, **I want** to view the framework **so that** I review configuration.
**Acceptance Criteria**: Active activities grouped by pillar; each shows name, description, points, evidence-required; tier thresholds shown; CLs only (Administrators, Members, UGLs cannot view config).

### US-6.3 — Award Points for Event Attendance
**As the** system, **I want** to auto-award points on recorded attendance **so that** participation is tracked.
**Acceptance Criteria**: No points for RSVP, only confirmed attendance; only attendees holding the Member role earn (A/CL/UGL never); recorded via manual/Excel/Teams; value per event type; group-scoped → event's group; community-wide → distributed equally across member's groups at event date (none if member has no group); matched by email.

### US-6.17 — Award Points for Event Delivery
**As the** system, **I want** to auto-award delivery points to presenters **so that** facilitating is recognized.
**Acceptance Criteria**: To designated presenters (US-2.18) holding the Member role only; per-event-type delivery value (separate from attendance); internal members only; attribution group-scoped → event's group, community-wide → equal split across member's groups at event date (none if no group); awarded when event marked completed (US-2.19).

### US-6.18 — Award Points for Organizing an Event
**As the** system, **I want** to auto-award organize points to designated event organizer(s) **so that** organizing/running an event is recognized — no evidence, because the portal is the system of record for the event and its organizers.
**Acceptance Criteria**: "Event organizing" is a system-defined **auto-tracked** activity (evidence = no; part of the fixed set, not UI-creatable/switchable, US-6.1); awarded to member(s) the creator designates as **organizer(s)** on the event (US-2.18), distinct from presenters (who earn delivery, US-6.17); only organizers holding the Member role earn (A/CL/UGL never — a leader who creates/organizes earns nothing); internal members only; **single configurable point value** on the "Organize an event" activity (not per event type, not overridable per event); attribution group-scoped → event's group, community-wide → equal split across organizer's groups at event date (none if no group); awarded automatically when the event is marked completed (US-2.19) with no submission/review.

### US-6.4 — Award Points for Forum Activity
**As the** system, **I want** to auto-award forum points **so that** knowledge sharing is recognized.
**Acceptance Criteria**: Two separate auto-tracked activities — "forum post created" and "forum reply created" — each independently configurable/deactivatable (US-6.1); only authors holding the Member role earn; attributed to the group whose forum the post is in; uncapped; LLM duplicate analysis (when enabled): analyze new posts vs existing posts in the same group (all forums/channels), show matches before submit, if user still submits post is flagged and held until a UGL (own group)/CL unflags or rejects; enable/disable is a global Admin setting (US-8.3); if enabled but LLM unavailable, submission rejected with retry message (fail closed); if disabled, posts publish immediately and earn.

### US-6.5 — Award Points for Certification Earned
**As the** system, **I want** to auto-award points on certification approval **so that** upskilling is recognized.
**Acceptance Criteria**: Awarded on claim approval; value read from the specific certification's per-certification value (US-5.1); credited to the single group selected at submission (US-5.4); not reversed on later revoke/expire.

### US-6.6 — Submit a Contribution with Evidence
**As a** Member, **I want** to submit evidence for external activity **so that** I earn points.
**Acceptance Criteria**: Members only; must belong to ≥1 group (else prompted); select an active evidence-required activity type (auto-tracked/deactivated not selectable); select a group context (routes to that group's leader; on approve points attributed there); provide description, evidence (URL/file), activity date; status "Pending Approval"; if member leaves/removed from selected group before approval, auto-rejected ("No longer a member of the selected group"), may resubmit; confirmation on submit.

### US-6.7 — View My Submissions
**As a** Member, **I want** to view my submissions + status **so that** I track pending/approved.
**Acceptance Criteria**: Members only; list shows activity type, group, date, status (Pending/Approved/Rejected); rejected show reason; resubmit rejected with updated evidence; **withdraw** only while Pending (confirmation; removed from leader queue; no points); withdrawn shows no reason, allows a new submission.

### US-6.8 — Approve/Reject a Contribution Submission
**As a** CL or UGL, **I want** to review submissions **so that** only valid activities earn points.
**Acceptance Criteria**: Reviewer sees member, group context, activity type, description, evidence, date; CLs any group, UGLs led group; approve (points awarded) or reject with reason; member notified (email + in-portal); approved appear in contribution history.

### US-6.9 — View Pending Contribution Submissions
**As a** leader, **I want** to see pending submissions **so that** I can process them.
**Acceptance Criteria**: UGLs see led group; CLs all groups; sorted oldest first; pending-count badge in nav; **authoritative leader-change reassignment rule** (referenced by US-1.26 and US-5.7): on UGL removal, group's pending contribution + certification reviews become visible to CLs/other leaders; a newly assigned UGL inherits all pending contribution + certification reviews for that group. Pending count shown as a nav badge and surfaced read-only in the notification bell (US-8.6, Option 2A) — not a stored notification.

### US-6.10 — View My Points and Tier
**As a** Member, **I want** points/tier by group **so that** I understand my standing per group.
**Acceptance Criteria**: Members only; quarter selector defaults to current, fixed trailing window of last 8 quarters (no "launch quarter"); selected quarter may be empty (graceful state); select a group for detail — lifetime points, selected-quarter points, tier for that quarter (scoped to group); pillar breakdown (quarter + all-time); lifetime totals period-independent; points history (activity, group, points, date, pillar; split points show per-group portion; filter by quarter or all-time); never combined across groups.

### US-6.11 — View Quarterly Tier Standings
**As a** Member, **I want** tier/points in a selected group **so that** I know my standing/finish.
**Acceptance Criteria**: Members only; per selected group + selected quarter (same selector as US-6.10); tier thresholds NOT shown, no progress-to-next-tier bar; current quarter shows tier + current-quarter points + days remaining; past quarter shows final tier + points (no countdown).

### US-6.12 — Quarterly Tier Badge Award
**As the** system, **I want** to assign tier badges **so that** members are recognized per group.
**Acceptance Criteria**: Quarters = calendar quarters in UTC; **tiers computed at runtime, never snapshotted** (derived by summing group's ledger entries for the quarter vs thresholds); different tiers in different groups same quarter; entry attributed to a fixed quarter by earned date (evidence/certification claims count toward submission quarter; auto points by triggering-action date); late approval across a boundary attributes to the submission quarter and recalculates that quarter's tier on next read (badge updated + notification fires if a higher threshold is crossed); badge per group + quarter (e.g., "Gold · Serverless Guild · Q2 2026"); historical badges preserved; members notified (email + in-portal); deactivated members excluded from distributions/leaderboards (badges preserved); members who left a group excluded from that group's live distribution/leaderboard/top lists but points remain in aggregate totals and historical badges remain.

### US-6.13 — View Group Contribution Summary
**As a** leader, **I want** a group contribution summary **so that** I understand group engagement.
**Acceptance Criteria**: Shows total group points (quarter), member count, top contributors, pillar breakdown; top contributors + member counts reflect current membership (left/deactivated excluded, though their points remain in aggregate totals); filter by period (quarter/month/custom).

### US-6.14 — View Community Contribution Summary
**As a** Community Leader, **I want** a community-wide summary **so that** I report overall engagement.
**Acceptance Criteria**: CLs only (Administrators cannot); total community points, active-contributor count, tier distribution, top contributors; breakdown by pillar + group; filter by period; CSV export — one row per member per group with columns member_name, member_email, user_group, tier, total_points, points_upskilling, points_peer_learning, points_assets_demos, points_thought_leadership; period/scope in file name; deactivated members excluded as rows; CSV downloaded to browser.

### US-6.15 — Manually Delete/Adjust Points
**As a** CL or UGL, **I want** to manually adjust/delete points **so that** errors are corrected.
**Acceptance Criteria**: CLs any member; UGLs own group members only; select a specific entry to delete or apply an adjustment (positive/negative) with reason; applies to a specific group; logged (adjustor, member, group, points, reason, timestamp); member notified in-portal; reflected in group total + quarter immediately; totals may go below zero (no floor, no extra warning); tiers recompute at runtime.

**Screen rework — 2026-08-11.** The adjust screen was reworked and the previously unbuilt half of this story was completed. Added acceptance criteria:
- The member is chosen by **searchable typeahead**, never by typing an internal id. A CL searches the whole community; a **UGL's search is scoped to the group they lead**.
- The group is a **dropdown populated from the groups the selected member belongs to**, shown by name, with **no preselected value**. For a UGL it contains only the group they lead, since any other choice would be rejected by the server. A member belonging to no adjustable group **blocks** the adjustment rather than offering a community-wide fallback.
- The quarter is a **dropdown** of the current quarter plus the previous 7 (BR-J4), current preselected.
- The point change requires an **explicit sign followed by digits** (`+10`, `-5`); a bare number is rejected so a leader cannot add points while believing they were subtracting.
- The form shows the member's **current total for the chosen group and quarter and the projected total**, so a sign error is visible before it becomes a permanent ledger entry. If the total cannot be read the form says so and still permits the adjustment.
- **Reversing a specific existing entry is now available in the UI** (this story always required it; only the backend had been built). An entry already reversed shows a "Reversed" badge and offers no action.
- The form states that an adjustment is permanent, that the member is notified, and that a total may go below zero.

**Defect fixed in the same change**: this screen could never complete an adjustment. The shared form component submitted `delta` as a JSON string while the API requires an integer, so every attempt returned 400. Now sent as a number and pinned by a test.

### US-6.16 — View Leaderboard
**As a** Member, **I want** per-group leaderboards **so that** I see top contributors + my standing.
**Acceptance Criteria**: Per group, top 10 by that group's quarterly points; entry shows rank, name, avatar, current-quarter points (that group), tier badge (that group); members see a leaderboard per group they belong to (switchable); UGLs see led group; CLs any; not combined across groups; filter by quarter/pillar; Administrators cannot access; deactivated + members who left the group excluded (points remain in aggregate totals); most-recent data on load; accessed via a link on the Home page (not a sidebar item).

---

# Module 7 — Analytics Dashboard
**Target service/bounded context**: Analytics Service — read-model/rollups fed from DynamoDB Streams into a separate queryable analytics store (service choice deferred to design); AI reporting via shared AI/Bedrock capability. Data refreshed on page load. Source: `requirements/usecases/07-analytics-dashboard.md`

### US-7.1 — View Community-Wide Dashboard
**As a** Community Leader, **I want** a community-wide dashboard **so that** I understand overall health.
**Acceptance Criteria**: CLs only (Administrators cannot); default landing for CLs; announcements panel (US-10.4, collapsed with active count — community-wide + group-targeted the CL authored); metrics total/active/new members, growth %, total events, avg attendance, certifications earned, points distributed; tier-distribution chart; top-contributors list (names link to profiles); data refreshed on load.

### US-7.2 — View User Group Dashboard
**As a** CL or UGL, **I want** a group-scoped dashboard **so that** I track group engagement.
**Acceptance Criteria**: Same metrics filtered to group; CLs any group, UGLs led group; default landing for UGLs (their group); announcements panel (community-wide + group-targeted, US-10.4); quarter selector (default current); quarter-scoped metrics (group events, points, tier distribution, top contributors); top-contributor names link to profiles; Group Members reflects membership as of the selected quarter, computed from membership-event history (US-1.34); comparison vs community average for the quarter.

### US-7.3 — Membership Growth Chart
**As a** CL or UGL, **I want** a membership-growth chart **so that** I track trends.
**Acceptance Criteria**: Monthly member-count line chart derived from membership-event history (US-1.34) so members who later left still count for the months they were members; CL toggle community-wide vs per-group; UGL sees own group; range last 3/6/12 months.

### US-7.4 — Contribution Points Chart
**As a** CL or UGL, **I want** points visualized **so that** I understand engagement patterns.
**Acceptance Criteria**: Bar chart points by pillar (current quarter); line chart total points trend over time; pie chart tier distribution.

### US-7.5 — Event Attendance Chart
**As a** CL or UGL, **I want** attendance trends **so that** I measure event effectiveness.
**Acceptance Criteria**: Bar chart RSVP vs actual per event; line chart attendance trend over time; filterable by event type + delivery mode.

### US-7.6 — Certification Progress Chart
**As a** CL or UGL, **I want** certification progress **so that** I track upskilling.
**Acceptance Criteria**: Bar chart certifications earned per quarter; breakdown by type/category; community coverage % (members with ≥1 cert).

### US-7.7 — Generate Custom Report via AI Agent
**As a** CL or UGL, **I want** to ask the AI agent NL questions **so that** I get custom insights without building reports.
**Acceptance Criteria**: Chat interface on dashboard; questions like "zero-contribution members this quarter", "top 10 in Q2", "compare Group A vs B"; returns formatted answers with tables/charts; respects role scoping (UGL own group, CL all); detailed agent design (LLM, guardrails, response time, multi-turn, error handling) deferred to design.

### US-7.8 — AI Agent Suggested Insights
**As a** CL or UGL, **I want** proactive insights **so that** I'm aware of notable changes.
**Acceptance Criteria**: 2–3 AI-generated insights (e.g., growth %, forum-activity drop, near-Gold members); scoped by role; updated daily via scheduled batch; if AI unavailable, show stale insights with "last updated" timestamp; can dismiss/drill in; implementation deferred to design.

### US-7.9 — Export Contribution Data
**As a** CL or UGL, **I want** to export contribution data as CSV **so that** I use it externally.
**Acceptance Criteria**: Select date range; CL scope community-wide or a group, UGL own group only; CSV only; **one row per ledger entry** with columns member_name, member_email, user_group, activity_type, pillar, points (per-group portion for split; may be negative), source (auto/evidence/adjustment), earned_date, quarter; range + scope in file name; deactivated members' historical entries included for reconciliation (excluded from live dashboards); downloaded to browser.

### US-7.10 — Export Member Data
**As a** Community Leader, **I want** to export member data as CSV **so that** I use it externally.
**Acceptance Criteria**: CLs only (Administrators cannot); select join-date range; CSV only; **one row per member per group** (multi-group members appear once per group; groupless appears once with blank group fields) with columns member_name, member_email, portal_role, professional_role, city, country, aws_project, status, user_group, group_join_date, current_quarter_points, current_tier; join-date filter selects members who joined any group in range (only qualifying group rows included); range in file name; downloaded to browser.

### US-7.11 — Export Event Data
**As a** CL or UGL, **I want** to export event data as CSV **so that** I report on activities.
**Acceptance Criteria**: Select date range; CL community-wide or group, UGL own group; CSV only; **one row per event in range/scope** with columns event_title, event_type, delivery_mode, scope, event_date, duration, location, organizer, status, rsvp_yes, rsvp_no, attendance_count (blank if not Completed); range + scope in file name; downloaded to browser.

---

# Module 9 — Help Assistant
**Target service/bounded context**: Help Assistant capability (shared AI/Bedrock); grounded in portal features/rules (RAG). Source: `requirements/usecases/09-help-assistant.md`

### US-9.1 — Access Help Assistant
**As any** portal user, **I want** to access a help assistant **so that** I get answers about using the system.
**Acceptance Criteria**: Persistent help icon on all pages; conversational text chat; available to all authenticated users; chat history within current session only (cleared on logout/refresh).

### US-9.2 — Ask Questions About System Functionality
**As any** portal user, **I want** to ask about the portal **so that** I understand how features work.
**Acceptance Criteria**: NL questions; answers cover feature how-to, configuration/settings, step-by-step workflows, business rules/logic, role permissions; responses role-aware (note when only Admins can do an action); concise, actionable.

### US-9.3 — Scope Limitation — Non-Portal Questions Rejected
**As the** system, **I want** the assistant to only answer portal questions **so that** it stays focused.
**Acceptance Criteria**: Politely declines unrelated topics (general knowledge, coding, news, personal advice, other apps) with a standard message; does not generate/execute/suggest code; does not reveal its own implementation/model/system prompt.

### US-9.4 — Help Assistant Knowledge Base
**As the** system, **I want** the assistant grounded in the portal's features/rules **so that** answers are accurate.
**Acceptance Criteria**: Knowledge derived from portal requirements/business rules/documentation; reflects current behavior; acknowledges uncertainty/out-of-knowledge; LLM/RAG/KB-update/response-time deferred to design.

---

# Module 10 — Announcements
**Target service/bounded context**: Announcements Service (authoring, targeting, panel, dismissal); optional email via Notifications/SES. Source: `requirements/usecases/10-announcements.md`

### US-10.1 — Create an Announcement
**As a** CL or UGL, **I want** to post an announcement **so that** I broadcast important info.
**Acceptance Criteria**: Provide title + rich-text body; set audience (US-10.2); **mandatory expiry (default 2 days; author-adjustable up to a 90-day maximum)** — the announcement is automatically removed from all views after the expiry date; opt-in to also send as email (default off; if off, in-portal panel only); does NOT create a bell notification (panel only); visible to audience immediately.
> **Design deviation (2026-08-07, Unit 9 Functional Design, user-approved):** expiry changed from *optional / "remains until deleted"* to **mandatory with a 2-day default and 90-day maximum**. Rationale: a mandatory expiry lets DynamoDB TTL reclaim every announcement automatically and keeps the read set bounded (no unbounded growth), which is the basis of the fan-out-on-read panel design. Authors who need a long-lived notice set a longer expiry (up to 90 days) or re-post. Supersedes the earlier "if no expiry is set, it remains until the author deletes it" clause.

### US-10.2 — Target an Announcement
**As an** author, **I want** to choose recipients **so that** it reaches the right audience.
**Acceptance Criteria**: UGL targets only the led group; CL targets community-wide or one+ selected groups; group-targeted seen by all that group's members incl. its UGL(s); community-wide seen by all members + leaders; Administrators don't receive.

### US-10.3 — Manage Announcements (Edit/Delete)
**As the** author, **I want** to edit/delete **so that** I can correct or retract.
**Acceptance Criteria**: List own announcements (title, audience, created date, expiry, email-sent flag, status Active/Expired); edit title/body/target/expiry of own; delete own (removed for everyone immediately); CLs can delete any announcement (moderation); UGLs manage only own group announcements.

### US-10.4 — View Announcements
**As a** Member (or leader in audience), **I want** to see targeted announcements **so that** I stay informed.
**Acceptance Criteria**: Panel on landing page (Member Home for Members US-8.1; analytics dashboard for leaders — UGL: community-wide + led group; CL: community-wide + group-targeted they authored); collapsed by default with active count; each shows title, rich-text body, author, source (group/"Community-wide"), date; multiple announcements; expired not shown; no separate top banner.

### US-10.5 — Dismiss an Announcement
**As a** member, **I want** to dismiss an announcement **so that** I clear ones I've read.
**Acceptance Criteria**: Dismiss hides the announcement from that member's own view; **dismissal is remembered client-side (browser localStorage)** so it does not reappear on the same browser; it does not delete the announcement or affect other members or the author.
> **Design deviation (2026-08-07, Unit 9 Functional Design, user-approved):** dismissal is **UI-only (localStorage), not persisted server-side** — there is no Dismissals table. Rationale: with expiry now mandatory and short (default 2 days, US-10.1), the only downside — a dismissed announcement reappearing on a *different* device or after clearing browser storage — is bounded by the short lifetime, and it removes an entire table and a per-read dismissal query from the hot path. Supersedes the earlier "remembered for that member" (interpreted as cross-device) intent; dismissal is now remembered per-browser only.

---

# Module 11 — What's New in AWS Feed
**Target service/bounded context**: Frontend-only feature (client-side fetch/parse/render of a CORS-enabled RSS/Atom feed) + admin-settings config in Platform/Settings. No backend service in Phase 1. Source: `requirements/usecases/11-whats-new-aws-feed.md`

### US-11.1 — Configure the What's New in AWS Feed
**As an** Administrator, **I want** to configure the feed and toggle it **so that** I control whether/where personas see AWS announcements.
**Acceptance Criteria**: Section in Admin → Settings (US-8.3); enable/disable toggle (default enabled); set single RSS/Atom feed URL (expected CORS-enabled); changes effective immediately; Administrators configure but don't see the feed nav/page; URL + toggle changes audit-logged (US-1.13).

### US-11.2 — What's New Navigation Item
**As a** CL/UGL/Member, **I want** a dedicated nav item **so that** I open the feed when I want.
**Acceptance Criteria**: When enabled, "What's New in AWS" appears in the sidebar for CL/UGL/Member and opens the page (US-11.3); not shown on any dashboard; same page/content for all three (community-wide, not group-scoped); hidden for all when disabled (US-11.6).

### US-11.3 — What's New Detail Page
**As a** CL/UGL/Member, **I want** a page listing all announcements **so that** I browse the full feed.
**Acceptance Criteria**: Lists all parsed items, reverse-chronological by pubDate; each a collapsible row/card with title, summary, date, category badge(s); reachable from the nav item; fetches/renders on every page load (no caching).

### US-11.4 — Search and Filter the Feed
**As a** viewer, **I want** to search/filter announcements **so that** I find relevant news.
**Acceptance Criteria**: Search box matches title/summary/details; category filter populated dynamically from feed `<category>` tags; combinable; updates immediately; graceful empty state on no match; Phase 1 filters by raw category tag (curated taxonomy deferred).

### US-11.5 — View Item Details
**As a** viewer, **I want** full details + optional original AWS link **so that** I get complete info.
**Acceptance Criteria**: Click expands inline to full Details from RSS `<description>` rendered as-is HTML (formatting/links preserved); secondary "Read full announcement on AWS ↗" link (RSS `<link>`) opens original in a new tab; that link is the only navigation away, explicit secondary action (no auto-redirect); **design must sanitize feed HTML before DOM injection** (SECURITY-05).
**DEVIATION DV-1 (2026-08-10, Code Generation)**: "rendered as-is" is **not** honoured literally — feed HTML is **sanitized** (DOMPurify, permissive allow-list; scripts, inline handlers, `javascript:` URLs, iframes/objects/embeds, SVG and inline styles stripped; links forced to `target="_blank" rel="noopener noreferrer"`). The story's own SECURITY-05 clause requires this, and HTML was measured present in 100/100 official-feed descriptions arriving from a third-party origin. Formatting AWS actually uses is preserved, so the user-visible intent of "as-is" holds.

### US-11.6 — Feature Disabled Behavior
**As an** Administrator, **I want** the feed to disappear for everyone when disabled **so that** I can remove it cleanly.
**Acceptance Criteria**: Disabled → nav item + page unavailable for all personas; enabled but no URL → neutral "not configured yet" empty state (not an error); disabling never affects other content.

### US-11.7 — Client-Side Feed Loading and Error Handling
**As the** system, **I want** the feed fetched/parsed in the browser **so that** no server component is required.
**Acceptance Criteria**: Client-side request to configured CORS URL, parsed as XML in-browser; fetch/parse on every page load (no caching/persistence); on fetch/parse failure (network, malformed XML, empty) show graceful error/empty state without breaking the page; read-only (never writes back).
**DEVIATION DV-3 (2026-08-10, Code Generation)**: the story is implemented as written — the fetch is genuinely client-side with no backend component — but the "configured CORS URL" is necessarily a **self-maintained mirror**, because measurement showed neither `aws.amazon.com/about-aws/whats-new/recent/feed/` nor `feeds.feedburner.com/AmazonWebServicesBlog` returns `Access-Control-Allow-Origin`. Mirror publishing/refresh is **outside application scope**; contract in `infra/whats-new-feed/README.md`. Two implementation notes: the fetch deliberately uses plain `fetch` with credentials omitted rather than the app's authenticated client, so no portal token is ever sent to the third-party feed origin (DW-13); and **RSS 2.0 only** is parsed (both candidate feeds are RSS 2.0), with Atom rejected explicitly rather than mis-parsed.

---

# Module 8 — Cross-Cutting Concerns (User-Facing Features)
**Target service/bounded context**: Split across Notifications Service (US-8.2/8.6/8.7/8.15), Platform/Settings Service (US-8.3/8.4/8.5), shared file-share capability (US-8.13), and shared frontend concerns (US-8.1 home, US-8.8 responsive, US-8.9 data tables, US-8.14 time zone). Source: `requirements/usecases/08-cross-cutting-concerns.md`

### US-8.1 — Member Home Page
**As a** Member, **I want** a personal dashboard landing page **so that** I see relevant activity + contributions in one place.
**Acceptance Criteria**: Members only (leaders/Admins don't have it); combines activity overview + full contribution view (no separate My Contributions page); shows announcements panel (active, dismissible, newest first), my groups (links), upcoming events (next 5 from my groups + community-wide), recent forum activity (latest 5 from my groups), My Contributions section (quarter selector, per-group standing points/tier/pillar, points history, my submissions + submit action per US-6.10/6.11); default landing after login (except first-time onboarding); loads most recent data.

### US-8.2 — Email Notifications
**As a** Member, **I want** email notifications for important activity **so that** I stay informed outside the portal.
**Acceptance Criteria**: Triggered for (recipient): welcome (new user, first login); RSVP confirmation + .ics (RSVP'er); cancellation, update+ics, post-event materials (RSVPs); removed from group (removed member); join request approved/rejected (requester); group restored (former members); @mention (mentioned); reply to my post (author); followed activity (follower); accepted answer (reply author); contribution decision (submitter); activity-type deactivated (affected pending submitters); certification decision/revoked/expiring/expired (member); tier badge (member); announcement email opt-in (audience); account deactivation (deactivated). 21 email notification types total (was 22; the event reminder was removed 2026-08-27 with US-2.2/2.10). Recipient scoping per US-8.15 matrix — Administrators get only transactional account/security emails; leaders never get contribution/certification/tier/points emails; group-membership emails apply to a leader only for groups they belong to as a member. Sent via SES.
**Send gating (before any email is sent):** the Notifications Service resolves the event → notification type → template (US-8.5), then must pass, in order: (1) **admin per-type enabled switch** (US-8.5, system-wide, email-only — if off, drop silently, no retry) → (2) **user preference** (US-8.7, per-recipient, opt-out categories only — mandatory types skip this check). Both gates independent; both must pass for email to send. In-portal delivery (US-8.6), where the type has one, is never affected by either gate.

### US-8.6 — In-Portal Notifications
**As a** Member, **I want** in-portal notifications **so that** I'm aware of activity while using the portal.
**Acceptance Criteria**: Bell icon with unread count; panel of recent notifications; triggered for welcome (new user), @mention, reply, followed activity, accepted answer, join request decision, contribution decision, activity-type deactivated, certification decision/revoked/expiring/expired, points adjusted by leader, tier badge; recipient scoping per US-8.15 (Administrators none; leaders never contribution/cert/tier/points); mark-as-read removes from panel; panel shows latest 20 unread; "+N older" summary; older beyond limit auto-discarded; in-portal cannot be muted or gated by the admin email switch (US-8.5) — it is independent of email delivery.
> **Leader review-queue counts (Option 2A — gap-analysis A1):** for leaders, the bell may additionally display a **read-only summary of pending review-queue counts** — Contributions (US-6.9), Certification Verifications (US-5.7), Forum Moderation (US-4.17), and Join Requests (US-1.21) — surfacing the **same counts as the nav pending-count badges**. These counts are **computed on the fly, are NOT stored notifications, generate no email, and are NOT part of the US-8.15 recipient matrix**. This is the only leader-facing use of the bell for review work; no new notification type is introduced.

### US-8.3 — Centralized Admin Settings
**As an** Administrator, **I want** a centralized settings landing page **so that** I manage all configuration in one place.
**Acceptance Criteria**: Default landing for Admins; sections: audit logging (enable/disable + CloudWatch Log Group name); Cognito user sync (pool ID + region read-only deploy outputs; configure sync schedule; last-sync status); Community access & sign-in (allowed-email-domains allow-list, OTP re-verification interval days, max session/refresh-token lifetime; notes residual-access window); MS Teams (enable/disable, credentials); LLM duplicate analysis (enable/disable); Bedrock model ID (for all AI features); What's New feed (enable/disable + URL); email config (sender + templates); community branding (portal name default "AWS Community Portal", logo); system-wide default time zone (US-8.14); changes effective immediately; Admins only.

### US-8.4 — Configure Email Sender Settings
**As an** Administrator, **I want** to configure sender name/address **so that** emails look professional/branded.
**Acceptance Criteria**: Set sender display name + email; sender email must be SES-verified; all outgoing email uses it; failed deliveries retried exponential backoff (up to 3 retries / 15 min); after retries, discarded (no failure notification).

### US-8.5 — Manage Email Templates
**As an** Administrator, **I want** to customize email templates **so that** communications match branding/tone.
**Acceptance Criteria**: View/edit templates for each notification type (welcome, event cancellation/update, RSVP confirmation, post-event materials, join request approved/rejected, group restored, **@mention in forum post**, **reply to my forum post**, followed activity, accepted answer, submission approved/rejected, activity-type deactivated, certification approved/rejected/revoked/expiring/expired, tier awarded, removed from group, announcement, account deactivation) — 21 types, one-to-one with US-8.2 email triggers; variables/placeholders (e.g., {{member_name}}, {{event_title}}, {{tier_name}}); preview before save; default templates provided; changes effective immediately; template set kept in sync with US-8.2/8.7 triggers.
**Per-type Enabled/disabled switch:** each of the 22 types has an admin-controlled **Enabled** toggle (default on), shown next to its template, independent of template content. Off ⇒ Notifications Service sends no email for that type to any recipient (email-only; never affects the type's in-portal delivery per US-8.6, and evaluated before user preferences per US-8.7). System-wide, not per-user. Applies equally to mandatory types (e.g., account deactivation, group restored) even though individual users can't opt out of those themselves. Takes effect immediately.

### US-8.7 — Manage Email Notification Preferences
**As any** email-receiving user (M/UGL/CL), **I want** to manage email preferences **so that** I only get emails I care about.
**Acceptance Criteria**: Accessible from Settings (groups notification prefs and, for leaders, file sharing US-8.13); Administrators have no preferences (only transactional emails); user sees opt-out categories relevant to notifications they can receive: post-event materials, @mention/reply, followed activity, accepted answer, contribution/certification decisions, tier badge, certification expiry, announcements (email opt-in); mandatory (cannot opt out): removed from group, join request decision, group restored, account-related; saved immediately; in-portal notifications cannot be muted; opt-out + mandatory lists together cover exactly US-8.2 triggers (kept in sync with US-8.5).
**Relationship to admin switch (US-8.5):** two independent gates on the same email — admin per-type switch (system-wide) checked first, user preference (per-user, opt-out categories only) checked second; both must allow sending. Neither overrides the other — a user can't re-enable an admin-disabled type, and enabling a type admin-side doesn't override a user's own opt-out.

### US-8.15 — Notification Recipients by Role
**As the** system, **I want** a single authoritative notification→recipient mapping **so that** notifications reach only participants and never leak.
**Acceptance Criteria**: Roles M/UGL/CL/A. Implements the recipient matrix (24 notification types; #21 Welcome is Email + in-portal) from the source: Administrators receive only #23 account deactivation (Cognito-synced) and #24 local-admin password reset; leaders never receive contribution/certification/tier/points notifications (#13–20); group-membership notifications (#6,11,12) apply to a UGL only as a member of groups they don't lead and never to a CL; welcome (#21) fires for any role on first login (email + in-portal); announcement (#22) to CL only when community-wide. This mapping is the single source of truth referenced by US-8.2/8.6/8.7. Every "Email" row is additionally subject to the admin per-type switch (US-8.5) before send; the in-portal leg of a row (where present) is never gated by that switch. **Note (Option 2A):** leader pending review-queue counts surfaced in the bell (US-8.6) are read-only queue counts, not notifications, and are intentionally **not** rows in this matrix — the matrix remains member-facing for actual notification events.

### US-8.13 — Create and Manage External File-Share Links
**As a** CL or UGL, **I want** a secure, revocable upload folder in the community S3 bucket **so that** an external party can upload files and I can view/download.
**Acceptance Criteria**: From File Sharing tab on Settings (CL + UGL only; Members/Admins excluded); create link: provide folder name → folder (key prefix) in pre-existing configured community S3 bucket (leaders don't choose buckets); set expiry (7/14/30/90 days), optional max file size, note; generate shareable link to copy/email; upload side: link page allows write-only upload into that folder (no list/view/delete), scoped to that folder only, brokered via short-lived per-upload write-only pre-signed URLs; owner side: owner/any CL (UGL: creator) can view file list (name, size, uploader if captured, date) + download; revoke any time (immediate; stops upload/download); expiry stops use; deleting link doesn't delete files; copy disabled for expired/revoked; security: bucket not public, write-only single-folder scope, unguessable time-bound revocable token, create/revoke audited; exact mechanism (per-upload presigned vs scoped creds, token model, expiry enforcement, size/type validation, malware scanning, bucket/CORS/IAM) deferred to design.

### US-8.14 — Time Zone Settings
**As any** user, **I want** times in my own time zone and (Admin) a community default **so that** times are meaningful.
**Acceptance Criteria**: Admin sets system-wide default (US-8.3) applied to new users / those who haven't chosen; every user can set own time zone from Settings (overrides default); Admin can change a user's time zone via Edit User (US-1.26); latest change wins; all dates/times across portal rendered in the user's effective time zone; tz abbreviation shown where helpful; IANA tz list; effective immediately, display-only (stored canonically e.g. UTC); quarters for tiering remain UTC (US-6.12) regardless of display tz.

### US-8.16 — Dismissible Feedback Panels and Clean UI Text
**Target**: cross-cutting frontend standard, ALL units. Added 2026-08-03 by user instruction during Unit 11 deployment review.
**As any** user, **I want** feedback messages I can dismiss and UI text free of internal jargon **so that** the portal feels polished and stays out of my way.
**Acceptance Criteria**: Every success/failure/warning/suggestion message panel anywhere in the portal has a visible dismiss control (✕) that removes it immediately; validation error messages identify the offending field(s) (never a bare "Validation failed."); user-facing UI text never contains internal requirement/story identifiers (e.g. "US-1.30") or internal codenames — those live in code comments/documentation only; enforced at every unit's code-generation review.

### US-8.9 — Configurable Data Tables
**As any** user, **I want** consistent controls on every search/listing table **so that** I can tailor display and have it remembered.
**Acceptance Criteria**: Applies to all listing tables (directory, admin user list, group directory, events, pending queues, points history, submissions, leaderboard, audit-driven lists); every column sortable (asc/desc, active indicated); column settings menu (reorder, show/hide via toggles with mandatory non-hideable primary identifier, rows-per-page 10/25/50/100); settings user-specific + persisted across sessions (per user, per table); defaults for first-time users (default sort, default visible columns, 25 rows); changes effective without full reload; persistence mechanism deferred to design.

### US-8.8 — Responsive Web Experience
**As a** Member, **I want** to use the portal on any device **so that** I participate from anywhere.
**Acceptance Criteria**: Fully usable on desktop/tablet/mobile browsers via responsive design; no native app; all core features accessible on all screen sizes (browsing, RSVP, forums, profiles, notifications); breakpoints/details deferred to design.

---

# Cross-Cutting Constraints & NFRs (Global — inherited by every story)
Per Q7 = A, these apply to all stories and services and are not repeated per story. Authoritative detail: `aidlc-docs/inception/business-requirements/requirements.md` (§4 NFRs, §6 Security, §7 Resiliency) and `requirements/non-functional-requirements.md`.

- **RBAC enforcement**: server-side per `Role-and-Permission-Mapping.md`; unauthorized → 403 (US-1.12). Object-level + function-level authorization (SECURITY-08).
- **Security baseline (enabled)**: SECURITY-01…15 apply — encryption at rest/in transit, API access + app logging, HTTP security headers on the SPA/CloudFront, input validation + sanitization (incl. feed HTML US-11.5), least-privilege IAM, app-level access control, hardening, pinned deps + scanning + SBOM, secure design, Cognito credential management, integrity/SRI, alerting, fail-closed exception handling.
- **Resiliency baseline (enabled)**: RESILIENCY-01…15 apply as relevant — Backup & Restore DR (RTO/RPO hours), single-region multi-AZ, monitoring/health checks, timeouts + graceful degradation on Bedrock/SES/Teams, DynamoDB PITR + S3 versioning, restore runbook, lightweight incident response + COE (proposed). Change management: exempt (IaC-only run). CI/CD: manual `sam deploy`; pipeline deferred.
- **Performance**: CRUD/nav < 500ms p95; semantic search < 2s p95; analytics load < 3s p95; help assistant target deferred; 5,000 concurrent users.
- **Scalability**: 10–12k members; serverless auto-scale (Lambda, DynamoDB on-demand); Streams-maintained rollups + separate analytics store.
- **Concurrency**: last-write-wins universally (no optimistic locking Phase 1).
- **Data retention**: audit logs 12 months; soft-deleted groups 2 weeks; all else indefinite.
- **Browser support**: latest 2 versions of Chrome/Firefox/Safari/Edge; no IE11.
- **Language**: English-only (no i18n). **Accessibility**: WCAG out of scope Phase 1.
- **AI/ML**: Amazon Bedrock, admin-configurable model ID; duplicate detection fails closed; insights show stale-with-timestamp on failure.
- **Email**: Amazon SES; retry exponential backoff up to 3 / 15 min, then discard.
- **Tech stack**: Polyglot Lambdas (Python/Node.js/Rust — language per service decided at Construction) · API Gateway REST · React+Vite SPA on S3/CloudFront · CloudFormation + SAM · IaC-only (not deployed by AI).
- **Out of scope (Phase 1)**: SSO/SAML/OIDC; native app; i18n; WCAG; app-level rate limiting on posts/submissions; active-session force-revocation; member hard-delete; data-privacy/GDPR erasure; the external CORS feed server; multi-region DR; CI/CD pipeline.

---

# Module 12 — Personal Progress Timeline
**Target service/bounded context**: Milestone Evaluator (EventBridge consumer, read-only observer of existing service events). Frontend: Profile page, Home page teaser. Source: brainstorm session 2026-08-14.

**Design Principles**:
- **Informational only** — milestones never award points or create framework activities. The scoring framework (Module 6) remains the single authority on points/tiers.
- **Pure observer** — reads events from existing services, writes milestone records, zero side effects back to source services.
- **Milestones are permanent** — once earned, never revoked (even if CL changes tier thresholds later). They are a historical record of "you were here at this moment."
- **Horizontal road metaphor** — scrollable left-to-right journey map, details on hover/tap. Minimal DOM, CSS-only scroll, progressive disclosure via tooltip.
- **Performance-first** — ≤3 DOM nodes per milestone (dot + icon + connector). No JS scroll listeners. Tooltip shows one detail card at a time.

## Timeline Rendering

### US-12.1 — Horizontal Journey Road on Profile
**As a** Member, **I want** to see my journey as a horizontal scrollable road on my Profile page **so that** I feel a sense of progression.
**Acceptance Criteria**
- A horizontal road renders in the right column below the Activity Summary card.
- Each earned milestone is a colored dot + emoji icon on the road. Road scrolls left (past) → right (present).
- A pulsing "you are here" indicator sits on the last earned milestone.
- A dashed line extends rightward from the current position to the next unearned milestone (faded dot).
- Hover (desktop) or tap (mobile) on any dot reveals a tooltip with title, detail text, and date.
- Empty state for members with zero milestones: "Your journey starts here — join a group to begin!"
- Render performance: ≤150 DOM nodes for 50 milestones. Pure CSS `overflow-x: auto`. No JS scroll listeners.

### US-12.2 — Next Milestone Indicator
**As a** Member, **I want** to see what my next milestone is and how close I am **so that** I know what to work toward.
**Acceptance Criteria**
- The road shows the next unearned milestone as a faded dot beyond the "you are here" marker.
- A dashed connector line leads from the current position to it.
- Tooltip on the faded dot shows what's needed (e.g., "Write your first forum post" or "2 more events to reach 5 attended").
- The system picks the milestone closest to completion — no manual goal selection by the member.

### US-12.3 — Automatic Milestone Evaluation
**As a** Member, **I want** my milestones to be earned automatically when I hit thresholds **so that** I don't need to claim them manually.
**Acceptance Criteria**
- Milestones are evaluated via event-driven processing (EventBridge consumers listening to existing service events).
- No manual action required from the member.
- New milestones appear on the road the next time the member views their profile.
- Evaluation latency: < 5 seconds from trigger event to milestone record written.
- Idempotent: reprocessing the same event never creates duplicate milestones.

### US-12.4 — Home Page Journey Teaser
**As a** Member, **I want** a compact milestone highlight on my Home page **so that** I'm reminded of my progress on every login.
**Acceptance Criteria**
- Home page shows below the stat row: last earned milestone (icon + title + date) and the next milestone with a progress micro-bar.
- Links to full road on Profile page ("View my journey →").
- Compact — single line height, does not push existing content significantly.

### US-12.5 — Public Profile Visibility
**As a** visitor to another member's Profile, **I want** to see their journey road **so that** I can understand their experience and be inspired.
**Acceptance Criteria**
- Timeline road is visible on public profile views (/directory/{id}).
- "You are here" pulsing indicator is hidden for viewers (it's the profile owner's private context).
- "Next milestone" faded dot is hidden for viewers (private motivation, not public).
- Only earned milestones (solid dots) are visible to others.

### US-12.6 — Community Leader Viewing Member Timelines
**As a** Community Leader, **I want** to see any member's timeline road on their profile **so that** I can recognize engaged members for spotlights or leadership roles.
**Acceptance Criteria**
- CL viewing /directory/{id} sees the same earned-milestone road as any member viewing another's profile.
- No additional CL-specific milestone data or admin controls.

### US-12.7 — New Milestone Celebration
**As a** Member, **I want** a subtle celebration when I earn a new milestone **so the** moment feels special.
**Acceptance Criteria**
- On the first profile view after a new milestone is earned: the new dot on the road glows with a brief pulse animation (CSS keyframe, ~2 seconds).
- Professional — no confetti, no sound. Just a highlighted glow on the new dot.
- Glow shown once per milestone (milestone marked `seen: true` after first display).

### US-12.8 — Tooltip Interaction (Performance)
**As a** Member, **I want** milestone details to appear only when I interact with them **so that** the road stays clean and fast.
**Acceptance Criteria**
- Title, detail text, and date are shown in a positioned tooltip on hover (desktop) or tap (mobile).
- Only one tooltip visible at a time. Disappears on mouse-leave or tap-elsewhere.
- No text is rendered on the road itself — only dots and icons.
- Tooltip latency: < 16ms (one frame) — data already in memory from the initial API response, no network call on hover.

### US-12.9 — Backfill for Existing Members
**As an** existing Member who joined before this feature launched, **I want** to see milestones I've already earned **so that** my history isn't blank.
**Acceptance Criteria**
- On first `GET /members/me/milestones` where no milestone records exist, a one-time backfill runs.
- Reads current profile stats (groups, activity counts, tiers, certifications) and writes milestone records with actual dates where available (group join date, account creation date).
- Undated milestones (e.g., "10 posts" where the 10th post date is unknown) use a "before timeline launch" placeholder date.
- Backfill completes in < 500ms for members with up to 5 years of history.
- Subsequent calls read from the pre-computed store (fast path).

### US-12.10 — Personal Best Quarter (Throttled)
**As a** Member, **I want** "Personal best quarter" to only appear when meaningfully beaten, not on every +1 point improvement.
**Acceptance Criteria**
- Personal best milestone triggers only when the new total exceeds the previous best by ≥20% OR ≥10 points (whichever threshold is lower).
- Capped at 3 lifetime "Personal best" entries to avoid road clutter.
- Detail text shows: "New best: 85 points in Q3 2026 (previous: 62 in Q1 2026)".

## Milestone Catalog

The milestone evaluator monitors existing service events and derives the following milestones. **No milestone awards points** — they are display-only records.

### Membership Milestones
| Milestone | Trigger Event | Icon |
|-----------|--------------|------|
| Joined the community | `UserProvisioned` | 🎉 |
| Joined first group | First `MemberJoinedGroup` | 👥 |
| Multi-group member | Active in 2+ groups simultaneously | 🌐 |
| Profile completed | Bio + skills + location all non-empty | ✨ |
| 6-month veteran | Account age ≥ 180 days + ≥1 activity per month | 🎖️ |
| 1-year anniversary | Account age ≥ 365 days | 🥳 |

### Forum Milestones
| Milestone | Trigger Event | Icon |
|-----------|--------------|------|
| First forum post | `PostCreated` (count = 1) | 💬 |
| Active discussant | `PostCreated` (count = 10) | 🗣️ |
| Prolific poster | `PostCreated` (count = 25) | 📢 |
| First accepted answer | `ReplyAccepted` (count = 1) | ✅ |
| Helpful expert | `ReplyAccepted` (count = 5) | 🧠 |
| Mentor | `ReplyAccepted` (count = 10) | 🎓 |

### Event Milestones
| Milestone | Trigger Event | Icon |
|-----------|--------------|------|
| First event attended | `EventAttended` (count = 1) | 📅 |
| Regular attendee | `EventAttended` (count = 5) | 🎪 |
| Event enthusiast | `EventAttended` (count = 10) | 🌟 |
| Community fixture | `EventAttended` (count = 25) | 💎 |

### Certification Milestones
| Milestone | Trigger Event | Icon |
|-----------|--------------|------|
| First certification | `CertificationApproved` (count = 1) | 🎓 |
| Multi-certified | `CertificationApproved` (count = 3) | 🏆 |
| Certification champion | `CertificationApproved` (count = 5) | 👑 |

### Tier Milestones (observed from scoring framework output)
| Milestone | Trigger Event | Icon |
|-----------|--------------|------|
| Reached Silver | `RollupUpdated` → tier = Silver in any group | 🥈 |
| Reached Gold | `RollupUpdated` → tier = Gold in any group | 🥇 |
| Leaderboard Top 3 | Ranked 1–3 in any group/quarter | 🏅 |

### Contribution Milestones (observed from scoring framework output)
| Milestone | Trigger Event | Icon |
|-----------|--------------|------|
| First contribution approved | `ContributionApproved` (count = 1) | 📝 |
| Consistent contributor | `ContributionApproved` (count = 5) | ⭐ |
| Pillar diversity | Points in 3+ pillars in one quarter | 🌈 |
| Cross-group contributor | Points in 2+ groups in same quarter (shows group names) | 🔗 |
| Personal best quarter | New total exceeds previous best by ≥20% or ≥10 pts (max 3) | 📈 |

## What Milestones Are NOT
- ❌ A scoring mechanism (no points awarded, ever)
- ❌ Configurable by CL (no admin UI for milestone definitions — they are code-defined thresholds)
- ❌ Revocable (tier thresholds change → existing milestones stay permanently)
- ❌ A duplicate of the activity feed (milestones are sparse highlights, not every action)
- ❌ A goal-setting tool (system picks the next milestone, no manual pinning)
- ❌ Coupled to the scoring framework (pure one-way observation, never writes back)

---

# Module 13 — Shoutouts
**Target service/bounded context**: Member Profiles service (shoutouts partition in existing DynamoDB table + GSI for feed). Source: brainstorm session 2026-08-14.

**Design Principles**:
- **Leader-to-member recognition** — CL can shout out any member; UGL can shout out own group members only.
- **Lightweight** — one message (max 280 chars), one recipient, one click to send. No categories, tags, or approval workflow.
- **Visible to all** — shoutouts appear on the Home page feed and permanently on the recipient's profile.
- **Bounded** — 3 shoutouts per leader per week, max 1 per recipient per leader per week. Scarcity creates value.
- **Performance-aware** — groups may have 13,000+ members. Recipient picker uses server-side search (existing paginated `/members` endpoint), not client-side list loading. Feed queries use a GSI, never scan.

## Sending Shoutouts

### US-13.1 — CL Sends a Shoutout
**As a** Community Leader, **I want** to give a public shoutout to any member with a short message **so that** I can recognize specific contributions the point system doesn't fully capture.
**Acceptance Criteria**
- A "👏 Give Shoutout" button appears in the Member Directory, Group Detail member rows, and CL Dashboard.
- Clicking opens a modal with: recipient (pre-filled if clicked from a member row, or a searchable picker), message textarea (280 char limit with counter), and remaining weekly quota display.
- On send: shoutout immediately appears on the Home feed and recipient's profile.
- Toast confirmation: "Shoutout sent to [Name]."
- CL can shout out any active Member across any group.
- CL cannot shout out other CLs, UGLs, or Administrators (leaders recognize members, not each other).
- Leader shoutouts display a "⭐ Leader Pick" badge to distinguish them from peer shoutouts.
- **Performance**: Recipient picker uses server-side search (existing `GET /members?q=...&limit=10`), never loads the full 13,000+ member list client-side.

### US-13.2 — UGL Sends a Shoutout (Own Group Only)
**As a** User Group Leader, **I want** to give a shoutout to members of my group **so that** I can recognize their contributions within my group context.
**Acceptance Criteria**
- A "👏 Shoutout" button appears in My Group → Members tab action column.
- Modal opens with recipient pre-filled (cannot be changed to someone outside the led group).
- Same message format (280 chars), same weekly quota (3/week), same confirmation.
- UGL can only shout out Members of their own led group.
- Displays "⭐ Leader Pick" badge (same as CL shoutouts).
- **Performance**: Pre-filled recipient from the already-loaded member row. If a picker is needed, scoped to `GET /groups/{ledGroupId}/members?q=...&limit=10`.

### US-13.11 — Member Sends a Peer Shoutout
**As a** Member, **I want** to give a shoutout to another member **so that** I can publicly thank a peer for helping me or contributing to the community.
**Acceptance Criteria**
- A "👏 Give Shoutout" button appears in the Member Directory next to member rows (visible to Members).
- Clicking opens the same modal as the leader flow: searchable recipient picker + message (280 chars) + quota display.
- Members can only shout out other Members (not CL/UGL/Admin).
- Members cannot shout out themselves.
- Peer shoutouts appear on the Home feed and recipient's profile WITHOUT the "⭐ Leader Pick" badge (plain style).
- Same toast and notification flow as leader shoutouts.
- **Performance**: Same server-side search as CL/UGL — never loads full member list.

### US-13.3 — Weekly Sending Limit (Role-Based)
**As a** community member, **I want** my shoutout quota enforced **so that** each shoutout remains meaningful and selective.
**Acceptance Criteria**
- **Leaders (CL/UGL)**: 3 shoutouts per calendar week (Monday–Sunday UTC).
- **Members**: 1 shoutout per calendar week.
- No sender can send more than 1 shoutout to the same recipient in the same week (all roles).
- The modal shows "Remaining this week: X of Y" (where Y is 3 for leaders, 1 for members) before sending.
- When quota is exhausted, the Send button is disabled with message: "You've used your shoutout for this week. Resets Monday." (member) or "You've used all 3 shoutouts for this week. Resets Monday." (leader).
- Quota resets every Monday 00:00 UTC (no scheduled job needed — checked at send time against createdAt dates).

## Viewing Shoutouts

### US-13.4 — Home Page Shoutouts Feed
**As a** Member, **I want** to see recent shoutouts on the Home page **so that** I'm aware of who's being recognized and what behaviors are valued.
**Acceptance Criteria**
- A "👏 Shoutouts" section appears on the Home page below the journey teaser.
- Shows the most recent shoutouts from the last 7 days, maximum 5 displayed.
- Each card shows: message text, recipient name + group, sender name + role, relative timestamp ("2 days ago"), and 👏 reaction count.
- Clicking the recipient's name navigates to their profile.
- If no shoutouts in the last 7 days: section is hidden (no empty state clutter).
- **Performance**: Single GSI query on `SHOUTOUT_FEED` partition, limit 5, no scan. Response < 100ms.

### US-13.5 — Shoutouts on Recipient's Profile
**As a** visitor to a member's profile, **I want** to see shoutouts they've received **so that** I understand their reputation and contributions.
**Acceptance Criteria**
- A "👏 Shoutouts Received" section appears on the member's profile page (right column, below the Journey road).
- Shows all shoutouts received (paginated if > 5, "Show more" button).
- Each entry shows: message, sender name + role, date, 👏 count.
- Sorted newest first.
- Visible to anyone viewing the profile (public).
- **Performance**: Single GSI query on `RECIPIENT#<memberId>` partition, newest first. No scan.

### US-13.6 — Peer Reaction (👏)
**As a** Member, **I want** to react 👏 to a shoutout **so that** I can show the community agrees with the recognition.
**Acceptance Criteria**
- Each shoutout card (on Home and Profile) has a 👏 button with the current count.
- Any authenticated member (including CL/UGL) can react once per shoutout (toggle on/off).
- Clicking when already reacted removes the reaction (toggle behavior).
- Count updates immediately in the UI.
- No notification sent for reactions (low-noise).
- **Performance**: Reaction is a conditional put on `SHOUTOUT#<id> / REACTION#<userId>`. Count maintained via atomic increment on the shoutout record. No read-modify-write race.

## Notifications & Milestones

### US-13.7 — Recipient Notification
**As a** Member, **I want** to be notified when I receive a shoutout **so that** I know a leader recognized my contribution.
**Acceptance Criteria**
- In-portal notification: "👏 [Sender Name] gave you a shoutout: '[first 50 chars]...'"
- Email notification (if enabled in preferences): Same message with portal link.
- Notification links to the Home page shoutouts section.
- Published via existing EventBridge → Notifications service pattern.

### US-13.8 — Shoutout Milestone (Journey Integration)
**As a** Member, **I want** receiving my first shoutout to appear on my journey road **so that** social recognition is part of my progression story.
**Acceptance Criteria**
- "First shoutout received" milestone added to the Module 12 milestone catalog (category: social, icon: 🎊).
- "5 shoutouts received" as a second social milestone (icon: 🌟).
- Milestone evaluator listens to `ShoutoutReceived` event.
- Milestone is informational only — no points awarded.

## Moderation

### US-13.9 — Leader Deletes Own Shoutout
**As a** leader who sent a shoutout, **I want** to delete it **so that** I can correct mistakes (wrong person, typo, inappropriate phrasing).
**Acceptance Criteria**
- The sender sees a "Delete" option on their own shoutout cards.
- Confirmation prompt: "Delete this shoutout? This cannot be undone."
- On delete: removed from Home feed and recipient's profile immediately.
- No notification sent to the recipient on deletion (silent removal).

### US-13.10 — CL Moderates Any Shoutout
**As a** Community Leader, **I want** to delete any shoutout **so that** I can remove inappropriate content regardless of who sent it.
**Acceptance Criteria**
- CL sees a "Delete" option on ALL shoutout cards (not just their own).
- Same confirmation and behavior as US-13.9.
- Audit logged: who deleted, which shoutout, when.

## Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-SO-1 | Home feed query latency | < 100ms (p95) — single GSI query, limit 5 |
| NFR-SO-2 | Profile shoutouts query | < 100ms (p95) — single GSI query per member |
| NFR-SO-3 | Send shoutout latency | < 500ms (write shoutout + publish event) |
| NFR-SO-4 | Recipient picker | Server-side search, never loads full member list. < 200ms response. |
| NFR-SO-5 | Reaction toggle | Atomic conditional put + counter increment. No race conditions. < 100ms. |
| NFR-SO-6 | Weekly limit check | Query sender's shoutouts for current week (max 3 records). < 50ms. |
| NFR-SO-7 | Storage | ~500 bytes/shoutout. 3/leader/week × 52 weeks × N leaders = negligible. |
| NFR-SO-8 | No full-table scans | All access patterns use partition key + sort key or GSI. Never scan. |

## Data Model (DynamoDB — member-profiles table)

```
Shoutout record:
  PK: SHOUTOUT#<shoutoutId>
  SK: META
  Attributes: shoutoutId, recipientId, recipientName, recipientGroupId,
              senderId, senderName, senderRole, message, createdAt, reactionCount

Home feed GSI (GSI-SHOUTOUT-FEED):
  PK: SHOUTOUT_FEED (fixed partition)
  SK: <createdAt> (descending — Query ScanIndexForward=false, limit 5)

Recipient profile GSI (GSI-SHOUTOUT-RECIPIENT):
  PK: RECIPIENT#<recipientId>
  SK: <createdAt> (descending)

Sender weekly history (for limit check):
  PK: SENDER#<senderId>
  SK: SHOUTOUT#<createdAt>
  (Query where SK > weekStart — returns ≤3 items)

Reactions:
  PK: SHOUTOUT#<shoutoutId>
  SK: REACTION#<userId>
  (Existence = reacted. Count maintained atomically on the shoutout META record.)
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/shoutouts` | CL / UGL | Send: `{ recipientId, message }` |
| GET | `/shoutouts/recent` | Any authenticated | Home feed (last 7 days, max 5) |
| GET | `/shoutouts/member/{id}` | Any authenticated | Recipient's profile feed |
| DELETE | `/shoutouts/{id}` | Sender or CL | Delete a shoutout |
| POST | `/shoutouts/{id}/react` | Any authenticated | Toggle 👏 reaction |

---

# Module 14 — Event Ideas
**Target service/bounded context**: Events Service (new `eventIdeas` partition in existing DynamoDB table). Frontend: Events page new "💡 Event Ideas" tab for Member, CL, and UGL. Source: brainstorm session 2026-08-15. Mockups: `requirements/mockup/member/event-ideas.html`, `requirements/mockup/leader/event-ideas.html`, `requirements/mockup/ugl/event-ideas.html`.

**Design Principles**:
- **Member demand signal** — members submit and vote, leaders act on the strongest signals
- **Group-scoped** — ideas belong to a specific group or community-wide; UGL sees only their group's ideas
- **Auto-archive** — ideas with no new votes for 30 days are automatically archived (no manual cleanup needed)
- **Vote count is public** — anyone can see how many votes an idea has; voter list is private
- **No trending banner, no leader notifications** — leaders check the backlog on their own schedule
- **Greenlight pre-fills Create Event** — reduces friction when a leader acts on a popular idea
- **Non-anonymous** — submitter's name is shown (filters frivolous submissions, enables leader follow-up)

## Submitting Ideas

### US-14.1 — Member Submits an Event Idea
**As a** Member, **I want** to suggest an event idea **so that** I can signal what topics my group would find valuable.
**Acceptance Criteria**
- A "💡 Event Ideas" tab appears on the Events page alongside "Browse Events" and "Content Library".
- Within the tab, a collapsible "Suggest an Event" form accepts: title (required, 100 chars), description (optional, 500 chars), format preference (Workshop / Presentation / Meetup / Webinar / Hackathon / AMA / Any), preferred time (Weekday morning / Weekday evening / Weekend / No preference), delivery mode (Virtual / In-Person / No preference), and target group (member's groups + Community-wide option).
- On submit: idea is immediately visible in the public feed with 0 votes and "Open" status.
- Toast confirmation: "Idea submitted! The community can now vote on it."
- A member can submit multiple ideas (no per-member limit).
- Members cannot submit ideas for groups they don't belong to (except Community-wide).

### US-14.2 — UGL and CL Can Also Submit Ideas
**As a** UGL or CL, **I want** to submit event ideas **so that** leaders can seed the backlog with ideas they've heard from members.
**Acceptance Criteria**
- Same form as US-14.1 available to UGL (scoped to their group + Community-wide) and CL (any group or Community-wide).
- Submitted ideas appear in the same feed and are subject to the same voting and greenlight workflow.

## Voting

### US-14.3 — Member Upvotes an Idea
**As a** Member, UGL, or CL, **I want** to upvote event ideas **so that** popular topics rise to the top.
**Acceptance Criteria**
- Each idea card shows a 👍 upvote button and the current vote count.
- One vote per user per idea (toggle: click to vote, click again to remove).
- Vote count is public (visible to all authenticated users). Voter list is private (not exposed in any API or UI).
- Voting is available for any Open idea regardless of which group it targets.
- No downvoting. Vote count never goes below 0.

## Viewing Ideas

### US-14.4 — Member Browses the Ideas Feed
**As a** Member, **I want** to see all submitted event ideas **so that** I can discover what others want and vote on ideas I support.
**Acceptance Criteria**
- The "💡 Event Ideas" tab on the Events page shows all Open ideas sorted by vote count (highest first) by default.
- Each card shows: title, description, format/time/delivery tags, submitter name, relative time, vote count + vote button, status badge (Open / Greenlit / Declined).
- Filter tabs: All / Open / Greenlit ✅ / My Ideas.
- Sort options: Most votes / Newest first.
- Greenlit ideas show the linked event date (read-only, voting disabled).
- Declined ideas show the leader's reason (voting disabled).
- Auto-archived ideas are hidden from the member feed.

### US-14.5 — Leader Views Ranked Backlog (CL — All Groups)
**As a** Community Leader, **I want** to see a ranked backlog of all community ideas **so that** I can identify and act on the most-wanted events.
**Acceptance Criteria**
- The "💡 Event Ideas" tab on the CL Events page shows ideas across all groups, ranked by vote count.
- Summary stats: Open count, Greenlit count, Top idea votes, Expiring in 7 days count.
- Each idea shows: rank, vote count + visual bar, title, description, tags, submitter, age, expiry warning (⏳ in N days / ⚠️ in ≤5 days in red), group badge.
- Filter by status (Open / Greenlit / Declined / Archived) and by group.
- Sort by votes (default) / Newest / Expiring soon.
- A count badge on the tab shows the number of Open ideas.

### US-14.6 — UGL Views Group-Scoped Backlog
**As a** User Group Leader, **I want** to see only my group's ideas **so that** I can act on what my members want.
**Acceptance Criteria**
- Same backlog UI as US-14.5 but filtered to the UGL's led group only.
- A scope note at the top of the tab reads: "Showing ideas submitted for [Group Name] only. Community-wide ideas are managed by the Community Leader."
- UGL cannot see or act on ideas from other groups.

## Leader Actions

### US-14.7 — Leader Greenlights an Idea
**As a** CL or UGL (own group), **I want** to greenlight a popular idea **so that** I turn community demand into a real event.
**Acceptance Criteria**
- "✅ Greenlight" button on each Open idea card in the leader backlog.
- Clicking opens a modal: optional note to submitter (free text), two actions: "Greenlight & Notify Submitter" and "Greenlight & Create Event Now".
- On "Greenlight & Notify Submitter": idea status changes to Greenlit; submitter receives an in-portal notification ("Your idea '[title]' was greenlit by [leader name]!") and email (if enabled).
- On "Greenlight & Create Event Now": same status change + notification, then navigates to the Create Event form pre-filled with the idea's title, description, format, delivery mode, and group scope.
- Greenlit ideas are visible in both member and leader feeds with a ✅ badge and linked event date (once the event is created).
- Only one greenlight per idea. A greenlit idea cannot be declined.

### US-14.8 — Leader Declines an Idea
**As a** CL or UGL (own group), **I want** to decline an idea **so that** I can provide closure when an idea isn't viable.
**Acceptance Criteria**
- "✕ Decline" button on each Open idea card.
- Clicking opens a modal requiring a reason (free text, required).
- On confirm: idea status changes to Declined; submitter receives notification with the leader's reason.
- Declined ideas remain visible in the member feed (with ✕ badge and leader reason) so submitters understand why.
- A declined idea cannot be greenlit.

### US-14.9 — Leader Adds a Comment to an Idea
**As a** CL or UGL, **I want** to comment on an idea **so that** I can acknowledge it or request clarification without committing to greenlight or decline.
**Acceptance Criteria**
- A "Comment" option is available on each idea in the leader backlog.
- Comment is visible to all viewers of the idea.
- Does not change the idea's status.
- Submitter is NOT notified of the comment (low-noise policy).

## Auto-Archive

### US-14.10 — Stale Ideas Auto-Archive
**As the** system, **I want** to auto-archive ideas that have had no new votes for 30 days **so that** the backlog stays relevant without manual cleanup.
**Acceptance Criteria**
- An idea transitions from Open to Archived automatically if no vote has been cast on it in the past 30 days AND it has not been greenlit or declined.
- Auto-archive runs as a nightly job.
- Archived ideas are hidden from the member feed and leader backlog by default (shown only when the "Archived" filter is selected).
- Submitter is NOT notified when their idea is archived (low-noise policy).
- An archived idea cannot be voted on, greenlit, or declined.
- Vote count and metadata are preserved (not deleted).

## Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-EI-1 | Feed query latency | < 100ms (p95) — single DynamoDB Query on vote-sorted GSI |
| NFR-EI-2 | Vote toggle latency | < 200ms — atomic conditional update, no race conditions |
| NFR-EI-3 | Submit idea latency | < 300ms |
| NFR-EI-4 | Auto-archive sweep | Runs nightly; processes all ideas with last-vote-at < 30 days ago |
| NFR-EI-5 | Scale | Supports communities with 13,000+ members; vote counts up to 10,000 per idea |
| NFR-EI-6 | No full-table scans | All access patterns use GSI Query. Feed sorted by vote count via sparse GSI. |

## Data Model (DynamoDB — events table)

```
Idea record:
  PK: IDEA#<ideaId>
  SK: META
  Attributes: ideaId, title, description, format, timePreference, deliveryMode,
              groupId (or "COMMUNITY"), submitterId, submitterName, voteCount,
              status (Open|Greenlit|Declined|Archived), createdAt, lastVoteAt,
              greenlitBy, greenlitAt, linkedEventId, declinedBy, declinedReason

Feed GSI (sorted by votes — for the ranked backlog):
  GSI-IDEA-FEED: PK=GROUP#<groupId>, SK=<voteCount padded>#<createdAt>
  → Query descending by SK gives highest-voted first

Vote record:
  PK: IDEA#<ideaId>
  SK: VOTE#<userId>
  (Existence = voted. Count maintained atomically on META record.)

Community-wide feed:
  GSI-IDEA-FEED: PK=GROUP#COMMUNITY → all community-wide ideas
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/events/ideas` | Any authenticated | Submit an idea |
| GET | `/events/ideas` | Any authenticated | Browse ideas (member feed) — filter by group, status, sort |
| GET | `/events/ideas/backlog` | CL / UGL | Leader backlog with vote ranking |
| POST | `/events/ideas/{id}/vote` | Any authenticated | Toggle vote |
| POST | `/events/ideas/{id}/greenlight` | CL / UGL | Greenlight with optional note |
| POST | `/events/ideas/{id}/decline` | CL / UGL | Decline with required reason |
| POST | `/events/ideas/{id}/comment` | CL / UGL | Add a comment |
| DELETE | `/events/ideas/{id}` | Submitter or CL | Delete own idea (Open only) |

---

# Traceability Matrix

Because IDs are preserved 1:1 (Q1 = A), every story above links directly to its source use-case module. This matrix confirms **completeness** against `requirements/usecases/` and records removed items.

**Status legend**: ✅ Covered (story present above) · 🪦 Removed (tombstoned in source — not implemented, per Q6 = A).

| Module | Source file | Active stories (all ✅ Covered) | Count | Removed (🪦) |
|---|---|---|---|---|
| 1 Auth & Authz | 01-authentication-and-authorization.md | US-1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19, 1.20, 1.21, 1.26, 1.27, 1.28, 1.30, 1.31, 1.32, 1.33, 1.34 | 28 | US-1.1, 1.22, 1.23, 1.24, 1.29 |
| 2 Events | 02-events-and-meetups.md | US-2.1 … 2.26 (US-2.20 reworked as standalone Content Library; US-2.22–2.26 added for Content Library rework 2026-08-18) | 26 | — |
| 3 Member Mgmt | 03-member-management.md | US-3.1 … 3.10 (all) | 10 | — |
| 4 Forums | 04-forums-and-discussions.md | US-4.1 … 4.18 (all) | 18 | — |
| 5 Certifications | 05-certifications.md | US-5.1 … 5.10 (all) | 10 | — |
| 6 Contributions | 06-member-contribution-tracking.md | US-6.1 … 6.18 (all; US-6.18 added for auto-tracked event organizing) | 18 | — |
| 7 Analytics | 07-analytics-dashboard.md | US-7.1 … 7.11 (all) | 11 | — |
| 8 Cross-cutting | 08-cross-cutting-concerns.md | US-8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.13, 8.14, 8.15 | 12 | — |
| 9 Help Assistant | 09-help-assistant.md | US-9.1 … 9.4 (all) | 4 | — |
| 10 Announcements | 10-announcements.md | US-10.1 … 10.5 (all) | 5 | — |
| 11 What's New | 11-whats-new-aws-feed.md | US-11.1 … 11.7 (all) | 7 | — |
| 12 Progress Timeline | brainstorm 2026-08-14 | US-12.1 … 12.10 (all) | 10 | — |
| 13 Shoutouts | brainstorm 2026-08-14 | US-13.1 … 13.11 (all) | 11 | — |
| 14 Event Ideas | brainstorm 2026-08-15 | US-14.1 … 14.10 (all) | 10 | — |
| **Total** | | | **180** | 5 |

### Notes on removed (tombstoned) items
- **US-1.1** SSO Login via GSI IdP — removed (SSO/SAML/OIDC eliminated, resolved issue #19).
- **US-1.22 / 1.23 / 1.24** Delegation of leader duties — removed (resolved issue #9; peer Community Leaders provide coverage; zero-CL safeguard added).
- **US-1.29** Authentication Mode Configuration (SSO vs Self-Registration) — removed (single Cognito email+password+OTP model).

### Content Library rework (2026-08-18)
**US-2.20** was originally "Content Library — Search Event Content" (a tab within Events, event-scoped, auto-indexed via GSI3). It has been **reworked** as "Content Library — Browse and Search Community Resources" — a standalone top-level page (`/content-library`) with three entry paths (event auto-promotion, member contribution opt-in, curator direct add), free-form topic tags, source filter, and community-wide scope. The original GSI3 auto-indexing implementation is dropped and replaced. **US-2.22–2.26** are new stories covering the three entry paths, curation operations, and topic autocomplete. **US-2.19** updated: event description is now mandatory before completion (enforced by the Complete operation).

### Numbering gaps (not missing — never existed in source)
- Module 8 jumps US-8.9 → US-8.13 (no US-8.10/8.11/8.12 in source).

### Specifics folded in from requirements review (previously flagged)
- **Semantic search = Amazon OpenSearch Serverless vector indices** (US-3.5, US-4.13) — captured in Module 3 & 4 stories and the shared Search capability.
- **Membership-event history (US-1.34)** — captured as its own story; feeds analytics US-7.2/7.3.
- **Fixed auto-tracked activity set** (event attendance, event delivery, event organizing, forum post created, forum reply created, certification approval) — captured in US-6.1/6.3/6.4/6.5/6.17/6.18. Note: **US-6.18 (event organizing)** was added during gap analysis (C1) — "Organize an event" is auto-tracked (portal is system of record for events + designated organizers); awarded to designated Member organizer(s) on completion. Mirrored in use case `06-member-contribution-tracking.md` and designation added to US-2.18 in `02-events-and-meetups.md`.

### Service / bounded-context grouping (for Units Generation)
Identity & Access (M1) · Member Profiles & Directory (M3) · Events (M2) · Forums (M4) · Certifications (M5) · Contributions & Scoring (M6) · Analytics (M7) · Announcements (M10) · Notifications (M8 notif) · Platform/Settings + File-Share (M8) · Help Assistant (M9) · shared **Search** (OpenSearch) and **AI/Bedrock** capabilities · What's New (M11, frontend-only). Final decomposition (microservices vs modular monolith) is decided in Workflow Planning / Units Generation.
