# Business Logic Model — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Member Profiles & Directory
Technology-agnostic business logic for the 8 stories (US-3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.10 — US-3.8/3.9 reassigned to Unit 2, see plan Amendment 2). Maps each contract operation to its logic, rules, and emitted events. Companions: `business-rules.md`, `domain-entities.md`. Plan: `../../plans/member-profiles-functional-design-plan.md`.

## Component archetype (in-service, no shared lib — FQ1)
```
handler (API GW proxy) → validation → authz (Principal + matrix) → domain service → repository (DynamoDB)
                                                                        ↘ event consumer (EventBridge, from Identity)
                                                                        ↘ event publisher (EventBridge, MemberProfileUpserted)
                                                                        ↘ read-time REST fan-out (Events/Forums/Contributions/Certifications)
                                                                        ↘ search delegate (Search service | keyword fallback)
```
Cross-cutting modules (`_conventions/`: logger, errors, authz, validation, envelope, idempotency, config) are copied per-service by the scaffold generator, same as Identity & Access.

## Profile record lifecycle (event-sourced cache — plan Q1/Q9)
Member Profiles owns **no independent identity or membership source of truth**. Its profile-extension record is a denormalized, read-optimized cache, kept current by consuming Identity & Access's published events:
- `UserProvisioned` → create profile-extension record (id = Cognito `sub`; seed firstName/lastName/email/role/status from the event; profile-only fields default empty).
- `UserRoleChanged` → update `role`.
- `UserDeactivated` → set `status=inactive` (record retained — no removal; searchable per BR-8).
- `UserReactivated` → set `status=active`.
- `MemberJoinedGroup` → upsert `groups[]` entry `{groupId, joinedAt=event.at}` (overwrite on rejoin — BR-G5 semantics carried through, plan Q9).
- `MemberLeftGroup` / `MemberRemoved` → remove that group's entry from `groups[]`.
Events are consumed idempotently (dedup by `eventId` in the idempotency table, same pattern as Identity & Access). The profile-extension record is never the write path for role/group changes — Identity & Access remains canonical; Member Profiles only mirrors.

## `getOwnProfile` (GET /members/me) — US-3.1
1. Load profile-extension record for `principal.userId`. 404 should not occur (JIT via `UserProvisioned`), but degrade to a minimal stub if missing (defensive — event lag).
2. Fan out (read-time, best-effort, independently try/caught — plan Q2):
   - Contributions & Scoring `GET /contributions/me` → current-quarter rollup (display-only, no tier meaning, BR-1) + per-group tier list.
   - Basic activity counts: Events (attendance count), Forums (post count), Contributions (submission count), Certifications (earned count) — each a lightweight count-only call, not the full activity list.
3. Assemble response: identity (name/email/role — read-only, Identity-owned), profile fields (city/country/professionalRole/awsProject/timeZone/bio/skills/avatar), `groups[]` with per-group `joinedAt` + tier, contribution-score rollup, basic activity-count block. Any fan-out failure → that section omitted/empty, response still 200 (BR-9).

## `updateOwnProfile` (PUT /members/me) — US-3.2
1. Validate patch: `city`, `country`, `professionalRole` (free-text job title, distinct from access role — BR-2), `awsProject` (boolean), `bio`, `skills[]`, `avatar`. `timeZone` accepted here too (also settable via Settings, US-8.14 — latest save wins, BR-3). Email/role/name rejected (identity fields, Identity-owned — BR-2).
2. Apply patch to profile-extension record; `updatedAt=now`.
3. Publish `MemberProfileUpserted` (BR-7) — triggers Search re-indexing (Unit 13) when semantic search is enabled.
4. Return updated `Member`.

