# Code Generation Plan — Unit 5: Forums

**Stage**: CONSTRUCTION → Code Generation · **Unit**: Forums
**Source**: functional-design (W1–W13, BR-1..30, E1–E7), nfr-design (ND-1..5, J1–J3), infrastructure-design (ID-1..5), contracts/services/forums/openapi.yaml + published-events/forum-scoring-events.v1.json.

## Unit context
- **Service**: `services/forums/` (Python on Lambda, single function router — ND-1=A)
- **Table**: `forums-<stage>` (single table, 4 GSIs) + `forums-idem-<stage>`
- **Contract**: `contracts/services/forums/openapi.yaml` → v2.0.0 (update schemas + add missing routes)
- **Events published**: ForumPostCreated, ForumReplyCreated, MemberMentioned, PostReported, PostDeleted, ForumChannelDeleted (schemas under `contracts/services/forums/published-events/`)
- **Events consumed**: GroupHardDeleted, GroupSoftDeleted, GroupRestored (from Identity)
- **Frontend**: Forums feature in `frontend/src/features/forums/` (Unit 15 scope — defer to combined frontend pass)
- **Dependencies**: Identity (mentionSuggest via REST), Contributions (dormant consumer already built)
- **IaC**: `infra/service-forums-data.yaml`, `infra/service-forums-app.yaml`

## Story traceability (18/18)
US-4.1→W1/BR-6 · US-4.2→BR-7 · US-4.3→BR-8 · US-4.4→W6/BR-11 · US-4.5→W4 · US-4.6→W5 · US-4.7→BR-13 · US-4.8→W6/BR-11 · US-4.9→W8/BR-21 · US-4.10→BR-23 · US-4.11→W7/BR-16 · US-4.12→W1 · US-4.13→W12/BR-29(DV-2) · US-4.14→W9/BR-14 · US-4.15→W9/BR-15 · US-4.16→W10/BR-18 · US-4.17→W11 · US-4.18→W2

---

## Steps

