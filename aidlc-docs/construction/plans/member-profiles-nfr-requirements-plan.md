# NFR Requirements Plan — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Member Profiles & Directory
Inherits platform-wide NFRs (`aidlc-docs/construction/platform-and-delivery/nfr-requirements/`). This plan records deltas specific to Member Profiles, following the same resolved-from-context approach used for Unit 2 Identity & Access (no blocking open questions — the platform baseline + Unit 2's precedent + this unit's functional design already answer the standard NFR categories).

## Steps
- [x] 1. Analyze functional design (business-logic-model.md, business-rules.md, domain-entities.md — event-sourced cache, read-time cross-service fan-out, search delegation)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (resolved from context below — no blocking open questions)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (N/A — no open questions)
- [x] 6. Generate NFR requirements artifacts (nfr-requirements.md, tech-stack-decisions.md)
- [x] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update state

## Questions analysis → resolved from existing artifacts (no blocking questions)

| # | Area | Resolution source | Decision |
|---|---|---|---|
| Q1 | Workload criticality | BR-9 (per-call degrade, no cross-service transaction); this unit is read-heavy, not on the auth path | **Classified STANDARD, not CRITICAL.** Unlike Identity & Access (auth gates the whole portal), Member Profiles' unavailability degrades the directory/profile pages but doesn't block login, events, forums, or contributions. A profile-record lag (event consumer down) is tolerable for minutes; directory search degrading to keyword fallback is an explicit designed behavior (BR-6b), not a failure. |
| Q2 | Availability & DR | Platform baseline (Backup & Restore, single-region multi-AZ) | **Inherited as-is.** DynamoDB PITR + on-demand backups on the profile table (BR retention — profiles are never hard-deleted, BR-8). No unit-specific deviation; target 99.5% (slightly below Identity's 99.9% given STANDARD criticality). |
| Q3 | Performance — read-time fan-out latency | business-logic-model.md (`getOwnProfile`/`getMember` fan out to 4 services; `memberActivity` fans out to 4 services with date-range) | **This is the unit's defining NFR risk.** Each fan-out call needs an aggressive timeout (target ≤300ms per downstream call) so a single slow dependency doesn't blow the overall response budget. p95 target for `getOwnProfile`/`getMember` **< 600ms** (higher than Identity's 400ms reads, to account for the fan-out); `browseDirectory` (no fan-out, just DynamoDB + optional Search) **< 400ms**; `memberActivity` (leader-only, heavier fan-out + date filtering) **< 1000ms**. All fan-out calls run in parallel (not sequential) to bound total latency to the slowest single call, not the sum. |
| Q4 | Scalability — directory scans | domain-entities.md (E1 notes no GSI planned initially; scan+filter at expected scale) | **Flagging for Infrastructure Design, not blocking here.** DynamoDB on-demand (platform default) handles write scale fine. Directory browse/search at scan+filter scale is acceptable for the stated Phase-1 community size (per requirements, most communities are in the hundreds-to-low-thousands range, matching the mockup's "2,418 members" sample); if `EnableSemanticSearch` is on, most search load goes to OpenSearch anyway (D3), reducing pressure on the DynamoDB scan path. A role/status GSI is recommended at Infrastructure Design if p95 on `browseDirectory` without `q` exceeds target under load testing. |
| Q5 | Security — data sensitivity | domain-entities.md E1 (bio, skills, avatar, city/country — all self-disclosed, non-sensitive PII); business-rules.md BR-4 (Administrator excluded from profile views) | **Same baseline tier as Identity, no elevation.** Fields are self-disclosed community-profile data (not credentials, not financial/health data). Standard encryption-at-rest/in-transit + fail-closed authZ (BR-4/5/13) suffices; no additional compliance regime. The Administrator-exclusion rule (BR-4) is itself a data-minimization control — Admins never see contribution/activity data by design. |
| Q6 | Reliability — event consumer lag | business-logic-model.md (profile record built entirely from Identity's events) | **Idempotent, at-least-once consumption is mandatory** (same idempotency-table pattern as Identity & Access) since the profile record is a derived cache with no independent recovery path other than replaying Identity's event history. A stuck/lagging consumer means directory/profile data goes stale (not wrong) — monitored via a consumer-lag metric + alarm, not a correctness bug. |
| Q7 | Tech stack | Platform inherited (Python 3.12, Lambda Powertools, boto3, DynamoDB on-demand, EventBridge, SAM) + Unit 2 precedent | **No new stack additions beyond platform baseline** — this is the first unit with no auth/credential/OTP surface, so it needs none of Identity & Access's Cognito/Secrets Manager/SES-specific dependencies. New dependency: an internal REST client helper for the 4-way fan-out (built on `boto3`'s `requests`-free pattern — using `urllib3`/`http.client` already vendored with the Lambda runtime, avoiding a new pinned dependency) with per-call timeout + circuit-breaker-lite (skip-on-recent-failure) logic. |
| Q8 | Maintainability | Platform CI baseline (contract-test gate, bandit, cfn-lint, dep-scan/SBOM) | **Inherited as-is.** Additional test focus: contract tests must assert the fan-out degrade behavior (mock a downstream 5xx/timeout and assert 200 with the affected section empty, not a 5xx bubbling up) — this is this unit's most novel failure mode relative to Identity & Access. |

**Design decisions above are flagged for user review at the stage gate — override any and I will revise.**
