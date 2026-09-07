# Requirement Verification Questions — Point Ledger (US-7.9)

**Change request (2026-08-11)**: "As a CL and UGL, I should be able to see the details of points for a Member. After giving him +5 adjustment there is no way I can verify it. For CL, add another tab in the Contributions page. Name it 'Point Ledger'. Filters — Groups, Custom Date Range, Member, activity types (all including Auto). Columns — Member name, Email, Point, Activity, Group name. There would be thousands of records, so performance and lazy loading matter. Default sort by date (latest first). Need an Export feature."

Answer each question after the `[Answer]:` tag.

---

## What I found first (so the questions make sense)

- The point ledger is **append-only** and stored per member. It is mirrored onto one index, **GSI3 = `GLEDGER#<groupId>#<quarter>`**, which supports a **single group, single quarter**, date-sorted, cursor-paginated read. That already backs an endpoint (`/contributions/group-ledger`) a CL uses today.
- There is **no index** for a community-wide, all-groups, arbitrary-date-range, date-sorted read, and none keyed by activity or member. So the expensive case is exactly "All groups, custom range."
- **Email is not on a ledger row** — it's resolved per member from a projection this service keeps. The existing group-ledger endpoint already does this per page (memoised), so email as a column is solved.
- A ledger row's `source` is one of **`auto`** (system-awarded: event attendance/delivery, organize, forum post/accepted-reply, certification), **`evidence`** (approved submission), or **`adjustment`** (manual ±, carries a reason). The human-readable `activity` is the activity name (or the reason for an adjustment).
- This maps to an existing, **not-yet-built** story, **US-7.9** (granular per-entry export with date range + scope + CSV). Your screen is effectively US-7.9 made interactive.

---

## Question 1 — Who gets the Point Ledger?
Your text says "As a CL and UGL…" but then "For CL, add another tab."

A) **CL only** — a new "Point Ledger" tab on the Contributions page, community-wide

B) **CL and UGL** — CL sees the whole community (with a group filter); a UGL gets the same tab but **locked to the group they lead** (they already have group-scoped ledger access)

X) Other (describe after [Answer]:)

[Answer]: B

---

## Question 2 — Group filter behaviour (this drives performance the most)
A CL viewing **all groups** over an arbitrary date range is the costly query — the index is per-group-per-quarter.

A) Group filter offers **"All groups" + individual groups**; "All groups" is the default (full community view)

B) Group filter is **required to a single group** (no "All groups") — keeps every query on the fast per-group index; the CL picks a group first

C) "All groups" allowed, but only when the date range is within a **single quarter**; a wider range requires picking a group

X) Other (describe after [Answer]:)

[Answer]: B

---

## Question 3 — The performance approach (architecture decision — please pick)
How should the all-groups / wide-range case be served? Each has a real cost/timeline tradeoff.

A) **Add a new index + backfill** — add a community-wide, date-sorted ledger index (partitioned by quarter) and backfill it onto all existing ledger rows. Cleanest queries and true "all groups, any range." **Cost**: a change to the live DynamoDB table (one index add) **plus a one-time data migration** over thousands of existing rows, and an Infrastructure-Design stage. Highest effort, most flexible.

B) **Fan-out and merge, no table change** — for the selected groups × the quarters the date range spans, query the existing per-group-per-quarter index and merge-sort by date. **Cost**: no migration, but multi-partition pagination is complex and gets slower as groups × quarters grows; "all groups, all time" is the worst case.

C) **Constrain to fit the existing index** — require a single group (Q2=B) and/or a single quarter, reusing the existing fast path with almost no backend change. **Cost**: least effort/lowest risk, but the CL cannot see a true all-community, all-time ledger in one view.

X) Other (describe after [Answer]:)

[Answer]: NO all group, NO Date range, use a Quarter filter defaulted to first. Do not load data on page load.

---

## Question 4 — Member filter
A) **Searchable member picker** (optional) — type a name/email, narrow the ledger to that one member. Reuses the picker built for Adjust Points, scoped to the selected group for a UGL. This directly serves your "verify a member's +5 adjustment" case.

B) No member filter — rely on group + date + activity filters only

X) Other (describe after [Answer]:)

[Answer]: A

---

## Question 5 — What does "activity types (all including Auto)" filter on?
A ledger entry has both a **source** (auto / evidence / adjustment) and an **activity name**. "Including Auto" is ambiguous.

A) Filter by **source**: a multi-select of `auto`, `evidence`, `adjustment`, defaulting to all selected (so "all including Auto" = everything shown by default)

B) Filter by **activity type**: a multi-select of the framework's activity types (event attendance, event delivery, forum post, forum accepted-reply, certification, each evidence activity, manual adjustment), with the auto-awarded ones included in the list

C) **Both** — a source multi-select AND an activity-type multi-select

X) Other (describe after [Answer]:)

[Answer]: C

---

## Question 6 — On-screen columns
You listed: Member name, Email, Point, Activity, Group name. Sorting is by date, so **date must also be a column**.

A) Your five **+ Earned date** (date shown, sorted newest-first)

B) Your five + Earned date **+ Source** (auto/evidence/adjustment) **+ Pillar** — richer, matches the export

C) Your five + Earned date only; keep it lean

X) Other (describe after [Answer]:)

[Answer]: B 

---

## Question 7 — Export
A) Export the **currently filtered view** to CSV, walking all matching rows (not just the visible page), with the **full US-7.9 column set** (member_name, member_email, user_group, activity_type, pillar, points, source, earned_date, quarter). Filename encodes the scope + date range. A safety cap (e.g. 100k rows) applies.

B) Export only the columns shown on screen

X) Other (describe after [Answer]:)

[Answer]: A

---

## Question 8 — Lazy loading / pagination style
A) **Cursor pagination with Prev/Next** and a rows-per-page control — the established pattern for the 13k-row Member Directory and Admin Users tables in this app (skeleton on first load, "Refreshing…" between pages)

B) **Infinite scroll** (append pages as you scroll)

X) Other (describe after [Answer]:)

[Answer]: A

---

## Question 9 — Default date range on open
Opening with no range set and "All groups" could try to load the entire history.

A) Default to the **current quarter**, newest first; the user widens the range as needed

B) Default to the **last 30 days**

C) No default — show nothing until the user sets a range and hits "Load"

X) Other (describe after [Answer]:)

[Answer]: Not applicable.

---

## Recommendation (if you'd rather not answer all nine)
A coherent, lower-risk default set that still fully serves the "verify a member's adjustment" goal:
**Q1=B, Q2=A, Q3=A** (do it properly with the new index + backfill), **Q4=A, Q5=C, Q6=B, Q7=A, Q8=A, Q9=A**.
If you want the fastest path with the least infrastructure risk instead: **Q2=B, Q3=C** (single group required, reuse the existing fast index), keeping the rest the same.

---

## Not asked (already decided)
- **Authorization** stays server-enforced: CL community-wide, UGL their led group only, Members/Admin denied (SECURITY-08). UI scoping is convenience, never the control.
- **Ledger immutability** is unchanged — this is a read/export feature; it writes nothing.
- **No time component** in the CSV dates (calendar date only), matching the other exports.
