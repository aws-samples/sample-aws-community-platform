# What's New in AWS — Brainstorming (Q5, Q6, Q7 + a forced re-look at Q4)

**Created**: 2026-08-10
**Stage**: CONSTRUCTION — pre-stage scoping, round 2
**Input**: `whats-new-scope-questions.md` answers — Q1=A, Q2=A, Q3=D, Q4=A, Q8=A accepted; Q5/Q6/Q7 open

---

## Part 1 — Answers accepted (no further discussion needed)

| Q | Answer | Recorded decision |
|---|---|---|
| Q1 | A | Increment to **Unit 15 Frontend SPA**; artifacts under `aidlc-docs/construction/frontend-spa/whats-new/` |
| Q2 | A | **Unit 5 Forums parked** at NFR Requirements; resumes after What's New |
| Q3 | D | **Code Generation only** (Part 1 Planning → Part 2 Generation). No Functional Design / NFR / Infra Design stages |
| Q8 | A | Add frontend tests for parser + filter logic |

**Two notes on those:**

**Q3=D consequence.** Skipping Functional Design means there is no stage that would normally record requirement deviations and design decisions. Your Q5 and Q6 answers *are* design-level decisions (one is a requirement deviation). They will be captured as numbered decisions in the **Code Generation Part 1 plan** instead, and mirrored into `aidlc-state.md`. Flagging so it is a choice, not an accident.

**Q8=A is cheaper than I described — I was wrong.** I said "no test runner wired". Corrected: **Vitest 2.1.9 is already a devDependency and `npm test` → `vitest run` already exists** in `frontend/package.json`. There are simply **zero test files** (`npm test` currently exits "No test files found"). So Q8=A adds no dependency and no script — just the first test files in the repo. One real gap remains, covered in Q7 below: `DOMParser` is a browser API and Vitest defaults to a node environment, so a DOM environment (`jsdom` or `happy-dom`) has to be added as a devDependency and configured.

---

## Part 2 — What I measured on the live feeds

I fetched both candidate feeds rather than reasoning from memory. Commands were plain read-only `curl` with an `Origin` header set to the portal's CloudFront domain.

### The CORS verdict — this is the headline

