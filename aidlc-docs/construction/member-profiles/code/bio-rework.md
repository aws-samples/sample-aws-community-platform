# Profile bio rework — code summary (US-3.2)

**Date**: 2026-08-11
**Units**: Unit 3 (member-profiles), Unit 15 (SPA)
**Plan**: `aidlc-docs/construction/plans/profile-bio-rework-code-generation-plan.md`
**Ships with**: the Adjust Points rework (one combined deploy)

---

## The reported defect

A member saving a 583-character bio saw "Validation failed." with no field and no limit.

**Two causes, both fixed:**

1. **The message was unreadable.** `require_str` produced `details: [{field:"bio", message:"length must be 1-500"}]`, but `services/member-profiles/src/app.py` serialised only `code` and `message`, dropping `details`. The SPA's `apiFetch` was already written to append `details` — it just never received them. Fixed by spreading `details` into the response, exactly as `certifications` and `contributions-scoring` already do.
2. **The limit was wrong and accidental.** `bio` shared one `require_str(max_len=500)` call with `city`, `country`, `professionalRole` and `avatar`, so a professional bio was capped at the length of a city name. No rule or design specified 500. Raised to 2000 as its own named constant.

---

## Changes

### Backend — member-profiles

| File | Change |
|---|---|
| `models.py` | New constants `SHORT_TEXT_MAX_LEN=500`, `BIO_MAX_LEN=2000`, `SKILL_MAX_LEN=60` |
| `profile_service.py` | bio validated at `BIO_MAX_LEN` on its own line; short fields stay at 500; each `skills[]` item validated (length + angle brackets); a non-list `skills` returns 400 |
| `app.py` | `except AppError` now includes `details` in the body |

### Contract

`contracts/services/member-profiles/openapi.yaml`: `bio` and `Member.bio` gain `maxLength: 2000`; short fields and skill items gain their caps; `updateOwnProfile` gains a `400` response; the `Error` schema gains an optional `details` array. Additive — no `gen_api_edge.py` regen. Contract gate still 5/5.

### Frontend — SPA

| File | Change |
|---|---|
| `components/FormModal.tsx` | `Field` gains opt-in `hint`, `maxLength`, `counter`. A counter textarea shows "N of max remaining" (amber near, red over), blocks Save while over, sets `aria-invalid`. The error line became a highlighted `role="alert"` block. |
| `features/singletons.tsx` | Bio field is now a counter textarea (max 2000) with a plain-text hint; read-view bio rendered `white-space: pre-wrap` |
| `features/MemberDetailPage.tsx` | Member-detail bio rendered `white-space: pre-wrap` |
| `lib/apiClient.ts` | The `details` join reads as a capitalised sentence ("Bio: length must be 1-2000") |

The `FormModal` counter and error-block changes are opt-in / additive, so the other seven `FormModal` uses are unaffected. The prominent `role="alert"` error block now benefits all of them.

---

## Decisions during generation

- **`SKILL_MAX_LEN = 60`** was not specified by the user (Q5 said "validate", not a number). 60 chars comfortably holds any real tag ("Amazon SageMaker Ground Truth" is 30) while bounding the payload. Flagged here rather than silently chosen.
- **A non-list `skills` returns 400** with a field-named detail rather than being coerced — the API is explicit, and `FormModal`'s tags field always sends an array anyway.
- **`aria-invalid` on the over-limit textarea** plus the `role="alert"` block and the red counter give three coordinated signals (FR-9/10/11) without a new dependency.
- **The message humanisation is capitalise-first-letter only.** Field names are already readable words (`bio`, `city`, `skills`); anything cleverer would need a field-name→label map that does not exist server-side.

---

## Verification

- `npx tsc -b` clean
- `python3 -m pytest services/member-profiles` — **72 pass** (was 63; +9 bio/skills/details tests, incl. a route-level assertion that the 400 body carries `details`)
- `make contract-tests SVC=member-profiles` — 5/5
- `npm test` / `npm run build` / `make test` — see the combined report
- `ruff check services/member-profiles` clean

## Not verified

No frontend test renders `FormModal`, so the counter's colour transitions, the Save-block, and the `role="alert"` announcement need a human pass — folded into the combined manual procedure. Deploy is held for the combined ship with the Adjust Points change.

## Follow-up (from Q4=A)

The identical dropped-`details` bug remains in **identity-access, announcements, settings, and one events handler**. Every validation error in those services is still unreadable. Scoped out by the user's choice; logged for a future change.
