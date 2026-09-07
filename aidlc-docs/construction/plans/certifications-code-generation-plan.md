# Unit 6 — Certifications: Code Generation Plan

**Stage**: CONSTRUCTION → Code Generation (Part 1 — Planning)
**Unit**: Unit 6 — Certifications · **Stories**: US-5.1–5.10 (10)
**Single source of truth for Part 2 execution.** Inputs: approved functional design (D1–D11, BR set), NFR requirements (N1–N4), NFR design (J1–J5), infrastructure design (F-A–F-D).

## Unit context
- **Implements**: definitions CRUD + catalog, claims (submit/withdraw/list), credited-group verification, claim-addressed revoke, daily expiry job + scan watchdog, badges, 5 published events, MembershipChanged auto-reject, scan-verdict trust promotion.
- **Depends on**: Identity & Access (REST membership/led-group reads, MembershipChanged events), Foundation (scanned bucket, bus, Scheduler), ApiEdge (routes, SPA bucket), GuardDuty verdicts.
- **Consumed by**: member-profiles' deployed fan-out (`listClaims` projections), Contributions (CertificationApproved — still mock), Notifications/Analytics (later), SPA.
- **Owns**: `certifications-<stage>` table (+3 staged GSIs), `certifications/` S3 prefixes, `badges/` SPA-bucket prefix.
- **Fifth real service.** Wire status vocabulary: Pending/Approved/Rejected/Withdrawn/Revoked/Expired (UI shows Approved as "Verified").

---

## Phase A — Contracts (source of truth first)