| Feed | HTTP | `Access-Control-Allow-Origin` |
|---|---|---|
| `https://feeds.feedburner.com/AmazonWebServicesBlog` (your Q6 suggestion) | 200 | **absent** |
| `https://aws.amazon.com/about-aws/whats-new/recent/feed/` (official What's New) | 200 | **absent** |

**Neither feed is CORS-enabled.** Answering your Q6 question directly: **no, the FeedBurner URL cannot be used directly from the browser.** It will fail the same way the official feed does. A browser `fetch()` from the portal origin gets blocked before your code ever sees a response body — and note the failure surfaces to JavaScript as an opaque `TypeError: Failed to fetch` with no status code, indistinguishable from the site being down.

This collides with **Q4=A** ("build exactly to the requirement, client-side fetch only, let the operator provide a CORS-enabled mirror"). Q4=A is still a legitimate choice, but combined with the measurement above it means: **the feature ships and is permanently empty for every user until somebody stands up a mirror.** No AWS-published feed satisfies the precondition. That is why Q4 is back on the table as B1 below.

### The FeedBurner AWS Blog feed, structurally

Good news on format — it is a clean match for your Phase-1 field mapping:

- **RSS 2.0** (`<rss version="2.0">`), channel title "AWS News Blog"
- **20 items** (rolling window)
- Per item: `<title>`, `<link>`, `<pubDate>` (RFC-822, e.g. `Thu, 06 Aug 2026 22:58:00 +0000`), **multiple `<category>`**, `<guid>`, `<description>`, plus `<dc:creator>` and `<content:encoded>`
- **53 distinct categories** across just 20 items (~2.65 per item) — e.g. `Amazon EC2`, `AWS Lambda`, `Launch`, `News`, `Compute`, `Database`, `Artificial Intelligence`
- `<description>`: **plain text, 64–422 chars, median 303. Zero HTML tags in all 20 items** — your Q5 instinct is correct for this feed
- `<content:encoded>`: **HTML, 6,753–17,013 chars, median 10,660**, tags `a br code img li p pre span strong` — this is the full article body

So: **RSS 2.0 only is sufficient** (Q6 option A). No Atom parsing needed for either candidate feed.

Two things worth your judgement rather than mine:

1. **It's the wrong content type for the module's name.** This is the AWS **News Blog** — 20 recent long-form blog posts. Module 11 is "What's New in AWS", which in AWS's own vocabulary means the **product/feature announcement** feed (short launch notices, many per day). Both are RSS 2.0 with identical field shapes, so the parser doesn't care. But your users will get blog articles where the nav item promises product announcements.
2. **53 categories over 20 items** makes the US-11.4 category dropdown longer than the list it filters. It works, it just looks odd. Worth deciding whether to sort by frequency, or cap the list.

---

## Part 3 — Open decisions

### Brainstorm 1 (reopens Q4): how do we actually get feed bytes into the browser?

Given the measurement, here are the real options. I've put the one I'd recommend first, because I don't think it was visible when you answered Q4.

**Option A — CloudFront same-origin path on the existing portal distribution.** Add a second origin (`aws.amazon.com` or `feeds.feedburner.com` as a custom origin) plus a cache behavior on path pattern `/feed/*` to the distribution that already serves the SPA. The browser then fetches `https://<portal-domain>/feed/...`, which is **same-origin — CORS never enters the picture**.

Why this is attractive here: it is **pure infrastructure, zero application code**. No Lambda, no service, no persistence. US-11.7's "no server-side component" and "no caching" survive largely intact (set the cache policy TTL to 0 to honour fetch-on-every-load literally, or accept a small TTL as a deliberate deviation). It works for *any* upstream feed the Administrator configures — as long as it's the one we pin as an origin, which is the catch: CloudFront origins are static IaC, so a truly arbitrary admin-supplied URL is **not** supported by this option. It converts `whatsNewFeedUrl` from "any URL" into "a path on our own domain", which narrows US-11.1.

Cost: `SpaDistribution` lives inside `infra/tools/gen_api_edge.py` (the generator's static tail), so this is a generator edit + regenerate — the sanctioned path, not a forbidden hand-edit of `api-edge.yaml`. It also touches Unit 1 Platform & Delivery files and needs a redeploy of the api-edge stack.

**Option B — Backend proxy in the deployed Settings service.** `GET /settings/whats-new/feed` fetches server-side, returns XML or parsed JSON. Fully supports an arbitrary admin-supplied URL. Costs: contradicts "no server-side component" outright, reopens a deployed service, adds an SSRF surface that has to be handled properly (the Administrator supplies the URL — it needs scheme/host validation, no redirects to link-local, a timeout), and pulls this frontend-only increment into backend + IaC + contract territory, which is at odds with Q3=D.

**Option C — Strict Q4=A, unchanged.** Client-side fetch only. Ship correct-by-spec, permanently empty in dev, and document a CORS-enabled mirror as an operator prerequisite. Honest and cheap; delivers no working feature today.

**Option D — Operator-provided mirror, treated as a real deliverable.** Same as C, but we also write the runbook for standing up the mirror (S3 bucket with a CORS policy + a scheduled copy of the feed), so "operator prerequisite" is an executable instruction rather than a hand-wave. Still no working feature until it's run.

#### Question 1
Which approach for getting the feed to the browser?

A) CloudFront same-origin path on the existing distribution (accepting that the feed source becomes IaC-pinned, narrowing US-11.1's "any URL")

B) Backend proxy in the Settings service (accepting the requirement deviation, SSRF hardening, and that Q3=D expands to include backend + IaC)

C) Strict client-side only, permanently empty until an operator mirror exists

