# Requirement Verification Questions — Certification Ledger + CL/UGL Dashboard Charts

**Change request (2026-08-12)**: "As a CL and UGL I want a Certification Ledger tab in the Certifications page. It will list all the member-wise certifications approved by CL or UGL. Big list, so pagination is needed. Filters — All | Specific Group, All Certificate | Specific Certificate, Date Range (Certification date), Status — Active | Expired, Member. Columns — Member, Certification Name, Certification Date, User Group, Status. Need an Export functionality. Should include all certifications that are either approved by CL or UGL. CL and UGL also see two Dashboard charts — (1) Quarterly Certification Growth (last 4 quarters, quarter by quarter; Filter — Groups for CL): Total Number of certifications, New Certifications in this Quarter. (2) Certification Snapshot (Filter — quarter, group or CL): Certification Name and count (bar chart)."

Answer each question after the `[Answer]:` tag. If none of the options fit, pick **X) Other** and describe.

---

## What I found first (so the questions make sense)

- **A "claim" is the single certification-holding entity.** Its lifecycle status is one of `Pending | Approved | Rejected | Withdrawn | Revoked | Expired`. The SPA already displays `Approved` as **"Verified"**. Only `Approved` and `Expired` rows represent certifications that were ever granted.
- A claim carries, denormalized at submission/approval (so ledger rows render with **no cross-service lookups**): `memberName`, `certName`, `creditedGroupId` (and often `creditedGroupName`), `dateEarned` (member-entered "earned" date; optional unless the cert has an expiry period), `decidedAt` (**approval timestamp**), `decidedBy` (who approved), `expiresAt`, `status`. Group name, where not stored, is resolvable from `/groups`.
- **There is NO index today that can list approved certifications community-wide, filtered by group / certification / date range / status.** The certifications table only has: `GSI1` = per-member claims, `GSI2` = sparse pending-queue, `GSI3` = sparse expiry/scan windows, and a per-certification `SLOT#<memberId>` collection for holder lookup. The service's stated design rule is **"No Scans anywhere."** So the ledger and both dashboard charts are a **new read/aggregation access pattern** — this is the main architecture decision below (mirrors the Point Ledger tradeoff you resolved earlier).
- "Approved by CL or UGL" — the system **never auto-approves** (it can only auto-*reject* on group departure). So in practice **every `Approved`/`Expired` claim was approved by a human CL or UGL.** I read the phrase as "include all granted certifications" rather than "filter by who approved." Q4 confirms this.
- The app already has the reusable pieces this feature needs: cursor pagination + rows-per-page (`DataTable`), `exportPagedCsv` (walks all matching rows), quarter helpers (`YYYY-Qn`, `trailingQuarters`, `quarterRange`), and shared chart primitives (`TrendChart`, `RankedBarChart`/`ColumnChart`). This mirrors the **Point Ledger** tab and the CL/UGL dashboard charts almost exactly.

---

# Part A — Certification Ledger tab

## Question A1 — UGL scope
The request says "As a CL and UGL," and the filters list "All | Specific Group" (a multi-group capability). How is a **UGL** scoped?

A) **CL sees all groups** (with the All | Specific-Group filter); a **UGL is locked to the single group they lead** (no group picker, no other group's data) — same model as the Point Ledger tab

B) Both CL and UGL can see all groups (UGL also gets the All | Specific-Group filter)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question A2 — What does "Certification Date" mean?
A granted claim has two candidate dates: the member-entered **earned date** (`dateEarned`, optional) and the **approval date** (`decidedAt`, always present on a granted claim).

A) **Approval date** (`decidedAt`) — always present; unambiguous; also what "approved by CL or UGL" naturally refers to

B) **Earned date** (`dateEarned`) — the date the member says they earned it; **falls back to approval date** when not provided

C) Show **both** as separate columns (Earned date + Approved date)

X) Other (please describe after [Answer]: tag below)

[Answer]: B. Earned date must be Mandatory

---

## Question A3 — Status filter: "Active | Expired"
Which claim statuses does the ledger include, and what do the two filter values map to?

A) Ledger includes **only `Approved` and `Expired`** claims. **Active = `Approved`** (currently held, not expired); **Expired = `Expired`**. `Revoked`/`Rejected`/`Withdrawn`/`Pending` are **excluded entirely**

B) Same as A, but also include **`Revoked`** rows (with a "Revoked" status), since a revoked cert was once approved

