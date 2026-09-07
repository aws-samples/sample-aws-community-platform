# What's New in AWS — Scope Clarification Questions

**Created**: 2026-08-10
**Stage**: CONSTRUCTION — pre-stage scoping for Module 11 (What's New in AWS Feed)
**Why this file exists**: "What's New in AWS" is **not a unit in the unit catalog**. Before entering the per-unit loop I need you to settle how it is scoped, because part of it is already shipped and one requirement carries a live-blocking risk.

---

## What already exists (verified in code, not assumed)

Module 11's 7 stories are split across two existing units by `unit-of-work-story-map.md`:

| Story | Owner unit | Status in code |
|---|---|---|
| US-11.1 Configure feed URL + toggle | Unit 11 Settings | **DONE + DEPLOYED** — `whatsNewEnabled` / `whatsNewFeedUrl` in `services/settings/src/models.py` + validated in `settings_service.py`; "🆕 What's New in AWS Feed" card in `frontend/src/features/admin.tsx` |
| US-11.6 Disabled behavior | Unit 11 Settings + SPA | **DONE** — nav item hidden portal-wide in `components/AppLayout.tsx`; disabled + "Not configured yet" states present in `WhatsNewPage` |
| US-11.2 Nav item | Unit 15 Frontend SPA | **DONE** — nav gating in `AppLayout.tsx`, excluded for Administrator |
| US-11.3 Detail page | Unit 15 Frontend SPA | **MOCK ONLY** |
| US-11.4 Search + category filter | Unit 15 Frontend SPA | **MOCK ONLY** |
| US-11.5 Inline expand + "Read on AWS" | Unit 15 Frontend SPA | **NOT BUILT** |
| US-11.7 Client-side fetch/parse/errors | Unit 15 Frontend SPA | **NOT BUILT** |

The real gap is `WhatsNewPage` in `frontend/src/features/singletons.tsx`. It renders a **hardcoded 4-item `WN_FEED` array** (`{title, category, date}`). Specifically missing:

- No `fetch` of the configured `whatsNewFeedUrl` — the URL is read only to decide the "Not configured yet" state
- No XML parsing (`DOMParser`), no `<pubDate>` reverse-chronological sort
- No summary derived from `<description>` (first paragraph, ~150 chars) — mock has no description at all
- No inline expand showing full `<description>` HTML, and **no sanitization** (the use case's own security note requires it before DOM injection)
- No `"Read full announcement on AWS ↗"` link to `<item><link>` in a new tab — the current link is `href="#"` with `preventDefault()`
- Search matches title + category only, not summary/details (US-11.4 requires all three)
- Categories are static from the sample, not populated dynamically from the feed's `<category>` tags
- No fetch/parse failure state (US-11.7)

**Note**: `dompurify` is already a pinned frontend dependency (added for Announcements), so client-side sanitization needs no new package.

---

## Blocking risk you should decide on (Question 4)

US-11.7 mandates a **browser-side** fetch of the feed URL, and the use case puts the CORS-enabled feed server **out of scope** ("Module 11 consumes it only"). In practice the public AWS What's New RSS endpoint does **not** send `Access-Control-Allow-Origin`, so a browser fetch from the portal origin fails at the CORS preflight. If we build exactly to the requirement, the feature ships correct-by-spec and **empty in the live portal** unless your operator stands up a CORS-enabled mirror. This is the same class of silent-feature-failure as the Events fan-out timeout found only at deploy time — worth deciding now, not at deploy.

---

## Question 1
"What's New in AWS" is not a unit in the catalog. How should this work be scoped?

A) As an increment to **Unit 15 Frontend SPA** (its story map already owns US-11.2–11.5, 11.7); artifacts go under `aidlc-docs/construction/frontend-spa/whats-new/`

B) As a **new standalone unit** ("Unit 16 — What's New Feed") added to `unit-of-work.md`, with its own construction folder and full per-unit stage treatment

C) As a **change request** against the already-complete Unit 11 Settings + Unit 15 SPA, logged like the other post-completion change requests (File Sharing rework, Directory pagination, etc.)

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
Unit 5 Forums is currently **NFR Requirements IN PROGRESS** (Functional Design approved 2026-08-08). What happens to it?

A) **Park Forums** at its current point and switch to What's New now; Forums resumes from NFR Requirements afterwards (same treatment as the parked Notifications unit)

