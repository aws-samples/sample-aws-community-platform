# What's New in AWS — Code Generation Plan (Part 1)

**Unit**: Unit 15 Frontend SPA — What's New increment (Module 11)
**Created**: 2026-08-10
**Stage**: CONSTRUCTION — Code Generation, Part 1 (Planning)
**Status**: COMPLETE — approved 2026-08-10, all 12 steps executed and verified

> **This plan is the single source of truth for Code Generation.** Part 2 executes these steps in order and marks each `[x]` on completion. Because Q3=D scoped this increment to Code Generation only (no Functional Design / NFR / Infrastructure Design stages), all design decisions and requirement deviations are recorded **here** rather than in design artifacts.

---

## 1. Unit context

| | |
|---|---|
| **Owning unit** | Unit 15 Frontend SPA (per `unit-of-work-story-map.md`) |
| **Artifacts location** | `aidlc-docs/construction/frontend-spa/whats-new/` |
| **Application code** | `frontend/src/features/whats-new/` (workspace root — never `aidlc-docs/`) |
| **Type** | Brownfield modification — `WhatsNewPage` already exists as a mock and is routed |
| **Backend services touched** | **None.** No new service, table, Lambda, IaC, or contract change |
| **Runtime dependencies** | Settings service `GET /settings` (already deployed) for `whatsNewEnabled` + `whatsNewFeedUrl`; the external mirror feed URL |
| **Blocked by** | Nothing. Unit 11 Settings is complete and deployed |
| **Parks** | Unit 5 Forums remains parked at NFR Requirements (Q2=A) |

### Verified preconditions (checked in code, not assumed)

- `GET /settings` is **not** in `ADMIN_ONLY_OPS` in `services/settings/src/app.py` — only `updateSettings` and `updateEmailTemplate` are. Any authenticated principal can read the gate fields, so Members can load this page. `AppLayout.tsx` already calls `useApi("/settings")` for every role in the deployed app, so this path is proven live.
- `WhatsNewPage` is imported in `frontend/src/App.tsx` line 21 from `./features/singletons` and routed at `/whats-new` line 138.
- Nav gating for US-11.2/11.6 already works in `AppLayout.tsx` (`whatsNewEnabled` filter, Administrator excluded by `navForRole`). **No change needed.**
- `dompurify@^3.4.13` already a dependency. `vitest@^2.0.0` already a devDependency with `npm test` → `vitest run` wired, zero test files.
- `make test` currently runs **pytest only** — frontend tests are not gated.

---

## 2. Decisions carried into this plan

Answers from `whats-new-scope-questions.md` and `whats-new-brainstorming.md`, plus consequences.

| ID | Decision | Source |
|---|---|---|
| **DW-1** | Feed served from a **self-maintained mirror of the official AWS "Recent Announcements" feed** on S3 + CloudFront with CORS enabled. Keeps US-11.7 (client-side fetch, no backend) and US-11.1 (Administrator sets the URL) both intact | Round-3 user decision |
| **DW-2** | **Details = full `<description>`, sanitized.** No `<content:encoded>` path — the official feed does not carry it | B2-Q2, forced by measurement |
| **DW-3** | **Always sanitize** feed content reaching the DOM, unconditionally. HTML measured in 100/100 official-feed descriptions | B2-Q3 |
| **DW-4** | **RSS 2.0 only.** No Atom parsing | Q6 → B3-Q4 = official feed |
| **DW-5** | Category taxonomy **normalized in the mirror publisher** — multiple `<category>` elements with human labels | B5-Q8 = A |
| **DW-6** | Publisher emits the **raw slug** as the label when it has no mapping, so it is visibly wrong and gets reported | B5-Q9 = B |
| **DW-7** | **Mirror creation and refresh sit OUTSIDE this application's scope.** No Lambda, no scheduler, no publisher script in this repo | B5-Q10 = C, user: *"will sit outside of this application scope"* |
| **DW-8** | Undated items (`<pubDate>` missing) **sort last**, remain visible and searchable | B5-Q11 = A |
| **DW-9** | Category filter options listed **alphabetically** | R2-Q5 = A |
| **DW-10** | Extract to **`frontend/src/features/whats-new/`** — page, parser, item component, filter separated | R2-Q6 = A |
| **DW-11** | **`happy-dom`** as the Vitest DOM environment (`DOMParser` is browser-only) | R2-Q7 = A |

