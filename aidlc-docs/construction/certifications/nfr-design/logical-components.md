# Logical Components — Unit 6: Certifications

Single self-contained Python service (`services/certifications/`), house shape (Units 2/3/4/11): one Lambda, `app.py` router with three dispatch branches, constructor-injected context for tests. No shared libraries (FQ1) — conventions copied per-unit (`_conventions/`: authz, envelope, errors, idempotency, logger, validation — take the current superset incl. ConflictError, per the Events drift note).

```
app.py (handler)
├── HTTP branch (authenticated)         → route table → OP_AUTHZ gate → service call
├── Event branch (EventBridge)          → membership_consumer | scan_consumer (by detail-type/source)
└── Scheduler branch                    → expiry_sweep (daily) | scan_watchdog (15-min, J4)

services/
├── definition_service   — create/edit/deactivate-reactivate (US-5.1/5.2/5.3); badge-upload grant;
│                          catalog assembly (+per-caller held/pending enrichment, no N+1)
├── claim_service        — submit (membership check via identity_client, duplicate slot, dateEarned/
│                          BR-C6 gate, evidence XOR), myClaims, withdraw, listClaims (BR-P1 projection
│                          switch — the member-profiles-facing route)
├── verification_service — queue (scope + filters + countOnly, oldest-first), decide (approve: freeze
│                          points/expiresAt, BR-V7 guard; reject: reason), evidence-url minting (BR-P2)
├── revocation_service   — claim-addressed revoke (D9, BR-R1..R3)
├── expiry_service       — daily sweep: T-14 mark-before-emit notice + Approved→Expired flip;
│                          continuation-bounded batches
└── watchdog_service     — PendingScan age scan (J3 SCANWATCH partition) → PendingScanAgeMinutes metric

consumers/
├── membership_consumer  — MemberLeftGroup/MemberRemoved → auto-reject (BR-S1..S3), idempotent
└── scan_consumer        — GuardDuty verdicts: evidence scanStatus stamp; badge copy-to-public-bucket
                           then Clean stamp (J5, trust promotion single point); oversize/quarantine
                           handling; idempotent; FileKeyPointer O(1) owner lookup

repository.py            — single table; item collections (definition, claim, CLAIMSLOT, FILEKEY
                           pointer, idempotency); sparse indexes: PENDING queue (J2), shared sweep GSI
                           EXPIRY|SCANWATCH (J3); conditional transitions; opaque whitelisted cursors;
                           NO scans
providers.py             — EventPublisher (5 types, batched, post-commit best-effort);
                           S3Broker (presigned POST grants w/ content-length-range ≤5MB (J1) +
                           per-request evidence GETs + public-bucket badge copy);
                           IdentityClient (membership read, 1.5s timeout, fail-closed)
models.py                — entities, status enums (wire: Pending/Approved/Rejected/Withdrawn/
                           Revoked/Expired), serializers: owner_claim / public_claim / queue_claim
authz (OP_AUTHZ map)     — per-op matrix rows + Administrator boundary 403 (D7); fail-closed loader
```

## External touchpoints
| Direction | What |
|---|---|
| Publishes | `CertificationApproved/Rejected/Revoked/ExpiringSoon/Expired` (schemas authored in `/contracts/services/certifications/published-events/`) |
| Consumes | Identity `MembershipChanged` (2 detail-types); GuardDuty scan verdicts (own prefixes only — F3-style prefix filters on the rules, both directions) |
| Sync REST out | Identity membership read (submit only) |
| Serves | SPA (all screens); member-profiles fan-out (`listClaims` projections); future Notifications/Analytics via events |
| S3 | Foundation scanned bucket `certifications/evidence/ · certifications/badges/` (grant/read/delete); SPA public bucket `badges/` (copy-on-Clean only — the unit's single cross-stack write, prefix-scoped IAM) |
| Schedules | Daily expiry sweep + 15-min scan watchdog (J4), both EventBridge Scheduler → this Lambda |

## Component → NFR traceability
| Component | Enforces |
|---|---|
| OP_AUTHZ + boundary gate | NFR-CT-SEC-1, D7, BR-A1..A5 |
| S3Broker presigned POST | NFR-CT-SEC-3 (N2 5MB at the door), BR-C7, J1 |
| scan_consumer | NFR-CT-SEC-4/5 (trust promotion), J5 |
| claim_service + CLAIMSLOT | BR-C2 race-free duplicates, NFR-CT-REL-2 |
| IdentityClient | NFR-CT-REL-1 fail-closed |
| expiry_service | BR-X1..X4, NFR-CT-AVAIL-3, mark-before-emit |
| watchdog_service | NFR-CT-SEC-8/N4 (30-min alarm has an emitter) |
| repository sparse indexes | NFR-CT-PERF-3, NFR-CT-SCALE-2, J2/J3 |
| serializers | BR-P1/P2 privacy projection |
| EventPublisher | BR-E1, NFR-CT-REL-6, D10 |

## Test seams
Constructor injection throughout (fake repo/publisher/clock/S3/identity); `EventPublisher.published[]`; sweep takes `now` as a parameter (expiry math testable without time travel); the three mandatory suites (NFR-CT-MAINT-1) map to: authz matrix → OP_AUTHZ table-driven tests; lifecycle → repository conditional-transition tests; degrade → IdentityClient/scan/publisher fault injection.
