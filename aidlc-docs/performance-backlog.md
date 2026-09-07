# Performance Backlog

Target load: **30,000 registered users, 500+ concurrent users.**
Source: code analysis on 2026-09-07 (hot read paths, DynamoDB access patterns, Lambda/API Gateway config). No code changed yet — this is the prioritized to-do list to work on later.

Legend: `[ ]` = not started. Severity: 🔴 High · 🟠 Medium · 🟡 Low.

---

## [ ] PERF-1 🔴 Eliminate synchronous cross-service fan-out on profile/dashboard views
**Where:** `services/member-profiles/src/profile_service.py` (`getOwnProfile`, `getMember`, `updateOwnProfile` → `_fan_out_basic`); `services/member-profiles/src/activity_service.py` (`memberActivity`); `services/member-profiles/src/fan_out_client.py` (`_DEFAULT_TIMEOUT_SECONDS = 2.5`).

**Problem:** Each profile view issues **4 parallel downstream HTTP calls** (contributions, events, forums, certifications) through API Gateway → one user action = **5 Lambda invocations**. The `contributions` leg (`/contributions/me` → `read_service.own_points`) itself does 4+ sequential DynamoDB reads. At 500 concurrent views this is up to ~2,500 concurrent downstream executions and page latency bounded by the slowest leg (up to 2.5s, worse on cold start).

**Fix direction:** Denormalize rollup/tier/activity counts onto the member-profiles projection (partly event-driven already via `MemberProfileUpserted`) so the common profile view needs **zero** fan-out; or collapse the 4 calls into one internal aggregate endpoint. Biggest win for both latency and the concurrency ceiling (PERF-4).

---

## [ ] PERF-2 🔴 Replace full-table `Scan` on data-growing request paths
**Where:**
- Announcements panel (hottest read — every landing page): `services/announcements/src/repository.py` `scan_all`; `active_set_cache.py` (30s TTL, **per warm container**); `announcement_service.list_moderation` calls `scan_all` directly; `by_author`/`targeting_group` filter in Python after a scan.
- Forums CL browse + reported queue: `services/forums/src/app.py` (~line 311 and ~835) `ctx.repo._table.scan(...)` paging all `FORUM#`/report items (also reaches into `repo._table` directly — layering smell).

**Problem:** Scans grow with total items; many cold containers under 500 concurrency each pay a scan on cache miss.

**Fix direction:** Back the announcement panel and forum/report listings with GSI queries (e.g. active-set GSI keyed by status/expiry; report queue GSI). Keep the `ActiveSetCache`, but make the miss path a bounded query, not a scan.

**Note:** These scans are acceptable and NOT in scope (async/nightly/admin only): member-profiles `all_profiles` (CSV export + nightly reindex), identity-access roster/group scans (nightly counts), settings email-template/file-share scans.

---

## [ ] PERF-3 🟠 Fix N+1 in the leaderboard (hot dashboard widget)
**Where:** `services/contributions-scoring/src/read_service.py` `leaderboard()`.

**Problem:** After the GSI-backed `leaderboard_page`, it loops rows calling `get_member_profile` — **one GetItem per row**. `limit` is capped at 1000 → up to 1,000 sequential GetItems in one request. The sibling `rollups()` already uses `batch_get_l1` (one `BatchGetItem`).

**Fix direction:** Replace the per-row `get_member_profile` with `BatchGetItem` (chunks of 100), mirroring `rollups()`. Small, contained change.

---

## [ ] PERF-4 🔴 Lambda concurrency ceiling & VPC cold starts at 500 concurrent
**Where:** `infra/services/service-identity-access-app.yaml` (`ProvisionedConcurrentExecutions: 1`); account-level Lambda concurrency limit; all interactive API functions are VPC-attached with some `dist/*.zip` at 15–17 MB.

**Problem:**
- Auth path has only **1** provisioned instance → everyone else cold-starts in-VPC on sign-in under load.
- Combined with PERF-1's ~5× amplification, 500 concurrent actions can demand ~2,500 concurrent executions → exceeds the **default 1,000 account limit** → throttling (429/5xx).

**Fix direction:** (a) Request a Lambda concurrency Service Quota increase; (b) raise provisioned concurrency on identity-access (and consider member-profiles read fn); (c) PERF-1 directly reduces the amplification. Background consumers/indexers' reserved caps (10/25/5) are intentional — leave them.

---

## [ ] PERF-5 🟡 Per-invocation overhead & minor hot-partition watch
**Where:** `Context.__init__` in several services (e.g. `services/identity-access/src/app.py`) constructs boto3 clients + reloads `permission_matrix.json` + re-instantiates services per request; contributions leaderboard GSI1 (group+quarter) read hot-partition for a very popular group.

**Fix direction:** Hoist boto3 clients / authorizer / matrix load to module scope for warm reuse (tens of ms/request). Watch the leaderboard GSI partition under load (on-demand + adaptive capacity mostly absorbs it; ~3,000 RCU/partition ceiling). Settings reads are already warm-cached — no action.

---

## Suggested order
1. **PERF-1** (fan-out) — biggest latency + concurrency win; relieves PERF-4.
2. **PERF-4** (quota increase + provisioned concurrency) — quick config wins.
3. **PERF-3** (leaderboard BatchGet) — low-risk, contained.
4. **PERF-2** (scan → GSI for announcements panel + forums browse).
5. **PERF-5** (module-scope clients; monitor hot partition).