C) Include every status; "Active | Expired" is just a convenience filter over an otherwise full list

X) Other (please describe after [Answer]: tag below)

[Answer]: Explain more

---

## Question A4 — "Approved by CL or UGL" — meaning + optional column
Confirming the interpretation and whether the approver should be shown.

A) It means **"include all granted certifications"** (every `Approved`/`Expired` claim). **No** "Approved By" column needed

B) Include all granted certifications **and add an "Approved By" column** (approver name / CL vs UGL)

C) It is a genuine **filter** — let the viewer filter by approver role (Approved-by-CL vs Approved-by-UGL)

X) Other (please describe after [Answer]: tag below)

[Answer]: explain more

---

## Question A5 — Performance approach for the list (the key architecture decision)
No index today serves "all members' approved certs, filtered by group/cert/date/status." How should it be served? (Same class of tradeoff as Point Ledger Q3.)

A) **Add a new index + backfill** — add an approved-certifications index (e.g. partitioned by quarter, sortable by certification date, carrying group/cert) and backfill it onto existing granted claims. Enables true "All groups, any range," fast paging, and **also powers both dashboard charts** from one structure. **Cost**: a live DynamoDB table change (one GSI) + a one-time migration + an Infrastructure-Design stage. Highest effort, most capable, cleanest long-term

B) **Fan-out over the per-certification SLOT collections, no table change** — iterate the certification definitions (there are only tens) and their approved-holder slots, then apply group/date/status filters in-service and page the merged result. **Cost**: no migration; moderate complexity; acceptable at current data volumes but degrades as holdings grow; date-range + group filtering happen in memory

C) **Constrain to fit existing access** — require a **single quarter** (and reuse per-member/per-cert reads), no arbitrary date range and no true "all-time all-groups" view — least effort/risk, least flexible

X) Other (please describe after [Answer]: tag below)

[Answer]: need brainstorming

---

## Question A6 — Date-range filter shape
The request says "Date Range (Certification date)." How should the control behave? (Interacts with A5.)

A) **Quarter picker defaulted to the current quarter** (newest first), like the Point Ledger and dashboards — simplest, index-friendly, and lines up with the quarterly charts

B) **True custom from/to date range** (free calendar range) — most flexible, but depends on A5=A (new index) to stay fast

C) Quarter picker **plus** an "All quarters" option (all-time), depends on A5=A

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question A7 — On-screen columns
Requested: Member, Certification Name, Certification Date, User Group, Status. Confirm the exact set.

A) **Exactly the five requested** (Certification Date per A2)

B) The five **+ Category** (AWS Certification / Community Badge) **+ Expires On** (blank if it never expires) — richer, and matches the export

C) The five + whatever A4 adds (e.g. Approved By)

X) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## Question A8 — Export
A) Export the **currently filtered view** to CSV, walking **all matching rows** (not just the visible page) via the established paged-export helper, with a superset of columns (member, email, certification, category, certification date, earned date, approved date, user group, status, expires on). Filename encodes scope + period. Safety cap (~100k rows) applies

B) Export only the columns shown on screen

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question A9 — Pagination style
A) **Cursor pagination with Prev/Next + rows-per-page** — the established pattern (Member Directory, Admin Users, Point Ledger)

B) Infinite scroll

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question A10 — Tab placement, label, and default
The Certifications page is role-aware. Today: **CL** = Pending Verifications · Definitions · Revoke; **UGL** = Pending Verifications · Catalog · My Submissions · Revoke.

A) Add a **"Certification Ledger"** tab to both the CL and UGL views; keep each role's existing **default tab (Pending Verifications)** unchanged — the Ledger is opt-in

B) Add it and make **"Certification Ledger" the default tab** for CL and UGL

C) Add it, and (like the Point Ledger) **do not load any data until a filter is chosen** (e.g. group for CL) to avoid a heavy query on tab open

X) Other (please describe after [Answer]: tag below)

[Answer]: C

---

# Part B — Dashboard charts (CL + UGL)

## Question B1 — Chart 1 "Total Number certification" — what does the line measure?
Per quarter, over the last 4 quarters.

A) **Cumulative holdings as of each quarter-end** — the running total of certifications currently held (granted and not yet expired/revoked) at the end of each quarter (a growth curve)

B) **Total granted ever, as of each quarter-end** — cumulative count of all approvals up to that quarter (expired/revoked still counted)

