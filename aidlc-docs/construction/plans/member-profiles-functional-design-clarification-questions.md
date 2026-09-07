# Member Profiles & Directory — Functional Design Clarification Questions

Raised during UI-mockup cross-check of `member-profiles-functional-design-plan.md` (Q6). One open decision needs your input; two related corrections are being applied directly (see note below) since the mockup evidence is unambiguous.

## Question 1
`admin/users.html` (mockup) and the already-shipped `AdminUsersPage.tsx` both operate against Identity & Access's `GET /users` for US-3.8 (view all members) and US-3.9 (export member list) — not against `GET /admin/members` on Member Profiles. Identity's `PortalUser` entity already carries city/country/professionalRole/awsProject, so `/users` alone already fully serves both stories today. How should Unit 3's scope handle this?

A) Drop `/admin/members` from Unit 3 entirely. Formally re-assign US-3.8/3.9 to Identity & Access (already shipped, already wired, no rework). Member Profiles' functional design then covers only US-3.1–3.7 + 3.10 (8 stories); update unit-of-work.md/story-map to reflect the re-assignment.

B) Keep `/admin/members` on Member Profiles as originally scoped in unit-of-work.md. Rework the already-shipped `AdminUsersPage.tsx` to call `/admin/members` instead of `/users`, and build Member Profiles as an event-synced read-replica of user identity data (per the original plan's Q6 resolution).

C) Keep `/admin/members` on Member Profiles, but only as an unused/reserved contract path for future divergence (e.g. if Identity's `/users` later drops profile fields) — no frontend rework now, no functional-design work on it this round; ship it as `501` until there's a real caller.

D) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Corrections being applied without a question (mockup evidence unambiguous)

1. **Activity summary is two-tiered.** A basic 4-stat block (events attended, forum posts, contributions, certifications — no points) is inline on every profile view (own + read-only others, US-3.1/3.3, visible to any role that can view a profile). The leader-only, points+date-range-filtered version is US-3.10 (`memberActivity`, CL any member / UGL own-group-only / Administrator and self excluded). Splitting these into two response shapes on `getOwnProfile`/`getMember` (basic block) vs `memberActivity` (detailed).

2. **CSV export scope narrowed.** The points/tier CSV in `leader/directory.html`'s "Export Member Data" modal (join-date range, `current_quarter_points`/`current_tier` columns) is **US-7.10**, owned by Unit 8 Analytics per `unit-of-work-story-map.md` (cross-unit note: "3, S3"), not Unit 3. Member Profiles' own export (US-3.9, admin-only, identity/role/group/status fields, no points, per `admin/users.html`'s Export button) is a separate, simpler CSV op scoped to whichever of `/users` or `/admin/members` wins Question 1 above. Unit 3's functional design will not include a points-bearing export.
