# Unit 6 — Certifications: NFR Design Plan

**Stage**: CONSTRUCTION → NFR Design (per-unit)
**Inputs**: approved `nfr-requirements/` (N1–N4), approved `functional-design/` (D1–D11, BR set), Units 2/3/4/11 precedent patterns.

## Checklist
- [x] Analyze NFR requirements (all NFR-CT-* rules)
- [x] Evaluate ALL 5 mandatory categories (below)
- [x] Questions assessment: **no open user questions** — every category resolves from approved artifacts or repo precedent; 5 judgement calls flagged for gate review instead (Unit 4 precedent)
- [x] Generate `nfr-design-patterns.md`
- [x] Generate `logical-components.md`
- [ ] Approval gate

## Category evaluation (Step 3 justification)
| Category | Evaluated | Outcome |
|---|---|---|
| Resilience patterns | Yes | Fully determined: conditional-write state machine (FD), mark-before-emit (BR-X2), idempotent consumers, fail-closed Identity call (NFR-CT-REL-1), post-commit publishing (BR-E1), self-healing sweep (NFR-CT-AVAIL-3). No user decision adds information. |
| Scalability patterns | Yes | Determined by NFR-CT-PERF-3/SCALE-1..3 (no-scan rule + sizing envelope). Index design is a technical consequence — J2/J3 flagged. |
| Performance patterns | Yes | Targets fixed in NFR requirements; badge static-serving already user-decided (N3=B); catalog enrichment shape follows from entity model. |
| Security patterns | Yes | AuthZ layering, privacy projections, scan gating, no-SVG, 5 MB door enforcement all fixed by FD/NFR; the enforcement *mechanism* is J1. |
| Logical components | Yes | House single-Lambda + services + repository + providers shape (Units 2/3/4/11); component list derived, no alternatives worth a question. |

## Judgement calls flagged for gate review (not questions — reversible at review)
- **J1** Presigned **POST** (not the house presigned PUT) for uploads, because POST policies enforce `content-length-range` ≤ 5 MB and exact content-type **at the storage door** (N2 is a requirement here; Events' 500 MB was advisory so PUT sufficed there).
- **J2** The pending-verification queue index is a **single-partition sparse index** (`PENDING` / `submittedAt`): the pending set is transient and small (hundreds), UGL/CL scoping filters a bounded read. Revisit only if pending volume approaches 10k.
- **J3** ONE shared sparse "sweep" GSI hosts **both** the expiry window (`EXPIRY`/`expiresAt`) and the scan watchdog (`SCANWATCH`/`uploadedAt`) as different partition values of the same index attributes — halves the GSI count the deployed zero-GSI table must stage through (Events F2 lesson: one GSI per UpdateTable, poll for ACTIVE).
- **J4** **Two Scheduler schedules** sharing the service Lambda (daily expiry sweep; 15-min scan watchdog powering the 30-min PendingScan alarm, N4) — a stuck scan emits nothing by itself, so something must look for it; 15-min resolution is the coarsest that honors a 30-min alarm.
- **J5** The **scan-verdict consumer** performs the badge copy-to-public-bucket and the oversize-delete — no separate pipeline/Lambda; it is the single point where "file became trustworthy" is known.
