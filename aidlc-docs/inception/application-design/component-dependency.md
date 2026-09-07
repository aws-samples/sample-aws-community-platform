# Component Dependencies — AWS Community Portal

Communication legend: **[S]** synchronous REST (request-time) · **[E]** asynchronous domain event via EventBridge · **[C]** DynamoDB Streams CDC · **[Q]** SQS durable async. Each service owns its own table(s) (Q5); no shared database.

---

## Service dependency matrix

| Service ↓ depends on → | Identity | Members | Events | Forums | Certs | Contrib | Analytics | Announce | Notif | Settings | Search | AI Gw |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Identity & Access** | — | | | | | | | | E→ | S (read settings) | | |
| **Member Profiles** | E (user lifecycle) | — | | | | | | | | | S (index/query) | via Search |
| **Events** | S (group/role check) | | — | | | E→Contrib | | | E→Notif | S (settings/Teams cfg) | | |
| **Forums** | S (group access) | S (mention target) | | — | | E→Contrib | | | E→Notif | S (dup toggle) | S (index/search) | S (dup detect) |
| **Certifications** | E (member left) | | | | — | E→Contrib | | | E→Notif | | | |
| **Contributions** | E (member left, group del) | | E (attendance/deliver/organize) | E (post/reply) | E (cert approved) | — | C→Analytics | | E→Notif | S (framework? no) | | |
| **Analytics** | C/E (membership hist) | C | C/E | C/E | C/E | C/E | — | | | | S | S (report/insights) |
| **Announcements** | E (group del) | | | | | | | — | E→Notif | S (email cfg) | | |
| **Notifications** | E | E | E | E | E | E | | E | — | S (templates/sender) | | |
| **Settings** | | | | | | | | | | — | | |
| **Search** | | E/C (member idx) | | E/C (forum idx) | | | | | | S (Bedrock model) | — | S (embed) |
| **AI Gateway** | | | | | | | | | | S (model id) | | — |

Notes:
- Sync service-to-service calls are **minimized**; used only where a request must read another context at request-time (e.g., Forums→Identity group-access on @mention; Events→Identity role/group check). All point/notification/index side-effects are **asynchronous** to keep services decoupled and resilient (RESILIENCY-10 timeouts + graceful degradation).
- **Analytics** is read-only: it never calls back; it projects from Streams/events.
- **Contributions** is the only writer of the point ledger; other services never write points directly — they emit events.

---

## Communication patterns

1. **Client → API Gateway → Service Lambda** [S]: Cognito authorizer validates JWT; handler runs shared AuthZ guard; response carries security headers.
2. **Domain choreography** [E]: a service publishes a domain event; interested services subscribe via EventBridge rules. No central orchestrator; eventual consistency; last-write-wins.
3. **CDC projections** [C]: each service's DynamoDB Streams feed its own rollups (Contributions) and the Search/Analytics projections.
4. **Durable async** [Q]: EventBridge → SQS (with DLQ) for SES email sends and embedding generation, so transient failures retry without blocking the request path.

---

## Key data-flow scenarios (text sequence diagrams)

### Scenario A — Record attendance → award points → tier → notify
```
Creator → API GW → Events.AttendanceRecorder.record()   [S]
Events → EventBridge: AttendanceRecorded                 [E]
Contributions.AutoAwardConsumer ← AttendanceRecorded     [E]
  → LedgerWriter.append(entry)   (Member-only; group/equal-split attribution)
Contributions table Stream → RollupProjector             [C]  (per-group/quarter rollup; late-quarter recompute)
Contributions → EventBridge: PointsAwarded / TierAchieved[E]
Notifications.EventRouter ← TierAchieved                 [E] → PreferenceFilter → SES [Q] + InPortalStore
Analytics.AnalyticsProjector ← Stream/PointsAwarded      [C/E] (dashboards refresh on read)
```

### Scenario B — Create forum post (with dup detection) → index → award
```
Member → API GW → Forums.PostManager.create()            [S]
Forums → AI Gateway.detectDuplicate()                    [S] (fail-closed: reject on error/timeout if enabled)
Forums table Stream / event: ForumPostCreated            [C/E]
Search.IndexWriter.upsert(post)  ← via SQS embedding      [Q]→[S embed via AI Gw]
Contributions.AutoAwardConsumer ← ForumPostCreated       [E] → LedgerWriter.append (author Member only)
Notifications ← MemberMentioned (if @mention)            [E] → SES/in-portal
```

### Scenario C — Certification approved → per-cert points
```
Leader → API GW → Certifications.VerificationQueue.decide(approve) [S]
Certifications → EventBridge: CertificationApproved (per-cert points, credited group) [E]
Contributions.AutoAwardConsumer ← CertificationApproved  [E] → LedgerWriter.append
Certifications → Notifications ← decision                [E] → SES/in-portal
```

### Scenario D — Group hard-delete (after 2-week grace)
```
Identity.GroupManager.hardDelete() (scheduled after grace)
Identity → EventBridge: GroupHardDeleted                 [E]
Contributions ← GroupHardDeleted  → remove group ledger entries (lifetime totals reduced)
Forums ← GroupHardDeleted → delete content + Search.IndexWriter.delete()  [E→S]
Search removes embeddings; Analytics projections updated  [C]
```

### Scenario E — Member semantic search
```
Member → API GW → Members.DirectoryQuery / SearchService.query("members", q) [S]
Search.QueryEngine → AI Gateway.embed(q) [S] → OpenSearch kNN → ranked hits
```

---

## Dependency principles
- **Acyclic at request-time**: sync dependencies form a DAG (edge services depend on Identity/Search/AI, not vice-versa). Cyclic needs are resolved via async events, not sync calls.
- **Contributions & Analytics decoupling**: Analytics never blocks Contributions; it consumes events/Streams.
- **Notifications is a pure sink** of events (+ Settings for templates).
- **Search & AI Gateway are shared leaf dependencies** (no domain callbacks).
- **Failure isolation** (RESILIENCY-10): sync cross-service calls have timeouts + graceful degradation (e.g., mention autocomplete degrades to no-suggestions; AI insights show stale-with-timestamp; dup detection fails closed by requirement).
