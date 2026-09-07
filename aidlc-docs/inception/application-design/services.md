# Services — AWS Community Portal (Microservices)

**Topology**: Microservices — one service per bounded context. Each service = one Lambda ("Lambdalith"), implemented in Python, Node.js, or Rust (language chosen per service at Construction), behind a shared Amazon API Gateway (REST), owning its own DynamoDB table(s). Inter-service communication is **synchronous REST** (only where a request must read another context's data) and **asynchronous domain events via Amazon EventBridge**; **DynamoDB Streams** drive per-service CDC (rollups/search indexing); **SQS** buffers durable async work (email, embeddings) with DLQs.

Decisions applied: Q1 microservices · Q2 polyglot monorepo (per-service package + per-language shared libraries; language per service decided at Construction) · Q3 single API Gateway, per-module paths · Q4 one Lambda per service · Q5 table-per-service · Q6 Streams+EventBridge+SQS · Q7 Cognito authorizer + shared authZ library (per-language) · Q8 single React SPA · Q9 shared cross-cutting capabilities.

---

## Core (edge & shared)

### API Gateway (edge)
- Single REST API; per-module base paths route to each service's Lambda: `/auth`, `/users`, `/groups`, `/members`, `/events`, `/forums`, `/certifications`, `/contributions`, `/analytics`, `/announcements`, `/notifications`, `/settings`, `/help`, `/search`.
- **Cognito authorizer** validates JWT (authN). Access/execution logging enabled (SECURITY-02). Response security headers + WAF at CloudFront/edge.

### Shared libraries (per-language, in the polyglot monorepo — not deployables)
Each shared library is provided as a per-language implementation (Python package / npm package / Rust crate), so a service can consume it regardless of the language chosen at Construction.
- `domain-models` — shared entity/DTO types, role enum, event payload schemas.
- `auth` — **authorization library**: role/permission checks per Role-and-Permission-Mapping; object-level + function-level guards (SECURITY-08). Invoked inside every service handler.
- `persistence` — DynamoDB access helpers (single-table-per-service patterns, optimistic-free last-write-wins).
- `events` — EventBridge publish + typed domain-event contracts; SQS producers/consumers.
- `common` — logging (structured, correlation IDs), error types (fail-closed), validation, time/tz, pagination, config.

### Shared cross-cutting services (Q9)
- **Search Service** — owns OpenSearch Serverless vector index; exposes index/query APIs; consumes indexing events/Streams from Members & Forums.
- **AI Gateway Service** — single controlled entry to Amazon Bedrock (embeddings, duplicate detection, AI reporting, help assistant, insights); enforces model config + guardrails; used by Search, Forums, Contributions, Analytics, Help.
- **Notifications Service** — email (SES) + in-portal notifications; consumes domain events; enforces the US-8.15 recipient matrix + preferences.
- **Audit** — cross-cutting; each service emits audit entries to CloudWatch Logs via `common` (US-1.13); toggle in Settings.

---

## Bounded-context services

### 1. Identity & Access Service  (`/auth`, `/users`, `/groups`)  — Module 1
- **Responsibilities**: Cognito integration (sign-in email+password, periodic OTP custom-auth, JIT provisioning, sync job, bulk import), built-in local Administrator (portal-managed creds), RBAC role assignment, user groups (CRUD, join/leave, approval join-requests, UGL assignment, soft-delete+restore), membership-event history (US-1.34), audit toggle & settings surface for sync.
- **Owns**: Users/portal-records table, Groups table, Membership-events table, Join-requests table, Local-admin credential store (Secrets Manager).
- **Publishes**: `UserProvisioned`, `UserRoleChanged`, `UserDeactivated/Reactivated`, `GroupCreated/Updated/SoftDeleted/Restored/HardDeleted`, `MemberJoinedGroup`, `MemberLeftGroup/Removed`.
- **Consumes**: none critical (source of identity truth).

### 2. Member Profiles & Directory Service  (`/members`)  — Module 3
- **Responsibilities**: profiles (view/edit own, view others read-only), directory browse, admin member list/export, activity summary. Delegates search to Search Service.
- **Owns**: Member-profile table (profile fields, skills, avatar, tz).
- **Publishes**: `MemberProfileUpserted` (→ Search indexing).
- **Consumes**: `UserProvisioned/RoleChanged/Deactivated` (from Identity) to keep profile records aligned.

### 3. Events Service  (`/events`)  — Module 2
- **Responsibilities**: events CRUD, recurring series + occurrences, RSVP, calendar, materials (S3), MS Teams attendance (review-before-award), manual attendance, presenter + organizer designation, Content Library, event-scoped upload links.
- **Owns**: Events table, RSVP table, Materials metadata, Upload-links table.
- **Publishes**: `AttendanceRecorded`, `EventDelivered`, `EventOrganized`, `EventCompleted`, `EventCancelled`, `MaterialsAdded`, `CalendarInviteDue`.
- **Consumes**: `GroupSoftDeleted` (cancel upcoming group events).

### 4. Forums Service  (`/forums`)  — Module 4
- **Responsibilities**: forums/channels/posts/replies, reactions, @mention (access-scoped), accepted answer, pin, follow, report/moderation, duplicate-flag handling. Delegates search + dup detection to Search/AI.
- **Owns**: Forums/Channels/Posts/Replies tables, Reactions, Follows, Reports.
- **Publishes**: `ForumPostCreated`, `ForumReplyCreated`, `PostDeleted`, `ForumChannelDeleted`, `MemberMentioned`, `PostReported`.
- **Consumes**: `GroupHardDeleted` (remove content + search entries), AI dup-check (sync via AI Gateway).

### 5. Certifications Service  (`/certifications`)  — Module 5
- **Responsibilities**: definitions (per-cert points), claims, credited-group verification queue, expiry scheduled job, revoke, badges, catalog.
- **Owns**: Certifications table, Claims table.
- **Publishes**: `CertificationApproved` (→ Contributions awards per-cert points), `CertificationRevoked/Expired`.
- **Consumes**: `MemberLeftGroup/Removed` (auto-reject pending claims credited to that group), UGL reassignment events.

### 6. Contributions & Scoring Service  (`/contributions`)  — Module 6
- **Responsibilities**: system of record for the **append-only point ledger**; scoring framework config (seeded; fixed 6 auto activities); evidence submissions + approval; manual adjustments; runtime per-group tiers; leaderboards; group/community summaries; Streams-maintained rollups.
- **Owns**: Ledger table (append-only), Framework config, Submissions table, Rollups (derived).
- **Publishes**: `PointsAwarded`, `PointsAdjusted`, `TierAchieved`.
- **Consumes**: `AttendanceRecorded`, `EventDelivered`, `EventOrganized`, `ForumPostCreated`, `ForumReplyCreated`, `CertificationApproved` (auto-award); `MemberLeftGroup` (auto-reject pending); `GroupHardDeleted` (remove ledger entries).

### 7. Analytics Service  (`/analytics`)  — Module 7
- **Responsibilities**: dashboards, charts, CSV exports, AI reporting agent + suggested insights. Read-model fed from Streams into a separate analytics store (choice deferred to Infra Design).
- **Owns**: Analytics store (derived; read-only projections), insights cache.
- **Publishes**: none (read-side).
- **Consumes**: domain events + Streams from Contributions, Events, Certifications, Identity (membership history), Forums; uses AI Gateway for reporting/insights.

### 8. Announcements Service  (`/announcements`)  — Module 10
- **Responsibilities**: authoring, targeting (community/group), panel retrieval, per-member dismissal, optional email (via Notifications), expiry.
- **Owns**: Announcements table, Dismissals table.
- **Publishes**: `AnnouncementPublished` (→ Notifications if email opted-in).
- **Consumes**: `GroupSoftDeleted` (hide group announcements).

### 9. Notifications Service  (`/notifications`)  — Module 8 (notifications)
- **Responsibilities**: email (SES, retry/backoff) + in-portal notifications; enforce US-8.15 recipient matrix + preferences; in-portal panel (latest 20 unread).
- **Owns**: In-portal notifications table, Preferences table.
- **Publishes**: none.
- **Consumes**: most domain events (mentions, replies, decisions, tier, RSVP/calendar invites, group membership, announcements, account) via EventBridge → SQS (durable) → SES/in-portal.

### 10. Platform / Settings Service  (`/settings`)  — Module 8 (settings) + Module 11 config
- **Responsibilities**: admin settings (Cognito sync schedule read-only pool info, community access/OTP/session, MS Teams, Bedrock model id, LLM dup toggle, What's New feed URL+toggle, email sender+templates, branding, default tz, audit toggle), external file-share links (S3 presign), time-zone defaults.
- **Owns**: Settings table, Email-templates table, File-share links table.
- **Publishes**: `SettingsChanged`.
- **Consumes**: none critical.

### 11. Help Assistant Service  (`/help`)  — Module 9
- **Responsibilities**: scoped conversational assistant (portal-only), grounded via AI Gateway (RAG design deferred), role-aware answers, refuses out-of-scope/implementation questions.
- **Owns**: (stateless; session-only history client-side) optional KB index (may reuse Search).
- **Consumes**: AI Gateway.

### Frontend — React + Vite SPA (S3 + CloudFront)
- Single SPA, feature-folder per module, shared design-system component library, role-aware routing/layout (admin/leader/ugl/member), matches mockups (fidelity B). **What's New feed (Module 11)** is client-side only (fetch/parse CORS RSS; sanitize HTML) — no backend service, only Settings config.

---

## Orchestration patterns
- **Sync REST**: client → API Gateway → service Lambda. Service-to-service sync calls minimized; used only for read-time lookups (e.g., Forums @mention autocomplete checks group access via Identity).
- **Async choreography (preferred)**: services publish domain events to EventBridge; interested services react (e.g., attendance → points → tier → notification). No central orchestrator; eventual consistency (last-write-wins).
- **CDC**: each service's DynamoDB Streams feed its own rollups and Search/Analytics projections.
- **Durable work**: SQS queues (with DLQs) for SES email and embedding generation.