D) Client-side only **plus** a written operator runbook for standing up a CORS-enabled mirror

E) Other (please describe after [Answer]: tag below)

[Answer]:

---

### Brainstorm 2 (Q5): your answer was "Feed will use markup not HTML"

Your instinct is **confirmed for `<description>`** — zero HTML in all 20 items. But the answer leaves one thing undecided, and I want to separate three things that got bundled together.

**(a) What is the expanded "Details" view actually made of?** US-11.5 says clicking an item expands it inline to show "the full Details rendered from the RSS `<description>`". For this feed, description is a 303-character teaser. The summary is that same text truncated to ~150. So **expanding reveals roughly 150 more characters** — a technically-correct expand that users will find pointless. The only substantive body in the feed is `<content:encoded>` (median 10,660 chars), which **is** HTML.

**(b) "Markup" is ambiguous.** If you meant Markdown, note that neither feed emits Markdown — description is plain prose and `content:encoded` is HTML. `markdown-it` is already a dependency (from the Announcements pivot), so a Markdown path is available if you're anticipating a *different* feed that does emit it, but it would do nothing for either candidate feed. If you meant "plain text, so no sanitization worry", that's true today but see (c).

**(c) Sanitization should be unconditional regardless of what today's feed contains.** Even if description is plain text right now, it's third-party content from a source we don't control, the RSS spec explicitly permits HTML there, and the feed can change without notice. Rendering it as React text content escapes it for free; the moment anything reaches `dangerouslySetInnerHTML`, DOMPurify goes in front of it. `dompurify` is already a pinned dependency. I'd treat this as non-negotiable and not really a question — say so if you disagree.

#### Question 2
What should the expanded Details view render?

A) **Full `<description>` as plain text** — matches the use case's field-mapping table exactly and your "not HTML" answer. Expand reveals ~150 more chars than the summary. Thin, but spec-faithful and the safest possible rendering

B) **`<content:encoded>` as sanitized HTML** (DOMPurify, permissive allow-list; `<a>` forced to `target="_blank" rel="noopener noreferrer"`; `<img>` allowed) — a genuinely useful expand with the real article body. Deviates from the field-mapping table, which maps Details ← `<description>`

C) **`<content:encoded>` if present, else full `<description>`** — best-effort richness, sanitized either way; behaves well across differently-shaped feeds

D) **Full `<description>` as plain text, and drop the inline expand entirely** — make "Read full announcement on AWS ↗" the only route to depth, since the feed's own teaser is already nearly complete

E) Other (please describe after [Answer]: tag below)

[Answer]:

#### Question 3
Sanitization policy for any feed-provided content that reaches the DOM:

A) **Always sanitize / always escape**, regardless of what the current feed happens to contain — treat the feed as untrusted third-party input permanently (my recommendation)

B) Sanitize only on the `content:encoded` path; render description as React text and rely on React's own escaping (functionally similar, but leaves no explicit rule if someone later switches description to `dangerouslySetInnerHTML`)

C) Other (please describe after [Answer]: tag below)

[Answer]:

---

### Brainstorm 3 (Q6): which feed, and how configurable?

The parser is the same either way (both are RSS 2.0, same fields). What differs is content type and what we pin as the reference.

#### Question 4
Feed source decision:

A) **AWS News Blog** (`feeds.feedburner.com/AmazonWebServicesBlog`) — your suggestion; blog articles, has `content:encoded`, 20-item window

B) **Official What's New feed** (`aws.amazon.com/about-aws/whats-new/recent/feed/`) — product/feature announcements, matches what the module name promises

C) **Stay source-agnostic**: parser handles RSS 2.0 with optional `content:encoded`; ship one of the above as the seeded default in Settings and a captured sample as the test fixture. Keeps US-11.1's "Administrator sets the URL" meaningful — but only compatible with Brainstorm-1 options B/C/D, since option A pins the origin in IaC

D) Other (please describe after [Answer]: tag below)

[Answer]:

