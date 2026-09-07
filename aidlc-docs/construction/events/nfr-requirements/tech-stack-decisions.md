# Tech Stack Decisions — Unit 4: Events

**Stage**: CONSTRUCTION → NFR Requirements · **Unit**: Events
Inherits all platform-wide choices (Unit 1). Records Events-specific additions. Companion: `nfr-requirements.md`.

## Inherited unchanged
Python 3.12 on Lambda · AWS Lambda Powertools · boto3 · AWS SAM packaging · DynamoDB on-demand (PITR, Retain) · EventBridge for domain events · API Gateway REST + Cognito authorizer · CloudWatch + X-Ray · pinned dependencies with lock, ruff/bandit/cfn-lint/dependency-scan/SBOM in CI · Schemathesis + pytest as the contract gate · single-region multi-AZ · Backup & Restore DR · CodePipeline per service.

## Events-specific additions

| Concern | Choice | Rationale |
|---|---|---|
| Recurrence expansion | **`datetime` + `calendar` (stdlib)** with hand-written frequency stepping | Four frequencies (daily, weekly, bi-weekly, monthly) with a 104-occurrence cap do not justify `python-dateutil`. Monthly stepping clamps to the last valid day, which is the one case worth testing explicitly (31 January + 1 month). Avoids a dependency for arithmetic we fully control. |
| .ics generation | **Hand-written RFC 5545 writer** (stdlib only) | The required surface is small and fixed: `VEVENT` with `UID`, `DTSTAMP`, `DTSTART`, `DTEND`, `SUMMARY`, `DESCRIPTION`, `LOCATION`, `ORGANIZER`, `SEQUENCE`, and `METHOD:REQUEST`/`CANCEL`. `icalendar` would add a dependency and a transitive `pytz` for perhaps 60 lines of output. Line folding at 75 octets and correct escaping of `,` `;` `\` and newlines are the details that need tests, not a library. |
| Attendance CSV | **stdlib `csv`** server-side; existing hand-written `parseCsv` on the frontend | Consistent with Identity & Access's bulk import. **No `openpyxl`, no SheetJS** — the xlsx path was deliberately removed from this repo over unpatched high-severity CVEs, and reintroducing it for one button would undo that decision. |
| Cross-service point-value read | **`urllib` + `ThreadPoolExecutor`**, reusing Unit 3's `FanOutClient` pattern verbatim (parallel calls, per-call timeout, per-container short-circuit) with a 60-second per-container value cache | No new HTTP dependency; the pattern is already proven and its degrade path is already contract-tested elsewhere. The cache is the only addition. |
| S3 brokering | **boto3 `s3` presigned PUT/GET**, minted per request, never stored, following Settings' `FileShareStorage` | Direct reuse of the reworked, live-verified pattern. The stored-URL failure mode (signature dies with the Lambda session, cannot be revoked) is already understood and avoided by construction. |
| Object metadata stamping | **EventBridge rule on S3 Object Created/Deleted → this service's Lambda** | Same as Settings' `file_share_event_consumer`. EventBridge rather than a direct S3 notification, because the bucket lives in the Foundation stack and a direct notification would close a circular dependency — a constraint already hit and solved once. |
| Malware scanning | **GuardDuty Malware Protection for S3** (decision N1) | Managed, no code, no container to maintain, and no attempt to scan a 500 MB object inside a Lambda. Scan status gates material visibility. Adds per-GB cost, accepted. |
| ~~Reminder scheduling~~ | ~~One EventBridge Scheduler schedule invoking a 5-minute sweep~~ | **WITHDRAWN 2026-08-27** — reminders removed (US-2.2/2.10 descoped). The one-schedule-per-service reasoning is worth keeping for any future scheduled sender: it beats thousands of per-event schedules to create, mutate and garbage-collect. |
| MS Teams | **`TeamsProvider` interface with a stub adapter** (decision D1); real Microsoft Graph adapter deferred | Everything downstream of the fetch — email matching, review, include/exclude, apply-and-award — is real and testable today. Writing an untestable Graph client now would add a dependency and a credential path with no way to verify either. |
| Public upload route | **API Gateway usage plan + per-token throttling**, opaque 404s, per-link upload cap | Decision N3, upholding AC-1 (no WAF). |
| Token generation | **`secrets.token_urlsafe(32)`**, stored as a SHA-256 hash, compared with `hmac.compare_digest` | stdlib; constant-time comparison; plaintext returned exactly once at creation. |

## What this unit does NOT need
No Cognito admin SDK, no SES, no Secrets Manager, no password hashing, no JWT signing (the gateway authorizer handles authentication), no OpenSearch, no Bedrock. Events reads identity from JWT claims and publishes everything else as domain events.

## Dependencies (pinned — `services/events/requirements.txt`)
| Package | Purpose |
|---|---|
| `boto3` (pinned) | dynamodb, events, s3 |
| `aws-lambda-powertools` (pinned) | structured logging, tracing, metrics |
| (dev) `pytest`, `schemathesis`, `moto` | unit and contract tests; `moto` for DynamoDB and S3 |

No new runtime dependency beyond what Units 2, 3, and 11 already pin. Recurrence, .ics, CSV, tokens, and the fan-out are all stdlib. All exact-pinned, lock committed, scanned with SBOM in CI (SECURITY-10).

## Frontend additions
No new npm packages. The calendar grid is hand-built CSS grid (matching the mockup's own approach) rather than a calendar library — the mockup's month view is a static 7-column grid, and adding a date-picker/calendar dependency for it would be disproportionate. Reuses the shipped `DataTable` server mode, `useDebounced`, `parseCsv`, `exportEndpointCsv`, and `apiFetch`.

## Deferred to NFR Design / Infrastructure Design
- Index design for the events table: which access patterns get which GSI (list by scope + date, list by series, materials by scope for the Content Library). Every listing must be an index query, not a scan.
- Reconciliation path for a partially-created series (NFR-EV-REL-6), given the 100-item transaction limit against a 104-occurrence cap.
- Exact fan-out timeout value, to be set against measured Contributions latency once that service is real rather than mocked.
- Material lifecycle states introduced by malware scanning (pending-scan, clean, quarantined) and how they surface in listings and the Content Library.
- Whether the S3 consumer shares this service's Lambda or gets its own function.
- S3 lifecycle policy for external uploads and orphaned objects.
