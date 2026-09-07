# Infrastructure Design Plan — Unit 5: Forums

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Forums
Inputs: `construction/forums/functional-design/*`, `construction/forums/nfr-design/*`, `construction/forums/nfr-requirements/*`, shared-infrastructure.md, existing `-data`/`-app` scaffolds (`.deploy-staging/service-forums-{data,app}.yaml`).

## Steps
- [x] 1. Analyze design artifacts
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (below)
- [x] 4. Store plan
- [x] 5. Collect + analyze answers — ID-1..5 all = A (recommended). 2026-08-13.
- [x] 6. Generate artifacts (`infrastructure-design.md`, `deployment-architecture.md`)
- [x] 7. Present completion message
- [x] 8. Await approval — user approved 2026-08-13
- [x] 9. Record approval + update aidlc-state.md

---

## Current scaffold state (`.deploy-staging/`)
**`-data`**: Table (`forums-<stage>`, pk/sk, PITR ✓, SSE ✓, Stream ✓, Retain ✓, **0 GSIs**) + IdempotencyTable (eventId, TTL ✓).
**`-app`**: Fn (mock_handler, 256MB/15s, DynamoDBCrudPolicy broad, ErrorAlarm, ApiInvokePermission). Params: Stage, RestApiId, RootResourceId, EventBusName, TableName, IdempotencyTableName, EnableSemanticSearch, OpsAlarmTopicArn.

## Needed changes (preliminary assessment)
**`-data`**:
- Add GSIs for access patterns (listing by group, channel post-list, user-rsvp/follow, moderation queue, inverted-index search)
- **Constraint**: DynamoDB allows ONE GSI change per UpdateTable → sequential deployments if multiple GSIs
- No TTL needed on main table (forum content doesn't expire)

**`-app`**:
- Handler → `app.handler`
- Memory/timeout: 256MB/60s (to handle the ~60-item TransactWrite + nightly sweep within one function; ND-1=A single function)
- Add `ApiBaseUrl` param (for MentionClient)
- Add EventBridge Rule (GroupHardDeleted/GroupSoftDeleted/GroupRestored) + DLQ
- Add EventBridge Scheduler (nightly sweep)
- Replace broad DynamoDBCrudPolicy with scoped least-privilege IAM
- Add `execute-api:Invoke` for Identity mentionSuggest
- Add `events:PutEvents` 
- Add alarms (throttles, DLQ depth, sweep-stall)
- Remove `EnableSemanticSearch` param (Forums doesn't use semantic search — DV-2)

**Shared infra**: NO changes — Forums has no S3 bucket (DV-4), no new public base path (all under `/forums`), no new Foundation resources.

---

## Questions

### ID-1 — GSI design: how many GSIs and what order?
Based on the data access patterns from the logical-components, Forums needs these query patterns beyond pk/sk:

| Access pattern | Proposed GSI | PK | SK |
|---|---|---|---|
| Browse forums by group + channel list by forum | **GSI1** | `groupId` | `sk` (reuse; type-prefixed items sort naturally) |
| Channel post-list (newest) + thread replies | **GSI2** | `channelId` OR `postId` (overloaded) | `createdAt` |
| Keyword search (inverted index) | **GSI3** (sparse) | `term` (e.g., `TERM#<normalized>`) | `postId` |
| Moderation queue by group | **GSI4** (sparse) | `reportGroupId` (only on Report items) | `createdAt` |

With 4 GSIs and DynamoDB's one-GSI-per-UpdateTable constraint, deployment requires 4 sequential UpdateTable calls (wait ACTIVE between each).

A) **(recommended)** 4 GSIs as above, deployed sequentially (GSI1→GSI2→GSI3→GSI4). Order by criticality: listings first, search next, moderation last.

B) 3 GSIs — merge moderation into the base table access pattern (Query by pk with a report-status filter; works if reports are stored under the group's partition).

C) 2 GSIs — merge browse+listing into one overloaded GSI, keep search GSI separate; handle moderation via base table.

[Answer]:

### ID-2 — Lambda memory/timeout for the single function
The function handles API (fast), EventBridge consumers (fast), AND the nightly sweep (up to 10 minutes at community scale). Options:

A) **(recommended)** **256MB / 60s** — sufficient for the TransactWrite create path (~60 items), event consumers, and the time-capped sweep (10-min cap is enforced in code, not by Lambda timeout; Lambda timeout gives a safety margin for API requests but the sweep self-terminates before 60s on API invocations — the sweep only runs on Scheduler events). Wait — re-reading: the sweep needs MORE than 60s. Revised: **512MB / 900s** on the function, with API routes self-timing at 29s (API GW limit) and the sweep self-capping at 600s.

B) **256MB / 60s** for the function + a separate sweep function with 512MB/900s.

C) **256MB / 900s** — keep memory low but allow the full timeout for sweep.

[Answer]:

### ID-3 — Follow-query pattern for notification fan-out (J3)
When emitting `ForumReplyCreated`/`ForumPostCreated` with `followerIds[]`, the handler queries post/channel follows. This requires a follows access pattern. Options:

A) **(recommended)** Store follows under the target's partition (e.g., `pk=POST#<postId>`, `sk=FOLLOW#<userId>`). Query follows by pk → bounded list. No extra GSI needed for this direction.

B) Store follows under the user's partition (good for "my follows" listing) and use a GSI for the reverse lookup (follows on a target).

C) Both directions via two item patterns (user→target for "my follows" + target→user for fan-out), no GSI.

[Answer]:

### ID-4 — Rate-limit counter storage
Per-user rate-limit counters (D-FO-3) — where to store?

A) **(recommended)** **In the main forums table** as TTL items (e.g., `pk=RATE#<memberId>#post#<hourWindow>`, `sk=RATE`, count attribute, TTL = window end). No extra table; TTL auto-cleans. Adds negligible items.

B) In the idempotency table (reuse the existing TTL table; different key pattern).

C) In-memory only (per-container; resets on cold start — less accurate but zero writes).

[Answer]:

### ID-5 — `EnableSemanticSearch` param: keep or remove?
The scaffold passes `EnableSemanticSearch` from root. Forums' DV-2 says no semantic search — keyword only. But the contract has `x-semantic-search: true` on the search endpoint (for future OpenSearch delegation).

A) **(recommended)** **Keep the param** but ignore it in the handler (always use keyword search). When Unit 13 (Search) is built, Forums can delegate to it behind this flag. No cost; preserves the upgrade path.

B) Remove the param entirely (simplifies; re-add when needed).

[Answer]:
