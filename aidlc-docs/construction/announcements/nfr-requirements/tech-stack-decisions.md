# Tech Stack Decisions — Unit 9: Announcements

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Announcements
Technology choices for the unit, derived from the project-level stack (already fixed) plus the NFR answers (Q1–Q6 = A). Companion: `nfr-requirements.md`.

## Inherited from the project (not re-decided)
| Area | Decision |
|---|---|
| Backend runtime | **Python on AWS Lambda** (single function, router pattern — matches Identity/Members/Events/Settings). |
| Data store | **DynamoDB single table** (`announcements-<stage>`) + idempotency table; on-demand capacity; SSE + `Retain`. |
| API | **REST via shared API Gateway**, Cognito authorizer at the edge; in-service fail-closed authZ. Routes under the already-registered `/announcements` base path (no `gen_api_edge`/api-edge regen). |
| Async | **EventBridge** for publish (`AnnouncementPublished`) and consume (`EventCreated`, `GroupSoftDeleted`/`GroupRestored`). |
| Frontend | **TypeScript + React + Vite** SPA (Unit 15). |
| IaC / CI-CD | CloudFormation + SAM; per-service CodePipeline, contract-test gated; `-data`/`-app` split. |
| DR | Backup & Restore (hours) + PITR on this table. |

## Unit-specific decisions (from NFR answers)
### D-AN-1 — Body format: Markdown, stored inert (REVISED 2026-08-07 — supersedes the `nh3` decision)
- **Choice**: the body is authored and **stored as Markdown**. The server does **no** HTML sanitization and carries **no native dependency** — `nh3` removed. The Lambda package stays pure-Python (no cross-platform wheel packaging, no `lambda_pkg` workaround, no `deploy.sh` build step).
- **Superseded**: server-side `nh3` (Rust `ammonia`) sanitize-on-write of HTML. Dropped because it was the first native dep in the repo and the dev deploy packages `src/` directly (no dep vendoring), forcing a bespoke Lambda-package build. Markdown avoids that and keeps data inert at rest.
- **Rejected**: `bleach` (deprecated), hand-rolled HTML sanitizer (fragile). Markdown chosen with the explicit tradeoff that sanitization moves to each render boundary.

### D-AN-2 — Render + sanitize on the client: markdown-it + DOMPurify (REVISED 2026-08-07)
- **Choice**: the SPA renders the Markdown body with **`markdown-it`** (`html:false` — raw HTML disabled) and runs the output through **DOMPurify** before `dangerouslySetInnerHTML` in `AnnouncementPanel`. Both pinned in `frontend/package.json`.
- **Role**: this IS the sanitization boundary now (not merely defense-in-depth). `html:false` stops embedded raw HTML becoming markup; DOMPurify strips anything remaining + guards mutation-XSS.
- **Non-browser consumers**: the Notifications email path (`AnnouncementPublished.bodyPreview`) must render/escape Markdown itself — flagged for Unit 10 (server no longer guarantees safe output).

### D-AN-3 — Panel active-set cache (Q2=A)
- **Choice**: in-process **warm-container cache** of the active-announcement set with a **30 s TTL** (same pattern as Settings' `SettingsClient`). No external cache (no ElastiCache) — the active set is tens of items. Cache miss falls back to a single bounded query. Targeting + expiry + `groupHidden` filtering is in-memory.

### D-AN-4 — Directory client for name denormalization (NFR-AN-REL-1)
- **Choice**: a lightweight REST **DirectoryClient** (author name via `GET /members/{id}`, group name via `GET /groups/{id}`), forwarding the caller's JWT — same pattern as Events' `DirectoryClient`. **1.5 s timeout, fail-closed** to id/email / raw group id. Used only on create/edit and auto-post (write path), never on the panel read.

### D-AN-5 — No new libraries beyond the above
- Recurrence/date handling: Python stdlib (`datetime`) for the +2d default / +90d clamp and TTL epoch — no `dateutil`.
- No SQS, Step Functions, ElastiCache, or WAF (STANDARD criticality; no unauthenticated surface). Deliberately excluded.

## Dependency inventory (new to this unit) — REVISED 2026-08-07 (Markdown pivot)
**Backend: ZERO new runtime dependencies** (body is inert Markdown; `nh3` removed — package is pure-Python). Frontend adds two:
| Dependency | Where | Purpose | Pinned |
|---|---|---|---|
| `markdown-it` | `frontend` (TS) | render Markdown body with `html:false` (NFR-AN-SEC-1) | exact version |
| `dompurify` | `frontend` (TS) | sanitize rendered HTML before injection (NFR-AN-SEC-2) | exact version |

*(Original inventory below is superseded — `nh3` no longer used.)*
| ~~Dependency~~ | ~~Where~~ | ~~Purpose~~ | ~~Pinned~~ |
|---|---|---|---|
| `nh3` | `services/announcements` (Python) | server-side HTML sanitization (NFR-AN-SEC-1) | exact version |
| `dompurify` | `frontend` (TS) | client-side render sanitization (NFR-AN-SEC-2) | exact version |

Both are actively maintained, sourced from official registries (PyPI / npm), and subject to the pipeline vulnerability scan (SECURITY-10).
