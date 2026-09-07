# Business Logic Model — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Platform & Delivery · **Approach**: A (contract-first)
Technology-agnostic design of the platform's own logic (the delivery substrate). No business-domain algorithms live here; those belong to each business service's Functional Design in Phase 4. Companion: `business-rules.md`, `domain-entities.md`.

## Scope
This unit provides the machinery that lets all other units be built mock-first and delivered as a product:
1. Contract lifecycle (authoring, versioning, validation)
2. Mock generation (from contracts)
3. Fixture management (one coherent seed)
4. Scaffold/bootstrap generation (per-service day-0 stacks + pipeline + mock handler)
5. `service-mode` lifecycle (mock → partial → complete)
6. Contract-test gate (the CI/CD quality bar)
7. Semantic Search capability gating (`EnableSemanticSearch`)

---

## 1. Contract lifecycle
```
author/edit OpenAPI + event schema in /contracts/services/<svc>/ (owner = folder)
   → validate (lint OpenAPI, JSON-Schema check, envelope conformance)
   → publish version (vN); breaking change ⇒ new vN file + envelope.version bump (Q1/Q2)
   → consumed by: mock factory, scaffold generator, contract-test harness, SPA client generator
```
- Single source of truth for API shapes (OpenAPI 3.x) and event payloads (JSON Schema) + the permission matrix + shared envelope/error schemas.
- Every downstream generator reads contracts; nothing hand-duplicates them (FQ1: specs, not code).

## 2. Mock generation (factory)
Input: a service's `openapi.yaml` (+ fixtures). Output: a Python mock Lambda handler for that service.
```
for each operation in openapi:
    if operation marked implemented=false (default at bootstrap): return 501 (Q7)
    else:
        GET/list   → read from seeded DynamoDB table (Q5)
        GET/{id}   → read item; 404 if absent
        POST/PUT   → persist to seeded table; return created/updated representation
        derived reads (points/tiers/analytics) → return PRECOMPUTED fixture values (mock does NOT run scoring) (Q5)
    apply realism controls: optional latency on derived reads, pagination, empty-state, chaos 4xx/5xx (default off)
    validate response against the operation's schema before returning
```
- Mocks are **contract-conformant by construction** — they are generated from the same schema the contract tests assert.
- Semantic-search endpoints honor the `EnableSemanticSearch` flag: when off, return the disabled behavior per the Q10 matrix (forum search / Help / AI reporting hidden; dup-check skipped).

## 3. Fixture management
- ONE shared dataset (Q4) keyed to the 4 personas; same entity IDs reused across services so cross-service views are coherent (a member's points in Contributions match that member in Members/Directory).
- Includes precomputed derived data (ledger + rollups + tiers) so leaderboards/tiers render without scoring logic.
- Loaded into each service's seeded `-data` table at bootstrap.

## 4. Scaffold / bootstrap generation (D12)
Input: a service name + its OpenAPI. Output (day-0, real infra + mock logic):
```
service-<name>-data.yaml   (tables/Streams/buckets, Retain)         → deployed once
service-<name>-app.yaml     (Lambda=mock handler, IAM role, routes from OpenAPI, rules, alarms)
pipeline-<name>.yaml        (CodePipeline from the reusable template)
contract-test wiring        (harness bound to this service's contract)
```
- Result: service is live in `mode=mock`, all endpoints returning fixture-backed 200s (implemented=false endpoints → 501 only once real work begins; at pure bootstrap all are mock-served).
- Routes owned by the service's `-app` stack (no cross-stack route contention).

## 5. `service-mode` lifecycle
```
mock ──(team implements ≥1 endpoint, deploys real code)──▶ partial ──(all endpoints implemented)──▶ complete
```
- State + `implementedPaths` recorded in the `service-mode` manifest (Q6), derived from per-endpoint `implemented` flags in the handler (Q7).
- Transition is an ordinary contract-test-gated code deploy — no swap (FQ7).
- Informational only; not an automated release gate (D14).

## 6. Contract-test gate (CI/CD quality bar)
Run identically against mock AND real (Q8):
```
for each operation:
    response status+body conform to OpenAPI schema
    401 when no/invalid token; 403 when role/scope violates the permission matrix
    unimplemented operations return 501 (not 5xx)
(optional) event producer/consumer payloads conform to their versioned JSON Schema
```
- This is the sole gate that lets real code replace a mock in a service's pipeline.

## 7. Semantic Search capability gating
- Single condition `EnableSemanticSearch` deploys/withholds Search (Unit 13) + AI Gateway (Unit 14) together (Q10).
- Consumer contracts document both on/off behaviors; mocks simulate both via the flag so the SPA is validated in both footprints.

---

## Cross-unit interactions (this unit → others)
- **Generates** the day-0 scaffold, mock, and pipeline for every service unit (2–14) and the SPA's generated API client (Unit 15, Q9).
- **Provides** shared infra outputs (VPC, Cognito user pool, EventBridge bus, API Gateway id, root-resource id) as **Parameters** to every service stack (D1).
- **Owns** `/contracts` conventions that all units bind to.

## Error handling (platform-level)
- Generators fail fast on invalid/inconsistent contracts (bad OpenAPI, missing envelope fields, schema/permission drift) — a broken contract must never produce a mock or scaffold.
- Standard error response shape (`error-response.v1.json`) returned by mocks and required of real services (generic messages, no internals — SECURITY-15).
