# What's New in AWS — Code Generation Summary

**Unit**: Unit 15 Frontend SPA — What's New increment (Module 11)
**Completed**: 2026-08-10
**Plan**: `aidlc-docs/construction/plans/whats-new-code-generation-plan.md` (12 steps, all complete)
**Stages executed**: Code Generation only (Q3=D — no Functional Design / NFR / Infrastructure Design)

---

## What changed

Replaced a mock with a real client-side RSS feed reader. `WhatsNewPage` previously rendered a hardcoded 4-item array (`{title, category, date}`) inside the shared `features/singletons.tsx` and never fetched anything — no XML parsing, no sort, no summary/expand, no sanitization, no error handling, and a `href="#"` link that did nothing.

### Created — `frontend/src/features/whats-new/`

| File | Purpose |
|---|---|
| `types.ts` | `FeedItem`, `FeedError`, `FeedFilter`. Documents that `detailsHtml` is unsanitized and must pass the sanitizer |
| `fetchFeed.ts` | Plain `fetch` with `credentials: "omit"`, 10s `AbortController` timeout, network/HTTP failures distinguished |
| `feedParser.ts` | RSS 2.0 parse via `DOMParser`; sort; summary derivation; `parsePubDate`; `splitCategoryText` |
| `filter.ts` | `collectCategories` (alphabetical, blanks excluded) + `filterItems` (title + summary + details) |
| `sanitize.ts` | Single DOMPurify policy; allow-list; forces `target="_blank" rel="noopener noreferrer"` |
| `FeedItemRow.tsx` | Collapsible row; sanitizes lazily on expand and memoizes |
| `WhatsNewPage.tsx` | Page: settings gate, fetch-on-mount, search/filter controls, four distinct outcome states |
| `index.ts` | Public surface of the feature module |
| `__fixtures__/hostile-feed.xml` | Adversarial fixture — 7 injection vectors + one benign-formatting control |
| `__fixtures__/loadFixture.ts` | Fixture loader that resolves the repo root by walking up from cwd |

### Created — elsewhere

- `infra/whats-new-feed/whats-new-sample.xml` — 9-item reference mirror feed, doubles as the parser fixture
- `infra/whats-new-feed/README.md` — the feed contract for the out-of-scope mirror maintainer

### Test files (4, 64 tests — first frontend suite in the repo)

| File | Tests | Covers |
|---|---|---|
| `feedParser.test.ts` | 24 | Canonical sample: item count, sort order, undated-last, CDATA vs escaped, ids, category facets, entity decoding, summary truncation. Plus `splitCategoryText` / `parsePubDate` / `buildSummary` units |
| `feedParser.malformed.test.ts` | 10 | Empty, malformed, non-RSS, HTML-error-page, empty channel, missing fields, guid fallback, duplicate categories, bad date |
| `sanitize.test.ts` | 12 | script / inline handlers / `javascript:` href / iframe-object-embed / style / SVG-script all neutralized; benign formatting and links preserved; `target`+`rel` forced |
| `filter.test.ts` | 18 | Facet ordering, search across three fields incl. details-only matches, exact category matching, combined filters, sort preservation |

### Modified

- `frontend/src/App.tsx` — import `WhatsNewPage` from `./features/whats-new`; route `/whats-new` unchanged
- `frontend/src/features/singletons.tsx` — mock `WhatsNewPage` + `WN_FEED` removed (546 → 490 lines); other three pages untouched; no imports became unused
- `frontend/vite.config.ts` — added `test.environment: "jsdom"` + include globs
- `frontend/package.json` — added `jsdom@25.0.1` (exact) as a devDependency
- `Makefile` — `make test` now runs the frontend suite after the Python suites
- `aidlc-docs/construction/frontend-spa/story-verification.md` — US-11.3/11.4/11.5/11.7 mock → real

### Not touched, deliberately

No backend service, DynamoDB table, Lambda, IaC template, API contract, or deployment. No change to `AppLayout.tsx` nav gating or the Settings service — both already shipped and correct. No mirror publisher or refresh automation (DW-7, outside application scope). Unit 5 Forums remains parked.

---

## Decisions

