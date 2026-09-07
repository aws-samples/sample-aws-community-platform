# Certification Ledger + Dashboard Charts — Frontend Components

**Stage**: CONSTRUCTION → Functional Design (additive to Unit 6).
**Extends**: `frontend-components.md` (base Unit 6). Reuses the shared design system: `DataTable` (cursor server paging + rows-per-page), `PeoplePicker`, `lib/exportCsv` (`exportPagedCsv`, `dateOnly`), `lib/quarters` (`currentQuarter`, `trailingQuarters`), `lib/useApi`, `components/charts` (`TrendChart`, `RankedBarChart`), `lib/useGroupName`. Closely mirrors `contributions/PointLedgerPanel.tsx` and the existing dashboard charts.

---

## 1. Component tree (additions)

```
CertificationsPage (role-aware tab shell)
├── CL:   [Pending Verifications] [Definitions] [Certification Ledger] [Revoke]
├── UGL:  [Pending Verifications] [Catalog] [My Submissions] [Certification Ledger] [Revoke]
│   └── CertificationLedgerPanel (role, ledGroupId)     ← NEW, shared by CL + UGL
└── ClaimModal — earned-date field now ALWAYS required (DR-6)

CLDashboardPage  (Community Analytics)
├── CertificationGrowthChart (scope: community | group)   ← NEW
└── CertificationSnapshotChart (scope: community | group)  ← NEW

UglDashboardPage
├── CertificationGrowthChart (locked to led group)         ← NEW
└── CertificationSnapshotChart (locked to led group)       ← NEW
```

Default tab stays **Pending Verifications** for both roles (A10). Members/Admins never see the ledger tab or the charts (server 403 regardless).

---

## 2. CertificationLedgerPanel (FR-1..13)

Props: `{ role: Role; ledGroupId?: string }`. Modeled on `PointLedgerPanel`.

**Filters (row of controls):**
- **User group** — CL: a `<select>` of all groups with an explicit **"All groups"** option and **no default** (nothing loads until chosen, A10/FR-3). UGL: fixed to the led group (shown read-only), loads the current quarter on open (already scoped, so no heavy query).
- **Certification** — `<select>` from `GET /certifications?includeInactive=true` with an **"All certificates"** option.
- **Quarter** — `<select>` from `trailingQuarters(8)`, defaulted to the current quarter (FR-6).
- **Status** — multi-select checkboxes **Active | Expired | Revoked**, all checked by default (FR-7).
- **Member** — optional `PeoplePicker` (single), scoped to the selected group (for a UGL, the led group).

**Behavior:**
- No fetch until the CL has chosen a group (or "All groups"); UGL fetches immediately.
- `useApi<{items, cursor?}>('/certifications/ledger?…')` with the current filters + `limit` + `cursor`; any filter change resets the cursor stack (same pattern as PointLedgerPanel).
- **DataTable** columns (FR-9): **Member** (name), **Certification Name**, **Certification Date** (`certificationDate`, `dateOnly`), **User Group** (name via `useGroupName`/denormalized), **Status** (badge: Active/Verified green · Expired gray · Revoked red), **Category**, **Expires On** (`dateOnly`, blank when none). No raw ids.
- **Cursor Prev/Next + rows-per-page** via `DataTable`'s `server` prop; skeleton on first load, "Refreshing…" between pages (FR-11).
- **Export CSV** button (FR-12/13): `exportPagedCsv('/certifications/ledger?<baseQuery>', filename, { transform })` mapping to `member, email, certification, category, certification_date, approved_date, user_group, status, expires_on`; filename encodes group/all + quarter (+ member). Disabled until a group is chosen (CL).
- Empty/no-filter states: "Select a user group to view the certification ledger." (CL, no group) / "No certifications match these filters." (empty result).

---

## 3. Dashboard charts (FR-14..17)

Two shared chart components, each taking a `scope` (`community` | `groupId`) and a quarter/quarters input, used on both dashboards.

### CertificationGrowthChart (Chart 1)
- `GET /certifications/stats/growth?quarters=4[&groupId=]` → `{ items: [{quarter, total, new}] }`.
- Rendered with **`TrendChart`** (same primitive as membership growth): two series — **Total** (cumulative valid holdings) and **New this quarter** — across the last 4 quarters (oldest→newest).
- **CL**: a group filter (All groups | specific group). **UGL**: locked to `ledGroupId` (no picker). Reuses the dashboards' existing group/quarter controls where present.
- Caption clarifies both series share the earned-date basis (Total = held as of quarter-end, counted from earned quarter; New = earned that quarter) — amended 2026-08-12.

### CertificationSnapshotChart (Chart 2)
- `GET /certifications/stats/snapshot?quarter=[&groupId=]` → `{ items: [{certId, certName, count}] }`.
- Rendered with **`RankedBarChart`** (certification name → count), sorted desc.
- **CL**: scope selector **Community-wide | specific group** + quarter picker. **UGL**: locked to led group + quarter.
- Empty state: "No certifications held for this period yet."

Both charts follow the dashboards' existing **per-panel isolation** (own loading/error state; a slow/failed panel cannot blank the page).

---

## 4. ClaimModal change (DR-6)
- The **earned date** input is now **always required** (previously only when the selected certification had an expiry period). Client validation blocks submit without it; the not-in-future rule stays. Server enforces BR-C5′ regardless.

---

## 5. Endpoint map (component → API)
| Component | Calls |
|---|---|
| CertificationLedgerPanel | `GET /certifications` (cert filter list), `GET /groups` (CL group filter), `GET /certifications/ledger?…` (paged + export walk) |
| CertificationGrowthChart | `GET /certifications/stats/growth?quarters=4[&groupId=]` |
| CertificationSnapshotChart | `GET /certifications/stats/snapshot?quarter=[&groupId=]` |
| ClaimModal (changed) | unchanged endpoints; earned date now required client-side |

## 6. Validation summary (client mirrors, server authoritative)
| Field | Rule |
|---|---|
| Ledger group (CL) | required before load (or explicit "All groups") |
| Ledger status | ≥1 of Active/Expired/Revoked (default all) |
| Ledger quarter | valid quarter; default current |
| Claim earned date | **required** (DR-6), not future |

## 7. Testing note
No component-test library exists in the repo (established limitation). Pure filter/query-building and CSV-mapping helpers for the ledger panel are extracted into a plain `.ts` module and unit-tested (the pattern used by PointLedger/AdjustPoints); the rendered panel + charts get a documented manual pass at Build and Test.
