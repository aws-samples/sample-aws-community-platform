# Components — AWS Community Portal

Each microservice (one Lambda, implemented in Python, Node.js, or Rust — language chosen per service at Construction) is internally structured with the **same layered component pattern** (hexagonal-lite), built from the shared per-language libraries. This doc defines the reusable component archetypes, then the notable components per service, plus shared and frontend components. Detailed business rules are deferred to per-unit Functional Design.

---

## A. Per-service component archetypes (inside every service Lambda)

| Component | Responsibility | Interface (in/out) |
|---|---|---|
| **Router / Handler** (language-appropriate Lambda HTTP framework, e.g. FastAPI/Powertools on Python, Express/Middy on Node.js, `lambda_http`+`axum` on Rust) | Parse HTTP request, correlation ID, dispatch to application handlers, map results → HTTP + security headers | in: API Gateway proxy event · out: HTTP response |
| **AuthZ Guard** (from shared `auth`) | Enforce authN context + object/function-level permission per Role-and-Permission-Mapping; deny→403 (fail-closed) | in: principal + action + resource · out: allow / 403 |
| **Application Service** (use-cases) | Orchestrate a use case: validate input, call domain + repository, publish events | in: validated command/query · out: result DTO |
| **Domain** | Entities, value objects, invariants (e.g., ledger entry, tier calc, RBAC rules) | pure functions/types |
| **Repository** (from shared `persistence`) | DynamoDB access for this service's table(s); last-write-wins | in: keys/items · out: entities |
| **Event Publisher** (from shared `events`) | Emit domain events to EventBridge; enqueue SQS work | in: domain event · out: ack |
| **Stream/Queue Consumer** | React to DynamoDB Streams / EventBridge / SQS (rollups, projections, notifications) | in: event batch · out: side-effects |
| **Integrations** | Service-specific external clients (Cognito, SES, Bedrock via AI Gateway, MS Teams, S3, OpenSearch) | varies |
| **Input Validation** (shared `common`) | Type/length/format/sanitization (SECURITY-05) | in: raw · out: validated / reject |

---

## B. Shared libraries (per-language, in the polyglot monorepo)
Each library below is provided as a per-language implementation (Python package / npm package / Rust crate) so any service can consume it regardless of its chosen language.
- **`domain-models`** — `Role`, `UserId`, `GroupId`, `Quarter`, `Pillar`, `PointEntry`, `DomainEvent` variants, DTOs shared across services.
- **`auth`** — `Authorizer` (permission matrix), `Principal` (from JWT claims + account type), guards `require_role`, `require_owns_resource`, `require_group_scope`.
- **`persistence`** — `DynamoRepo<T>` helpers, key builders, pagination, GSI query helpers.
- **`events`** — `EventBus` (EventBridge put), typed event schemas + versions, `SqsProducer/Consumer`.
- **`common`** — structured `Logger` (correlation/request id), `AppError` (fail-closed, generic user messages, global handler), validation, IANA time-zone conversion, config loader (Settings/SSM), CSV writer.

## C. Shared cross-cutting services (own components)
- **Search Service**: `IndexWriter` (upsert/delete vectors), `QueryEngine` (semantic search), `EmbeddingClient` (via AI Gateway). Owns OpenSearch Serverless collection.
- **AI Gateway Service**: `BedrockClient`, `PromptBuilder`, `Guardrails` (scope/PII/injection), `ModelConfigResolver` (admin model id). Facades: `embed()`, `detectDuplicate()`, `report()`, `insights()`, `helpAnswer()`.
- **Notifications Service**: `EventRouter` (maps domain event → recipients via US-8.15 matrix), `PreferenceFilter`, `EmailSender` (SES + retry/backoff/DLQ), `InPortalStore` (latest-20 panel).
- **Audit**: `AuditLogger` (in `common`) → CloudWatch Logs; toggle honored from Settings.

---

## D. Notable components per bounded-context service
(Only components beyond the archetypes are highlighted.)

