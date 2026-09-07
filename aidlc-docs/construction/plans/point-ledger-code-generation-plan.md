# Code Generation Plan — Point Ledger + CL Leaderboard move (US-7.9)

**Units**: Unit 7 (Contributions & Scoring), Unit 15 (SPA)
**Date**: 2026-08-11
**Requirements**: `aidlc-docs/inception/business-requirements/point-ledger-requirements.md` (approved; DR-5 = keep Top Contributors, add Leaderboard)
**Design stages**: Application/Units/Functional/NFR/Infra all SKIPPED — no new data model, no new index, no infra. Reuses the `GLEDGER#<groupId>#<quarter>` index and established table/export patterns. This plan is the single source of truth.

**Deploy note**: this has a backend + contract change → a **full root-stack deploy** (not SPA-only).

---

## Activity-category derivation (resolves DR-3)

Auto entries store display strings with dynamic suffixes, so the activity-type filter operates on **derived categories**, not raw `activity` text. Canonical categories and how each is recognised from a ledger row (`source` + `activity` prefix):

| Category code | Label | Match rule |
|---|---|---|
| `event-attendance` | Event Attendance | `source=auto` & activity starts `Attend:` |
| `event-delivery` | Event Delivery | `source=auto` & activity starts `Present:` |
| `organize-event` | Organize Event | `source=auto` & activity == organize-event framework name |
| `forum-post` | Forum Post | `source=auto` & activity == forum-post framework name |
| `forum-accepted-reply` | Forum Accepted Reply | `source=auto` & activity starts forum-accepted-reply framework name (incl. "(reversed)") |
| `certification` | Certification | `source=auto` & activity starts `Certification:` |
| `evidence` | Evidence Submission | `source=evidence` |
| `adjustment` | Manual Adjustment | `source=adjustment` |

Event type (Workshop/Hackathon/…) and specific certification names are **collapsed** into their category — the filter is by category, not by event type or cert name. Documented as a deliberate interpretation of "activity types".

---

## Steps

### Step 1 — Backend: category deriver + tests
- [x] `models.py`: add `ACTIVITY_CATEGORIES` (code→label) and `category_of(row) -> str` using the table above (falls back to `other` if unrecognised). Pure function.
- [x] test the deriver against one row of each source/prefix, incl. the `(reversed)` accepted-reply and an unknown shape.

### Step 2 — Backend: filtered, cursor-correct group-ledger read
- [x] `repository.py`: add `query_group_ledger_filtered_page(group_id, quarter, *, limit, cursor, predicate)` — pages the GSI3 `GLEDGER#<groupId>#<quarter>` query (newest first), applies `predicate(row)` in the loop, accumulates up to `limit` MATCHING rows, and returns `(rows, next_cursor)` where the cursor is the underlying `LastEvaluatedKey` at the stopping point (fetch-until-full; same pattern as Admin Users/Directory). No scan; still one group+quarter partition.
- [x] Keep the existing `query_group_ledger_page` for the unfiltered path (or route both through the new one with `predicate=None`).

### Step 3 — Backend: extend `group_ledger` service with filters
- [x] `read_service.group_ledger`: read optional `memberId`, `source` (repeatable/CSV → set), `activityType` (repeatable/CSV of category codes → set). Validate: source ∈ {auto,evidence,adjustment}; activityType ∈ ACTIVITY_CATEGORIES; memberId length-bounded. Build a predicate combining them (AND across kinds, OR within a set). Pass to the repo. Keep email resolution + activity fallback. Add `activityCategory` (derived) to each returned row so the UI/CSV can show/label it.
- [x] Authorization unchanged: UGL forced to led group; CL names a group; else 403.

### Step 4 — Contract (additive)
- [x] `contracts/services/contributions-scoring/openapi.yaml` `groupLedger`: add params `memberId`, `source` (style form, explode, enum items), `activityType` (enum items = category codes). Add optional `activityCategory` to `GroupLedgerRow`. Bump the file's version note. Additive under a routed base path → **no gen_api_edge regen**.

