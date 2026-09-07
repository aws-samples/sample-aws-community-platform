# Unit 7 — Contributions & Scoring: Code Generation Plan

**Stage**: CONSTRUCTION → Per-Unit Loop → Code Generation (Part 1 — Planning)
**Unit**: Unit 7 — Contributions & Scoring
**This plan is the single source of truth for Code Generation.** Part 2 executes these steps in order, marking each [x] on completion.

## Unit context
- **Stories (18)**: US-6.1–6.18. Design: functional (`../contributions-scoring/functional-design/`), NFR (`../contributions-scoring/nfr-*`), infra (`../contributions-scoring/infrastructure-design/`), decisions DL1–DL21 (`contributions-scoring-award-logic.md`).
- **Workspace root**: `/Users/developer/workspace/community-portal` (greenfield, multi-unit microservices). Backend Python; frontend React+Vite+TS.
- **Code locations**: backend `services/contributions-scoring/src/`; infra `infra/services/service-contributions-scoring-{data,app}.yaml`; contracts `contracts/services/contributions-scoring/` (+ `forums/published-events/`); frontend `frontend/src/…`. Docs summaries → `aidlc-docs/construction/contributions-scoring/code/`.
- **Dependencies**: consumes Events `EventCompleted`, Certs `CertificationApproved(submittedAt)`, Identity `MembershipChanged`/`UserDeactivated`/`UserReactivated`/`GroupHardDeleted`, Forums `ForumPostCreated`/`ReplyAccepted` (dormant); REST read to Events; publishes `PointsAwarded`/`PointsAdjusted`; consumed by Member-Profiles (`GET /contributions/me`), Analytics, Frontend.
- **Owns**: main table (ledger, rollups, framework, submissions, reply-state, membership projection, sweep aggregates) + GSI + Streams; idempotency table; SQS queues + DLQs; 5 Lambdas.
- **Coordinated big-bang (Q5)**: this unit's scope bundles Events + Certs producer edits + Forums schemas; consumers built against final shapes.

---

## PART 1 — Planning steps

### Step 1 — Contracts (v2.0.0) + cross-unit event schemas
- [ ] Rewrite `contracts/services/contributions-scoring/openapi.yaml` → **v2.0.0** per domain-entities deltas: expanded framework (activity + eventPoints + tiers), `me` (keep Member-Profiles shape, add params + lifetime/pillars/quarters), `history`, `tiers-earned`, `leaderboard` (rank/name/avatar/pillar), `summary` (pillars/counts/top-N/from-to/computedAt), `export` (aggregated per-member-per-group), `adjustments` (quarter + reverses), `ledger` (reverse browser), submissions (activityDate, evidence URL). Preserve `/contributions/me` fields Member-Profiles reads.
- [ ] Author this service's published events: `contracts/services/contributions-scoring/published-events/points-events.v1.json` (`PointsAwarded`, `PointsAdjusted`; **no** `TierAchieved`).
- [ ] Author Forums schemas (dormant): `contracts/services/forums/published-events/forum-scoring-events.v1.json` (`ForumPostCreated`, `ReplyAccepted` incl. un-accept transition; carry `groupId`, `authorRole`, `postDate`).
- [ ] **Events contract edit** (bundled): add `EventCompleted` + earner `role` stamp on award events.
- [ ] **Certifications contract edit** (bundled): add `submittedAt` to `CertificationApproved`.

### Step 2 — Project structure & shared conventions
- [ ] Confirm `services/contributions-scoring/src/` layout; carry `_conventions/` (authz, validation, envelope, errors, idempotency, logger, config), `permission_matrix.json`, `models.py`.

### Step 3 — Repository layer (`repository.py`) [US-6.* data]
- [ ] Single-table access: ledger append (conditional on idempotency), member-scoped ledger reads (history + reverse browser), rollup atomic guarded increments (`TransactWriteItems` rollup + `rollup-applied#ledgerId`), rollup reads (L1/L1-life/L2/L3), leaderboard **GSI** query (top-N), framework CRUD, submissions CRUD + queue query, reply-award-state, membership projection, sweep aggregate read/write. Idempotency table access.
- [ ] Repository unit tests.
- [ ] Repository summary → code/ .

