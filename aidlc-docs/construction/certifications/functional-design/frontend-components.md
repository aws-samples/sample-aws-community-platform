# Unit 6 — Certifications: Frontend Components (D11 — full rebuild)

Scope: rebuild `CertificationsPage.tsx` to mockup fidelity, add the profile Verified Badges card, nav pending-count badges. Design refs: `member/certifications.html`, `leader/certifications.html`, `ugl/verifications.html`, `member/profile.html`. Reuses the shared design system (DataTable incl. server conventions, FormModal patterns, States, useApi/useDebounced, apiClient).

## Component tree

```
CertificationsPage (role-aware tab shell)
├── Member:  [Catalog] [My Submissions]
│   ├── CatalogGrid
│   │   └── CertCard (badge image, Held/Available badge, name, category,
│   │                 expiry countdown, "+N pts on approval", Submit Claim)
│   ├── ClaimModal (submit + resubmit prefill)
│   └── MySubmissionsTable (+ WithdrawConfirm)
├── CL:      [Pending Verifications] [Definitions] [Revoke]   (Revoke split to its own tab 2026-08-07)
│   ├── VerificationQueueTable (+ filters: certification, group)
│   │   └── RejectReasonModal
│   ├── DefinitionsTable (Edit / Deactivate / Reactivate — revoke no longer here)
│   │   └── DefinitionModal (create + edit, incl. badge-image upload)
│   └── RevokeFlow on the Revoke tab (member picker → their certifications → reason → confirm)
└── UGL:     [Pending Verifications] [Catalog] [My Submissions] [Revoke]   (change requests 2026-08-07)
    ├── VerificationQueueTable (single-group, no group filter; own claim shown
    │   as an "Awaiting Community Leader" badge instead of Approve/Reject, Q2=B)
    ├── CatalogGrid (submit enabled — same as Member)
    ├── ClaimModal (group field fixed to the led group, read-only; "no points" hint)
    ├── MySubmissionsTable (+ WithdrawConfirm)
    └── RevokeFlow on the Revoke tab: PeoplePicker scoped to the led group
        (GET /members?groupId=), holdings filtered to the led group; backend
        enforces 404 outside the led group and 403 on self-revoke
    Default tab: Pending Verifications (Q6=A).

ProfilePage / MemberDetailPage
└── VerifiedBadgesCard (badge grid, newest-first) → BadgeDetailModal

AppLayout nav
└── pending-count pill on Certifications/Verifications item (CL/UGL)
```

Admin: no nav item, no route reachable (service 403s regardless — BR-A1; UI simply never offers it).

## Screens & behaviors

### Member — Catalog (US-5.10)
- `GET /certifications` → 3-col `CertCard` grid (mockup layout). Card: badge image (fallback tile when none), **"✓ Held" green / "Available" gray** badge, name, "category · expires in Xy Ym" countdown when held+expiring (from `heldExpiresAt`), `+{points} pts on approval` tag, **Submit Claim** button (hidden when `held` or `pendingClaim` — the duplicate rule surfaced before the server 409).
- Empty state + ComingSoon/501 handling per house convention.

### Member — ClaimModal (US-5.4)
- Certification select (active, not held/pending — server re-checks BR-C1/C2); **User group to credit** select fed by the caller's real groups (`GET /groups?mine=true` via Identity, replacing the shipped hardcoded ids) with the mockup's routing hint; zero groups → modal replaced by the **"join a group first"** prompt linking to User Groups (422 path also lands here).
- **dateEarned** date input — shown always, marked required when the selected certification has an expiry period (client mirror of BR-C5/C6; server 422 "already expired" rendered inline).
- Evidence: URL input OR file picker (pdf/png/jpg/jpeg) — exactly one, client-enforced; file flow = `POST /certifications/evidence-uploads` → presigned PUT with progress → attach `fileKey`+`fileName`. Notes textarea.
- On success: confirmation toast + submissions list refresh.

### Member — My Submissions (US-5.5)
- `GET /certifications/claims/me`, columns per mockup: Certification (name, not id), User Group, Evidence (link out / filename), Submitted, Status badge (Pending amber / **"Verified"** green ← wire `Approved`, D1 / Rejected red with inline "Reason: …" / Withdrawn gray / Revoked red with reason / Expired gray), action column: **Withdraw** (Pending only → confirm dialog → `DELETE /certifications/claims/{id}`), **Resubmit** (Rejected/Withdrawn/Revoked/Expired → ClaimModal prefilled).
- "Awaiting scan" chip on Pending+PendingScan; Quarantined → "Upload rejected — please re-upload" row state driving a fresh ClaimModal.

