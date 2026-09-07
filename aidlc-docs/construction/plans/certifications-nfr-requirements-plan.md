# Unit 6 — Certifications: NFR Requirements Plan

**Stage**: CONSTRUCTION → NFR Requirements (per-unit)
**Unit**: Unit 6 — Certifications
**Status**: AWAITING ANSWERS — please fill every `[Answer]:` tag, then say "done".

## Assessment checklist
- [x] Analyze functional design artifacts (D1–D11, BR set, entities, contract deltas)
- [x] Classify workload criticality vs Units 2/3/4 precedent
- [x] Inherit platform NFR baseline (Unit 1) + reuse Unit 4 upload/scan NFR precedent
- [x] Identify certifications-specific NFR deltas (below + questions)
- [x] Collect answers; resolve ambiguities (N1=A 99.5%; N2=5 MB per file custom; N3=B static badge serving; N4=A 30-min PendingScan alarm — all unambiguous)
- [x] Generate `nfr-requirements.md` + `tech-stack-decisions.md`
- [ ] Approval gate

## Pre-resolved (from precedent + approved functional design — no questions needed)
- **Criticality: STANDARD** (Events precedent): nothing blocks at runtime on Certifications — login/events/forums proceed; member-profiles degrades its cert sections gracefully; Contributions consumes events asynchronously. But like Events (and unlike Units 3/11), **claim data is NOT reconstructible by replay** — claims are original member-submitted records, so PITR is mandatory, not prudent.
- **Tech stack fixed by platform decisions**: Python Lambda, single service table (DynamoDB on-demand), EventBridge, single-Lambda router with consumer + scheduler branches, no new runtime dependencies expected (dates/uploads/events all stdlib + boto3 — no PDF/image processing libraries; files are stored and served, never parsed).
- **Evidence/badge scanning**: GuardDuty Malware Protection reused (D5/C2=A); scan-gated visibility 3-state, Events J3 precedent.
- **Uploads are authenticated** (member/CL JWT) — unlike Events' public token endpoint, no unauthenticated write surface; platform API GW throttling suffices, no per-token abuse controls needed.
- **No provisioned concurrency** (not on the auth-critical interactive path — Unit 3 precedent).
- **Mandatory test suites** (Unit 4 NFR-EV-MAINT precedent): (1) authorization matrix incl. the two counter-intuitive rules — Admin blanket 403 on ALL ops and Members-only submission; (2) lifecycle transitions — every illegal transition → 409; (3) degrade/fail-closed path — Identity unreachable → submission 503 (fail closed, BR-C3) while reads stay 200; scan-verdict consumer idempotency.
- **Daily expiry sweep**: EventBridge Scheduler, once daily; sparse-index bounded; mark-before-emit (BR-X2). Exact hour is an ops constant (default 06:00 UTC, before US/EU waking hours), not a requirement.

## Questions

## Question N1 — Availability target
STANDARD criticality suggests the 99.5% tier used for Member Profiles and Events (Identity runs 99.9%).

A) **99.5%** monthly for the certifications API. (Recommended — consistent with STANDARD peers.)

B) 99.9% (CRITICAL tier — implies tighter alarm/response posture for a service nothing blocks on).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question N2 — Evidence file size cap
US-5.4 evidence is an image or PDF of a certificate. Events allows 500 MB for event materials (decks/recordings), which is far beyond any certificate scan. An oversized cap invites junk storage and slow scans; presigned-POST policy can enforce the cap at the storage door.

A) **10 MB per evidence file** (certificate PDFs/photos are typically < 2 MB), one file per claim; badge images capped at **2 MB**. (Recommended)

B) 25 MB evidence / 5 MB badge (roomier for high-res scans).

C) Other (please describe after [Answer]: tag below)

[Answer]: 5 MB per file

## Question N3 — Badge image serving path
Badge images render on every catalog card and profile badge — the highest-frequency image read in the portal. Evidence files are rare, private, per-request presigned GETs (settled). Badges are different: visible to all authenticated users, rendered in lists.

A) **Short-lived presigned GET URLs embedded in catalog/badge API responses** (consistent with everything else in this repo; a catalog of ~20 badges = 20 URL signings per response, pure CPU, no extra calls; browser caches per URL lifetime). (Recommended — no new infrastructure; revisit only if profiling shows render jank.)

B) Copy Clean badge images to the SPA's public CloudFront bucket and serve as static assets (fastest render + real browser caching, but a new cross-stack write path and cache-invalidation story on image edit).

C) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question N4 — Stuck-scan operational threshold
A claim with an uploaded file is not reviewable until the GuardDuty verdict lands (usually seconds to ~minutes). If the verdict never arrives (misconfigured plan, consumer bug — the class of silent failure this repo keeps finding in deployment), claims pile up invisibly in "awaiting scan" and members blame the leaders.

A) **Alarm when any claim sits in PendingScan > 30 minutes** (metric emitted by the sweep/consumer; visible operational signal for an otherwise-silent failure). (Recommended)

B) No alarm; rely on member complaints / manual observation.

C) Other (please describe after [Answer]: tag below)

[Answer]: A
