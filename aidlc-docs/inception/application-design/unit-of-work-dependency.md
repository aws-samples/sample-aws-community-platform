# Unit of Work — Dependency Matrix & Build Order

Companion to `unit-of-work.md` and `unit-of-work-story-map.md`. Captures inter-unit dependencies, communication patterns, and the build/sequencing order under the mock-first delivery model.

## Communication patterns (FQ2)
- **Async events (EventBridge)** — primary cross-service coupling; producers publish, consumers react. Loose, eventually consistent.
- **DynamoDB Streams (CDC)** — each service's own table stream drives its rollups; Search/Analytics consume for projections.
- **SQS (+DLQ)** — durable async buffering (Notifications email, embeddings).
- **Sync REST** — only for read-time lookups (e.g., Forums → Identity for @mention group-access checks). Minimized.
- **Contracts** — all of the above are specified in `/contracts` (OpenAPI + event JSON Schema). No shared code (FQ1).

## Dependency legend
- **E→**: publishes an event the target consumes (async, loose).
- **←E**: consumes an event the source publishes.
- **REST**: synchronous read-time call.
- **INFRA**: depends on Unit 1 platform resources (API GW, Cognito, EventBridge bus, VPC).
- **AI/SEARCH**: synchronous invocation of the shared AI Gateway / Search service.

## Dependency matrix (runtime)

| Unit | Depends on (runtime) | Nature |
|---|---|---|
| 1 Platform & Delivery | — | provides INFRA to all |
| 2 Identity & Access | 1 | INFRA; source of identity truth (publishes user/group events) |
| 3 Member Profiles | 1, 2, 4, 5, 6, 7, (13 Search), (14 AI) | ←E Identity (incl. group-membership events); REST→4,5,6,7 (activity-summary + rollup fan-out at read time, US-3.1/3.3/3.10, added 2026-08-02); index via 13; embeddings via 14. **US-3.8/3.9 reassigned to Unit 2 (2026-08-02) — Member Profiles no longer serves an admin member list.** |
| 4 Events | 1, 2 | INFRA; ←E `GroupSoftDeleted`; publishes attendance/delivery events |
| 5 Forums | 1, 2 | ←E `GroupHardDeleted`/`GroupSoftDeleted`/`GroupRestored`; REST→2 (@mention scope). *(Functional Design 2026-08-08 DV-1/DV-2: dup-check→14 and index/search→13 **removed** — duplicate detection out of scope, semantic search downgraded to in-service keyword. Forums no longer depends on 13/14 at runtime.)* |
| 6 Certifications | 1, 2 | ←E `MemberLeftGroup`/`MemberRemoved`; publishes `CertificationApproved` |
| 7 Contributions & Scoring | 1, 2, 4, 5, 6 | ←E attendance/delivery/organize/forum/cert events (auto-award); ←E group/member events |
| 8 Analytics | 1, 2, 4, 5, 6, 7, (14 AI) | ←E + Streams from many; AI reporting/insights via 14 |
| 9 Announcements | 1, 2, 10 | ←E `GroupSoftDeleted`; E→10 for optional email |
| 10 Notifications | 1, (2,4,5,6,7,9 as event sources) | ←E most domain events → SES/in-portal |
| 11 Settings | 1 | INFRA; publishes `SettingsChanged` (consumed by 2,4,5,10,14,frontend) |
| 12 Help Assistant | 1, 14 AI | AI-grounded; conditional on AI |
| 13 Search (shared) | 1, 14 AI | ←E index events from 3,5; embeddings via 14; conditional |
| 14 AI Gateway (shared) | 1 | invoked by 3,5,7,8,12,13; conditional |
| 15 Frontend SPA | 1, all service REST APIs | consumes every `/…` path via API GW |

**No dependency cycles that block sequencing.** Contributions (7) consumes events from 4/5/6 but only at runtime; with event contracts defined up front and mock producers, 7 can be built independently. Search (13) and AI Gateway (14) are consumed synchronously but are optional (D3) and stubbed via contracts until present.

## Build & sequencing order (supersedes Q6 = A; per mock-first D12)

Under mock-first, the **entire UI works end-to-end against mocks before real services are built**. Sequence:

```
Phase 0 — Contracts (prerequisite)
  /contracts: OpenAPI per service + event schemas + permission spec + fixtures

Phase 1 — Platform & Delivery (Unit 1)
  foundation (VPC, Cognito, EventBridge, observability) + API Edge (API GW + authorizer)
  + mock factory + scaffold generator + contract-test harness + pipeline template + root template

Phase 2 — Per-service bootstrap (all 15 services, in parallel)
  scaffold -data + -app (mock seed) + routes + pipeline for every service → all live in `mock` state

Phase 3 — Frontend SPA (Unit 15)
  full UI working end-to-end through API Gateway against mocks

Phase 4 — Real services replace mocks (contract-test-gated code deploys), dependency-informed order:
  4a. Identity & Access (Unit 2)          ← first real service; auth never mocked
  4b. Members, Events, Forums, Certifications (Units 3,4,5,6)   ← independent producers, parallel
  4c. Contributions & Scoring (Unit 7)    ← consumes 4b events (auto-award)
  4d. Analytics (Unit 8)                  ← downstream of most
  4e. Search, AI Gateway (Units 13,14)    ← shared enablers (conditional)
  4f. Notifications (Unit 10)             ← event sink for 2/4/5/6/7/9
  4g. Announcements, Settings, Help (Units 9,11,12)

Phase 5 — Release
  assemble root template + dist/ artifacts + validate + tag (after all units `complete`)
```

### Notes on ordering
- **Parallelism**: Phase 2 bootstraps are independent (each is its own scaffold). Phase 4b producers are mutually independent and can proceed in parallel by different teams.
- **Stubs via mocks**: because every service exists in `mock` from Phase 2, a real service consuming another's events/reads can develop against that other's mock — no strict finish-before-start dependency (avoids the Q6=B rigidity).
- **Conditional units (13, 14)**: if a customer disables Search/AI (D3), consumers degrade gracefully; these units can be sequenced late without blocking core flows.
- **Frontend early (Phase 3)** validates the full contract surface and UX before backend investment — the core goal of the mock-first approach.

## Stack dependency (deploy-time, via Parameters — D1)
```
foundation.yaml ── outputs (VpcId, SubnetIds, UserPoolId, EventBusName, RestApiId, RootResourceId)
   │  (passed as Parameters, NOT Fn::ImportValue)
   ├─→ api-edge.yaml
   ├─→ service-<name>-data.yaml ── outputs (TableName, TableArn, StreamArn, BucketName)
   │        │ (Parameters)
   │        └─→ service-<name>-app.yaml   (also receives RestApiId/RootResourceId, EventBusName)
   └─→ frontend.yaml (receives RestApiUrl, UserPoolId for runtime config injection)
root-template.yaml nests all of the above for the customer install.
```
Parameter-passing (not exports) keeps stacks independently deployable in dev and portable to the customer account (no pre-existing SSM/exports required).
