# Component Methods — AWS Community Portal

High-level **interface contracts** (method signatures + purpose + I/O). Language-neutral signatures (map to each service's application handlers / REST operations, regardless of the service's implementation language — Python, Node.js, or Rust, decided at Construction). **Business rules are deferred to per-unit Functional Design.** Signatures are representative of each service's primary operations, not an exhaustive list of all 144 stories' endpoints. Types like `Principal`, `Page<T>`, `Result` come from the shared per-language libraries; every method is guarded by the AuthZ library first (fail-closed).

Convention: `METHOD path → Component.method(input) : output` (maps to REST + application handler).

---

## Shared: AuthZ (`auth.Authorizer`)
- `authorize(principal: Principal, action: Action, resource: ResourceRef) : Result<()>` — object/function-level check; err→403.
- `require_group_scope(principal, group_id) : Result<()>` — UGL/CL scoping.

## Shared: Events (`events.EventBus`)
- `publish(event: DomainEvent) : Result<()>` — to EventBridge.
- `enqueue(work: AsyncWork) : Result<()>` — to SQS.

---

## 1. Identity & Access
- `POST /auth/login → CognitoAdapter.login(email, password) : AuthChallenge | Session` — may return OTP challenge (US-1.32).
- `POST /auth/otp → CognitoAdapter.verifyOtp(session, code) : Session`.
- `POST /auth/local-admin/login → LocalAdminAuth.login(email, password) : Session`.
- `POST /auth/local-admin/reset → LocalAdminAuth.requestReset(email) : Ack` / `LocalAdminAuth.setPassword(token, newPw) : Ack`.
- `POST /auth/logout → SessionManager.logout(principal) : Ack`.
- `GET /users → UserAdmin.list(filter, page) : Page<UserSummary>` (Admin).
- `PUT /users/{id} → RoleChangeHandler.editUser(principal, id, {role, groups, profileFields}) : User` (US-1.26; suspend-not-destroy).
- `POST /users/import → BulkImporter.import(file) : ImportReport` (Admin).
- `POST /users/{id}/disable → UserAdmin.setEnabled(id, false) : Ack` / enable.
- `POST /groups → GroupManager.create(principal, {name, desc, leaders, approvalRequired}) : Group` (CL).
- `PUT /groups/{id} → GroupManager.edit(principal, id, patch) : Group` (CL).
- `DELETE /groups/{id} → GroupManager.softDelete(principal, id) : Ack` / `restore(id)`.
- `POST /groups/{id}/join → GroupManager.join(principal, id) : Membership | JoinRequest`.
- `POST /groups/{id}/leave → GroupManager.leave(principal, id) : Ack`.
- `POST /groups/{id}/leaders → GroupManager.assignLeader(principal, id, memberId) : Ack` (CL; one-group rule).
- `GET /groups/{id}/requests → JoinRequestManager.list(principal, id) : Page<JoinRequest>`.
- `POST /groups/{id}/requests/{rid} → JoinRequestManager.decide(principal, rid, approve|reject, reason?) : Ack`.
- (internal) `MembershipHistoryWriter.record(memberId, groupId, type, ts)` ; `SyncJob.run()` (scheduled).

## 2. Member Profiles & Directory
- `GET /members/me → ProfileManager.getOwn(principal) : Profile`.
- `PUT /members/me → ProfileManager.updateOwn(principal, patch) : Profile` (emits `MemberProfileUpserted`).
- `GET /members/{id} → ProfileManager.getPublic(principal, id) : PublicProfile` (non-Admin; read-only).
- `GET /members → DirectoryQuery.browse(filter, page) : Page<DirectoryRow>`.
- `GET /members/search → (delegates) SearchService.query("members", q, filter) : Page<DirectoryRow>`.
- `GET /admin/members → AdminMemberList.list(filter, page) : Page<AdminRow>` / `export(filter) : CsvUrl` (Admin, identity-only).
- `GET /members/{id}/activity → ActivitySummaryAssembler.get(principal, id, range) : ActivitySummary` (leaders only).