C) **Per-quarter total** — the number of certifications *active* during that quarter (not cumulative)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question B2 — Chart 1 "New Certifications in this Quarter"
A) Count of certifications **approved within the quarter** (bucketed by approval date `decidedAt`)

B) Count bucketed by **earned date** (`dateEarned`, fallback approval date)

X) Other (please describe after [Answer]: tag below)

[Answer]: B

Note: whichever date basis you pick here should match Question A2 for consistency across the ledger and charts.

---

## Question B3 — Do expiry/revocation reduce the counts?
A) **Yes** — "Total Number" reflects **currently valid holdings**: expiring or revoking a certification decrements it (a true "active certifications" curve)

B) **No** — counts are of **certifications ever granted**; expiry/revocation does not reduce them

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question B4 — Chart 1 group filter (CL) and UGL scope
A) **CL** gets a group filter (**All groups** aggregate + pick a specific group); **UGL** chart is **locked to their led group** (no picker)

B) CL group filter as above; UGL not shown Chart 1 at all

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question B5 — Chart 2 "Certification Snapshot" — the count basis
A bar chart of **certification name → count**, filtered by quarter + group/scope.

A) Count = **certifications granted (approved) during the selected quarter**, grouped by certification name

B) Count = **certifications held as of the selected quarter** (cumulative holdings by certification name), grouped by certification name

X) Other (please describe after [Answer]: tag below)

[Answer]: What is the difeference bwteen A and B

---

## Question B6 — Chart 2 scope filter ("quarter, group or CL")
"Group or CL" is ambiguous — I read "CL" as "the whole community (Community-Leader/all-groups view)."

A) A scope selector: **Community-wide (all groups)** vs **a specific group**, plus the quarter picker — for the **CL**. The **UGL** sees the same chart **locked to their led group** + quarter picker

B) Same as A but UGL does not get Chart 2

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question B7 — Where the charts live
The CL landing dashboard is "Community Analytics" (`CLDashboardPage`); the UGL has `UglDashboardPage`. Both already host live charts fed by real services.

A) Add **both charts to both** the CL and UGL dashboards (UGL versions scoped to the led group)

B) Add them **only to the CL** dashboard

C) Other split (please describe)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Recommendation (if you'd rather not answer every question)

A coherent, lower-risk set that fully serves the intent and keeps the ledger and charts consistent:

- **Ledger**: A1=A (UGL locked to led group), A2=A (approval date), A3=A (Approved + Expired only; Active=Approved), A4=A (include all; no approver column), **A5=A (new index + backfill — it also powers the charts)**, A6=A (quarter picker, default current), A7=B (richer columns), A8=A (full paged CSV export), A9=A (cursor paging), A10=A (add tab, keep Pending default).
- **Charts**: B1=A (cumulative current holdings), B2=A (by approval date), B3=A (active/valid holdings — expiry & revoke decrement), B4=A, B5=A (granted in the quarter), B6=A, B7=A (both dashboards).

If you'd rather avoid the live-table migration for now: **A5=B or A5=C** with **A6=A** (quarter-scoped), keeping everything else — at the cost of no true all-time/all-groups view and in-memory filtering.

---

## Not asked (already decided / out of scope)

- **Authorization** stays server-enforced (SECURITY-08): CL community-wide, UGL their led group only; Members and Administrators denied. UI scoping is convenience, never the control.
- **Extension baselines** already enabled for this project (Security = Yes, Resiliency = Yes, Property-Based Testing = No) — not re-asked; they apply to this enhancement.
- This is a **read/export + charts** feature: it writes no new claim data and does not change the certification lifecycle, business rules, or the verification/revocation/expiry flows.
- CSV dates are calendar-date only (no time component), matching every other export in the app.

---
---

# Round 2 — Clarifications & Brainstorming

You asked for more on **A3, A4, A5, B5**, and your **A2** answer ("earned date mandatory") has an implication to confirm. Answer the new `[Answer R2]:` tags below.

---

## A2 follow-up — Making "Earned date" mandatory (submission change + historical fallback)

**Why this matters:** Today `dateEarned` is required **only** when the chosen certification has an expiry period (rule BR-C5); for a never-expiring badge it's optional. Choosing earned date as the ledger's "Certification Date" (A2=B) **and** making it mandatory means:

1. **Submission changes** (beyond a read-only ledger): the claim form always requires an earned date, and the server always validates it. This edits the claim flow (US-5.4 / BR-C5) — a real, in-scope change to how members submit.
2. **Historical rows:** granted claims approved *before* this change for non-expiring certs have **no earned date** and one cannot be invented. The ledger and the earned-date charts must fall back to the **approval date** for those rows.

### Question A2-R2 — Confirm scope of "earned date mandatory"
A) **Yes** — make earned date mandatory on submission going forward (form + server), AND for historical claims that lack it, **fall back to approval date** in the ledger and charts