## `getMember` (GET /members/{id}) — US-3.3
1. authz: 403 if `principal.role == Administrator` (BR-4 — Admins use Identity's `/users` list, not this view).
2. Load target profile-extension record; 404 if none.
3. Same fan-out as `getOwnProfile` step 2, for the target member (rollup/tier + basic activity counts). Read-only — no edit action exposed (BR-5).
4. Return `PublicProfile` (superset of directory fields: bio, skills, avatar, verified badges via Certifications read, per-group tier, contribution rollup, basic activity counts, per-group join dates).

## `browseDirectory` (GET /members) — US-3.4, US-3.5
1. Parse query params: `limit`/`cursor` (pagination, BR-10), `q` (search text), `role`, `groupId`, `certId` (filters — `certId` param ignored/omitted when `principal.role == CommunityLeader`, per US-3.5's CL-directory-omits-cert-filter rule, BR-6).
2. If `q` present and `EnableSemanticSearch` is on (Settings flag, read via config — D3): delegate to Search service `GET /search?kind=member&q=<q>` for ranked candidate IDs, then hydrate + apply `role`/`groupId`/`certId` filters against the profile-extension table.
3. If `q` present and semantic search is off (D3 degrade): case-insensitive substring match against `firstName+lastName+email+skills` in DynamoDB (BR-6b).
4. If `q` absent: plain attribute-filtered scan/query (`role`, `groupId`, `certId`).
5. Results include deactivated members with an inactive badge (never excluded — BR-8); contribution points never shown in directory rows (BR-11, distinct from the profile-view rollup).
6. Response `{items, count}` with pagination cursor; `count` = total matching (not page size).

## `memberActivity` (GET /members/{id}/activity) — US-3.10
1. authz: 403 for `Administrator` (BR-4) and for `Member` viewing anyone but themself (this story is leader-only; a member's own basic counts are on `getOwnProfile`, not here — BR-12). `CommunityLeader` → any member. `UserGroupLeader` → only members of their led group (403 otherwise, BR-13).
2. Parse `range` query params (from/to dates, BR-14).
3. Fan out to Events (attendance list + count in range), Forums (post list + count), Contributions (submissions + current-quarter + lifetime points), Certifications (earned certs in range) — fuller detail than the basic block on `getOwnProfile`/`getMember` (plan Amendment 1).
4. Assemble `ActivitySummary`: events attended, forum posts, contributions submitted, certifications earned, points (current quarter + lifetime), filtered by range.

## Onboarding & welcome (US-3.6, US-3.7) — no new endpoints (plan Q3)
- **US-3.6** is frontend orchestration: on first successful login (detected client-side, e.g. no prior `groups[]` on the freshly-JIT-provisioned profile), the SPA presents Identity & Access's `GET /groups` and lets the member `POST /groups/{id}/join` — both existing Identity endpoints. Member Profiles contributes no backend logic beyond having a profile record to check `groups[]` against.
- **US-3.7** is owned by Notifications (Unit 10): triggered off the same `UserProvisioned` event Member Profiles itself consumes for profile creation, delivered as an in-portal welcome notification with links to group directory/events/guidelines. Member Profiles does not send or store this notification.

## Search indexing (US-3.5 embedding trigger — plan Q5)
Member Profiles publishes `MemberProfileUpserted` after every profile create (from `UserProvisioned`) or update (`updateOwnProfile`, or profile fields changed via Identity's Edit User → `UserRoleChanged`/future profile-sync event). Search (Unit 13) consumes this event and calls AI Gateway (Unit 14) to (re)generate the embedding. Member Profiles never calls AI Gateway directly. No member-profile hard-delete exists (Phase 1) — embeddings are never removed (BR-8).

## Traceability (stories → operations)
| Story | Operation(s) |
|---|---|
| US-3.1 | getOwnProfile |
| US-3.2 | updateOwnProfile |
| US-3.3 | getMember |
| US-3.4 | browseDirectory (no `q`) |
| US-3.5 | browseDirectory (with `q`, role/group/cert filters) |
| US-3.6 | (frontend orchestration over Identity's `/groups`; profile record existence only) |
| US-3.7 | (Notifications, off `UserProvisioned`; no Member Profiles logic) |
| US-3.10 | memberActivity |

All 8 in-scope stories covered. US-3.8/US-3.9 now traced under Unit 2 Identity & Access (`services/identity-access/README.md`).