- [x] **Step 1**: Rewrite `contracts/services/certifications/openapi.yaml` → **v2.0.0** per domain-entities.md contract-delta table: 13 ops (9 reshaped incl. removed `POST /certifications/{id}/revoke`; new `revokeClaim`, `listClaims`, `grantEvidenceUpload`, `grantBadgeUpload`, `evidenceUrl`), full schemas (Certification with description/category/points/expiryPeriodMonths/badgeImageUrl/active/held/heldExpiresAt/pendingClaim; Claim with evidence/notes/dateEarned/status enum/reasons/frozen points+expiresAt), `x-mock-collection` hints for the generator.
- [x] **Step 2**: Author 5 event schemas (single family file `certification-lifecycle.v1.json`, house convention) under `contracts/services/certifications/published-events/` (approved/rejected/revoked/expiring-soon/expired `.v1.json`, enveloped, payloads per business-logic-model §10).
- [x] **Step 3**: Edit `contracts/platform/permissions/role-permission-matrix.v1.json` — remove Administrator `browse certification-catalog` row (D7); version note in the file header comment.
- [x] **Step 4**: Extend `platform/fixtures/` (4 definitions, 5 claims covering Approved/Pending/Rejected/Withdrawn/PendingScan) certifications+claims fixtures to v2 shapes (statuses stay "Approved"-compatible, add dateEarned/evidence/category/points fields; one claim per interesting state incl. Withdrawn + PendingScan).
- [x] **Step 5**: Regenerate the certifications mock (13 ops; gate 13/13; api-edge regen verified no-op; all 12 services' gates still pass) from v2.0.0 (mock factory); run `gen_api_edge.py` check — expected **no-op** (all under `/certifications`); regenerate contract tests; **contract gate green on the regenerated mock before any real code**.

## Phase B — Backend (`services/certifications/src/`)

- [x] **Step 6**: `_conventions/` — copy the current superset (incl. ConflictError; authz/envelope/errors/idempotency/logger/validation) per the Events drift note.
- [x] **Step 7**: `models.py` — entities, status/scan enums, `new_id`/`now_iso`, serializers `owner_claim` / `public_claim` / `queue_claim`, `cert_status_wire↔label` NOT here (frontend concern), expiry arithmetic helpers (`compute_expires_at(anchor, months)`, BR-C6/V7 checks).
- [x] **Step 8**: `authz.py` + bundled `permission_matrix.json` (post-D7 copy) — OP_AUTHZ map for all 13 ops, Administrator boundary 403, fail-closed loader, ledGroupId resolution (JWT-first, IdentityClient fallback, deny on unresolvable).
- [x] **Step 9**: `repository.py` — single-table: definition items, claim items (+GSI1/2/3 sparse key maintenance on every transition — key removal ON the same conditional write), CLAIMSLOT conditional put/delete, FILEKEY pointers, idempotency store; queries: my-claims, pending-queue (+filters/countOnly), holder-lookup via slot collection, expiry window, scanwatch window; opaque whitelisted cursors; **no scans**; conditional transitions (validate+mutate in ONE write, returns prior state for 409 messages).
- [x] **Step 10**: `providers.py` — `EventPublisher` (5 types, batched ≤10, post-commit best-effort, `published[]`); `S3Broker` (presigned **POST** grants with content-length-range ≤ 5 MB + exact content-type + exact key (J1); per-request evidence GET ≤ 5 min; badge copy-to-SPA-bucket); `IdentityClient` (GET /groups mine + led-group fallback, 1.5 s timeout, 1 retry, fail-closed 503); `metrics` emitter (SweepRunOutcome, PendingScanAgeMinutes, EventPublishFailure, AuthzDenied).
- [x] **Step 11**: `definition_service.py` — create/edit/deactivate-reactivate (US-5.1/5.2/5.3), badge-upload grant + badgeImageStatus, catalog assembly with per-caller enrichment (2 queries, no N+1), includeInactive for leaders.
- [x] **Step 12**: `claim_service.py` — submit (US-5.4: membership via IdentityClient, CLAIMSLOT duplicate guard, dateEarned/BR-C5/C6 gates, evidence XOR + FILEKEY pointer write, scanStatus init), myClaims (US-5.5), withdraw (BR-W1), `listClaims` with the BR-P1 projection switch (memberId/certId/status/from/to/countOnly — member-profiles compatibility).
- [x] **Step 13**: `verification_service.py` — queue (US-5.7: scope, filters, countOnly, oldest-first), decide (US-5.6: BR-V3 reviewable gate, BR-V4 reason, BR-V5 no-self, approve freezes points+expiresAt w/ BR-V7 guard, transactional slot handling on reject), evidence-url minting (BR-P2).
- [x] **Step 14**: `revocation_service.py` — claim-addressed revoke (US-5.8/D9, BR-R1..R3, slot delete, event).
- [x] **Step 15**: `expiry_service.py` — daily sweep (US-5.1): EXPIRY window query, T-14 mark-before-emit notice, Approved→Expired conditional flip + event, continuation-bounded, `now` injected.
- [x] **Step 16**: `watchdog_service.py` — SCANWATCH window, max-age metric emit (N4).
- [x] **Step 17**: `consumers.py` — `membership_consumer` (BR-S1..S3, per-claim Rejected + system CertificationRejected events, idempotent) + `scan_consumer` (J5: verdict → evidence stamp | badge copy-then-Clean | quarantine handling incl. oversize delete; FILEKEY lookup; idempotent).
- [x] **Step 18**: `app.py` — 3-branch router (HTTP route table + OP_AUTHZ gate; EventBridge branch by source/detail-type; Scheduler branch by `job`); context wiring with constructor injection; generic error envelope.

## Phase C — Backend tests (`services/certifications/tests/`) — 3 mandatory suites + unit coverage

- [x] **Step 19**: `test_authz_matrix.py` — table-driven: every op × every role (Admin 403 on ALL incl. browse; Members-only submit; UGL scope + fail-closed unresolvable ledGroupId; owner-only 404-not-403).
- [x] **Step 20**: `test_lifecycle.py` — every legal + illegal transition (409s), freeze-at-approval (BR-V6), BR-V7 expired-at-approval, duplicate rule across all 6 states (slot presence), withdraw rules, revoke rules.
- [x] **Step 21**: `test_degrade_failclosed.py` — Identity down → submit 503 / reads 200; scan-verdict + membership idempotency (replay envelope id); publish failure never fails writes; sweep double-run concurrency (mark-before-emit, zero duplicates).
- [x] **Step 22**: `test_definitions.py`, `test_claims.py` (incl. BR-C5/C6 date edges, evidence XOR, listClaims projections + member-profiles param compatibility), `test_verifications.py` (queue order/filters/countOnly, scan gate), `test_revocation.py`, `test_expiry.py` (anchor fallback, T-14 exactly-once, window math), `test_watchdog.py`, `test_repository.py` (sparse-key maintenance on transitions, cursors, slot conditional writes), `test_uploads.py` (POST policy fields, key uniqueness BR-C7, 5 MB/type door), `test_consumers.py`, `test_events_published.py` (5 payloads vs schemas).
- [x] **Step 23**: Run full certifications pytest → green; run repo-wide `make test` → no regressions.

## Phase D — IaC

- [x] **Step 24**: `service-certifications-data.yaml` — add GSI1/2/3 definitions (deploy-time staging is 3 sequential updates — F-C; template carries all three, tool stages them).
- [x] **Step 25**: Generalize the GSI staging tool → `infra/tools/stage_gsis.py` (service-agnostic; supersedes stage_events_gsis.py usage for this unit) + wait_for_gsi reuse.
- [x] **Step 26**: `service-certifications-app.yaml` — rewrite per infrastructure-design.md (handler, env, prefix-scoped IAM ×2 buckets, execute-api grant, MembershipRule, prefix-filtered MalwareScanRule, 2 Scheduler schedules + role, 6 alarms, new SpaBucket/ApiBaseUrl/FileShareBucket params).
- [x] **Step 27**: Cross-unit edits — `service-settings-app.yaml` exclusion list (F-A); `service-events-app.yaml` scan-rule prefix filter (F-B); `infra/root-template.yaml` param wiring for certifications.
- [x] **Step 28**: cfn-lint + sam validate all touched templates → clean (pre-existing W8001 tolerance only).

## Phase E — Frontend (D11 full rebuild)

- [x] **Step 29**: `lib/certStatus.ts` (wire→label helper, D1) + `lib/apiClient.ts` additive helper for S3 presigned-POST multipart upload (no auth header, progress callback).
- [x] **Step 30**: Rebuild `features/CertificationsPage.tsx` as the role-aware shell (Member: Catalog|My Submissions; CL: Pending Verifications|Definitions; UGL: Verifications) with data-testid coverage.
- [x] **Step 31**: `features/certifications/CatalogGrid.tsx` + `CertCard` (mockup card layout, Held/Available, expiry countdown, points tag, Submit Claim gating).
- [x] **Step 32**: `ClaimModal.tsx` — real groups from Identity, dateEarned conditional-required, evidence URL XOR file (presigned-POST flow + progress), notes, join-a-group-first state, server 409/422 rendering; resubmit prefill mode.
- [x] **Step 33**: `MySubmissionsTable.tsx` — mockup columns, status badges ("Verified" label), withdraw confirm, resubmit, reason display, awaiting-scan / re-upload states.
- [x] **Step 34**: `VerificationQueueTable.tsx` + `RejectReasonModal.tsx` — filters (cert; group CL-only), oldest-first, evidence link/fresh-URL fetch, approve confirm + BR-V7 409 rendering, disabled awaiting-scan rows, mockup captions.
- [x] **Step 35**: `DefinitionsTable.tsx` + `DefinitionModal.tsx` — full field set incl. badge-image upload with scanning state, deactivate/reactivate confirms.
- [x] **Step 36**: `RevokeFlow.tsx` — member picker (GET /users) → approved certs → reason → claim-addressed revoke.
- [x] **Step 37**: `VerifiedBadgesCard.tsx` + `BadgeDetailModal.tsx` on ProfilePage/MemberDetailPage (replaces raw-certId pills); remove the DashboardPage hardcoded cert stat if still present.
- [x] **Step 38**: Nav pending-count pill (CL/UGL) via countOnly; bell-panel Option-2A count line.
- [x] **Step 39**: `tsc` + `npm run build` → clean.

## Phase F — Docs & bookkeeping

- [x] **Step 40**: `services/certifications/README.md` (service doc, house format) + `aidlc-docs/construction/certifications/code/code-summary.md` (what/where/decisions/defects-found).
- [x] **Step 41**: `service-mode.json` → certifications `complete` (post-gate); update unit story map checkboxes; final verification pass: pytest, make test, ruff, cfn-lint, contract gate 12/12, npm build — all green, recorded with real numbers.

## Story traceability
| Story | Steps |
|---|---|
| US-5.1 | 1,2,11,15,26,35 |
| US-5.2 | 1,11,35 |
| US-5.3 | 1,11,35 |
| US-5.4 | 1,10,12,17,26,31,32 |
| US-5.5 | 1,12,33 |
| US-5.6 | 1,13,34 |
| US-5.7 | 1,13,34,38 |
| US-5.8 | 1,14,36 |
| US-5.9 | 1,12,37 |
| US-5.10 | 1,11,31 |

**Not in scope** (recorded): deployment to AWS (user-directed, as with prior units); evidence-orphan S3 lifecycle rule (follow-up); Contributions' consumption of CertificationApproved (Unit 7).
