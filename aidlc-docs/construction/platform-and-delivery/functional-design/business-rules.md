# Business Rules — Unit 1: Platform & Delivery

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Platform & Delivery
Rules governing the delivery substrate. Companion: `business-logic-model.md`, `domain-entities.md`.

## Contract & ownership rules
- **BR-1 (Ownership)**: Each `/contracts/services/<svc>/` folder is owned solely by service `<svc>`. Only the owner may change its schemas; all other services treat them as read-only. Cross-cutting specs live under `/contracts/platform/` and are owned by this unit.
- **BR-2 (Specs, not code)**: Contracts are specifications only (OpenAPI + JSON Schema). No executable/shared code is placed in `/contracts` (FQ1).
- **BR-3 (Single source of truth)**: Mocks, scaffolds, contract tests, and the SPA API client are all **generated** from `/contracts`. Hand-duplicating a contract shape elsewhere is prohibited.

## Versioning rules (Q1/Q2)
- **BR-4 (Version location)**: Every event payload carries a `version` integer in the envelope AND a versioned filename (`<event>.v<N>.json`).
- **BR-5 (Breaking change)**: Any non-backward-compatible change to an existing version requires a **new** `vN+1` file; the old version is retained until all consumers migrate. Consumers select by version.
- **BR-6 (Additive change)**: Backward-compatible additions (new optional field) may extend the current version in place.

## RBAC / permission-spec rules (Q3, FQ3a)
- **BR-7 (AuthN vs authZ split)**: API Gateway (Cognito authorizer) performs authentication only. Authorization is enforced **in-service**, fail-closed (deny → 403).
- **BR-8 (Permission source of truth)**: Every service enforces authorization from `/contracts/platform/permissions/role-permission-matrix.v<N>.json`. No service invents its own role rules.
- **BR-9 (Scope semantics)**: A permission's `scope` dictates the object-level check the handler MUST perform:
  - `global` — role alone suffices.
  - `own` — principal must own the target resource (IDOR guard).
  - `group` — principal's role must be scoped to the target's group (e.g., UGL ↔ led group).
- **BR-10 (Roles)**: Exactly one role per principal ∈ {Administrator, CommunityLeader, UserGroupLeader, Member}; `accountType=local-admin` is an orthogonal flag (built-in admin, portal-local auth).
- **BR-11 (Fail-closed default)**: Any action not explicitly granted is denied.

## Mock & fixture rules (Q4/Q5)
- **BR-12 (Fixture coherence)**: All mocks read from ONE shared fixture dataset; the same entity IDs represent the same entities across services (no contradictory data between services).
- **BR-13 (No business logic in mocks)**: Mocks persist CRUD but do NOT compute derived data. Points, tiers, rollups, and analytics are served from precomputed fixtures. Scoring/tier/analytics algorithms exist only in the real services.
- **BR-14 (Realism defaults)**: Simulated latency and empty/paginated states are available; error injection ("chaos") defaults **off** and is opt-in per environment.
- **BR-15 (Contract conformance)**: A mock response MUST validate against its operation's schema before being returned.

## Service-state & 501 rules (Q6/Q7, FQ8, D13)
- **BR-16 (States)**: A service is `mock`, `partial`, or `complete`. `partial` = real code deployed with some endpoints implemented.
- **BR-17 (501 rule)**: An unimplemented endpoint returns HTTP **`501 Not Implemented`** — never a `5xx` error. The SPA treats `501` as "coming soon" / feature hidden.
- **BR-18 (Manifest derivation)**: `implementedPaths` in the `service-mode` manifest is derived from per-endpoint `implemented` flags in the deployed handler; the manifest is informational (no automated release gate — D14).

## Contract-test gate rules (Q8)
- **BR-19 (Single gate)**: Real code may replace a mock in a service's pipeline only after passing the contract-test suite.
- **BR-20 (Parity)**: The same suite runs against mock and real; both must pass identical schema/auth/501 assertions.
- **BR-21 (Auth assertions)**: The suite asserts 401 (no/invalid token) and 403 (role/scope violation per the permission matrix), in addition to schema conformance.

## Semantic Search rules (Q10)
- **BR-22 (Single capability)**: Search (OpenSearch) + AI (Bedrock) are one capability "Semantic Search", gated by the single condition `EnableSemanticSearch`. They are never deployed independently.
- **BR-23 (Feature behavior when OFF)**:
  - Member search — **unaffected** (always text search; no semantic dependency).
  - Forum search — **unavailable/hidden** (no keyword fallback).
  - Forum duplicate detection — **skipped**; post creation proceeds.
  - AI reporting & suggested insights — **unavailable/hidden**.
  - Help Assistant — **unavailable/hidden**.
- **BR-24 (Contract-documented)**: Each affected endpoint documents both enabled/disabled behavior; mocks simulate both modes via the flag.

## Data-safety & delivery rules (D4/D6)
- **BR-25 (Retain)**: All DynamoDB tables and S3 buckets carry `DeletionPolicy: Retain` + `UpdateReplacePolicy: Retain`. The `-data`/`-app` split ensures frequent app deploys never touch data stacks.
- **BR-26 (Parameterize, not import)**: Service stacks receive shared-infra references as CloudFormation Parameters, never via `Fn::ImportValue` (portability to the customer account).
- **BR-27 (Prebuilt default install)**: Customer install uses prebuilt dependency-complete artifacts in `dist/`; building from source is optional.
- **BR-28 (Release timing)**: A customer release is cut only after all units are `complete` (process discipline; no automated gate — D14).