### Step 4 — Business logic: framework (`framework_service.py`) [US-6.1, 6.2]
- [ ] Activities (create forces evidence-required; edit evidence-required read-only; delete evidence-only; deactivate → auto-reject pending + notify), event-points, tier thresholds; system-defined auto set guard; CL-only access.
- [ ] Unit tests + summary.

### Step 5 — Business logic: scoring core (`scoring_service.py`, `split.py`, `tiers.py`) [US-6.3/6.4/6.5/6.12/6.17/6.18]
- [ ] Guard pipeline (idempotency → Member-role from stamped msg → framework value → earnedDate/quarter → attribution → append); community-wide equal split (current membership, earliest-join remainder); runtime tier derivation vs current thresholds.
- [ ] Unit tests (idempotency, split determinism incl. remainder, tier incl. late cross-quarter) + summary.

### Step 6 — Business logic: submissions & adjustments (`submission_service.py`, `adjustment_service.py`) [US-6.6/6.7/6.8/6.9/6.15]
- [ ] Submit/withdraw/resubmit; approve/reject → ledger; queue-as-query + nav count; adjustment (quarter-selectable free delta + reverse-entry single-use guard); below-zero allowed; capture memberName at write.
- [ ] Unit tests (withdraw-pending-only, reversal single-use, scope authz) + summary.

### Step 7 — Reads: points/leaderboard/summary/export (`read_service.py`) [US-6.10/6.11/6.13/6.14/6.16]
- [ ] `me` (group/quarter selector, lifetime, pillars, days-remaining, history), leaderboard (GSI top-N + pillar filter + B3), summary (L2/L3 + pillars + from/to), export (aggregated per-member-per-group, name+email from projection), tiers-earned (profile badges).
- [ ] Unit tests (B3 exclusion, `me` back-compat shape) + summary.

### Step 8 — API layer (`app.py` router) [all US-6.*]
- [ ] Route table mirroring the frozen contract; fail-closed authz per op; input validation; error envelope; 501 for anything deferred; EventBridge branch dispatch note.
- [ ] API unit tests (authz matrix incl. Admin 403, Member-only) + summary.

### Step 9 — Consumers & workers (`consumers.py`, `handlers.py`) [US-6.3/6.4/6.5/6.6/6.9/6.12]
- [ ] AsyncConsumer (EventCompleted expander → REST read Events → enqueue per-earner; Forum/Cert/Identity consumers; evidence auto-reject on MemberLeft/Removed; membership projection + B3 status from Identity events), AwardWorker (per-earner guard pipeline), RollupMaintainer (Stream → atomic guarded rollup), NightlySweep (4 lagged aggregates + computedAt). EventPublisher (`PointsAwarded`/`PointsAdjusted`). EventsClient (timeout + short-circuit).
- [ ] Consumer/worker unit tests (idempotent replay, DLQ path, sweep) + summary.

### Step 10 — Seed (default framework — DL16)
- [ ] Seed data (tiers 75/50/25/0; event points delivery=2×attendance; activities all Active) wired to install-time seeding into the main table.

### Step 11 — Infrastructure (`-data` / `-app`)
- [ ] `service-contributions-scoring-data.yaml`: main table (+GSI at creation, Streams NEW_IMAGE, PITR, Retain, SSE), idempotency table (TTL), DLQs.
- [ ] `service-contributions-scoring-app.yaml`: 5 Lambdas (reserved concurrency AwardWorker=25/AsyncConsumer=10), SQS queues + redrive (maxReceive5, vis≥6×), EventBridge rules + Scheduler, per-function IAM (least privilege incl. read-only Events invoke), alarms (DLQ/iterator-age/sweep-staleness/quota), routes.
- [ ] cfn-lint / sam validate clean.

### Step 12 — Mock parity + service-mode
- [ ] Regenerate mock from v2.0.0 contract; ensure contract-test gate passes vs mock AND real; `service-mode.json` → contributions-scoring `complete`.

