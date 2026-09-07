# Point Ledger + CL Leaderboard move — code summary (US-7.9)

**Date**: 2026-08-11
**Units**: Unit 7 (Contributions & Scoring), Unit 15 (SPA)
**Plan**: `aidlc-docs/construction/plans/point-ledger-code-generation-plan.md`

---

## What was built

A CL/UGL **Point Ledger** tab on the Contributions page: individual point entries for one
group + quarter, filterable by member / source / activity category, cursor-paginated, with a
CSV export in the US-7.9 column set. Plus the CL **Leaderboard moved** from the Contributions
page to the Community Dashboard.

### Backend (contributions-scoring)
| File | Change |
|---|---|
| `models.py` | `SOURCES`; `CATEGORY_LABELS`; `category_of(row)` — derives a stable activity category from `source` + the three code-generated prefixes |
| `repository.py` | `query_group_ledger_filtered_page(...)` — fetch-until-full page over the GSI3 `GLEDGER#<group>#<quarter>` partition applying a predicate, returning a full page + a correct cursor (no scan) |
| `read_service.py` | `group_ledger` extended with optional `memberId` / `source[]` / `activityType[]` filters (validated; unknown value → 400), returns `activityCategory` + label per row; `_parse_multi` helper |
| contract | additive `memberId` / `source` / `activityType` params on `groupLedger`; optional `activityCategory`/`activityCategoryLabel` on `GroupLedgerRow` |

### Frontend (SPA)
| File | Change |
|---|---|
| `contributions/pointLedger.ts` (+ test) | Pure helpers: category/source options, `buildLedgerQuery`, `toExportRow` (US-7.9 columns), `exportFilename` — 10 tests |
| `contributions/PointLedgerPanel.tsx` | The tab: group (required; UGL locked), quarter (default current), member picker, source + activity multi-selects, columns per Q6=B, cursor Prev/Next, CSV export, **no load until a group is chosen** |
| `ContributionsPage.tsx` | `Tab` += `ledger`; Point Ledger tab for CL+UGL; **Leaderboard tab removed for CL only**; `?tab=leaderboard` fallback for CL; `Leaderboard` exported |
| `CLDashboardPage.tsx` | New **Leaderboard** section (kept Top Contributors — DR-5 default) |

---

## Decisions / deviations (flag)

- **Activity categories are coarser than the approved plan listed.** The plan named forum-post,
  forum-accepted-reply and organize-event as separate categories. In the data these auto awards
  store only a **CL-editable display name** with no category code, so they cannot be reliably
  separated on historical rows. They collapse into **`other-auto`**. Reliable categories:
  `event-attendance` / `event-delivery` / `certification` (stable prefixes), `evidence` /
  `adjustment` (source), and `other-auto`. **This is a reduction from the plan — please confirm
  it's acceptable, or I can enrich the ledger write path to stamp a category on new entries
  (legacy rows would still bucket to other-auto).**
- **DR-5 = default (keep Top Contributors, add Leaderboard).** Not replaced.
- **Scope stays on the fast index**: single group + single quarter only — no all-groups, no
  custom date range (per the approved Q2/Q3 answers). No new GSI, no migration, no infra change.

---

## Verification
- `python3 -m pytest services/contributions-scoring` — pass (added filter/deriver/pagination tests)
- `make contract-tests SVC=contributions-scoring` — **group-ledger PASSES**; overall 18/23 (the 5 failures are pre-existing framework/summary/export mock-fixture issues, confirmed at HEAD, unrelated to this change)
- `cd frontend && npx tsc -b` clean; `npm test` **128 pass** (was 118); `npm run build` clean
- `make test` repo-wide — green, no regression
- `ruff check services/contributions-scoring` — clean

## Not verified
No test renders the PointLedgerPanel or the dashboard Leaderboard section (no component-test
library). The filter/query/export logic is covered by the pure-helper tests and the backend
filter tests, but the wiring (picker → query, paging controls, export button, the dashboard
placement) needs a human pass on the deployed screen.

## Deploy
**Full root-stack deploy** (backend + contract change), not SPA-only.