B) Make it mandatory going forward, and **hide/exclude** historical claims that have no earned date from the earned-date views (don't fall back)

C) **Don't** change submission; keep earned date optional and simply **fall back to approval date** wherever earned date is missing (ledger "Certification Date" = earned date if present, else approval date)

X) Other (please describe after [Answer R2]: tag below)

[Answer R2]: If you look at a practicle Scenario. I appear for an AWS CEritification. passed, AWS issues a Cenrtificate, which has a date printed in it. All over the world evry certicate has a date. and that date the candidate earner it; not the date on which open one approve it on some system. I am not able to understand what is you confusion ? unless you came from moon.

---

## A3 — Which statuses appear (Active | Expired), and Revoked

A granted claim is currently one of: **Approved** (valid, held), **Expired** (lapsed), or **Revoked** (a leader pulled it). `Rejected`/`Withdrawn`/`Pending` were never granted, so they never appear. Your filter offers only **Active | Expired** (two values), so **Revoked has no filter slot** — the only real question is whether a revoked badge still shows as a row.

- **A** — Ledger shows **Approved + Expired only**; Active = Approved, Expired = Expired; **Revoked excluded**. (Matches the two-value filter cleanly.)
- **B** — Also include **Revoked** rows (shown with a "Revoked" status), even though the filter toggle is Active|Expired, for a fuller "what was ever granted" audit.

### Question A3-R2
A) Approved + Expired only (Revoked excluded)

B) Include Revoked rows too

X) Other (please describe after [Answer R2]: tag below)

[Answer R2]: Show also Revoked, and add Revoked also in the filter

---

## A4 — "Approved by CL or UGL" + approver column

Because the system **never auto-approves**, every granted claim was approved by a human CL or UGL — so the phrase means **"all granted certifications,"** not a filter. The only decision is whether to **show who approved**.

- **Cost note:** a claim stores the approver's **id**, not their role or name. Showing an approver **name** or **CL/UGL role** needs a per-row lookup into Identity (a cross-service, per-row read this codebase deliberately avoids) unless we denormalize the approver name at approval time.

- **A** — Include all granted certs; **no "Approved By" column** (simplest).
- **B** — Add an **"Approved By"** column; requires denormalizing the approver's display name onto the claim at approval time (small backend change) so no per-row lookup is needed.
- **C** — Offer an approver-**role filter** (Approved-by-CL vs Approved-by-UGL); requires storing the approver's role on the claim.

### Question A4-R2
A) Include all; no approver column

B) Add "Approved By" column (denormalize approver name at approval)

C) Add approver-role filter

X) Other (please describe after [Answer R2]: tag below)

[Answer R2]: A

---

## B5 — "Certification Snapshot": flow vs stock (the A/B difference)

- **A = flow (new in the quarter):** for the selected quarter, how many of each certification were **newly earned/granted that quarter**. Bars = "5 earned AWS SA in Q3, 3 earned Security badge in Q3…"
- **B = stock (held as of the quarter):** how many of each certification are **currently held** as of that quarter. Bars = "37 hold AWS SA, 12 hold Security badge…"

It's the classic flow-vs-stock distinction. Because it's titled a **"Snapshot"** and complements Chart 1 (which already shows totals + new), **B (current holdings by certification)** is the more natural pairing, but **A** is right if you want a per-quarter inflow breakdown.

### Question B5-R2
A) Flow — certifications newly granted in the selected quarter, by certification name

B) Stock — certifications currently held as of the selected quarter, by certification name

X) Other (please describe after [Answer R2]: tag below)

[Answer R2]: B

---

## A5 — Architecture brainstorm (please confirm the direction)

**The need, restated from your answers:** a single-**quarter** ledger view (A6=A), UGL locked to their led group (A1=A), no load until a filter is chosen (A10=C), filterable by group (All|specific for CL), certification (All|specific), status (Active|Expired), and member; plus two dashboards needing a **4-quarter growth series** (cumulative valid holdings + new-in-quarter) and a **per-certification snapshot** — for all groups or one group.