B) Finish Forums' remaining stages first, then start What's New

C) Run both in parallel — What's New is frontend-only and touches no Forums file

D) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3
Which construction stages should execute? This is a **frontend-only** feature: no new service, no DynamoDB table, no Lambda, no IaC change, no contract change (settings config already ships).

A) **Functional Design → Code Generation** only (skip NFR Requirements / NFR Design / Infrastructure Design as not-applicable — no backend, no infrastructure)

B) **Functional Design → NFR Requirements → Code Generation** (skip NFR Design + Infrastructure Design) — NFR Requirements kept solely to formalize the XSS-sanitization and degrade-path rules

C) All five stages, accepting that NFR Design and Infrastructure Design will mostly record "no change"

D) **Code Generation only** — the use case + stories are detailed enough to implement directly

E) Other (please describe after [Answer]: tag below)

[Answer]: D

## Question 4
How do we handle the CORS problem described above?

A) **Build exactly to the requirement** — client-side fetch only. Ship it, document that a CORS-enabled feed mirror is an operator prerequisite, and let the page show its graceful error state until one exists

B) **Client-side first, with a documented fallback** — same as A, but the error state explicitly tells the Administrator the feed URL is unreachable/not CORS-enabled, so the failure is self-diagnosing rather than looking like an empty feed

C) **Deviate: add a thin backend proxy** in the already-deployed Settings service (e.g. `GET /settings/whats-new/feed` fetching server-side and returning parsed JSON). Removes the CORS dependency entirely, but contradicts "no server-side component" in US-11.7 and reopens a deployed service — a recorded requirement deviation

D) **Deviate with caching** — backend proxy as in C plus a short server-side cache, contradicting both "no server-side component" and "no caching"

E) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5
US-11.5 says the `<description>` HTML is "rendered as-is", while the same use case's security note says the design phase **must** address sanitization. These conflict. How do we resolve it?

A) **Sanitize with DOMPurify using a permissive allow-list** — keep formatting tags, headings, lists, and links (`<a href>` forced to `target="_blank" rel="noopener noreferrer"`), strip scripts/iframes/event handlers/inline styles. Closest thing to "as-is" that is safe

B) **Sanitize aggressively** — text plus links only; drop all other markup

C) **Render as-is with no sanitization**, exactly as US-11.5's literal wording says (rejected recommendation: this is a stored-XSS vector from a third-party source and would be the first unsanitized HTML injection in the portal — Announcements already set the sanitize-on-render precedent)

D) Other (please describe after [Answer]: tag below)

[Answer]: Feed will use markup not HTML

## Question 6
Which feed formats must the parser accept?

A) **RSS 2.0 only** — `<item>` / `<title>` / `<description>` / `<pubDate>` / `<category>` / `<link>`, exactly the field mapping table in the use case

B) **RSS 2.0 and Atom 1.0** — also handle `<entry>` / `<summary>` or `<content>` / `<updated>` / `<category term>` / `<link href>`; the use case says "RSS/Atom" in the config text but only maps RSS fields

C) Other (please describe after [Answer]: tag below)

[Answer]: Can this directly be used ? - https://feeds.feedburner.com/AmazonWebServicesBlog

## Question 7
`WhatsNewPage` currently lives in the shared `frontend/src/features/singletons.tsx` grab-bag. Where should the real implementation go?

A) **Extract to its own feature module** — `frontend/src/features/whats-new/` with the page, a feed-parser module, and the item component split out (parser is testable in isolation)

B) **Keep it in `singletons.tsx`**, just replace the mock internals in place — smallest diff

C) Other (please describe after [Answer]: tag below)

[Answer]: What is the implecation for both ?

## Question 8
The frontend currently has no test runner wired (backend uses pytest; frontend is verified by `tsc` + `npm run build` only). The feed parser is the first genuinely unit-testable frontend logic in this project. What do you want?

A) **Add Vitest** for the parser and filter logic (malformed XML, empty feed, missing fields, sort order, sanitization) — first frontend test suite in the repo, run in single-shot mode

B) **No frontend tests** — stay consistent with the existing project convention; verify by `tsc` + `npm run build` + manual check against a sample feed fixture

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

**Please fill in each `[Answer]:` tag with a letter choice** (add a description after the letter if you pick the "Other" option). Tell me when you're done and I'll validate the answers for contradictions before starting the first stage.