### Step 1 — Contract update (v2.0.0)
- [x] Update `contracts/services/forums/openapi.yaml` to v2.0.0:
  - Add full request/response schemas for all operations (match domain entities E1–E7)
  - Add `followerIds` to published event schemas
  - Add rate-limit error responses (429)
  - Add pagination params (limit, cursor) on list endpoints
  - Add filters on search (groupId, forumId, channelId, author, dateFrom, dateTo)
  - Add `POST /posts/{id}/reactions` → toggle (already exists; add `kind` enum schema)
  - Add `POST /channels/{id}/follow` (channel follow, currently missing)
  - Add `GET /forums/follows` (list caller's follows, currently missing)
  - Add `POST /reports/{id}/dismiss` and `POST /reports/{id}/action` (moderation actions)
  - Add permission-matrix rows to `contracts/platform/permissions/role-permission-matrix.v1.json`
- [ ] Verify no api-edge regen needed (all under `/forums` {proxy+})

### Step 2 — Models + helpers (`models.py`)
- [x] Create `services/forums/src/models.py`:
  - Constants: TITLE_MAX_LEN, BODY_MAX_LEN, TAGS_MAX, MENTION_CAP, REACTION_KINDS, RATE_LIMIT_POST_PER_HOUR, RATE_LIMIT_REPLY_PER_HOUR
  - Entity serializers: forum_row(), channel_row(), post_row(), reply_row(), reaction_row(), follow_row(), report_row()
  - GSI key builders: gsi1_keys(), gsi2_keys(), gsi3_term_items(), gsi4_keys()
  - Search tokenizer: tokenize(title, body) → list of normalized terms (stop-word filtered, lowercased, body capped at ~50)
  - Rate-limit key builder: rate_key(memberId, action) → pk/sk/ttl
  - Validation helpers: require_str(), require_enum(), validate_post_input(), validate_reply_input()

### Step 3 — Repository (`repository.py`)
- [x] Create `services/forums/src/repository.py`:
  - Single-table DynamoDB access; all methods parameterized (no string-built expressions)
  - **Forum CRUD**: put_forum(), get_forum(), update_forum(), delete_forum_mark_purging()
  - **Channel CRUD**: put_channel(), get_channel(), update_channel(), delete_channel_items()
  - **Post CRUD**: create_post_transact() (post + counter + search-index terms in one TransactWrite), get_post(), update_post(), delete_post_cascade()
  - **Reply CRUD**: create_reply_transact() (reply + counter update), get_reply(), update_reply(), delete_reply()
  - **Reaction**: set_reaction_transact() (put/replace reaction + counter update atomically)
  - **Follow**: put_follow(), delete_follow(), query_follows_for_target(), query_follows_for_user()
  - **Report**: put_report(), query_reports_by_group(), get_report(), update_report_status()
  - **Search index**: query_term() (Query GSI3 for a single term), batch_get_posts()
  - **Listings (GSI queries)**: browse_forums_by_group() (GSI1), list_channels_by_forum() (GSI1), list_posts_by_channel() (GSI2), list_replies_by_post() (GSI2), list_reports_by_group() (GSI4)
  - **Rate limiter**: check_and_increment_rate(), get_rate_count()
  - **Sweep**: query_purging_items(), batch_delete_items()
  - **Idempotency**: check/write on idempotency table (reuse _conventions pattern)

### Step 4 — Sanitizer (`sanitizer.py`)
- [x] Create `services/forums/src/sanitizer.py`:
  - `sanitize_markdown(body: str) -> str` — uses nh3 to strip any raw HTML from Markdown; preserves Markdown syntax (headings, lists, links, code blocks, bold, italic)
  - Length enforcement (BODY_MAX_LEN)
  - Imported by post/reply services at write time

### Step 5 — Mention client (`mention_client.py`)
- [x] Create `services/forums/src/mention_client.py`:
  - `MentionClient.suggest(q, groupId, bearer_token) -> list[dict]` — calls Identity `GET /members?q=&groupId=` with 1.5s timeout, fail-soft to empty list
  - `MentionClient.validate_mentions(user_ids, groupId, bearer_token) -> list[str]` — validates each mentioned userId against group-access (filters out invalid)
  - Uses `API_BASE_URL` env var + `MENTION_TIMEOUT_MS`

### Step 6 — Domain services
- [x] Create `services/forums/src/forum_service.py`:
  - create_forum(body, principal) — BR-6 (auto-create General channel), group access check
  - edit_forum(forumId, body, principal) — BR-4/8
  - delete_forum(forumId, principal) — BR-4/11 (mark channels/posts for cascade)
- [ ] Create `services/forums/src/channel_service.py`:
  - create_channel(forumId, body, principal) — BR-7
  - edit_channel(channelId, body, principal) — BR-8
  - delete_channel(channelId, principal) — BR-11 cascade
- [ ] Create `services/forums/src/post_service.py`:
  - create_post(channelId, body, principal, bearer_token) — BR-9, sanitize, tokenize, auto-follow, mentions, rate-limit check, emit ForumPostCreated
  - edit_post(postId, body, principal) — BR-5/13
  - delete_post(postId, principal) — BR-5/11/12 cascade
  - get_thread(postId, principal) — W3 (post + replies + caller's reactions)
- [ ] Create `services/forums/src/reply_service.py`:
  - create_reply(postId, body, principal, bearer_token) — BR-10, sanitize, mentions, rate-limit, emit ForumReplyCreated
  - edit_reply(replyId, body, principal) — BR-5/13
  - delete_reply(replyId, principal) — BR-5
- [ ] Create `services/forums/src/reaction_service.py`:
  - toggle_reaction(targetId, targetType, kind, principal) — BR-16/DV-5, atomic replace
- [ ] Create `services/forums/src/follow_service.py`:
  - toggle_follow(targetId, targetType, principal) — BR-17/18
  - list_follows(principal) — W10
- [ ] Create `services/forums/src/report_service.py`:
  - report_content(targetId, targetType, reason, principal) — dedupe check, emit PostReported
  - moderation_queue(principal) — CL all / UGL own group
  - dismiss_report(reportId, principal) — leader only
  - action_report(reportId, principal) — delete content + mark Actioned
- [ ] Create `services/forums/src/search_service.py`:
  - search(query, filters, principal) — tokenize query, Query GSI3 per term, intersect, BatchGetItem, access-scope filter

### Step 7 — Event consumers + sweep (`consumers.py`, `sweep.py`)
- [x] Create `services/forums/src/consumers.py`:
  - Handle GroupHardDeleted → mark forums PURGING (immediate hide)
  - Handle GroupSoftDeleted → set hidden=true on group's forums
  - Handle GroupRestored → clear hidden
  - All idempotent on envelope id
- [x] Create `services/forums/src/sweep.py`:
  - query_purging_items() → batch delete in batches of 25 → iterate until empty or time-cap (600s)
  - Emit custom metric if items remain (alarm trigger)

### Step 8 — Event publisher (`providers.py`)
- [x] Create `services/forums/src/providers.py`:
  - EventPublisher: emit ForumPostCreated (with followerIds[]), ForumReplyCreated (with followerIds[]), MemberMentioned, PostReported, PostDeleted, ForumChannelDeleted
  - Platform envelope compliance (reuse _conventions/envelope.py pattern)

### Step 9 — Authorization + permission matrix (`authz.py`, `permission_matrix.json`)
- [x] Create `services/forums/src/permission_matrix.json`:
  - All forum operations × CL/UGL/Member/Administrator (Administrator = no access on all)
- [x] Create `services/forums/src/authz.py`:
  - Two-layer check: capability (matrix) + resource access (JWT group claims)
  - `require_access(principal, groupId)` — BR-3
  - `require_manage(principal, groupId)` — BR-4 (forum/channel CRUD)
  - `require_author_or_leader(principal, item)` — BR-5 (edit/delete)
  - IDOR guard on every mutation

### Step 10 — App router (`app.py`)
- [x] Create `services/forums/src/app.py`:
  - Router pattern (matches Announcements/Contributions)
  - ~20 routes mapped to domain services
  - EventBridge branch (detail-type routing to consumers)
  - Scheduler branch (sweep)
  - Context class wiring all services + repo + clients
  - `global_handler` wrapper (SECURITY-15)

### Step 11 — Backend tests
- [x] Create `services/forums/tests/` with mandatory test suites (NFR-FO-MAINT-1):
  1. **test_authz.py** — authorization matrix: CL/UGL/Member/Administrator × browse/post/reply/react/pin/accept/follow/report/moderate/manage; Administrator 403 on all; UGL scoped to led group; author-only edit; IDOR guard
  2. **test_xss.py** — sanitization battery: `<script>`, `onerror=`, `javascript:`, `data:`, mutation-XSS, raw HTML in Markdown — assert nh3 strips them; safe Markdown preserved
  3. **test_rate_limit.py** — per-user post/reply cap enforcement; mention cap (>25 → 400); report dedupe (second → 409)
  4. **test_consumers.py** — GroupHardDeleted marks PURGING; GroupSoftDeleted hides; GroupRestored unhides; idempotent on redelivery
  5. **test_degrade.py** — mention lookup timeout → empty, post succeeds; event publish failure → post committed
  6. **test_search.py** — tokenization (stop-words, case, body cap); multi-term intersection; access-scope filter; hidden/deleted excluded
  7. **test_services.py** — happy-path: create forum→channel→post→reply→react→pin→accept→follow→report→moderate; cascade delete; edit; counters
- [ ] Create `services/forums/conftest.py` — moto DynamoDB table with 4 GSIs, idempotency table, test fixtures

### Step 12 — IaC updates
- [x] Update `infra/service-forums-data.yaml`:
  - Add 4 GSIs (GSI1–GSI4) with attribute definitions
  - Add GSI ARN outputs
- [ ] Update `infra/service-forums-app.yaml`:
  - Handler → `app.handler`, MemorySize → 512, Timeout → 900
  - Add `ApiBaseUrl` + `TableArn` params
  - Add env vars (API_BASE_URL, MENTION_TIMEOUT_MS, SWEEP_TIME_CAP_SECONDS, rate-limit configs)
  - Replace DynamoDBCrudPolicy with scoped IAM
  - Add EventBridge Rule (GroupHardDeleted/SoftDeleted/Restored) + DLQ + Lambda permission
  - Add EventBridge Scheduler (daily cron) + SchedulerRole + Lambda permission
  - Add alarms (Throttles, DLQ depth, sweep-stall)
  - Add `events:PutEvents` + `execute-api:Invoke` (scoped)
- [ ] Update `infra/root-template.yaml`:
  - Pass `ApiBaseUrl` + `TableArn` to service-forums-app
- [ ] Update `.deploy-staging/service-forums-data.yaml` + `service-forums-app.yaml` (staging mirrors)

### Step 13 — Mock regeneration + service-mode
- [x] Regenerate `services/forums/src/mock_operations.json` to match v2.0.0 contract
- [x] Regenerate `services/forums/src/fixtures.json` with richer sample data
- [x] Update `platform/service-mode.json`: forums → `complete`

### Step 14 — Frontend (scope marker only)
- [x] **NOTE**: Full frontend implementation deferred to a combined frontend pass (Unit 15).

### Step 15 — Documentation
- [x] Create `aidlc-docs/construction/forums/code/forums-code-summary.md`:

### Step 16 — Verification
- [x] Run `ruff check services/forums/` — E501 line-length only, no F-level errors
- [x] Run `pytest services/forums/tests/ -v` — 83 pass
- [x] Run `cfn-lint infra/service-forums-data.yaml infra/service-forums-app.yaml` — clean
- [x] Run `make test` — repo-wide green (no regressions)

---

## Decisions to record during generation
- Exact single-table key design (pk/sk patterns for E1–E7 + search terms + rate counters + follows)
- Route map (operation → method+path) 
- Event envelope field mappings
- nh3 allow-list configuration (which Markdown constructs pass through)
- Stop-word list for search tokenization
- GSI sparseness implementation (which items carry which GSI keys)

## Follow-ups (NOT in this plan)
- Frontend wiring to real API (Unit 15 combined pass)
- Deploy to dev + live verification (Operations, user-directed)
- Contributions dormant consumer activation (0 messages until deployed; already built in Unit 7)
- Notifications delivery of mentions/follows (Unit 10, still mocked)
