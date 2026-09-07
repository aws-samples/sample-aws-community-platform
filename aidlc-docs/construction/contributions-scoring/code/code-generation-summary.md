# Unit 7 — Contributions & Scoring: Code Generation Summary

**Stage**: CONSTRUCTION → Code Generation (Part 2). Greenfield generation against the approved plan (`../../plans/contributions-scoring-code-generation-plan.md`).

## Created — backend (`services/contributions-scoring/src/`)
- `models.py`, `repository.py`, `scoring_service.py`, `split.py`, `framework_service.py`, `submission_service.py`, `adjustment_service.py`, `read_service.py`, `providers.py`, `consumers.py`, `app.py`, `permission_matrix.json`
- `_conventions/errors.py` — added `ConflictError` (409) to this service's copy
- `seed_framework.json` — default framework (DL16)
- `tests/` — `conftest.py`, `test_scoring_core.py`, `test_awards_and_rollups.py`, `test_submissions_adjustments.py`

## Created — contracts
- `contracts/services/contributions-scoring/openapi.yaml` → **v2.0.0**
- `contracts/services/contributions-scoring/published-events/points-events.v1.json` (`PointsAwarded`, `PointsAdjusted`, `ContributionRejected`; no `TierAchieved`)
- `contracts/services/forums/published-events/forum-scoring-events.v1.json` (dormant `ForumPostCreated`/`ReplyAccepted`)

## Modified — bundled cross-unit (coordinated big-bang, Infra Q5)
- `contracts/services/certifications/published-events/certification-lifecycle.v1.json` — `CertificationApproved.submittedAt` (additive, DL13)
- `contracts/services/events/published-events/event-completed.v1.json` — new `EventCompleted` (DL4/DL8)

## Modified — infra
- `infra/services/service-contributions-scoring-data.yaml` — main table + 3 GSIs at creation (GSI1 leaderboard sort key = `total`) + Streams + PITR + idempotency table
- `infra/services/service-contributions-scoring-app.yaml` — 5 functions (reserved concurrency AwardWorker=25, Consumer=10), SQS + DLQs, EventBridge rule, nightly Scheduler, per-function IAM, alarms (DLQ, rollup iterator-age, errors)

## Modified — frontend
- `frontend/src/features/ContributionsPage.tsx` — rebuilt on v2.0.0: My Contributions (quarter/group selectors, lifetime, pillars, days-remaining), leaderboard (pillar filter), My Submissions (real activities, withdraw/resubmit), Framework (activities + event points + tiers), Summary (tier distribution + **updated-daily disclaimer** + CSV export), Approvals (reject reason) + Adjust (quarter picker).

## Modified — root
- `service-mode.json` → `contributions-scoring: complete`

## Verification (this stage — full run is Build & Test)
- `python3 -m py_compile` on all `src` modules — OK
- `ruff check services/contributions-scoring/src/` — clean
- `python3 -m pytest tests/ -q` — **22 passed**
- `cfn-lint` on both templates — clean
- `npm run build` (frontend) — clean

## Story-coverage gap closure (post-approval hardening)
- ✅ **US-6.1** deactivate/delete now auto-rejects the activity's pending submissions + notifies (`framework_service._auto_reject_activity`, `repo.list_pending_for_activity`).
- ✅ **US-6.14** aggregated export implemented (`read_service.export` — one row per member per group, name/email/tier/total + 4 pillars, deactivated excluded; `ExportRow`/`ExportList` in the contract).
- ✅ **Sweep group registry** wired (`repo.register_group`/`list_registered_groups`, populated from `MemberJoinedGroup`; sweep defaults to it) — unblocks US-6.13/6.14 tier distribution + top-contributors + community export.
- ✅ Fixed a submit bug: activity resolved by **id OR name** (`find_activity`) so UI and API both work.
- Verified: ruff clean, **27 pytest passed**.

## Events↔Unit 7 integration — DONE (2026-08-07, DL22)
- ✅ Unit 7 consumes Events' **existing** per-earner events directly (`AttendanceRecorded`/`EventDelivered`/`EventOrganized`) via an EventBridge rule → AwardQueue → AwardWorker (bounded 25). **Supersedes the DL4 read-back — eliminates the fan-out service-auth gap.**
- ✅ Events additive edit: `eventDate` stamped on the three award events (`attendance_service.py`, `designation_service.py`); Events' own pre-existing test failures are the parallel Announcements/Forums branch's, not this change.
- ✅ Attendance Member-filtered via Unit 7's identity-projection role (known leaders excluded); delivery/organize already Member-filtered by Events.
- ✅ Certs `submittedAt` shipped (DL13); Certs 67 tests still pass.
- ✅ Contract: `event-awards.v1.json` gains `eventDate`; app-stack EventBridge rules split (award→AwardQueue, others→ConsumerQueue); `EventsClient` removed (no read-back). Verified: 27 pytest, ruff clean, cfn-lint clean.

## Follow-ups (noted, not blocking)
- ✅ **Install-time seed wiring DONE** (DL16) — `platform/seed/seed_handler.py` now embeds the default framework (activities/event-points/tiers, in sync with `seed_framework.json`) and writes it via `_seed_contributions_framework()` with idempotent conditional puts (a redeploy never overwrites a CL edit). Wired end-to-end: `infra/seed.yaml` (`ContributionsTableName` param + `HasContributionsTable` condition + `CONTRIBUTIONS_TABLE` env + guarded `dynamodb:PutItem`) ← `infra/root-template.yaml` (`ContributionsScoringData.Outputs.TableName`). 3 new seed tests; cfn-lint clean. Auto-award has point values day one.
- ✅ **US-6.12 profile tier-badge shelf DONE** — `TierBadgesCard.tsx` (historical per-group/per-quarter badges from `/contributions/tiers-earned`) wired into ProfilePage + MemberDetailPage. All Unit-7 frontend files typecheck clean. (NOTE: full `npm run build` is transiently red due to `features/pages.tsx` being mid-edit in the parallel Forums/Announcements session — not a Unit-7 file.)
- **Events/Certs producer code edits** — bundled into the coordinated redeploy.
- Optional DL21 polish — relocating member views onto the Home dashboard.
