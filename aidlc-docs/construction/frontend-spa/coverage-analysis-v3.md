# Requirements Coverage v3 — UI + Mock APIs (Option B complete)

**Verdict: YES — all 144 stories are now demonstrable at screen level and mock-API level.**
Real per-service business logic is still deferred (mocks are fixture-backed and logic-free, by
design — Approach A). This document supersedes `coverage-analysis-v2.md`.

Legend: ✅ demonstrable on mocks (UI action + mock endpoint returns real fixture data).

## Totals
- **112 mock operations** across 12 services; **all contract-test gates green**.
- **26 platform unit tests** pass; **SPA builds clean** (`tsc -b && vite build`).
- Every route wired in `frontend/src/App.tsx`; every nav item resolves to a real screen.

## Per-module coverage (all ✅ at prototype level)

| Module | Stories | Screens / interactions on mocks |
|---|---|---|
| M1 Identity & Access | 28 | Auth screen (login/OTP/self-register/reset note); Groups list + **detail** (members, join-requests review, assign-leader, membership history, join/leave, edit/delete); Users admin (list, edit role/groups, disable/enable, bulk import) |
| M2 Events | 21 | List (US-8.9 table) + create + **recurring series** + RSVP; **Calendar** view; **Content Library** search; **Event detail** (overview, RSVP list, materials add/list, manual + Teams attendance, designations, secure upload link, edit, cancel, complete) |
| M3 Members | 10 | Directory (text search + CSV export) → **member detail** (profile + activity summary); own profile view + edit + **certification badges** |
| M4 Forums | 18 | Forum/channel browse, new post/forum/channel, **thread view** (replies, reactions, accept answer, pin, follow, report, @mention suggest), **semantic search** (gated), **moderation queue** |
| M5 Certifications | 10 | Catalog + **definition create/edit/revoke** (leaders); my claims + submit + **withdraw**; verification queue + approve/reject; badges on profile |
| M6 Contributions | 18 | **My points/tier**, leaderboard, my submissions + submit, framework, **group/community summary + CSV export**, approvals + approve/reject + **manual adjustment** |
| M7 Analytics | 11 | Metrics chart with **scope toggle** (community/group) + **chart-type toggle** (points/attendance/tiers/growth), AI report chat, suggested insights (gated), **CSV exports** |
| M8 Notif/Settings/Frontend | 12 | Home, notifications bell/panel + **mark-read/mark-all**, notification preferences edit, admin settings (community/OTP/session/Bedrock/feed/**timezone**/audit), **email templates edit**, **secure file-share**, US-8.9 tables, responsive shell |
| M9 Help | 4 | Help drawer chat → `/help/ask` (semantic-gated) |
| M10 Announcements | 5 | List, create (leaders), dismiss, **edit/delete** (leaders), audience targeting |
| M11 What's New | 7 | Client-side feed with search/filter; admin feed-URL config in settings |

## Semantic-search behavior (Q10 / D3)
- `/forums/search`, `/analytics/ai/*`, `/help/ask`, `/search` are flagged `x-semantic-search`.
- When `ENABLE_SEMANTIC_SEARCH=false`, the mock returns 501 and the UI degrades gracefully
  (search/insights show a "disabled for this environment" state; member text search and
  posting still work). Demonstrable by toggling the env var on the local server.

## What remains (explicitly out of scope for this milestone)
- **Real business logic** per service (scoring math, real Cognito authN, enforced RBAC,
  OpenSearch/Bedrock, EventBridge choreography). These land unit-by-unit in the real
  per-service construction passes.
- Mocks are stateful only within a process (create returns a new id echoing the body); they do
  not persist across restarts. This is intentional for a fixture-backed prototype.

## How to run / verify
- Contracts + mocks: `for svc in $(ls contracts/services); do python3 platform/contract-tests/run_service.py $svc; done` → all green.
- SPA: `cd frontend && npm run build` → clean.
- Local end-to-end: `make local-mocks` (terminal 1) + `cd frontend && npm run dev` (terminal 2).
- See `docs/RUN-AND-DEPLOY.md` for the local and AWS paths.
