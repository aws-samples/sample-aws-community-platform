# NFR Requirements — Unit 3: Member Profiles & Directory

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Member Profiles & Directory
Platform-wide NFRs (Unit 1 `nfr-requirements.md`) are **inherited**. This document records member-profiles-specific requirements and deltas. Companion: `tech-stack-decisions.md`. Plan: `../../plans/member-profiles-nfr-requirements-plan.md`.

## Workload criticality (RESILIENCY-01)
- **Criticality: STANDARD** (not CRITICAL, unlike Identity & Access). Unavailability degrades the directory/profile pages but does not block login, events, forums, contributions, or certifications — those services have no runtime dependency on Member Profiles. A profile-record consumer lag (Identity's events not yet processed) makes profile/directory data stale, not wrong, and not blocking.
- **Upstream deps**: Identity & Access (events: `UserProvisioned`/`UserRoleChanged`/`UserDeactivated`/`UserReactivated`/`MemberJoinedGroup`/`MemberLeftGroup`/`MemberRemoved`), Contributions & Scoring / Events / Forums / Certifications (sync REST read-time fan-out), Search (conditional, semantic query + indexing), AI Gateway (conditional, indirectly via Search).
- **Downstream consumers**: Search (via `MemberProfileUpserted`); Frontend SPA (all profile/directory screens).

## Availability & recovery (RESILIENCY-02/08 — inherited, standard tier)
- **NFR-MP-AVAIL-1**: Single-region, multi-AZ on managed services (Lambda, DynamoDB, EventBridge). Target **99.5%** for this unit's API (below Identity's 99.9%, consistent with STANDARD criticality).
- **NFR-MP-AVAIL-2**: DR = **Backup & Restore** (RTO/RPO hours), same as platform baseline. DynamoDB PITR + on-demand backups on the profile table.
- **NFR-MP-AVAIL-3**: Loss of the profile-extension table is **recoverable by replay** — since it is a derived cache (no independent source of truth for identity/role/group data), a full or partial table loss can, in principle, be rebuilt by replaying Identity & Access's historical events (subject to EventBridge/archive retention) plus prompting members to re-save profile-only fields. This is a materially lower-severity failure mode than losing Identity's own table.

## Performance
- **NFR-MP-PERF-1**: p95 **< 600 ms** for `getOwnProfile`/`getMember` (higher than Identity's 400ms reads, to account for the read-time fan-out to Contributions/Events/Forums/Certifications). p95 **< 400 ms** for `browseDirectory` (no fan-out — DynamoDB query/scan + optional Search delegation). p95 **< 1000 ms** for `memberActivity` (leader-only, heavier multi-service fan-out + date-range filtering — acceptable given its lower call frequency and non-interactive-critical-path usage).
- **NFR-MP-PERF-2**: All fan-out calls within a single request run **in parallel**, not sequentially, so total added latency is bounded by the slowest single downstream call, not their sum.
- **NFR-MP-PERF-3**: Each downstream fan-out call has an aggressive per-call timeout (target ≤ 300 ms) — a slow or unresponsive dependency must degrade that section (BR-9) well within the unit's own p95 budget, not consume it entirely.
- **NFR-MP-PERF-4**: `browseDirectory` is not a candidate for provisioned concurrency (not on an interactive auth-critical path); standard on-demand Lambda scaling suffices.

## Scalability
- **NFR-MP-SCALE-1**: DynamoDB **on-demand**, consistent with platform default. `browseDirectory`'s attribute-filtered scan is acceptable at the community sizes described in requirements (hundreds to low thousands of members, per the mockup's "2,418 members" sample scale); flagged for Infrastructure Design to add a role/status GSI if load testing shows p95 regression on the no-`q` path.
- **NFR-MP-SCALE-2**: When `EnableSemanticSearch` is on (D3), most search-query load is offloaded to OpenSearch via the Search service, further reducing pressure on the DynamoDB scan path for `q`-bearing requests.
- **NFR-MP-SCALE-3**: Event consumption (6 Identity events) must keep pace with Identity's write volume; consumer concurrency scales with EventBridge/Lambda defaults — no special ceiling needed (this unit is not a bottleneck risk the way Cognito/SES rate limits are for Identity).