## 3. Events
- `POST /events → EventManager.create(principal, dto) : Event` (CL any / UGL led group).
- `PUT /events/{id} → EventManager.edit(principal, id, patch) : Event` / `DELETE cancel` / `POST complete`.
- `POST /events/recurring → RecurrenceExpander.createSeries(principal, dto) : [Event]` (occurrences).
- `POST /events/{id}/rsvp → RsvpManager.rsvp(principal, id, yes|no) : Ack` (emits invite/.ics).
- `GET /events/{id}/rsvps → RsvpManager.list(principal, id) : Page<Rsvp>` / `export`.
- `GET /events, GET /events/{id}, GET /events/calendar → EventQuery.*` (role-scoped).
- `POST /events/{id}/materials → MaterialsManager.add(principal, id, file|link) : Material`.
- `POST /events/{id}/attendance → AttendanceRecorder.record(principal, id, entries|file) : Ack` (emits `AttendanceRecorded`).
- `POST /events/{id}/attendance/teams → TeamsAttendanceMatcher.fetchAndReview(id) : MatchReview` → `apply(review) : Ack`.
- `PUT /events/{id}/designations → DesignationManager.set(principal, id, {presenters[], organizers[]}) : Ack`.
- `GET /events/content-library → ContentLibrarySearch.search(principal, q, filters, page) : Page<Content>`.
- `POST /events/{id}/upload-links → UploadLinkManager.create(principal, id, {expiry, maxSize}) : ShareLink` / `revoke`.

## 4. Forums
- `POST /forums, /forums/{id}/channels → ForumChannelManager.create/edit/delete(...)` (CL any / UGL led).
- `POST /channels/{id}/posts → PostManager.create(principal, id, {title, body, images}) : Post` (runs `DuplicateChecker` if enabled, fail-closed; emits `ForumPostCreated`).
- `POST /posts/{id}/replies → ReplyManager.create(principal, id, body) : Reply` (emits `ForumReplyCreated`).
- `PUT/DELETE /posts/{id} → PostManager.editOwn/delete(...)` (author or leader; delete→remove index).
- `POST /posts/{id}/reactions → ReactionManager.toggle(principal, id, kind) : Ack`.
- `GET /forums/mention-suggest → MentionResolver.suggest(principal, postId, q) : [Member]` (access-scoped).
- `POST /posts/{id}/accept/{replyId} → AcceptedAnswerManager.mark(...)`.
- `POST /posts/{id}/pin → PinManager.pin/unpin(...)` (leaders).
- `POST /channels/{id}/follow, /posts/{id}/follow → FollowManager.toggle(...)`.
- `POST /posts/{id}/report → ModerationQueue.report(...)` ; `GET /forums/moderation → ModerationQueue.list(principal) : Page<Report>`.
- `GET /forums/search → (delegates) SearchService.query("forum", q, filter)`.

## 5. Certifications
- `POST /certifications → CertificationDefManager.create(principal, {..., points}) : Certification` (CL) / edit / deactivate.
- `GET /certifications/catalog → Catalog.list(principal) : [Certification]`.
- `POST /certifications/{id}/claims → ClaimManager.submit(principal, id, {creditedGroup, evidence}) : Claim` / `withdraw`.
- `GET /certifications/claims/me → ClaimManager.listOwn(principal) : [Claim]`.
- `GET /certifications/verifications → VerificationQueue.list(principal) : Page<Claim>` (credited-group routing).
- `POST /certifications/claims/{id}/decision → VerificationQueue.decide(principal, id, approve|reject, reason?) : Ack` (approve emits `CertificationApproved` with per-cert points).
- `POST /certifications/{id}/revoke → RevocationManager.revoke(principal, memberId, reason) : Ack`.
- (internal) `ExpiryJob.runDaily()`.