| ID | Decision |
|---|---|
| DW-1 | Feed served from a self-maintained CORS-enabled mirror of the official AWS feed on S3 + CloudFront |
| DW-2 | Details = full `<description>`, sanitized. No `<content:encoded>` path (the official feed has none) |
| DW-3 | Feed content sanitized unconditionally |
| DW-4 | RSS 2.0 only; Atom rejected with a clear error |
| DW-5 | Category taxonomy normalized by the mirror publisher into separate `<category>` elements with human labels |
| DW-6 | Publisher emits the raw slug when it has no label — visibly wrong beats silently dropped |
| DW-7 | Mirror creation/refresh outside application scope; this repo ships the contract + reference sample only |
| DW-8 | Undated items sort last, remain visible and searchable |
| DW-9 | Category filter options alphabetical |
| DW-10 | Extracted to its own feature module |
| **DW-11 (revised)** | **`jsdom`, not `happy-dom`** — see below |
| DW-12 | Pattern-gated defensive taxonomy split in the parser |
| DW-13 | Feed fetch uses plain `fetch` with credentials omitted, never `apiFetch` |
| DW-14 | Feed contract documented for the out-of-scope maintainer |
| DW-15 | Single canonical sample read by tests; no duplicated fixture |

### DW-11 revised during generation — happy-dom was insufficient

`happy-dom` was chosen on my recommendation as the lighter option. It does **not implement `DOMParser` for `"text/xml"`**: it silently returns an HTML document whose `documentElement` is `<HTML>`, never produces a `<parsererror>` node, and accepts malformed XML without complaint. Consequences were concrete — RSS-vs-Atom detection and every malformed-feed test were untestable, and five tests failed at module load because the parser correctly rejected what happy-dom handed it.

Verified `jsdom@25.0.1` behaves properly before switching: `documentElement` is `rss`, malformed input yields `parsererror`, and Atom (`feed`) and HTML (`html`) documents are correctly rejected. Rationale is recorded in `vite.config.ts` so the choice is not silently reverted later.

### Two implementation details worth knowing

**The DW-12 pattern gate is load-bearing.** `splitCategoryText` splits on commas only when *every* comma-separated part matches `^[a-z0-9-]+:[a-z0-9-]+/[a-z0-9._-]+$`. Without that gate the legitimate label `Security, Identity & Compliance` — which appears in the real feed — would be shredded into two bogus facets. Both directions are asserted in tests.

**Fixture loading could not use `import.meta.url`.** Under jsdom, Vitest rewrites `import.meta.url` to a non-`file:` scheme, so `readFileSync(new URL(...))` throws `The URL must be of scheme file`. `__fixtures__/loadFixture.ts` resolves the repo root by walking up from `process.cwd()` until the canonical sample is visible, which works whether tests run from `frontend/` (`npm test`) or the repo root (`make test`).

---

## Requirement deviations

| # | Requirement | Deviation |
|---|---|---|
| DV-1 | US-11.5: `<description>` "rendered as-is" | Rendered **sanitized**. The use case's own security note requires it, and HTML was measured in 100/100 official-feed descriptions |
| DV-2 | Use case: categories are "a flat list (e.g. 'Amazon EC2', 'Compute', 'Storage')" | **Factually wrong about upstream** — one `<category>` element holding a comma-joined machine taxonomy; 8/100 items have none. The described shape is produced by the mirror (DW-5), not upstream |
| DV-3 | US-11.7: fetched from "the configured CORS-enabled URL" | Behaviour unchanged, but no AWS-published feed sends `Access-Control-Allow-Origin` (measured), so the URL is a self-maintained mirror |

---

## Verification

| Gate | Result |
|---|---|
| `npm test` (frontend) | **64 passed**, 4 files |
| `make test` (repo-wide) | **exit 0** — platform + 8 service suites + frontend, no regressions |
| `npx tsc -b` | clean |
| `npm run build` | clean — 604.41 kB / 188.21 kB gzip |
| Bundle delta | **+18.4 kB** vs a clean `HEAD` baseline build (586.02 kB). Confirmed no test-only code leaked: no `jsdom`, `saxes`, `node:fs` or fixture-loader strings in the bundle |
| Sample feed | Parses as valid RSS 2.0; sort, facets, entity decoding and both description encodings verified |

**Not verified**: no live browser journey against a real deployed mirror — no CORS-enabled mirror exists yet (DW-7 puts it outside this scope), so the fetch path has been exercised only against fixtures and unit tests. The first real-mirror load is the outstanding risk, and the error states were written specifically so that a CORS failure names itself instead of looking like an empty feed.

## Follow-ups

1. **Stand up the mirror** per `infra/whats-new-feed/README.md`, then set the URL in Administrator → Settings and confirm a live load. Until then the page shows its "could not be reached" state.
2. **Replace the sample's placeholder content** with mirrored upstream content before serving it to users — the current item text is authored for this repo, not real AWS announcements.
3. **Two-level category filter** (service area vs service) remains deferred by the use case. Upstream's two token families already support it and DW-5's labels leave the door open.
4. `WhatsNewPage` and `AppLayout` each call `useApi("/settings")`, so the settings object is fetched twice on this route. Harmless, and left alone to keep the diff focused.