### New decisions this plan proposes (please confirm or overrule)

**DW-12 — Defensive fallback for a non-normalized feed.** DW-5 puts normalization in the publisher, and DW-7 puts the publisher outside our scope. Those two together mean **the SPA depends on a component we do not own honouring a shape we specified.** US-11.1 also lets the Administrator point the setting at *any* URL, including raw upstream. If that happens, an un-normalized feed yields exactly one useless filter option: `marketing:marchitecture/compute,general:products/amazon-ec2`.

Proposal: the parser splits a `<category>` element on commas **only when its text matches the machine-taxonomy pattern** (contains both `:` and `/`), and uses the raw token as the label, consistent with DW-6's fail-loudly stance. The pattern gate is essential, not decoration — the sample's item 8 carries the legitimate label `Security, Identity & Compliance`, which **contains a comma** and has no colon or slash, so it is left intact. A naive comma split would shred it into two bogus facets.

**DW-13 — The feed fetch must not carry portal credentials.** The feed lives on a third-party origin. The fetch therefore uses **plain `fetch()`**, not `apiFetch()`. `apiFetch` prefixes the API base URL and attaches the caller's Cognito JWT; using it here would leak a portal bearer token to whatever host the Administrator configured. Explicitly: no `Authorization` header, `credentials: "omit"`, and the response treated as untrusted input.

**DW-14 — Feed contract documented for the out-of-scope maintainer.** Since DW-7 externalizes the publisher, this repo carries the **specification** the mirror must satisfy (`infra/whats-new-feed/README.md`) alongside the reference sample. Without it, DW-5 is an undocumented assumption in someone else's head.

**DW-15 — Single canonical sample, no duplicated fixture.** `infra/whats-new-feed/whats-new-sample.xml` is read directly by the parser tests via `fs.readFileSync` rather than copied into a frontend fixtures folder, so the reference feed and the tested feed cannot drift apart.

---

## 3. Requirement deviations to record

| # | Requirement | Deviation | Rationale |
|---|---|---|---|
| **DV-1** | US-11.5: `<description>` HTML "rendered as-is" | Rendered **sanitized**, not as-is | The same use case's own security note mandates addressing sanitization. Third-party HTML, measured present in 100/100 items. Matches the Announcements precedent |
| **DV-2** | `usecases/11-whats-new-aws-feed.md`: categories are "a flat list (e.g. 'Amazon EC2', 'Compute', 'Storage')" | **Factually wrong about upstream.** Upstream emits ONE `<category>` element holding a comma-joined machine taxonomy; 8/100 items have none. The use case's described shape is delivered by the mirror (DW-5), not by upstream | Measured on the live official feed |
| **DV-3** | US-11.7: feed fetched from "the configured CORS-enabled URL" | Unchanged in behaviour, but the CORS-enabled URL is now **our own mirror** (DW-1) because no AWS-published feed sends `Access-Control-Allow-Origin` | Measured: both candidate feeds lack the header |

Use case + `stories.md` get updated in Step 12 so these are not left as silent divergences.

---

## 4. Story traceability

| Story | Covered by steps | Notes |
|---|---|---|
| US-11.2 Nav item | — | **Already shipped**, no change (verified in `AppLayout.tsx`) |
| US-11.3 Detail page — all items, reverse chronological, collapsible rows, fetch on every load | 3, 5, 6, 7 | Sort with undated last (DW-8) |
| US-11.4 Search + category filter | 4, 6 | Search spans title + summary + details; categories dynamic + alphabetical (DW-9) |
| US-11.5 Inline expand + "Read full announcement on AWS ↗" | 5, 6 | Sanitized (DV-1); `target="_blank" rel="noopener noreferrer"` |
| US-11.6 Disabled / not-configured behavior | 6 | Disabled + not-configured states preserved; nav gating already shipped |
| US-11.7 Client-side fetch, parse, graceful errors | 2, 3, 6, 8 | Plain `fetch` (DW-13); no caching; self-diagnosing error states |
| US-11.1 Configure feed URL + toggle | — | **Already shipped + deployed** in Unit 11 Settings, no change |