#### Question 5
The category dropdown will hold ~53 entries for a 20-item feed. How should it behave?

A) All categories, alphabetically — simplest, matches "populated dynamically from the feed"

B) All categories, sorted by frequency (most-used first), alphabetical within ties

C) Cap to the top N by frequency (e.g. 20) with the rest reachable via the search box

D) Other (please describe after [Answer]: tag below)

[Answer]: A *(answered in chat 2026-08-10)*

---

### Brainstorm 4 (Q7): implications of the two file layouts

You asked for the implications rather than picking. Here they are concretely.

**Current state**: `frontend/src/features/singletons.tsx` is 546 lines holding four unrelated exported pages (`ProfilePage`, `SettingsPage`, `FileSharingPage`, `WhatsNewPage`) behind 13 imports — `useApi`, `apiFetch`, `FormModal`, `Toggle`, `DataTable`, `VerifiedBadgesCard`, `TierBadgesCard`, `States`, `timezones`, `tiers`, `Avatar`, and a `Role` type.

**Option A — extract to `frontend/src/features/whats-new/`** (page + `feedParser.ts` + item component):

- The parser becomes a plain `.ts` module with **no React imports**, so a Vitest file can import it directly. That matters concretely for Q8=A: the alternative pulls React, `apiClient`, `DataTable` and friends into the test's module graph just to reach one pure function.
- Cost: one new folder, ~3–4 files, and a one-line import-path change wherever the route is registered.
- **Caveat that applies either way**: `DOMParser` is a browser API and Vitest runs in node by default, so this needs `jsdom` or `happy-dom` as a devDependency plus `test.environment` in `vite.config.ts`. Option A doesn't avoid that — it just keeps the rest of the app out of the test.
- Consistent with how Events was organised (`EventModal`, `EventManagePage`, `EventCalendarPage` all got their own files rather than growing a shared module).

**Option B — replace the mock internals in place inside `singletons.tsx`**:

- Smallest diff, no route changes, nothing moves.
- Grows an already-mixed 546-line module toward ~700+ with the parser, sanitization and filter logic in the same file as profile and file-sharing screens.
- Testing the parser means importing `singletons.tsx`, which evaluates every page component and `apiClient` at import time — so the test needs a DOM environment *and* likely module mocking, and stays sensitive to unrelated edits in that file. This is the main tension with Q8=A.

#### Question 6
File layout:

A) Extract to `frontend/src/features/whats-new/` — page, parser module, item component split out

B) Replace the mock internals in place in `singletons.tsx`

C) Other (please describe after [Answer]: tag below)

[Answer]: A *(user delegated the choice to the AI recommendation; answered in chat 2026-08-10)*

#### Question 7
DOM environment for the tests (needed because `DOMParser` is browser-only):

A) **`happy-dom`** — lighter and faster than jsdom, sufficient for `DOMParser` + `dompurify`

B) **`jsdom`** — heavier, but the most widely used and best-documented option

C) **Avoid a DOM environment entirely** — hand-write a small regex/string-based RSS reader so the parser is pure and testable in node (rejected recommendation: hand-rolled XML parsing mishandles CDATA, entities and namespaces, and `DOMParser` is free in the browser where this actually runs)

D) Other (please describe after [Answer]: tag below)

[Answer]: A *(happy-dom; answered in chat 2026-08-10)*

---

**7 questions.** Fill in each `[Answer]:` with a letter (add a description after the letter for "Other"). Tell me when you're done — I'll re-validate the full answer set for contradictions, then produce the Code Generation Part 1 plan for your approval.

---
---

# Round 3 — Mirror decision accepted + two corrections that change earlier answers

**Added**: 2026-08-10
**User decision**: "we will maintain our version of this official RSS and publish through a S3|cloudfront url. Create a sample first."

## Brainstorm 1 — RESOLVED

**Decision: self-maintained mirror of the official AWS feed, published to S3 + CloudFront with CORS enabled.** This is Brainstorm-1 option D promoted to an owned deliverable. Recorded as decision **DW-1**.