**What already exists:** per-member claims (GSI1), a sparse pending queue (GSI2), sparse expiry/scan windows (GSI3), and a per-certification `SLOT#<memberId>` collection listing **current** approved holders. Critically, **a claim's SLOT is deleted the moment it leaves Approved** (expiry/revoke/withdraw), so slots know *current* holders but **carry no earned date, no group, and no history** — they cannot produce Expired rows, date ranges, group filters, or past-quarter growth.

### Why the two no-migration options fall short here
- **Fan-out over SLOTs (old option B):** gives *current* holders per cert cheaply (fine for a "held now" snapshot), but **cannot** render Expired rows, filter by group, filter by earned-date/quarter, or draw historical growth. Insufficient for this feature.
- **Constrain hard (old option C):** we could force single-cert or single-member reads, but that can't do "All certificates, this quarter, this/all groups" as a member-wise list, and still can't do the growth chart.

### Proposed direction — one new sparse index, serving both the ledger and the charts

Add a single **"granted" GSI** that indexes **every claim that has ever been granted** (Approved, Expired, and — if A3=B — Revoked-after-approval), and **backfill** it onto existing granted claims (one-time migration).

- **Partition by earned-quarter**, sorted by earned date:  `GLED#<earnedQuarter>` / `<earnedDate>#<claimId>`  (earnedQuarter derived from earned date, falling back to approval date per A2-R2). Each indexed item carries the fields the ledger and charts read: `memberId`, `memberName`, `certId`, `certName`, `creditedGroupId` (+name), `status`, `dateEarned`, `decidedAt`, `expiresAt`, `revokedAt`.
- **Ledger (single quarter):** one partition query for the selected quarter, with an in-memory predicate for group/cert/status/member and **cursor paging using the fetch-until-full loop already proven by the pending queue** — bounded by claims-in-that-quarter, never a table scan. UGL's group predicate is forced to their led group server-side.
- **Chart 2 snapshot (one quarter):** the same single-partition read, aggregated by `certName`.
- **Chart 1 growth (last 4 quarters):**
  - *New-in-quarter (B2=B, earned date):* the per-quarter partition counts.
  - *Cumulative valid holdings as of each quarter-end (B1=A, B3=A):* computed from the granted items' **active window** — a badge is valid from `decidedAt` until `min(expiresAt, revokedAt)`; "as of quarter-end Q" counts items with `decidedAt ≤ Qend AND (expiresAt is null or > Qend) AND (revokedAt is null or > Qend)`. This reads the granted index across the relevant quarters (index-only, no scan).

**Note on date basis (so there's no surprise):** the ledger's displayed "Certification Date" and Chart 1's *New-in-quarter* bar use the **earned date** (your A2/B2). Chart 1's *cumulative holdings* line is inherently a "valid at that time" measure, so its as-of boundary uses **approval/expiry dates** (when the badge actually became/stopped being active). This is the correct semantics for a growth curve; flagging it because the two lines on Chart 1 therefore use slightly different date bases by design.

**Costs:** one GSI added to the live certifications `-data` stack + a one-time backfill migration over existing granted claims + an Infrastructure-Design pass. This is the only option that satisfies the full request (Expired rows, group + earned-date filters, and historical growth) while honoring the service's "no scans" rule, and it powers the ledger and both charts from one structure.

**Scale assumption:** the growth aggregation reads all granted claims across the displayed quarters in memory, consistent with how the CL/UGL dashboards already compute live figures. Appropriate for thousands of claims / tens of certifications; if holdings later reach a much larger scale, a nightly pre-aggregation (like the contributions sweep) would be the follow-up — out of scope now.

### Question A5-R2 — Confirm the architecture direction
A) **Yes** — add the one new "granted" GSI (partitioned by earned-quarter) + backfill, powering both the ledger and the charts as described. Include an Infrastructure-Design stage for the index/migration

B) **Yes to the index, but pre-aggregate now** — additionally build a nightly rollup for the dashboard charts from day one (more work up front; cheaper chart reads)

C) **Avoid the migration for now** — quarter-scoped ledger only, computed by a bounded in-memory approach without a new GSI, and accept that the growth chart's historical accuracy is best-effort (revisit later)

X) Other (please describe after [Answer R2]: tag below)

[Answer R2]:
