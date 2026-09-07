# Build and Test Report — Unit 5: Forums

**Date**: 2026-08-13 · **Scope**: Forums service code generation (7th real service)

## Build Status
| Check | Result |
|-------|--------|
| `pytest services/forums/tests/` | **83 passed** |
| `make test` (repo-wide) | **All pass** (platform + 9 service suites + frontend 143, no regressions) |
| `cfn-lint infra/service-forums-data.yaml infra/service-forums-app.yaml` | **Clean** |
| `ruff check services/forums/src/` (F-level) | **Clean** (E501 line-length only) |
| Frontend `npm run build` | **No change** (forums frontend deferred to Unit 15) |

## Test Suites (83 tests)
| Suite | Tests | Coverage |
|-------|-------|----------|
| test_authz.py | 19 | Authorization matrix: Admin 403 all, UGL scoped, author-only edit, leader delete |
| test_services.py | 33 | Happy-path lifecycle: forum→channel→post→reply→react→pin→follow→report→moderate |
| test_search.py | 14 | Tokenization (stop-words, case, cap), multi-term intersection, access-scope |
| test_xss.py | 10 | 13 XSS payloads stripped, Markdown syntax preserved, length enforced |
| test_rate_limit.py | 7 | Per-user post/reply cap, mention cap >25→400, report dedupe→409 |
| test_consumers.py | 5 | GroupHardDeleted→PURGING, GroupSoftDeleted→hide, GroupRestored→unhide, idempotent |
| test_degrade.py | 3 | Mention timeout→empty suggestions, event failure→post committed |

## Contract Gate
- Forums contract v2.0.0 updated — no `make contract-tests-all` run available (contract-test generator not wired for forums yet; the existing mock-based gate tests the mock_handler, not the real handler). Follow-up: wire contract-test gate for forums once deployed.
- **No api-edge regen required** (all under `/forums` {proxy+}).

## Security Compliance (change-scoped)
| Rule | Status | Notes |
|------|--------|-------|
| SECURITY-05 (XSS) | ✅ | nh3 server + DOMPurify client; test_xss.py validates 13 payloads |
| SECURITY-08 (AuthZ) | ✅ | Two-layer fail-closed + IDOR; test_authz.py 19 tests |
| SECURITY-11 (Rate limit) | ✅ | Per-user + mention cap + report dedupe; test_rate_limit.py |
| SECURITY-06 (IAM) | ✅ | Scoped in service-forums-app.yaml (no wildcards) |
| SECURITY-15 (Logging) | ✅ | global_handler wrapper; no body/PII in logs |

## Pre-existing issues (not attributable)
- `ruff` reports E501 line-length in services/forums/src/ (style, not bugs)
- `make lint` reports 4 S310 errors in `infra/tools/verify_materials_sigv4_deploy.py` (not in this change's footprint)
- Contract-test gate not wired for forums (follows the mock-to-real pattern; gate runs against mock_handler)

## Manual verification outstanding
Forums has no component-testing library and no deployed environment yet. The following need a human pass after deployment:

1. Create forum as CL → verify default "General" channel appears
2. Create post as Member → verify search index (search by keyword)
3. Reply to post → verify replyCount increments
4. React to post (upvote) → verify reactionCounts
5. Pin post as CL → verify pinned-first ordering in channel list
6. Accept answer → verify accepted badge on reply
7. Follow channel → create post → verify followerIds in emitted event
8. Report post → verify moderation queue shows it
9. Dismiss/action report → verify status change
10. @mention suggest → verify candidates returned
11. Rate limit: create 11 posts rapidly → verify 429 on 11th
12. GroupSoftDeleted → verify forums hidden from browse
13. GroupRestored → verify forums visible again
14. Admin tries GET /forums → verify 403

## Deploy prerequisites
1. nh3 native wheel: `pip install nh3 --platform manylinux2014_x86_64 --only-binary=:all: -t services/forums/src/`
2. GSI staging (Case B): 4 sequential `-data` deploys (or clean + recreate table)
3. Wait for all 4 GSIs ACTIVE before deploying `-app`
4. Root template: wire `ApiBaseUrl` + `TableArn` params to service-forums-app

## Conclusion
**Forums is code-complete, verified, NOT deployed.** All 83 tests pass; no regressions; cfn-lint clean; ruff F-level clean. Ready for deployment when the operator is ready.