Why this is the better answer than the CloudFront same-origin path I put first:

| | Self-maintained S3 mirror (chosen) | CloudFront same-origin path |
|---|---|---|
| US-11.7 "client-side fetch, no server component" | **Intact** — browser fetches a static XML file | Intact |
| US-11.1 "Administrator sets the feed URL" | **Intact** — any CORS-enabled URL still works; the mirror is just the sensible default | **Narrowed** — origin pinned in IaC |
| Coupling to portal infrastructure | **None** — feed lives beside the portal, not inside it | Feed becomes part of the api-edge stack |
| Control over feed shape | **Full** — we can normalize before publishing (see Brainstorm 5) | None — proxies upstream bytes verbatim |
| Upstream outage | Last good copy keeps serving | Feed goes down with upstream |

The mirror also removes the class of problem that bit Events at deploy time: a `TypeError: Failed to fetch` with no status code. A same-origin static file either 200s or 404s.

**Sample created**: `infra/whats-new-feed/whats-new-sample.xml` — 9 items, valid RSS 2.0, verified to parse.

---

## Correction 1 — your Q5 answer does not hold for the official feed

I only measured the FeedBurner blog feed in round 2. Now that the official What's New feed is the source, I measured it too, and the result reverses the conclusion:

| | FeedBurner AWS News Blog | **Official What's New (the real source)** |
|---|---|---|
| Items | 20 | **100** |
| `<description>` content | plain text, **0/20 had HTML** | **HTML in 100/100** — `<p>` and `<a>` |
| `<description>` length | 64–422, median 303 | **782–4,099, median 1,676** |
| `<content:encoded>` | present, median 10,660 | **absent** |
| `<category>` | 3 separate elements, friendly names | **1 element, comma-joined machine taxonomy** |
| Other item fields | `dc:creator`, `guid` | `guid` (isPermaLink=false), `author` (always `aws@amazon.com`) |

So: **"Feed will use markup not HTML" was true of the blog feed but is false for the official feed.** Every one of the 100 items carries HTML in `<description>`. Sanitization is therefore **mandatory, not precautionary** — this is third-party HTML going into our DOM.

The upside: at a median of 1,676 characters the description is genuinely substantial, which dissolves the "expand reveals only 150 more characters" problem from round 2. **Brainstorm 2 Question 2 option A is now clearly the right answer** (Details = full `<description>`, sanitized), and option B/C are moot because the official feed has no `<content:encoded>`. I'm treating Question 2 as answered = **A, with mandatory sanitization**, unless you say otherwise. Question 3 (always sanitize) is likewise settled as **A** by the data.

---

## Correction 2 — the use case's category assumption is factually wrong

`usecases/11-whats-new-aws-feed.md` states categories are "a flat list (e.g., 'Amazon EC2', 'Compute', 'Storage')". Measured reality on the official feed:

- **One** `<category>` element per item, not several
- Its text is a comma-joined machine taxonomy, e.g.
  `marketing:marchitecture/compute,general:products/amazon-ec2`
- **8 of 100 items have no category at all**
- 77 distinct tokens in two families: `marketing:marchitecture/<service-area>` (compute, databases, analytics, artificial-intelligence, storage, security-identity-and-compliance, networking-and-content-delivery, developer-tools, migration, applications) and `general:products/<product-slug>` (amazon-ec2, amazon-bedrock, aws-glue, amazon-msk, aws-govcloud-us)

Rendered raw, a US-11.4 category dropdown would offer the user `marketing:marchitecture/compute` as a filter label. That is not shippable.

Worth noting: those two families are exactly the **service-area / service split** the use case defers to "a later phase". The upstream data already supports two-level filtering; only the labels are unusable.

---

## Brainstorm 5 (new) — normalize at mirror time, or pass through verbatim?