## Security (Security Baseline — same tier as Identity, no elevation)
- **NFR-MP-SEC-1 (SECURITY-08)**: Fail-closed in-service authZ on every handler from the permission matrix; explicit 403 for Administrator on `getMember`/`memberActivity` (BR-4) and for out-of-scope UGL/Member callers on `memberActivity` (BR-13) — enforced in-service, never relying on the frontend to hide the action.
- **NFR-MP-SEC-2 (SECURITY-05)**: Validate all inputs (city/country/professionalRole/bio/skills as free text — reject HTML/script; `awsProject` boolean; `avatar` URL format; query params `q`/`role`/`groupId`/`certId`/`limit`/`cursor`/`from`/`to`). Body size caps on profile updates (bio/skills length limits).
- **NFR-MP-SEC-3 (SECURITY-06)**: Per-Lambda execution role scoped to: this service's DynamoDB tables (profile + idempotency), its EventBridge bus (PutEvents for `MemberProfileUpserted`, subscription to Identity's events), and read-only invoke permission on the API Gateway routes of Contributions/Events/Forums/Certifications (for the read-time fan-out) — no wildcards, no write access to any other service's data.
- **NFR-MP-SEC-4 (SECURITY-01)**: Profile table encrypted at rest (AWS-managed KMS, platform default); TLS 1.2+ to all AWS APIs and to the cross-service REST fan-out calls (same-account API Gateway, already TLS-terminated).
- **NFR-MP-SEC-5 (SECURITY-15)**: Fan-out failures (BR-9) must be caught and logged individually, never surfaced as raw exceptions or stack traces in the response — the platform's generic error shape applies only to the primary request path; degraded sections are simply omitted/empty, not error objects.
- **NFR-MP-SEC-6 (SECURITY-14)**: Alert on sustained event-consumer lag (profile data going stale beyond a defined threshold, e.g. 15 minutes) and on elevated fan-out failure rates per downstream service (signals a dependency outage worth surfacing operationally, even though it degrades gracefully from the caller's perspective).

## Reliability / Resiliency (Resiliency Baseline)
- **NFR-MP-REL-1 (RESILIENCY-10)**: Explicit per-call timeouts on every downstream fan-out call (Contributions/Events/Forums/Certifications/Search) and on Identity event consumption; graceful degradation is the designed behavior (BR-9), not an edge case — contract tests must assert it (see NFR-MP-MAINT-1).
- **NFR-MP-REL-2 (RESILIENCY-06)**: Health check endpoint (shallow) + deep check verifying DynamoDB reachability (this unit has no Cognito/SES/Secrets Manager dependency to deep-check, unlike Identity & Access).
- **NFR-MP-REL-3**: Event consumption is idempotent (dedup by `eventId` in the idempotency table, same pattern as Identity & Access) — safe to redeliver/replay without corrupting the profile-extension record.
- **NFR-MP-REL-4 (RESILIENCY-12)**: DynamoDB PITR + on-demand backups on the profile table; profiles never hard-deleted (BR-8), so no destructive-delete risk to guard against beyond standard backup hygiene.
- **NFR-MP-REL-5 (RESILIENCY-05/07)**: Metrics + alarms — fan-out failure rate per downstream service, fan-out p95/p99 latency per downstream service, event-consumer lag, `browseDirectory`/`getMember`/`memberActivity` error rate and p95. X-Ray tracing across API → Lambda → downstream fan-out calls → (Search/OpenSearch when applicable).

## Maintainability
- **NFR-MP-MAINT-1**: Contract-test gate (Schemathesis + pytest), same as Identity & Access, **plus** an explicit degrade-path test suite: for each fan-out target, simulate a 5xx/timeout and assert the primary response is still 200 with that section empty/omitted, never a 5xx bubbling up to the caller. This is this unit's most novel failure mode relative to Unit 2 and must not regress silently.
- **NFR-MP-MAINT-2**: bandit + cfn-lint/cfn_nag + dependency scan + SBOM in CI (platform default, unchanged).

## Compliance / scope
- **NFR-MP-COMP-1**: No regulated regime (Phase 1). Profile fields (city/country/professionalRole/bio/skills/avatar) are self-disclosed, non-sensitive community data — same PII-minimization posture as Identity & Access (name/email only, minimized in logs/events). Data residency = customer's chosen single region (inherited).

## Security Compliance Summary (this stage)
| Rule | Status | Note |
|---|---|---|
| SECURITY-01 Encryption | Compliant | Table KMS-encrypted; TLS to AWS APIs + intra-account REST fan-out |
| SECURITY-02 Access logging | Compliant (inherited) | API GW execution/access logs at edge |
| SECURITY-03 App logging | Compliant | JSON + correlation IDs; no PII beyond what's needed |
| SECURITY-04 Security headers | N/A | No HTML served by this service (SPA/CloudFront) |
| SECURITY-05 Input validation | Compliant | validation.py; free-text length caps; query-param validation |
| SECURITY-06 Least privilege | Compliant | Scoped exec role (DDB/EventBridge/read-only cross-service invoke) |
| SECURITY-07 Network | Compliant (inherited) | Lambda in private subnets, VPC endpoints |
| SECURITY-08 Access control | Compliant | Fail-closed in-service authZ; Admin/UGL/Member scoping (BR-4/13) |
| SECURITY-09 Hardening | Compliant | Generic errors; no default creds (none held by this service) |
| SECURITY-10 Supply chain | Compliant | Pinned reqs + scan/SBOM in CI |
| SECURITY-11 Rate limiting | Compliant (inherited) | API GW throttling (platform default; no unit-specific need) |
| SECURITY-12 Auth & credentials | N/A | This service holds no credentials — authN is Identity & Access's responsibility |
| SECURITY-13 Integrity | Compliant (inherited) | Auditable pipeline; safe parsing |
| SECURITY-14 Alerting | Compliant | Alarms on fan-out failure rate + consumer lag |
| SECURITY-15 Exception handling | Compliant | Global fail-closed handler; per-call fan-out failures caught individually |

## Resiliency Compliance Summary (this stage)
| Rule | Status | Note |
|---|---|---|
| RESILIENCY-01 Criticality | Compliant | Classified STANDARD; deps mapped |
| RESILIENCY-02 RTO/RPO | Compliant (inherited) | Backup & Restore; PITR |
| RESILIENCY-03 Change mgmt | N/A (inherited) | Exempt per platform decision |
| RESILIENCY-04 Deploy/rollback | Compliant (inherited) | CodePipeline; redeploy previous version rollback |
| RESILIENCY-05 Monitoring | Compliant | Fan-out + consumer-lag metrics/alarms (NFR Design) |
| RESILIENCY-06 Health checks | Compliant | Shallow + deep (DDB only — no Cognito/SES dep) |
| RESILIENCY-07 Resiliency monitoring | Compliant | Fan-out failure-rate alarms |
| RESILIENCY-08 Multi-zone | Compliant (inherited) | Managed multi-AZ services |
| RESILIENCY-09 Auto-scaling | Compliant | On-demand DDB + Lambda default scaling |
| RESILIENCY-10 Circuit breaking | Compliant | Per-call timeouts + graceful per-section degrade (BR-9) — this unit's defining pattern |
| RESILIENCY-11 DR strategy | Compliant (inherited) | Backup & Restore; also uniquely rebuildable via event replay |
| RESILIENCY-12 Backup | Compliant | PITR + on-demand backups; no hard-delete (BR-8) |
| RESILIENCY-13 Failover procedures | Compliant (inherited) | Platform runbook; single-region restore |
| RESILIENCY-14 Resiliency testing | Deferred-to-Operations (inherited) | Degrade-path scenarios captured in NFR Design + contract tests |
| RESILIENCY-15 Incident response | Compliant (inherited) | Lightweight IR + COE (platform decision) |

**No blocking security or resiliency findings.**
