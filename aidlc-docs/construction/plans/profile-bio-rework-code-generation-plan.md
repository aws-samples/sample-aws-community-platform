# Code Generation Plan — Profile bio rework (US-3.2)

**Units**: Unit 3 (member-profiles), Unit 15 (SPA)
**Date**: 2026-08-11
**Requirements**: `aidlc-docs/inception/business-requirements/profile-bio-rework-requirements.md` (approved)
**Ships with**: the Adjust Points rework — one combined deploy

**Workflow note**: as with the Adjust Points change, the conditional design stages (Application
Design, Units Generation, Functional Design, NFR Requirements, NFR Design, Infrastructure
Design) are **SKIPPED** — no new component, data model, dependency or infrastructure; every
rule is already designed (BR-17) and the two decisions (limit=2000, plain-text) were taken at
Requirements. This plan is the single source of truth. Part 2 executes and checks off each step.

---

## Steps

### Step 1 — Backend: bio limit, skills validation, named constant
- [x] `services/member-profiles/src/models.py`: add `BIO_MAX_LEN = 2000` and `SKILL_MAX_LEN = 60` constants (NFR-3 — bio no longer shares 500)
- [x] `services/member-profiles/src/profile_service.py` `update_own_profile`:
  - bio validated at `BIO_MAX_LEN` on its own line, separate from the `city/country/professionalRole/avatar` group that stays at 500 (FR-2)
  - each `skills[]` item validated with `require_str(..., max_len=SKILL_MAX_LEN)` — length + the existing angle-bracket rejection (FR-4). A non-list `skills`, or a non-string item, returns 400 with a field-named detail
  - `bio` continues to reject `<`/`>` via `require_str` (FR-3, BR-17 unchanged)
- [x] Story: US-3.2

### Step 2 — Backend: surface `details` in the error response (the message fix)
- [x] `services/member-profiles/src/app.py`: change the `except AppError` handler to spread `details` when present, identical to `contributions-scoring`/`certifications`:
  `return _resp(err.status, {"code": err.code, "message": err.message, **({"details": err.details} if err.details else {})})` (FR-1)
- [x] Story: US-3.2

### Step 3 — Backend tests
- [x] `services/member-profiles/tests/`: bio of `BIO_MAX_LEN` accepted, `BIO_MAX_LEN+1` rejected 400 with a `details` entry naming `bio`; a `<` in bio rejected with the angle-bracket message; `city` still capped at 500 (proves the split); an over-long and an angle-bracket `skill` rejected; and a route-level test asserting the 400 body now CONTAINS `details` (pins FR-1 so it cannot silently regress)
- [x] Story: US-3.2

### Step 4 — Contract
- [x] `contracts/services/member-profiles/openapi.yaml`: `bio` gains `maxLength: 2000`; `updateOwnProfile` gains a `400` response; the `Error` schema gains an optional `details` array (DR-1). Additive, same routed base path → no `gen_api_edge.py` regen
- [x] Story: US-3.2

### Step 5 — Frontend: FormModal gains an opt-in counter + prominent errors
- [x] `frontend/src/components/FormModal.tsx`:
  - extend `Field` with optional `maxLength?: number`, `hint?: string`, and a `counter?: boolean` flag (NFR-4 — opt-in, so the other 7 uses are unchanged)
  - a `textarea` field with `counter` renders a live "N of {maxLength} remaining" line that turns amber near and red over the limit (FR-6, FR-7)
  - **Save blocked** while any counter field is over its `maxLength` (FR-7); no hard-stop on typing
  - the error block (currently a thin faint line) becomes a **highlighted danger block with `role="alert"`**, matching the file-share modal's existing pattern, placed where it will be seen (FR-9)
- [x] Stories: US-3.2 (FR-6/7/9)

### Step 6 — Frontend: wire the Bio field + preserve line breaks on render
- [x] `frontend/src/features/singletons.tsx` `ProfilePage`: the Bio field gets `type:"textarea"`, `counter:true`, `maxLength:2000`, and a "Plain text. Line breaks are preserved." hint; render the read-view bio (`m.bio`) with `white-space: pre-wrap` on the escaped text (FR-8)
- [x] `frontend/src/features/MemberDetailPage.tsx`: same `white-space: pre-wrap` on the member-detail bio (FR-8 — both sites change together)
- [x] Story: US-3.2

### Step 7 — Frontend: humanise the error message
- [x] `frontend/src/lib/apiClient.ts`: the `details` join already appends `field: message`; adjust so the field is Capitalised and the pairs read as sentences ("Bio: length must be 1-2000"), still generic and safe (FR-10). This is a small, shared improvement — verify no test asserts the old exact string
- [x] Story: US-3.2

### Step 8 — Documentation + story write-back
- [x] Amend US-3.2 in `stories.md` and `requirements/usecases/03-*.md` (bio 2000, plain text with line breaks, clear/highlighted errors)
- [x] `aidlc-docs/construction/member-profiles/code/bio-rework.md` — the message-drop root cause, the accidental-500 finding, the four services still affected (Q4=A follow-up), and what is/ isn't verified
- [x] Update `aidlc-state.md`

### Step 9 — Verification (combined with the Adjust Points change)
- [x] `cd frontend && npx tsc -b` clean
- [x] `cd frontend && npm test` — all pass (existing 118 + any new)
- [x] `python3 -m pytest services/member-profiles -q` — pass, incl. the new bio/skills/details tests
- [x] `cd frontend && npm run build` clean
- [x] `make test` repo-wide green
- [x] `make contract-tests SVC=member-profiles` — still green after the contract edit
- [x] `ruff check services/member-profiles` clean

---

## Story traceability

| Requirement | Step |
|---|---|
| FR-1 (details in response) | 2, 3 |
| FR-2, FR-5, NFR-3 (bio 2000, constant) | 1, 3, 4 |
| FR-3 (keep `<>` rejection) | 1, 3 |
| FR-4 (skills validation) | 1, 3 |
| FR-6, FR-7 (counter, Save block) | 5, 6 |
| FR-8 (line breaks, both sites) | 6 |
| FR-9 (prominent, announced error) | 5 |
| FR-10 (human sentence) | 7 |
| FR-11 (inline pre-save) | 5, 6 |
| DR-1 (contract) | 4 |

**9 steps.** Backend: 3 files touched + tests. Frontend: 4 files. Contract: 1. Plus docs.
No infrastructure, no new dependency, no `gen_api_edge` regen.