Owning the mirror creates a choice that did not exist before: **where does the taxonomy get cleaned up?** Doing it in the publisher means the SPA parser stays a plain, spec-shaped RSS reader and US-11.4 works exactly as written. Doing it in the SPA means the mirror is a byte-faithful copy and all the mapping logic ships to the browser.

The sample I created takes the **normalized** approach so you can see it concretely. Upstream item 1 becomes:

```xml
<!-- upstream: one element, machine taxonomy -->
<category>marketing:marchitecture/compute,general:products/amazon-ec2</category>

<!-- mirror: separate elements, human labels -->
<category>Compute</category>
<category>Amazon EC2</category>
```

Note the sample's item 8 shows why splitting must happen in the publisher and not by comma-splitting in the browser: one of its real category labels is `Security, Identity & Compliance`, which **contains a comma**. A client-side comma split would shred it into two bogus facets.

### Question 8
Where is the category taxonomy normalized?

A) **In the mirror publisher** — it emits multiple `<category>` elements with human labels (as the sample does). SPA parser stays a plain RSS reader; US-11.4 works as written; the slug-to-label mapping is a publisher concern and can be corrected without redeploying the SPA

B) **In the SPA** — mirror is a byte-faithful copy; the browser splits the taxonomy and maps slugs to labels. Mirror stays trivially auditable against upstream, but the mapping ships in the bundle and every correction is a frontend redeploy

C) **Neither — show raw tokens** and accept `marketing:marchitecture/compute` as a filter label (rejected recommendation: unusable UI)

D) Other (please describe after [Answer]: tag below)

[Answer]: A *(answered in chat 2026-08-10)*

### Question 9
Unmapped slugs will appear (AWS adds services faster than any mapping is maintained). What should the publisher do with a slug it has no label for?

A) **Derive a label mechanically** — strip the prefix, replace hyphens with spaces, title-case it (`general:products/aws-glue` → `AWS Glue`), with a small override table only for names that don't survive that (e.g. `amazon-msk`, `aws-govcloud-us`)

B) **Emit the raw slug** as the label so it's visibly wrong and gets reported

C) **Drop unmapped categories** — cleaner UI, silently loses filter coverage

D) Other (please describe after [Answer]: tag below)

[Answer]: B *(emit the raw slug so it is visibly wrong and gets reported; answered in chat 2026-08-10)*

### Question 10
How does the mirror get refreshed? (This is an operations concern, not SPA code — it does not change US-11.7.)

A) **Scheduled Lambda + EventBridge Scheduler** in the portal's own infrastructure — fetch upstream, normalize, write to the S3 bucket, on a schedule (e.g. hourly). Automated and self-healing; adds a small Lambda to the estate

B) **A script an operator runs** (`infra/whats-new-feed/refresh.py`) publishing manually or via cron outside the portal. Zero added AWS resources; refresh depends on somebody running it

C) **Manual for now** — publish the sample, wire the SPA against it, defer automation to the Operations phase

D) Other (please describe after [Answer]: tag below)

[Answer]: C — *"will sit outside of this application scope"* *(answered in chat 2026-08-10)*

### Question 11
Item 9 in the sample has no `<pubDate>`. US-11.3 sorts by pubDate descending — what happens to undated items?

A) **Sort last**, still visible and searchable (what the sample's verification assumed)

B) **Drop them** — if it has no date it doesn't belong in a chronological feed

C) **Treat as newest** — surface them at the top so the gap is noticed

D) Other (please describe after [Answer]: tag below)

[Answer]: A *(sort last, still visible and searchable; answered in chat 2026-08-10)*

---

## Still open from round 2

Questions **5** (category dropdown ordering — now much less pressing, the normalized sample yields 17 clean labels for 9 items rather than 53 for 20), **6** (file layout), and **7** (DOM test environment: happy-dom vs jsdom) remain unanswered. Question **1** is resolved by DW-1; questions **2**, **3** and **4** are resolved by the corrections above (**4 = B**, the official What's New feed, since that is what we are mirroring).
