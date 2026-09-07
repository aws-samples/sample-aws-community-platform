# Platform / Settings Service (Unit 11)

Real Python Lambda service (mock retired) owning centralized admin configuration,
email templates, and external file-share links.

## Responsibilities (stories: US-8.3, US-8.4, US-8.5, US-8.13, US-8.14 config side, US-11.1/11.6 config side, + Self-Registration master switch)
- **Centralized Admin Settings** (US-8.3): singleton settings record —
  community branding (name, logo), system default time zone (US-8.14),
  **Self-Registration on/off switch** + allowed-email-domain allow-list (US-1.30),
  Email OTP re-verification interval (US-1.32 knob),
  MS Teams integration, LLM duplicate-post analysis toggle, Bedrock model ID,
  What's New feed enable + URL (US-11.1/11.6), email sender config (US-8.4).
  Administrator-only writes; any authenticated user may read.
- **Public settings subset** (`GET /public/settings`, unauthenticated, served
  from the public `/public` base path like `/auth`): backs the pre-login
  Self-Registration tab gate and branding. **World-readable** — this route has no
  authorizer and is internet-facing, so it carries only what the login screen
  renders: `communityName`, `logoUrl`, `selfRegistrationEnabled` (`PUBLIC_FIELDS`
  in `models.py`).
- **Internal settings subset** (`GET /internal/settings`, no authorizer but
  emitted only into the **private** API — `PRIVATE_ONLY_BASES` in
  `infra/tools/gen_api_edge.py`): admin config other services enforce
  server-side. `selfRegistrationEnabled`, `allowedEmailDomains`,
  `otpIntervalDays`, `teamsEnabled`, `defaultTimezone` (`INTERNAL_FIELDS`).
  Reachable only via the execute-api VPC endpoint; there is no internet path.
  Split out of `/public/settings` on 2026-08-28 — `allowedEmailDomains` (which
  corporate domains may self-register) and `otpIntervalDays` (how long a departed
  employee's access persists) were world-readable there, and no pre-login caller
  used them.
- **Email templates** (US-8.5): defaults bundled; per-template subject/body
  overrides stored in the table.
- **External file-share links** (US-8.13): CL/UGL only. One record = one file
  slot (`<folder>/<fileName>`) in the community S3 bucket (Foundation-owned,
  private, BlockPublicAccess). Copy Link mints a fresh ~1h write-only presigned
  PUT; owner-side listing/downloads use fresh presigned GETs. No expiry —
  Deactivate stops future mints, Delete removes the record and the file. CL sees
  and manages all slots; UGL only their own.

## Intentionally NOT in this service (per requirement change 2026-08-02)
- **Audit Logging section** — removed from the settings UI/API (identity-access
  keeps its own env-level AUDIT_ENABLED default).
- **Cognito User Sync section** — removed (sync schedule stays fixed in the
  identity-access -app stack's EventBridge rule).
- The OTP re-verification **feature and its admin knob stay** (confirmed by
  user follow-up): `otpIntervalDays` lives here and is read live by
  Identity & Access.
- **`sessionLifetimeHours`** — removed 2026-08-11. It was stored, validated
  (1–720) and rendered on the settings screen, but nothing ever read it: session
  length is the Cognito ID token lifetime, set on the user pool client in
  `infra/foundation.yaml` (currently the 1-hour default, no refresh flow), which
  a runtime setting cannot influence. Reintroducing an admin-configurable
  session requires a refresh-token flow plus an `UpdateUserPoolClient` call.

## Events
- Publishes `SettingsChanged` (contracts/services/settings/published-events/)
  on every successful write.

## Consumers of live settings
- **identity-access** — `SettingsClient` (providers.py) reads
  `GET /internal/settings` with a 30s per-container cache; falls back to
  CFN-Parameter env vars if unreachable. Enforces `selfRegistrationEnabled`,
  `allowedEmailDomains`, `otpIntervalDays` at login/register time.
- **events** — `SettingsCache` (providers.py) reads `GET /internal/settings` for
  `teamsEnabled` (BR-T1 gate), 30s cache, fails **closed**. Note MS Teams is
  locked OFF platform-wide by `update_settings`, which forces
  `teamsEnabled=False` server-side regardless of the request.
- **frontend** — AuthScreen (pre-login tab gate + branding), AppLayout
  (branding + What's New nav visibility), Admin Settings page, member/leader
  Settings page, What's New page (US-11.6 disabled behavior).

## Environment
| Variable | Purpose |
|---|---|
| `TABLE_NAME` | settings single table |
| `IDEMPOTENCY_TABLE` | S3 file-share event-consumer idempotency |
| `EVENT_BUS_NAME` | SettingsChanged publication |
| `FILE_SHARE_BUCKET` | community file-share bucket (US-8.13) |

## Key design
Single table:
- `SETTINGS/CONFIG` — singleton settings record
- `TEMPLATE#<id>/META` — email template override
- `FILESHARE#<id>/META` — file slot, **GSI1** `CREATOR#<userId>` /
  `FILESHARE#<createdAt>` for the per-creator (UGL) listing
- `FILEKEY#<folder>/<file>/META` — pointer to the owning slot
- `FOLDERS/REGISTRY` — string set of known folder names

Defaults for the singleton and templates ship in `models.py` so a fresh deploy
is never empty.

### File-share listing performance (rework 2026-08-04)
The listing does **no S3 calls**. `uploaded`/`sizeBytes`/`uploadedAt` are stored
fields whose only writer is `file_share_event_consumer`, driven by an
EventBridge rule on S3 `Object Created`/`Object Deleted` for the bucket. Before
this, every page load issued one `ListObjectsV2` per distinct folder in the
result set, so latency grew with the number of folders a leader used.

The `FILEKEY` pointer does two jobs with one item: O(1) reverse lookup from an
S3 key to its slot (so the consumer needs no second index), and race-free
`fileName`-unique-per-folder enforcement via a conditional put (previously a
full-table scan per create, which two concurrent creates could both pass).

Listings are cursor-paginated: UGL by GSI1 Query on their own partition, CL by
paged Scan. `FOLDERS/REGISTRY` replaced a full-table scan on every Create-dialog
open with a single `get_item`.

**Deploy note**: the GSI and the trigger require the `-data` and `-app` stacks
plus Foundation. Run `infra/tools/backfill_file_share_state.py` once per stage
afterwards — pre-existing slots have no stored upload state or pointer, so
already-uploaded files would otherwise read as "Awaiting upload".

## Tests
`python3 -m pytest services/settings` — service + route + authZ coverage
(moto DynamoDB + S3).
