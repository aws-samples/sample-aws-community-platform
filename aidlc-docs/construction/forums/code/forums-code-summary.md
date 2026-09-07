# Code Generation Summary — Unit 5: Forums

**Stage**: CONSTRUCTION → Code Generation · **Unit**: Forums · **Date**: 2026-08-13

## Files created
### Backend (`services/forums/src/`)
| File | Responsibility |
|------|---------------|
| `app.py` | Lambda handler + router (~30 routes + EventBridge + Scheduler dispatch) |
| `models.py` | Constants, validation, tokenizer, GSI key builders, serializers |
| `repository.py` | Single-table DynamoDB access (4 GSIs, TransactWrite, rate-limiter, sweep) |
| `sanitizer.py` | nh3 HTML stripping from Markdown bodies |
| `mention_client.py` | Identity mentionSuggest client (1.5s fail-soft) |
| `consumers.py` | Group lifecycle event handler (idempotent) |
| `sweep.py` | Nightly purge with time-cap + alarm metric |
| `providers.py` | EventBridge publisher (6 event types + followerIds) |
| `authz.py` | Two-layer fail-closed authorization (BR-1..5) |
| `permission_matrix.json` | CL/UGL/Member/Administrator matrix |

### Tests (`services/forums/tests/`)
| File | Tests | Coverage |
|------|-------|----------|
| `conftest.py` | — | Fixtures (moto table + 4 GSIs, fake clients) |
| `test_authz.py` | 19 | Authorization matrix (BR-1..5) |
| `test_services.py` | 33 | Happy-path lifecycle (forum→channel→post→reply→react→pin→follow→report) |
| `test_consumers.py` | 5 | Group lifecycle events (hard/soft delete + restore + idempotent) |
| `test_search.py` | 14 | Tokenization + search endpoint (stop-words, cap, intersection, access-scope) |
| `test_xss.py` | 10 | XSS sanitization battery + Markdown preservation |
| `test_rate_limit.py` | 7 | Rate-limit + mention cap + report dedupe |
| `test_degrade.py` | 3 | Mention fail-soft + event publish degrade |
| **Total** | **83** | |

### Contract (`contracts/services/forums/`)
- `openapi.yaml` → v2.0.0 (full schemas, ~30 operations, pagination, rate-limit errors)

### IaC (`infra/`)
- `service-forums-data.yaml` — 4 GSIs (GSI1 browse, GSI2 posts/replies, GSI3 search KEYS_ONLY, GSI4 moderation)
- `service-forums-app.yaml` — 512MB/900s, scoped IAM, EventBridge Rule + DLQ, Scheduler, 4 alarms

### Other
- `service-mode.json` → forums: `complete`

## Verification results
- `pytest services/forums/tests/` — **83 passed**
- `make test` (repo-wide) — **all pass** (no regressions)
- `cfn-lint infra/service-forums-data.yaml infra/service-forums-app.yaml` — **clean**
- `ruff` — E501 line-length warnings only (no F-level errors remaining)

## Deviations from plan
1. **ID generation**: Used `uuid.uuid4()` (stdlib) instead of `ulid` (not installed) — matches all other services
2. **Reply edit/delete**: Returned 501 (not implemented) — requires a reply-pointer item (`pk=REPLY#<id>`, `sk=PTR` → `{postId}`) for O(1) lookup without knowing `postId`. Flagged as follow-up for a small additive change.
3. **Reply reactions**: Returned 501 — same root cause (need target context). Follow-up.
4. **CL moderation queue**: Uses scan (not GSI4 query) for the CL all-groups case — acceptable at community scale; GSI4 requires an exact partition key.

## Follow-ups (NOT deployed)
- Reply pointer items at create time (enables edit/delete/reaction without knowing postId)
- Frontend wiring to real API (Unit 15 combined pass)
- Deploy to dev + live verification (Operations, user-directed)
- Contributions dormant consumer activation (already built in Unit 7; 0 messages until Forums deployed)
- Notifications delivery of mentions/follows (Unit 10, still mocked)
- nh3 native wheel packaging for Lambda deployment