## 6. Contributions & Scoring
- `GET/PUT /contributions/framework → ScoringFramework.get/update(principal, config) : Framework` (CL; fixed 6 auto enforced).
- `POST /contributions/submissions → SubmissionManager.submit(principal, {activity, group, evidence}) : Submission` / `withdraw`.
- `GET /contributions/submissions/me → SubmissionManager.listOwn(principal) : [Submission]`.
- `GET /contributions/approvals → ApprovalManager.listPending(principal) : Page<Submission>`.
- `POST /contributions/submissions/{id}/decision → ApprovalManager.decide(principal, id, approve|reject, reason?) : Ack` (approve → `LedgerWriter.append`).
- `POST /contributions/adjustments → AdjustmentManager.adjust(principal, {member, group, delta, reason}) : Ack` (emits `PointsAdjusted`).
- `GET /contributions/me → PointsQuery.own(principal, quarter?, group?) : PointsView` (runtime tier).
- `GET /contributions/leaderboard → LeaderboardQuery.get(principal, group, quarter, pillar?) : Leaderboard`.
- `GET /contributions/summary/{group|community} → SummaryQuery.get(principal, scope, range) : Summary` / `export`.
- (internal consumers) `AutoAwardConsumer.on(AttendanceRecorded|EventDelivered|EventOrganized|ForumPostCreated|ForumReplyCreated|CertificationApproved)` ; `RollupProjector.onStream(entries)` (late-quarter recompute); `TierCalculator.compute(member, group, quarter) : Tier` (runtime).

## 7. Analytics
- `GET /analytics/dashboard/{community|group} → DashboardAssembler.get(principal, scope, quarter) : Dashboard`.
- `GET /analytics/charts/{type} → ChartDataProvider.get(principal, scope, params) : ChartData`.
- `GET /analytics/export/{contribution|member|event} → CsvExporter.export(principal, scope, range) : CsvUrl`.
- `POST /analytics/ai/report → AIReportAgent.ask(principal, question) : ReportAnswer` (role-scoped; guardrails).
- `GET /analytics/ai/insights → InsightsBatch.latest(principal, scope) : [Insight]` (stale-with-timestamp fallback).
- (internal) `AnalyticsProjector.onStream(...)`, `MembershipGrowthProjector.onEvent(...)`, `InsightsBatch.runDaily()`.

## 8. Announcements
- `POST /announcements → AnnouncementManager.create(principal, {title, body, audience, expiry, emailOptIn}) : Announcement` (emits `AnnouncementPublished` if email).
- `PUT/DELETE /announcements/{id} → AnnouncementManager.edit/delete(...)` (author; CL moderation delete-any).
- `GET /announcements/panel → PanelQuery.forUser(principal) : [Announcement]` (audience-scoped).
- `POST /announcements/{id}/dismiss → DismissalStore.dismiss(principal, id) : Ack`.

## 9. Notifications
- `GET /notifications → InPortalStore.list(principal) : Panel(latest20)` / `POST /{id}/read`.
- `GET/PUT /notifications/preferences → PreferenceManager.get/update(principal, prefs) : Prefs`.
- (internal) `EventRouter.on(DomainEvent) : [Recipient]` (US-8.15 matrix) → `PreferenceFilter` → `EmailSender.send()` (SES, retry/DLQ) + `InPortalStore.push()`.

## 10. Platform / Settings
- `GET/PUT /settings → SettingsManager.get/update(principal, section, values) : Settings` (Admin; emits `SettingsChanged`).
- `GET/PUT /settings/email-templates → EmailTemplateManager.*` (preview/save).
- `POST /settings/file-share → FileShareManager.create(principal, {folder, expiry, maxSize}) : ShareLink` / `revoke` / `listFiles`.
- `PUT /settings/timezone (system default) → TimeZoneDefaults.set(...)`.

## 11. Help Assistant
- `POST /help/ask → HelpAnswerer.ask(principal, message, sessionCtx) : Answer` (ScopeGuard refuses out-of-scope/implementation).

## Shared cross-cutting service methods
- **Search**: `IndexWriter.upsert(kind, id, doc)` / `delete(kind, id)` ; `QueryEngine.query(kind, text, filter, page) : Page<Hit>`.
- **AI Gateway**: `embed(text) : Embedding` (vector of floats) ; `detectDuplicate(post, candidates) : DupResult` (fail-closed) ; `report(scopeCtx, question) : ReportAnswer` ; `insights(scopeCtx) : [Insight]` ; `helpAnswer(ctx, q) : Answer`.
- **Notifications** (above). **Audit**: `AuditLogger.log(actor, action, ts, ip)`.
