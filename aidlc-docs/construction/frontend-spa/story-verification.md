# Story-by-Story Verification — all 144 user stories

**Date**: 2026-07-30. Source of truth: `aidlc-docs/inception/user-stories/stories.md`.
**Scope of this check**: does every story have a **screen** and a **mock API** that represents it? Real
per-service business logic is deferred by design (Approach A) — see the ⚙️ classification below.

**Verdict: YES.** Every one of the 144 stories is represented at screen + mock-API level.
- **112 mock operations** across 12 services; **all contract-test gates green**.
- **26 platform unit tests** pass; **SPA builds clean**.
- Gaps found during this verification were closed (listed at the end).

Legend:
- ✅ **Demonstrable** — a UI action drives a mock endpoint that returns real fixture data.
- ⚙️ **Represented / backend-deferred** — a pure system/async behavior (email send, Cognito sync,
  JIT provisioning, runtime tier computation, .ics, CloudWatch audit). The triggering screen/config
  and/or endpoint exists; the real asynchronous behavior lands with the real service. This is expected
  for a mock-first prototype and does not represent a missing screen.

## Module 1 — Identity & Access (28)
| Story | Status | Where |
|---|---|---|
| US-1.2 Login | ✅ | AuthScreen → `POST /auth/login` |
| US-1.27 Built-in local admin | ✅ | AuthScreen (local-admin note + login path) |
| US-1.28 (tombstoned) | n/a | Removed — no separate local-admin reset path |
| US-1.3 Logout | ✅ | Topbar "Sign out" |
| US-1.15 JIT provisioning | ⚙️ | first-login auto-create (backend); represented via register/login |
| US-1.30 Self-registration | ✅ | AuthScreen register tab → `POST /auth/register` |
| US-1.32 Periodic OTP | ✅ | AuthScreen OTP step → `POST /auth/otp` |
| US-1.33 Disable/enable user | ✅ | AdminUsers Disable/Enable → `/users/{id}/disable`,`/enable` |
| US-1.20 Cognito password reset | ✅ | AuthScreen "Forgot password" panel → `POST /auth/reset` (request code) → `POST /auth/reset/confirm` (code + new password) |
| US-1.4 Cognito sync | ⚙️ | scheduled batch (backend); sync schedule field in Admin Settings |
| US-1.31 Bulk import | ✅ | AdminUsers Bulk Import → `POST /users/import` |
| US-1.26 Edit user (role+group) | ✅ | AdminUsers Edit → `PUT /users/{id}` |
| US-1.5 Assign role | ✅ | via Edit User |
| US-1.6 Deactivation | ⚙️ | system effect of disable; triggered from AdminUsers |
| US-1.19 Reactivation | ✅ | AdminUsers Enable → `POST /users/{id}/enable` |
| US-1.7 Create group | ✅ | Groups → `POST /groups` |
| US-1.18 Edit group | ✅ | GroupDetail Edit → `PUT /groups/{id}` |
| US-1.8 Join group | ✅ | Groups/GroupDetail → `POST /groups/{id}/join` |
| US-1.9 Leave group | ✅ | GroupDetail Leave → `POST /groups/{id}/leave` |
| US-1.10 Assign UGL | ✅ | GroupDetail "Make leader" → `POST /groups/{id}/leaders` |
| US-1.11 Delete group | ✅ | GroupDetail Delete → `DELETE /groups/{id}` |
| US-1.16 Group directory | ✅ | Groups list → `GET /groups` |
| US-1.17 Remove member | ✅ | GroupDetail Remove → `DELETE /groups/{id}/members/{memberId}` |
| US-1.21 Review join requests | ✅ | GroupDetail Requests approve/reject |
| US-1.34 Membership history | ✅ | GroupDetail History → `GET /membership-history` |
| US-1.12 RBAC | ⚙️ | nav-gated in UI; real server enforcement deferred |
| US-1.13 Audit log | ⚙️ | CloudWatch (backend); toggle in Admin Settings |
| US-1.14 Toggle audit | ✅ | Admin Settings audit checkbox |