### Leader — VerificationQueueTable (US-5.6/5.7)
- `GET /certifications/verifications` (+`certId`/`groupId` filters — group filter CL-only; UGL sees no group column, per mockups). **Oldest-first default sort**; server order respected.
- Columns: Member (avatar+name), User Group (CL only), Certification, Evidence (link opens `evidenceUrl` directly; file evidence fetches a fresh URL via `GET /claims/{id}/evidence-url`), Submitted, Action **Approve / Reject**.
- Approve → confirm → `POST /claims/{id}/decision {decision:"approve"}`; expired-at-approval 409 rendered with the server's explanation. Reject → **RejectReasonModal** (reason required, client+server) → `{decision:"reject", reason}`.
- Non-decidable rows (awaiting scan) show a disabled state with tooltip.
- Caption lines from the mockups (credited-group explanation) reproduced.

### CL — DefinitionsTable + DefinitionModal (US-5.1/5.2/5.3)
- `GET /certifications?includeInactive=true`; columns: Certification, Category, Expiry ("3 years"/"None"), Points, Status (Active/Inactive), actions **Edit · Deactivate** / **Reactivate**.
- DefinitionModal (create + edit): Name, Description, Category select, Expiry period (months, optional), **Points awarded on approval** (number ≥ 0, B1 hint text), **Badge image upload** (`POST /certifications/badge-uploads` → presigned PUT; preview; "scanning…" state until Clean).
- Deactivate/Reactivate = PUT with `active` toggle + confirm dialog (copy: holders keep badges).

### CL — RevokeFlow (US-5.8, D9)
- Entry on the Definitions tab (mockup's widget, completed): member typeahead/picker → `GET /certifications/claims?memberId=X&status=Approved` → that member's held certifications as cards → pick one → **reason (required)** → confirm → `POST /certifications/claims/{claimId}/revoke`.
- Copy: "Points already awarded are retained."

### Profile — VerifiedBadgesCard (US-5.9)
- Own profile: `GET /certifications/claims/me` filtered Approved; others' profiles (MemberDetailPage): `GET /certifications/claims?memberId=X` (public projection).
- Grid of badge image + name + "Earned {dateEarned || decidedAt}" (**newest first**); click → **BadgeDetailModal**: name, description, date earned.
- Members only (hidden for leader/admin subjects — they cannot hold claims anyway). Replaces the shipped raw-certId pills.

### Nav pending-count (US-5.7)
- CL/UGL nav item gains a count pill from `GET /certifications/verifications?countOnly=true` (fetch on layout mount + refresh after any decision; same Option-2A read-only count surfaced in the bell panel — no stored notification).

## State & data conventions
- All lists via `useApi` with nonce-refresh after mutations (house pattern); tables on the shared DataTable (rows selector, column menu = US-8.9 for free).
- Display-name resolution (member names in queue/revoke) comes server-side in queue payloads — the UI never does per-row identity lookups (anti-pattern removed in the Settings rework).
- Wire→label map: `Approved → "Verified"` in one shared `certStatusLabel()` helper; all other statuses verbatim.
- Errors: server messages surfaced inline (409/422 paths above); 501 → ComingSoon; fail-closed empty states.

## Validation summary (client mirrors, server authoritative)
| Field | Rule |
|---|---|
| Claim: certification | required, active, not held/pending |
| Claim: creditedGroupId | required, ∈ caller's groups |
| Claim: evidence | exactly one of URL / file; URL http(s); file type whitelist |
| Claim: dateEarned | required if cert expires; not future; not already-expired |
| Reject: reason | required, ≤ 500 chars |
| Revoke: reason | required |
| Definition: name/description/category/points | required; points ≥ 0 integer |
| Definition: expiry | positive integer months, optional |

## Endpoint map (component → API)
| Component | Calls |
|---|---|
| CatalogGrid | GET /certifications |
| ClaimModal | GET /groups (mine), POST /certifications/evidence-uploads, POST /certifications/claims |
| MySubmissionsTable | GET /certifications/claims/me, DELETE /certifications/claims/{id} |
| VerificationQueueTable | GET /certifications/verifications, GET /certifications/claims/{id}/evidence-url, POST /certifications/claims/{id}/decision |
| DefinitionsTable/Modal | GET /certifications?includeInactive=true, POST /certifications, PUT /certifications/{id}, POST /certifications/badge-uploads |
| RevokeFlow | GET /users (picker, existing Identity route), GET /certifications/claims?memberId&status=Approved, POST /certifications/claims/{id}/revoke |
| VerifiedBadgesCard | GET /certifications/claims/me · GET /certifications/claims?memberId=X |
| Nav pill | GET /certifications/verifications?countOnly=true |