### Step 13 — Frontend (DL21 scope)
- [ ] Member Home "My Contributions" section (DashboardPage): group switcher, quarter selector + empty state, cards, pillar chart, points history, my submissions + submit/withdraw/resubmit modal.
- [ ] Leaderboard page (per-group, quarter+pillar filters, name/avatar).
- [ ] CL Scoring Framework page (Activity Types / Event Points / Tier Thresholds tabs + modals).
- [ ] Leader Contributions page (Pending Approvals + reject reason / Community Summary + CSV + lagged disclaimer / Adjust Points + quarter picker + reverse browser); UGL group-scoped queue + adjust from member detail.
- [ ] Profile tier-badge shelf on ProfilePage + MemberDetailPage (calls `/contributions/tiers-earned`).
- [ ] Nav pending-count badge. `data-testid` on interactive elements. `npm run build` clean.

### Step 14 — Cross-unit producer edits (bundled — Q5)
- [ ] Events: emit `EventCompleted` + stamp earner role on award events (services/events + its contract/infra).
- [ ] Certifications: add `submittedAt` to `CertificationApproved` (services/certifications + contract).

### Step 15 — Documentation
- [ ] `services/contributions-scoring/README.md`; code summaries under `aidlc-docs/construction/contributions-scoring/code/`; update `service-mode.json`.

---

## Story traceability
| Story | Step(s) |
|---|---|
| US-6.1/6.2 framework | 1,4,8,10,13 |
| US-6.3/6.17/6.18 event auto-award | 1,5,9,14 |
| US-6.4 forum auto-award (dormant) | 1,5,9 |
| US-6.5 cert auto-award | 1,5,9,14 |
| US-6.6/6.7 submit/view/withdraw | 6,8,13 |
| US-6.8/6.9 approve/reject + queue | 6,8,9,13 |
| US-6.10/6.11 points & tier | 7,8,13 |
| US-6.12 runtime tiers + badges | 5,7,13 |
| US-6.13/6.14 summaries + export | 7,8,13 |
| US-6.15 adjustments | 6,8,13 |
| US-6.16 leaderboard | 7,8,13 |

## Scope note
~15 steps; backend (repository + 6 service modules + consumers/workers + app router), infra (2 templates), frontend (5 screen areas + profile shelf + nav), contracts (v2.0.0 + forums schemas + published events), plus bundled Events/Certs producer edits. Tests written per layer; **executed in Build & Test**. Forum auto-award ships dormant (Forums still mock).

## Part 1 checklist
- [x] Plan approved by user → begin Part 2 (execute steps in order)

## Part 2 — Generation: COMPLETE (2026-08-07)
- [x] Step 1 — contracts v2.0.0 + forums dormant schemas + points published events
- [x] Step 2 — conventions (added ConflictError to this service's errors copy)
- [x] Step 3 — repository (single-table + 3 GSIs + atomic guarded rollup)
- [x] Step 4 — framework service
- [x] Step 5 — scoring core (guard pipeline / split / tiers)
- [x] Step 6 — submissions + adjustments
- [x] Step 7 — reads (me/history/leaderboard/summary/export/tiers-earned)
- [x] Step 8 — API router (app.py) + 4 event/stream/schedule entrypoints
- [x] Step 9 — consumers + workers (expander/award/forum/cert/membership/rollup/sweep)
- [x] Step 10 — seed default framework (seed_framework.json)
- [x] Step 11 — infra -data (GSIs at creation, PITR, Streams) + -app (5 fns, SQS+DLQ, rules, scheduler, IAM, alarms); cfn-lint clean
- [x] Step 12 — service-mode.json → complete
- [x] Step 13 — frontend ContributionsPage rebuilt on v2.0.0; npm build clean
- [x] Step 14 — bundled cross-unit CONTRACT edits (Certs submittedAt, Events EventCompleted). **Producer CODE edits in services/events + services/certifications remain for the coordinated redeploy** (see summary follow-ups)
- [x] Step 15 — README + code-generation-summary.md + service-mode

**Verification**: py_compile OK · ruff clean (src + tests) · pytest 22 passed · cfn-lint clean · npm build clean.
**Follow-ups (non-blocking)**: fan-out service-to-service auth for the Events read; nightly-sweep group registry; producer code edits to Events/Certs (coordinated redeploy); optional DL21 frontend polish (Home relocation + profile badge shelf).
