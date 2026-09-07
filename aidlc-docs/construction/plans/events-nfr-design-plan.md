# NFR Design Plan — Unit 4: Events

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Events
**Inputs**: `events/functional-design/` (approved) · `events/nfr-requirements/` (approved, decisions N1–N6) · Security + Resiliency baselines
**Outputs**: `events/nfr-design/nfr-design-patterns.md`, `events/nfr-design/logical-components.md`

## Steps
- [x] 1. Analyze NFR requirements (criticality STANDARD, N1–N6, NFR-EV-* requirements, both compliance tables)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions — **all five mandatory categories evaluated; every item resolved from approved artifacts or precedent, so no question requires user input at this stage.** Resolutions and the four judgement calls are tabled below and flagged for review at the stage gate
- [x] 4. Store plan
- [x] 5. Collect and analyze answers — not applicable, no open questions
- [x] 6. Generate NFR design artifacts
- [x] 7. Present completion message
- [ ] 8. Await explicit approval
- [ ] 9. Record approval + update `aidlc-state.md`

## Mandatory category evaluation (per nfr-design.md Step 3)

| Category | Applicable? | Resolution source | Outcome |
|---|---|---|---|
| **Resilience patterns** | Yes | NFR-EV-REL-1..9; Unit 3's `FanOutClient`; Settings' fail-closed S3 ordering | Per-call timeouts + per-container short-circuit + per-section degrade; idempotency by event id; transactional RSVP counters; mark-before-emit on the reminder sweep; S3-delete-before-row on material removal. All established patterns, no new decision. |
| **Scalability patterns** | Yes | NFR-EV-SCALE-1..5; the Member Directory and File Share pagination reworks | Every listing is a GSI query with a fetch-until-full page loop and an opaque cursor. Partition walk over the caller's scopes (the pattern already shipped for Admin Users' role walk). No scans anywhere. |
| **Performance patterns** | Yes | NFR-EV-PERF-1..6; decision N6 | 60-second per-container point-value cache; parallel fan-out; sparse indexes so hot queries touch small partitions; presigned URLs keep file bytes out of Lambda. |
| **Security patterns** | Yes | NFR-EV-SEC-1..13; decisions N1, N3 | Three-layer authorization with 404-not-403; token hashed with constant-time compare; malware-scan gate as an explicit state machine; prefix-scoped S3 access; per-token throttling. |
| **Logical components** | Yes | Functional design's 7 services; Units 2/3/11 module conventions | Router with five input branches, seven domain services, one repository, six providers, three consumers. No queues, no Step Functions, no distributed circuit breaker — nothing in the NFRs justifies them at this tier. |

## Judgement calls made at this stage (flagged for review — override any and I will revise)

| # | Call | Reasoning |
|---|---|---|
| J1 | **Series creation refined to a two-phase write, superseding NFR-EV-REL-6's ordering.** Write the series record **first** with `status = Provisioning`, then the occurrences, then flip to `Active`. | NFR-EV-REL-6 said occurrences first, series last, on the grounds that orphans fail safer than a series pointing at nothing. Two-phase is strictly better: there is no state that is invisible or unexplainable, a partial failure is *resumable* rather than merely tolerable, and a `Provisioning` series is self-describing in the UI. "Series pointing at nothing" was only a hazard because the original ordering had no way to say "incomplete". This is a deliberate improvement on the approved requirement, not a drift — calling it out so you can reject it. |
| J2 | **Sparse GSIs rather than filtered queries** for the Content Library and the reminder sweep: the index key attribute is written only when the item qualifies (material clean + parent event Completed; schedule record still Pending) and **removed** when it stops qualifying. | Keeps both indexes proportional to qualifying items rather than to table size, so the reminder sweep costs the same whether the portal holds 100 events or 100,000. The cost is that qualification transitions must maintain the key attribute — which is exactly what the malware-scan and publish transitions already touch. |
| J3 | **Malware scanning modelled as an explicit three-state machine on the material** (`PendingScan` → `Clean` \| `Quarantined`) rather than a boolean. | Decision N1 gates visibility on a clean scan, which means "not yet scanned" and "failed scanning" must be distinguishable: the first is transient and shows the uploader a "Scanning…" state, the second is terminal and needs an operator signal. A boolean would conflate them and make a quarantined file look like a slow one forever. |
| J4 | **The reminder sweep and the S3-object consumer run in this service's existing Lambda**, dispatched by the router's branches, rather than as separate functions. | Consistent with how Member Profiles handles its EventBridge branch and Settings handles its S3 consumer. Separate functions would triple the deployment surface and duplicate the wiring for workloads measured in single-digit invocations per minute. Revisit only if the sweep's duration starts competing with request latency. |

**No blocking security or resiliency findings at this stage.**