### Identity & Access
- `CognitoAdapter` (sign-in, custom-auth OTP triggers, admin APIs), `SyncJob` (scheduled), `BulkImporter` (CSV/XLSX → Cognito + portal record), `LocalAdminAuth` (portal-managed creds in Secrets Manager, portal-local reset), `GroupManager`, `JoinRequestManager`, `MembershipHistoryWriter` (US-1.34), `RoleChangeHandler` (suspend-not-destroy).

### Member Profiles & Directory
- `ProfileManager`, `DirectoryQuery`, `AdminMemberList/Export`, `ActivitySummaryAssembler` (reads activity via events/other services), `ProfileIndexer` (emits `MemberProfileUpserted`).

### Events
- `EventManager` (CRUD + status transitions), `RecurrenceExpander` (series→occurrences), `RsvpManager`, `CalendarInviteBuilder` (.ics), `MaterialsManager` (S3), `TeamsAttendanceMatcher` (email match + review), `AttendanceRecorder`, `DesignationManager` (presenters + organizers), `ContentLibrarySearch`, `UploadLinkManager` (presign, reuses US-8.13 model).

### Forums
- `ForumChannelManager`, `PostManager`, `ReplyManager`, `ReactionManager`, `MentionResolver` (access-scoped autocomplete), `AcceptedAnswerManager`, `PinManager`, `FollowManager`, `ModerationQueue`, `DuplicateChecker` (via AI Gateway, fail-closed), `ForumIndexer` (emits post/reply events; delete → remove index).

### Certifications
- `CertificationDefManager` (per-cert points), `ClaimManager` (submit/withdraw/resubmit, duplicate guard), `VerificationQueue` (credited-group routing), `ExpiryJob` (daily), `RevocationManager`, `BadgeManager`, `Catalog`.

### Contributions & Scoring
- `LedgerWriter` (append-only), `ScoringFramework` (seeded config; fixed 6 auto), `AutoAwardConsumer` (reacts to attendance/delivery/organize/forum/cert events; equal-split attribution), `SubmissionManager` (evidence), `ApprovalManager`, `AdjustmentManager` (may go negative), `TierCalculator` (runtime), `LeaderboardQuery`, `SummaryQuery`, `RollupProjector` (Streams → per-group/quarter rollups; late-quarter recompute).

### Analytics
- `DashboardAssembler`, `ChartDataProvider`, `MembershipGrowthProjector` (from membership history), `CsvExporter` (contribution/member/event schemas), `AIReportAgent` (NL→query via AI Gateway, role-scoped guardrails), `InsightsBatch` (daily; stale-with-timestamp fallback), `AnalyticsProjector` (Streams → analytics store).

### Announcements
- `AnnouncementManager` (author/target/expiry), `PanelQuery` (audience-scoped), `DismissalStore` (per-member), `EmailOptInPublisher`.

### Notifications
- `EventRouter`, `PreferenceFilter`, `EmailSender`, `InPortalStore`, `TemplateRenderer` (uses Settings templates + placeholders).

### Platform / Settings
- `SettingsManager` (all admin sections), `EmailTemplateManager`, `FileShareManager` (S3 presign, revoke/expiry, audit), `TimeZoneDefaults`, `WhatsNewConfig` (feed URL/toggle).

### Help Assistant
- `HelpSession` (stateless), `HelpAnswerer` (AI Gateway + grounding), `ScopeGuard` (refuse out-of-scope/implementation).

---

## E. Frontend components (React + Vite SPA)
- **Shell**: `AppLayout` (role-aware nav/sidebar/topbar, notification bell, help drawer), `AuthProvider` (Cognito), `RoleRouter` (route guards per role), `ApiClient` (REST + auth token).
- **Design system**: shared `components/` (Table with US-8.9 controls, Card, Badge, Modal, Tabs, Toasts, Announcement panel, Help drawer) — matches mockup styling (fidelity B).
- **Feature folders** (per module): `auth`, `members`, `events` (+content-library, calendar), `forums`, `certifications`, `contributions` (points/leaderboard), `analytics` (charts, AI report chat), `announcements`, `notifications` (prefs), `settings` (admin), `help`, `whats-new` (client-side RSS fetch/parse/sanitize).
- **Cross-cutting**: time-zone rendering (IANA), responsive layout, data-table preference persistence (US-8.9).