---

## 5. Execution steps

### Step 1 — Test infrastructure
- [x] Add `happy-dom` to `frontend/package.json` devDependencies, pinned (DW-11)
- [x] Add a `test` block to `frontend/vite.config.ts` setting `environment: "happy-dom"` and including `src/**/*.test.ts`
- [x] Confirm `npm test` runs and reports zero failures with no test files yet present

### Step 2 — Feed types + fetch module
- [x] Create `frontend/src/features/whats-new/types.ts`: `FeedItem { id, title, link, pubDate: Date | null, categories: string[], summary, detailsHtml }` and `FeedLoadResult`
- [x] Create `frontend/src/features/whats-new/fetchFeed.ts` — plain `fetch(url, { credentials: "omit" })` per DW-13, no auth header, explicit `AbortController` timeout, distinguishing network/CORS failure from a non-2xx response so the UI can say which (US-11.7)

### Step 3 — RSS parser
- [x] Create `frontend/src/features/whats-new/feedParser.ts` — `parseFeed(xml: string): FeedItem[]` using `DOMParser`
  - [x] RSS 2.0 only (DW-4); detect and report `<parsererror>` rather than returning silent garbage
  - [x] Handle both CDATA-wrapped and entity-escaped `<description>`
  - [x] `<pubDate>` via RFC-822 parse; unparseable or absent → `null`, sorted last (DW-8)
  - [x] Collect **all** `<category>` elements; drop blanks; apply the DW-12 pattern-gated taxonomy split
  - [x] Derive `summary` from description text content: strip tags, collapse whitespace, truncate at ~150 chars on a word boundary, ellipsis only when actually truncated
  - [x] Sort reverse-chronologically (US-11.3), stable for equal dates
  - [x] Item identity from `<guid>`, falling back to `<link>`, then title+date — never array index

### Step 4 — Filter logic
- [x] Create `frontend/src/features/whats-new/filter.ts` — `filterItems(items, { q, category })`
  - [x] Search matches title + summary + details text, case-insensitive (US-11.4)
  - [x] Category match is exact against the item's category list
  - [x] Combined predicates; `collectCategories(items)` returns a de-duplicated alphabetical list (DW-9), blanks excluded

### Step 5 — Sanitization policy + item component
- [x] Create `frontend/src/features/whats-new/sanitize.ts` — single DOMPurify configuration (DW-3/DV-1): allow `p br strong em b i ul ol li code pre a h3 h4 span`; allow `href title` on `<a>`; force `target="_blank" rel="noopener noreferrer"`; forbid `script iframe object embed style` and all `on*` handlers; strip inline `style`
- [x] Create `frontend/src/features/whats-new/FeedItemRow.tsx` — collapsible row: title, summary, formatted date, category badges; expands inline to sanitized details plus the "Read full announcement on AWS ↗" link (US-11.5)
- [x] `data-testid` attributes per the automation-friendly rule: `wn-item`, `wn-item-toggle`, `wn-item-details`, `wn-item-external-link`

### Step 6 — Page component
- [x] Create `frontend/src/features/whats-new/WhatsNewPage.tsx`, replacing the mock
  - [x] Read `whatsNewEnabled` / `whatsNewFeedUrl` via existing `useApi("/settings")`
  - [x] Preserve the shipped disabled and not-configured states (US-11.6)
  - [x] Fetch + parse on every mount, no caching (US-11.3/11.7)
  - [x] Search input + category `<select>`, existing `data-testid` values `wn-search` / `wn-category` retained
  - [x] Reuse `Loading`, `ErrorState`, `EmptyState` from `components/States.tsx`
  - [x] Distinguish three empty-ish outcomes rather than collapsing them: fetch/CORS failure, feed parsed but empty, filters matched nothing
- [x] Create `frontend/src/features/whats-new/index.ts` re-exporting `WhatsNewPage`

