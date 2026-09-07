# Contributions & Scoring (Unit 7)

Real Python service. Points/tiers tracked **per group, per quarter**, all derived
from an **append-only ledger** (system of record). Rollups are a Stream-maintained
cache; **tiers are never stored** — derived on read from a rollup total vs the
current thresholds.

## Modules (`src/`)
| Module | Responsibility |
|---|---|
| `app.py` | 5 Lambda entrypoints: `api_handler`, `consumer_handler`, `award_worker_handler`, `rollup_handler`, `sweep_handler` (NFR Q1=A). |
| `models.py` | ledger/framework/submission shapes, quarter math, tier derivation, serializers. |
| `repository.py` | single-table DynamoDB access; atomic guarded rollup increment (Q2=A′); leaderboard GSI (sort key = `total`). |
| `scoring_service.py` | auto-award guard pipeline (attendance/delivery/organize/forum/cert). |
| `split.py` | community-wide equal-distribution split (BR-S2). |
| `framework_service.py` | scoring framework config + value lookups (BR-F*). |
| `submission_service.py` | evidence lifecycle + approval queue (BR-E*). |
| `adjustment_service.py` | quarter-selectable adjustment + single-use reversal (DL20). |
| `read_service.py` | my-points, leaderboard, summary, export, tiers-earned. |
| `consumers.py` | expander, award worker, forum/cert/membership consumers, rollup maintainer, nightly sweep. |
| `providers.py` | EventPublisher, EventsClient (fan-out read), Metrics. |

## Key decisions (DL1–DL21, `aidlc-docs/.../contributions-scoring-award-logic.md`)
- Staged fan-out: one `EventCompleted` → expander reads Events → per-earner SQS jobs → parallel award workers; **the user's click never waits** (DL3/DL4).
- Exactly-once rollup: guard + increments in one `TransactWriteItems` (DL15/Q2=A′).
- Nightly sweep for tier distributions + active-contributor count + community top-contributors — the **only** lagged metrics; carry `computedAt` for the UI disclaimer (DL14).
- Forum: post=1; **accepted reply=2, reversible** on un-accept (DL17). Dormant until Forums is real (DL10).
- Manual adjustment: quarter-selectable free delta + reverse-entry convenience, single-use (DL20).
- Tier-achievement notifications **removed** (DL19).
- Evidence is **link-only** in v1 (`evidenceFileKey` reserved; Infra Q1=B).

## Coordinated big-bang (Infra Q5)
This unit bundles additive producer edits, redeployed with all units together:
- Events → `EventCompleted` + earner role stamp.
- Certifications → `CertificationApproved.submittedAt`.
- Forums → `ForumPostCreated`/`ReplyAccepted` schemas (dormant).

## Tests
`tests/` — split determinism, tier derivation, quarter math, award idempotency +
exactly-once rollup, forum toggle, submission lifecycle, adjustment + single-use
reversal, authz scoping. Run: `python3 -m pytest tests/ -q`.
