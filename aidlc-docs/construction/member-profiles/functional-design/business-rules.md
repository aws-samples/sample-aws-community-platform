# Business Rules — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Member Profiles & Directory
Enforceable rules distilled from use case 03-member-management.md, the frozen contract, and the UI-mockup cross-check (2026-08-02). Rule IDs referenced by code and tests. Companions: `business-logic-model.md`, `domain-entities.md`.

## Profile & rollup (1–3)
- **BR-1** — The contribution-score rollup shown on a profile (own or another's) is a **display-only sum of current-quarter points across all the member's groups**. It carries no tier meaning and is never used for tiering — tiering is always evaluated per group (US-3.1/3.3).
- **BR-2** — Identity fields (name, email) are read-only on this service — Identity & Access owns them. `professionalRole` (free-text job title) is distinct from and never conflated with the portal access role (Member/UGL/CL/Administrator), which remains admin-managed via Identity's Edit User (US-3.2).
- **BR-3** — `timeZone` may be set both via a member's own profile edit and via an Administrator's Edit User action (Identity & Access); whichever save happens most recently wins — no separate conflict resolution (US-3.2/US-1.26).

## Visibility & access control (4–6)
- **BR-4** — Administrators cannot open the community profile view (`getMember`) or the leader activity summary (`memberActivity`) — both return 403 for role `Administrator`. Administrators manage identity/role/group data exclusively through Identity & Access's `GET /users` + Edit User (US-3.3, US-3.8 reassignment note).
- **BR-5** — `getMember` (viewing another member's profile) is strictly read-only — there is no edit action on this endpoint. Editing is only ever performed on one's own profile via `updateOwnProfile` (US-3.3/US-3.2).
- **BR-6** — The Community-Leader-facing member directory omits the "certification held" filter (search/role/group filters only); the member-facing directory includes all three filters (role, group, certification) (US-3.5). Enforced by role in the `browseDirectory` handler, not by a separate endpoint.
- **BR-6b** — When semantic search (`EnableSemanticSearch`, D3) is disabled, directory text search (`q` param) degrades to a case-insensitive substring match against name/email/skills — never a hard failure or 501 for the base directory (only the semantic ranking degrades, not the list itself).

## Deactivation & retention (7–9)
- **BR-7** — Every profile create or update publishes `MemberProfileUpserted` after the write succeeds (best-effort, at-least-once — consumers idempotent), consistent with the platform event envelope (US-3.2/US-3.5).
- **BR-8** — There is no member-profile hard-delete in Phase 1 — members are only ever deactivated (via Identity's `UserDeactivated`). Deactivated members' profile records and search embeddings are **retained and remain searchable**, shown with an inactive badge in directory/search results (US-3.5).
- **BR-9** — Cross-service read-time fan-out (rollup/tier lookups on `getOwnProfile`/`getMember`; activity data on `memberActivity`) is independently try/caught per downstream call. A downstream service outage degrades only that section of the response (empty/omitted) — it never fails the overall profile or activity response (resiliency — no cross-service transaction, no cascading failure).

## Directory & pagination (10–11)
- **BR-10** — `browseDirectory` supports pagination (`limit`/`cursor`); the directory must never return an unbounded result set regardless of community size (US-3.4).
- **BR-11** — Contribution points are never shown in directory rows (US-3.4) — only on the individual profile view's display-only rollup (BR-1). This is a strict field-level exclusion, not merely a UI choice.

## Activity summary scoping (12–14)
- **BR-12** — The basic activity-count block (events attended, forum posts, contributions, certifications — no points) is inline on every profile view (`getOwnProfile`/`getMember`) and visible to any role permitted to view that profile. The detailed activity summary (`memberActivity`: adds points current-quarter + lifetime, date-range filter) is a **separate, leader-only** capability — not exposed via the basic profile fan-out (US-3.1/3.3 vs US-3.10; plan Amendment 1, confirmed against `member/profile.html` + `member/view-profile.html` mockups).
- **BR-13** — `memberActivity` scoping: Community Leader may view any member; User Group Leader may view only members of the group they lead (403 for members outside their led group); Administrator is excluded entirely (BR-4); a Member cannot use this endpoint to view anyone (including themself — their own basic counts come from `getOwnProfile`) (US-3.10).
- **BR-14** — `memberActivity` supports filtering by date range; when no range is given, defaults to all recorded activity for that member (US-3.10).

## Service boundary (15 — reassignment record)
- **BR-15** — Member Profiles does not implement an admin member list or CSV export. US-3.8 (admin member list) and US-3.9 (export member list) are served by Identity & Access's `GET /users`, which already carries every required field (role/status/city/country/professionalRole/awsProject/groups) via its existing role index. This reassignment was made 2026-08-02 after confirming both the shipped frontend and the UI mockup call Identity's endpoint, and that Identity's real DynamoDB table is already correctly indexed for this use while Member Profiles' table was not.
- **BR-16** — Member Profiles ships no points-bearing CSV export. The points/tier member export shown in the Community-Leader directory mockup (join-date range, current-quarter points, tier) is US-7.10, owned by Unit 8 Analytics — out of scope for this service entirely (no points data ever flows through Member Profiles).

## Validation & errors (17–18, platform conventions)
- **BR-17** — All inputs validated (type, length, format, enum) before processing; reject HTML/script in free-text (`bio`, `skills`) per platform SECURITY-05 convention, same as Identity & Access.
- **BR-18** — Unimplemented contract operations return `501` until shipped (FQ8/platform BR-17); all errors use the platform error shape with generic messages (SECURITY-15).