## Module 2 — Events (21)
US-2.1 create ✅ · ~~US-2.2 reminder~~ REMOVED 2026-08-27 · US-2.3 recurring ✅ · US-2.4 edit ✅ ·
US-2.5 cancel ✅ · US-2.15 materials ✅ · US-2.19 mark complete ✅ · US-2.6 RSVP ✅ ·
US-2.7 RSVP list + CSV ✅ · US-2.8 .ics invite ⚙️ · US-2.9 calendar ✅ · ~~US-2.10 reminder email~~ REMOVED 2026-08-27 ·
US-2.11 Teams config ✅ (Admin Settings) · US-2.12 Teams attendance ✅ · US-2.16 manual attendance ✅ ·
US-2.17 configure points ✅ (framework) · US-2.18 designate presenters/organizers ✅ ·
US-2.13 browse + filters ✅ · US-2.14 details ✅ · US-2.20 content library ✅ · US-2.21 upload link ✅.

## Module 3 — Members (10)
US-3.1 my profile ✅ · US-3.2 edit ✅ · US-3.3 view other ✅ · US-3.4 directory ✅ ·
US-3.5 search ✅ (text; semantic backend) · US-3.6 onboarding ⚙️ · US-3.7 welcome ✅ (notif) ·
US-3.8 admin list ✅ · US-3.9 admin export CSV ✅ · US-3.10 activity summary ✅.

## Module 4 — Forums (18)
US-4.1 create forum ✅ · US-4.2 create channel ✅ · US-4.3 edit forum/channel ✅ ·
US-4.4 delete forum/channel ✅ · US-4.5 create post ✅ · US-4.6 reply ✅ · US-4.7 edit post/reply ✅ ·
US-4.8 delete post/reply ✅ · US-4.9 @mention ✅ · US-4.10 mention notif ⚙️ · US-4.11 react ✅ ·
US-4.12 browse ✅ · US-4.18 channel post list ✅ · US-4.13 search ✅ · US-4.14 pin ✅ ·
US-4.15 accepted answer ✅ · US-4.16 follow ✅ · US-4.17 report + moderation ✅.

## Module 5 — Certifications (10)
US-5.1 create ✅ · US-5.2 edit ✅ · US-5.3 deactivate ✅ (active toggle) · US-5.4 submit claim ✅ ·
US-5.5 my submissions + withdraw ✅ · US-5.6 verify ✅ · US-5.7 pending ✅ · US-5.8 revoke ✅ ·
US-5.9 badges ✅ (profile) · US-5.10 catalog ✅.

## Module 6 — Contributions (18)
US-6.1 configure framework ✅ (add/edit/remove) · US-6.2 view framework ✅ · US-6.3 event points ⚙️ ·
US-6.17 delivery points ⚙️ · US-6.18 organize points ⚙️ · US-6.4 forum points ⚙️ · US-6.5 cert points ⚙️ ·
US-6.6 submit ✅ · US-6.7 my submissions + withdraw ✅ · US-6.8 approve/reject ✅ · US-6.9 pending ✅ ·
US-6.10 my points/tier ✅ · US-6.11 tier standings ✅ · US-6.12 tier badge ⚙️ · US-6.13 group summary ✅ ·
US-6.14 community summary + CSV ✅ · US-6.15 manual adjust ✅ · US-6.16 leaderboard ✅ (+ Home link).

## Module 7 — Analytics (11)
US-7.1 community dash ✅ · US-7.2 group dash ✅ (scope toggle) · US-7.3 growth chart ✅ ·
US-7.4 points chart ✅ · US-7.5 attendance chart ✅ · US-7.6 cert progress ✅ · US-7.7 AI report ✅ ·
US-7.8 insights ✅ · US-7.9 export contributions ✅ · US-7.10 export members ✅ · US-7.11 export events ✅.

## Module 8 — Cross-cutting (12)
US-8.1 member home ✅ (+ leaderboard/contributions links) · US-8.2 email notifications ⚙️ ·
US-8.6 in-portal notifications ✅ (bell + mark-read) · US-8.3 admin settings ✅ (domains, sync, Teams, LLM, feed, branding, tz, audit) ·
US-8.4 email sender ✅ · US-8.5 email templates ✅ (edit) · US-8.7 email prefs ✅ ·
US-8.15 recipient matrix ⚙️ (backend mapping) · US-8.13 file-share ✅ (leader Settings) ·
US-8.14 time zone ✅ (system default + per-user) · US-8.9 data tables ✅ · US-8.8 responsive ✅.

