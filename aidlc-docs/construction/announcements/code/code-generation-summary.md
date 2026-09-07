# Code Generation Summary — Unit 9: Announcements

**Stage**: CONSTRUCTION → Code Generation (Part 2) · **Date**: 2026-08-07 · **Sixth real service.**
Executed all 24 steps of `../../plans/announcements-code-generation-plan.md`. Not deployed in this stage.

## What was built
**Backend (`services/announcements/src/`)** — 10 modules: `app.py` (router + EventBridge branch, fail-closed authz, Administrator-denied), `models.py`, `announcement_service.py`, `panel_query.py`, `active_set_cache.py`, `sanitizer.py` (nh3), `directory_client.py` (1.5s fail-closed), `consumers.py`, `providers.py` (EventPublisher), `repository.py` (single-table, no GSI, TTL). `requirements.txt` adds pinned `nh3==0.2.18`.

**Contract** — `contracts/services/announcements/openapi.yaml` → **v2.0.0**: structured `target{scope,groupIds}`, mandatory-server-defaulted `expiresAt`, rich-text `body`, `emailOptIn`, `view`/`scope` params on `listAnnouncements`, extended `Announcement` schema, **`dismissAnnouncement` removed**. New `published-events/AnnouncementPublished.v1.json`.

**Tests** — 6 files, the 5 mandatory suites (authz matrix, XSS battery, expiry, consumers, degrade + service/panel/repo). **46 tests pass.**

**Frontend (`frontend/`)** — `lib/dismissedAnnouncements.ts` (localStorage), `components/AnnouncementPanel.tsx` (collapsible, DOMPurify-rendered, dismiss), `features/AnnouncementModal.tsx` (CL community/multi-group picker / UGL readonly, required expiry, email toggle), rebuilt `AnnouncementsPage` (role-based columns, CL moderation toggle, Edit/Delete), panel embedded on `DashboardPage` (the landing page for all non-admin roles). `dompurify@^3.1.7` added.

**IaC** — `-data`: TTL on the main table's `ttl` attr (PITR/SSE/Stream already present). `-app`: real `app.handler`, `AWS::Events::Rule` (EventCreated + GroupSoftDeleted/GroupRestored) + SQS DLQ + Lambda permission, `ApiBaseUrl` param + env, least-privilege IAM (own tables CRUD + events:PutEvents + execute-api:Invoke Members/Groups GET + sqs:SendMessage), throttle + DLQ-depth alarms. `root-template.yaml` wired (TableArn + ApiBaseUrl; dropped unused EnableSemanticSearch). `service-mode.json` → announcements **complete**.

**Mock alignment** — regenerated the mock from v2.0.0 (dismiss dropped, 4 ops); `fixtures.json` announcements entry updated to the v2.0.0 shape so the contract gate passes.

## Verification
- `pytest services/announcements/tests` → **46 passed**.
- `ruff check` (src + tests) → clean.
- `cfn-lint` (announcements -data/-app + root-template) → clean.
- Contract gate → announcements **4/4**; all 12 services pass (`make contract-tests-all`).
- `npm run build` → clean (468.38 kB / 131.12 kB gzip).

## Design notes / decisions during generation
- Authorization enforced **inline by role** (matches the working Member Profiles/Events pattern — the permission-matrix JSON is not packaged into service Lambdas), matching matrix semantics.
- **Panel read is self-scoped**: allowed for any authenticated non-Administrator (CL/UGL lack an explicit `view announcement` matrix entry but must see the panel; viewing returns only the caller's own targeted announcements, no cross-user data). No shared matrix edit made.
- `emailSent` is set = `emailOptIn` at create ("dispatched to Notifications"); actual delivery is owned by Unit 10.
- Auto-post from `EventCreated` runs system-triggered (no JWT), so author/group names fail-closed to ids — acceptable and documented.
- DynamoDB numbers deserialize as `Decimal` (test asserts value, not type).

## Not done (follow-ups)
- Not deployed (Build & Test / Operations).
- Central `platform/fixtures` announcements shape not updated (only the service's own copy) — cosmetic, mock-only.
- Live email delivery depends on the Notifications unit (still mocked).

## Post-generation change (2026-08-07, pre-deploy) — pivot to Markdown body
User-requested during deployment prep, to eliminate the native-dependency deploy friction. The body is now **stored as inert Markdown** instead of server-sanitized HTML:
- **Removed** `nh3` (native dep) and the whole workaround it forced: `services/announcements/src/sanitizer.py` → replaced by `body.py` (`normalize_body`, length-bound only); `requirements.txt` back to pure-Python (boto3 + powertools); `infra/tools/build_announcements_pkg.py`, the `deploy.sh` build step, the `lambda_pkg/` dir, and the `-app` CodeUri redirect all **removed** (CodeUri back to `src/`).
- **Sanitization moved to the client render boundary**: `AnnouncementPanel` renders with `markdown-it` (`html:false`) + **DOMPurify** before injection. Frontend deps: `markdown-it` + `dompurify`. Modal body field relabelled Markdown.
- **Flagged for Unit 10 (Notifications)**: the email path must render/escape `AnnouncementPublished.bodyPreview` itself (server no longer guarantees safe output).
- Contract body descriptions updated (Markdown); mock fixture body → Markdown; test suite 2 reworked (`test_sanitizer.py` → `test_body.py`: Markdown stored verbatim/inert + length-bounded).
- Re-verified: **39 pytest pass**, ruff clean, contract gate announcements 4/4, `npm run build` clean (561.81 kB / 176.32 kB gzip). Design artifacts updated: BR-14, NFR-AN-SEC-1/2, tech-stack D-AN-1/D-AN-2 + dependency inventory, nfr-design-patterns.
