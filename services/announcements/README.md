# Announcements Service (Unit 9)

Broadcast announcement panel, distinct from the notification bell and forum posts.
Community Leaders and User Group Leaders author announcements targeted community-wide
or to selected user group(s); the targeted audience sees them in a collapsible panel
on their landing page. Stories US-10.1–10.5. Contract: `contracts/services/announcements/openapi.yaml` (v2.0.0).

## Architecture — fan-out-on-read
An announcement is **one stored definition** (`ANN#<id>/ANN`). Post/edit/delete are
**O(1) writes** regardless of audience size (up to 13k+); the panel is computed at
read time from the caller's audience (JWT claims) against a small, 30s-warm-container-
cached active set. No per-user materialization, no write fan-out. Mandatory expiry
(default 2 days, max 90 days) + DynamoDB TTL keep the table bounded.

## Modules (`src/`)
| Module | Role |
|---|---|
| `app.py` | Router (API GW proxy + EventBridge branch); fail-closed authz; Administrator denied on all ops |
| `models.py` | Item↔API shapes, target normalization, expiry default/clamp, derived Active/Expired status |
| `announcement_service.py` | create/edit/delete/list + event-triggered auto-post; inline role authz |
| `panel_query.py` | `view=panel` — audience filter (claims + expiry + groupHidden), newest-first |
| `active_set_cache.py` | 30s per-warm-container cache of the active set |
| `sanitizer.py` | `nh3` server-side HTML sanitization on write (fail-closed escape fallback) |
| `directory_client.py` | Author/group name denormalization at create (1.5s fail-closed) |
| `consumers.py` | `EventCreated` auto-post (announce=true) + `GroupSoftDeleted`/`GroupRestored` hide/restore; idempotent |
| `providers.py` | `EventPublisher` — `AnnouncementPublished` (Notifications sends email) |
| `repository.py` | Single-table DynamoDB (no GSIs) + idempotency + TTL |

## Authorization (role-permission-matrix.v1.json semantics, enforced inline)
- **Create**: CommunityLeader (community or selected groups) / UserGroupLeader (their led group only — target forced).
- **Edit**: author only. **Delete**: author, or any CommunityLeader (moderation).
- **Panel/read**: any authenticated non-Administrator (self-scoped). **Administrator**: 403 on everything.
- **Dismissal**: client-side only (localStorage) — no server endpoint (BR-11).

## Events
- **Publishes** `AnnouncementPublished` (Notifications, Unit 10, sends email when `emailOptIn`).
- **Consumes** `EventCreated` (Events, Unit 4 — auto-post when `announce=true`), `GroupSoftDeleted`/`GroupRestored` (Identity, Unit 2 — hide/restore group announcements).

## Tests (`tests/`) — the 5 mandatory NFR-AN-MAINT-1 suites
`test_authz.py` (authorization matrix), `test_sanitizer.py` (XSS battery), `test_expiry.py`
(mandatory/clamp/exclusion), `test_consumers.py` (idempotent auto-post + group hide/restore),
`test_service_panel_repo.py` + `test_degrade.py` (targeting + fail-closed directory).

Run: `python -m pytest services/announcements/tests -q` · Contract gate: `make contract-tests SVC=announcements`.

## Dependencies
`boto3`, `aws-lambda-powertools`, and **`nh3`** (HTML sanitizer; `bleach` deprecated). SPA adds `dompurify` (defense-in-depth).