### Step 5 — Backend tests (filters + authz + pagination)
- [x] `tests/`: memberId filter; single & multi source; single & multi activityType; combined filters; fetch-until-full returns a full page and a working cursor across a filtered partition; UGL forced to led group; Member/Admin 403; empty filters == current behaviour. Contract gate stays green.

### Step 6 — Frontend: PointLedger tab component
- [x] `frontend/src/features/contributions/PointLedgerPanel.tsx`, props `{ role, ledGroupId }`:
  - Group: CL → dropdown of all groups (`/groups`), **no default**; UGL → fixed to `ledGroupId`. **No data load until a group is selected** (FR-3).
  - Quarter: dropdown `trailingQuarters(8)`, default current (FR-4).
  - Member: optional `PeoplePicker` single-select, group-scoped for UGL (FR-5).
  - Source multi-select (auto/evidence/adjustment, default all) + Activity-category multi-select (from `ACTIVITY_CATEGORIES`, default all) (FR-6/7).
  - Columns (FR-9): Member name, Email, Points, Activity, Group name (resolved via `groupNameFrom`), Earned date, Source, Pillar (label). Newest-first (server order).
  - Cursor Prev/Next via `DataTable` server mode + cursor stack; reset stack on any filter change (FR-11).
  - Export button → `exportPagedCsv('/contributions/group-ledger?<filters>', filename, { transform })` mapping rows to the US-7.9 column set; filename encodes group + quarter (+ member if set) (FR-12/13).
  - `data-testid`s: `tab-ledger`, `pl-group`, `pl-quarter`, `pl-member`, `pl-source-*`, `pl-activity-*`, `pl-export`.
- [x] Pure helpers extracted + tested: activity-category option list, and the CSV row transform (US-7.9 column mapping).

### Step 7 — Frontend: wire the tab + remove Leaderboard for CL
- [x] `ContributionsPage.tsx`: extend `Tab` with `"ledger"`. Add a **Point Ledger** tab for `isLeader` (CL + UGL). **Remove the Leaderboard tab for a CL** (`!isCL` gate — Members + UGL keep it, FR-15). Render `<PointLedgerPanel>` on `tab==="ledger"`. Fix the initial-tab fallback so a CL with `?tab=leaderboard` lands on `approvals`, not a missing tab (FR-17).

### Step 8 — Frontend: Leaderboard onto the CL dashboard
- [x] `CLDashboardPage.tsx`: add a new card/section rendering `<Leaderboard role="CommunityLeader" />` (the component from ContributionsPage — export it or lift it to a shared module). **Keep** the existing Top Contributors panel (DR-5 default). Place the Leaderboard as its own full-width section.
- [x] If `Leaderboard` must be imported, export it from ContributionsPage (or move it to `features/contributions/Leaderboard.tsx` and import in both) — pick the smaller-diff option at build time and note it.

### Step 9 — Docs + story write-back
- [x] Amend US-7.9 (and US-6.16 for the leaderboard placement) in `stories.md` + `requirements/usecases/07-*.md`.
- [x] `aidlc-docs/construction/contributions-scoring/code/point-ledger.md` — summary, the activity-category interpretation, DR-5 choice, what's verified/not.
- [x] Update `aidlc-state.md`.

### Step 10 — Verify (full gate, run in order)
- [x] `python3 -m pytest services/contributions-scoring -q` — pass incl. new filter/deriver tests
- [x] `make contract-tests SVC=contributions-scoring` — green
- [x] `cd frontend && npx tsc -b` — clean
- [x] `cd frontend && npm test` — pass incl. new helper tests
- [x] `cd frontend && npm run build` — clean
- [x] `make test` repo-wide — green
- [x] `ruff check services/contributions-scoring` — clean

---

## Traceability
FR-1/2 → 3,7 · FR-3/4 → 6 · FR-5 → 3,6 · FR-6/7 → 1,3,6 · FR-9/10 → 6 · FR-11 → 6 · FR-12/13 → 6 · FR-15/16/17 → 7,8 · DR-1..4 → 2,3,4,6 · DR-5 → 8.

**Files**: backend 4 (models, repository, read_service, tests) + contract 1; frontend 3–4 (PointLedgerPanel + tests, ContributionsPage, CLDashboardPage, maybe a lifted Leaderboard module) + docs. No infra, no new index, no migration.