## Module 9 — Help (4)
US-9.1 access ✅ · US-9.2 ask ✅ · US-9.3 scope guard ⚙️ (LLM behavior) · US-9.4 KB grounding ⚙️.

## Module 10 — Announcements (5)
US-10.1 create ✅ · US-10.2 target ✅ · US-10.3 edit/delete ✅ · US-10.4 view ✅ · US-10.5 dismiss ✅.

## Module 11 — What's New (7)
US-11.1 config + toggle ✅ · US-11.2 nav (CL/UGL/Member) ✅ · US-11.3 detail page ✅ ·
US-11.4 search + category filter ✅ · US-11.5 item details ✅ · US-11.6 disabled behavior ✅ (toggle) ·
US-11.7 client-side load ✅.

**UPDATED 2026-08-10 — mock → real.** The ✅ marks above were originally recorded against a
mock: `WhatsNewPage` in `features/singletons.tsx` rendered a hardcoded 4-item array
(`{title, category, date}`) and never fetched anything. US-11.3/11.4/11.5/11.7 are now
implemented for real in `frontend/src/features/whats-new/` — live fetch of the configured
CORS-enabled mirror, RSS 2.0 parse, reverse-chronological sort, ~150-char summaries,
inline expand of sanitized `<description>`, dynamic alphabetical category facets, search
across title + summary + details, and distinct error/empty/no-match states. 64 frontend
tests (first frontend suite in the repo). US-11.1/11.2 needed no change — already shipped
in Unit 11 Settings and `AppLayout.tsx` respectively.

Deviations recorded: **DV-1** US-11.5's "rendered as-is" is rendered *sanitized*;
**DV-2** the use case's category-shape claim was factually wrong about upstream;
**DV-3** the CORS-enabled URL is a self-maintained mirror. See
`construction/frontend-spa/whats-new/code-summary.md`.

## Gaps found in this verification and closed
1. **US-11.2** — "What's New" nav was missing for CL/UGL; added to leader nav.
2. **US-6.16 / US-8.1** — Home had no leaderboard / My Contributions link; added.
3. **US-4.3/4.4/4.7/4.8** — forum/channel and post/reply edit+delete had no endpoints/UI; added `PUT`/`DELETE` `/forums/{id}`, `/channels/{id}`, `/posts/{id}`, `/replies/{id}` + UI.
4. **US-6.1** — framework was view-only; added create/edit/delete activity (`POST`/`PUT`/`DELETE /contributions/framework`).
5. **US-6.7 / US-5.x** — submission withdraw added (`DELETE /contributions/submissions/{id}`).
6. **US-1.17** — remove-member endpoint + button (`DELETE /groups/{id}/members/{memberId}`).
7. **US-1.19** — Enable button in AdminUsers.
8. **US-3.9** — admin CSV export button.
9. **US-8.13** — file-share moved from Admin to leader Settings (CL/UGL; Members/Admins excluded).
10. **US-8.3/8.4/1.4/1.30/2.11/6.4/11.1/11.6** — Admin Settings expanded: sender name/email, allowed domains, sync schedule, Teams config, LLM-duplicate toggle, feed enable toggle.
11. **US-7.6/7.11** — added certifications chart + events export.
12. **US-2.7/2.13** — RSVP CSV export, event browse filters. (US-2.2's reminder lead-time field was added here and removed again on 2026-08-27.)
13. **US-5.3** — certification active/inactive toggle in edit.
14. Local mock server: added `/membership-history` and `/replies` route mappings.

## Backend-deferred set (⚙️ — no missing screen)
US-1.4 sync, US-1.6 deactivation effects, US-1.12 RBAC enforcement, US-1.13 audit write,
US-1.15 JIT, US-2.8 .ics, US-3.6 onboarding, US-4.10 mention email,
US-6.3/6.4/6.5/6.17/6.18 auto-award, US-6.12 runtime tiering, US-8.2 email send, US-8.15 recipient
matrix, US-9.3/9.4 LLM guardrails/RAG. These are real service behaviors implemented in the
per-unit construction passes; each already has its representing screen/config/endpoint in the prototype.