### Step 7 — Wire up, remove the mock
- [x] Update the `WhatsNewPage` import in `frontend/src/App.tsx` to `./features/whats-new` (route path `/whats-new` unchanged)
- [x] Delete `WN_FEED` and the mock `WhatsNewPage` from `frontend/src/features/singletons.tsx`, leaving `ProfilePage` / `SettingsPage` / `FileSharingPage` untouched; prune imports that become unused

### Step 8 — Tests
- [x] `feedParser.test.ts` against the canonical sample via `fs.readFileSync` (DW-15): 9 items parsed; reverse-chronological order with the undated item last; CDATA and escaped descriptions both yield HTML; item with no category contributes no blank facet; short description gets no ellipsis; entity-bearing title and comma-bearing category label survive intact; DW-12 taxonomy split fires on machine tokens and does **not** fire on `Security, Identity & Compliance`
- [x] `feedParser.malformed.test.ts`: malformed XML, empty `<channel>`, non-RSS document, missing required fields → graceful result, never a throw
- [x] `sanitize.test.ts` against a new `frontend/src/features/whats-new/__fixtures__/hostile-feed.xml` (kept out of `infra/` so it can never be published by mistake): `<script>`, `onerror=`, `javascript:` href, `<iframe>`, inline `style` all neutralized; benign formatting preserved; `<a>` gains `target`/`rel`
- [x] `filter.test.ts`: search across all three fields, category exactness, combined filters, no-match empty result, alphabetical facet ordering

### Step 9 — Repo gate
- [x] Add the frontend Vitest run to `make test` so these tests are actually gated alongside pytest
- [x] Verify: `npm test` green, `npx tsc -b` clean, `npm run build` clean, `make test` green repo-wide with no regression in the 5 existing pytest suites

### Step 10 — Feed contract for the out-of-scope mirror (DW-14)
- [x] Create `infra/whats-new-feed/README.md`: required RSS 2.0 shape, the normalization contract (DW-5/DW-6) with a before/after taxonomy example, the mandatory CORS response header, why it exists (measured absence of CORS upstream), refresh expectations, and an explicit statement that publishing and refreshing are **outside application scope** (DW-7)
- [x] Cross-reference the sample as the reference artifact

### Step 11 — Documentation
- [x] Create `aidlc-docs/construction/frontend-spa/whats-new/code-summary.md` — files created/modified, decisions DW-1…DW-15, deviations DV-1…DV-3, test inventory, verification results
- [x] Update `aidlc-docs/construction/frontend-spa/story-verification.md` for US-11.3/11.4/11.5/11.7 moving from mock to real

### Step 12 — Requirement artifact updates (deviations recorded, not silent)
- [x] `requirements/usecases/11-whats-new-aws-feed.md`: correct the category-shape claim (DV-2), note sanitization (DV-1), note the mirror (DV-3)
- [x] `aidlc-docs/inception/user-stories/stories.md`: deviation notes on US-11.5 and US-11.7
- [x] `aidlc-docs/aidlc-state.md`: mark this increment, keep Unit 5 Forums flagged parked

---

## 6. Scope boundaries — explicitly NOT in this plan

- No backend service, Lambda, DynamoDB table, IaC template, or API contract change
- No mirror publisher, refresh script, scheduler, or S3/CloudFront template (DW-7 — outside application scope)
- No change to `AppLayout.tsx` nav gating or to Unit 11 Settings (both already shipped)
- No deployment. Operator action, and unnecessary here since no backend changes
- No caching or persistence of feed content (US-11.7)
- No two-level service-area taxonomy filter (deferred by the use case), though DW-5's labels leave the door open
- Unit 5 Forums untouched

## 7. Scope summary

**12 steps.** Roughly 11 new frontend files (7 source, 4 test), 2 modified (`App.tsx`, `singletons.tsx`), 2 config (`package.json`, `vite.config.ts`), 1 build file (`Makefile`), 1 infra doc, plus documentation and requirement updates. One new devDependency (`happy-dom`); no new runtime dependency. 5 stories move from mock to real; 2 already shipped.
