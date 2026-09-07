# Requirements — Profile bio: message fix, size limit, counter, line breaks

**Date**: 2026-08-11
**Units affected**: Unit 3 (Member Profiles), Unit 15 (Frontend SPA)
**Story**: US-3.2 Edit Profile — amended
**Source**: change request `audit.md` 2026-08-11T15:10:00Z; answers in `profile-bio-rework-questions.md`
**Ships with**: the Adjust Points rework (single combined deploy, per user instruction)

---

## 1. Intent analysis

| Aspect | Assessment |
|---|---|
| Request type | **Bug fix** (unreadable error) + **Enhancement** (bigger limit, counter, line breaks) |
| Scope | **Two components** — member-profiles service (limit, message, skills) + SPA (counter, line breaks) |
| Complexity | **Low** |
| Depth | **Standard** |
| Risk | **Low** — no auth, no data migration, no new dependency; bigger limit and preserved whitespace are backward-compatible with stored data |

### The reported defect, root cause

A member editing their profile saw "Validation failed." with no field, no limit. The reported bio was measured at **583 characters with no angle brackets**, so it failed purely on the length cap — confirming the diagnosis below.

The server already builds `details: [{field: "bio", message: "length must be 1-500"}]`, and the SPA's `apiFetch` already appends `details` to the surfaced message. The details are lost at `services/member-profiles/src/app.py` where the `AppError` handler serialises only `code` and `message`:

```python
except AppError as err:
    return _resp(err.status, {"code": err.code, "message": err.message})
```

`certifications` and `contributions-scoring` already spread `details` into the body; member-profiles does not. **FR-1 copies the correct line.**

### A correction the user accepted

The limit was **500, not the 512 assumed in the request**, and it was accidental — `bio` shared one `require_str(..., max_len=500)` call with `city`, `country`, `professionalRole` and `avatar`. No rule or design specifies 500. Q1 raises bio specifically to 2000.

### A deliberate change from the opening request

The request said "allow markup." The answers (Q3=C, Q6) chose **plain text with line breaks preserved, no markup**. This requirement follows the answers. The angle-bracket rejection (BR-17) is therefore **retained**, and no Markdown or HTML rendering is introduced.

---

## 2. Functional requirements

### Backend — member-profiles (Unit 3)

- **FR-1** — The `AppError` handler in `services/member-profiles/src/app.py` MUST include `details` in the response body when present, matching `certifications`/`contributions-scoring`. This is the fix for the meaningless message and applies to every validation error in the service, not just bio.
- **FR-2** — `bio` MUST be length-bounded at **2000 characters**, independent of the 500 cap that stays on `city`, `country`, `professionalRole` and `avatar`. An over-length bio MUST return 400 with a `details` entry naming the field and the limit.
- **FR-3** — `bio` MUST continue to reject `<` and `>` (BR-17 unchanged); the failure message ("must not contain '<' or '>'") now reaches the client via FR-1.
- **FR-4** — Each `skills[]` item MUST be validated: a per-item length bound and the same angle-bracket rejection as bio (Q5=A, closes the current gap where skills bypass validation entirely). An offending item returns 400 with a `details` entry.
- **FR-5** — Scope of these limits (bio 2000, skill item length) is documented so the numbers are no longer accidental.

### Frontend — SPA (Unit 15)

- **FR-6** — The Bio field MUST show a live character counter reading "N of 2000 remaining" (Q2=A), updating as the user types.
- **FR-7** — The counter MUST turn a warning colour as the limit approaches and an error colour when exceeded, and **Save MUST be blocked while the bio is over the limit** (Q2=A). The field does not hard-stop typing — the user can see and delete the excess.
- **FR-8** — Bio MUST render with **line breaks preserved** in both places it appears — the member's own profile and the member-detail page (Q3=C) — instead of collapsing whitespace as it does today. It remains escaped plain text; no HTML or Markdown is interpreted.

### Error visibility (added 2026-08-11 on user follow-up)

- **FR-9** — When a save fails validation, the error MUST be **clearly presented and visually prominent**, not the thin single line the edit form shows today. It MUST: (a) sit in a highlighted error block (danger colour, not a faint caption), (b) be scrolled/kept into view so a user does not miss it below the fold, and (c) carry `role="alert"` so assistive technology announces it (matching the pattern other modals in the SPA — e.g. the file-share create modal — already use).
- **FR-10** — Where the server returns per-field `details` (now delivered by FR-1), the message MUST read as a human sentence naming the field and what is wrong (e.g. "Bio: length must be 1–2000"), not a raw `field: message` join. The offending field SHOULD be visually indicated where practical.
- **FR-11** — Client-side validation the user can hit before saving (bio over 2000) MUST be surfaced **inline at the field** (the counter turning red, FR-7) so it never requires a round-trip to discover. The server response covers anything the client cannot pre-check.

---

## 3. Non-functional requirements

- **NFR-1 (Security, SECURITY-05)** — The counter and Save-block are client aids; the server limit and angle-bracket rejection remain the enforcement point. FR-4 extends validation coverage rather than relaxing it.
- **NFR-2 (Security)** — FR-8 preserves line breaks via CSS/escaped text only (`white-space: pre-wrap` on escaped content). No `dangerouslySetInnerHTML`, no sanitizer needed, because no markup is interpreted — the safest reading of "plain text with line breaks".
- **NFR-3 (Maintainability)** — The bio length limit MUST be a named constant, not an inline literal, so it is not accidentally re-shared as 500 was.
- **NFR-4 (Consistency)** — The counter is the first of its kind in the SPA. If added to `FormModal` it MUST be an opt-in field option so the seven other `FormModal` uses are unaffected.

---

## 4. Contract

- **DR-1** — Add `maxLength: 2000` to `bio` and a `400` response to `updateOwnProfile` in `contracts/services/member-profiles/openapi.yaml`, so the limit and the failure mode are contractual rather than Python-only. The `Error` schema gains an optional `details` array (member-profiles only — Q4=A scopes the code fix to this service, and the schema addition is additive and harmless to others). This is the one additive contract change; it needs no `gen_api_edge.py` regeneration (same routed base path).

---

## 5. Explicitly unchanged

No change to: authorization, the `MemberProfileUpserted` event shape (Q6 keeps bio plain text, so no plain-text-alongside-Markdown field is needed), the DynamoDB table, IAM, or any other service. **Q4=A** deliberately leaves the identical dropped-`details` bug in identity-access, announcements, settings and events as a **known follow-up** rather than fixing it here.

---

## 6. Traceability

| Requirement | Source | Verification |
|---|---|---|
| FR-1 | Defect (dropped details) | Backend test: an over-long bio returns 400 with `details` naming `bio` |
| FR-2, FR-5, NFR-3 | Q1=2000 | Backend test: 2000 accepted, 2001 rejected; city still capped at 500 |
| FR-3 | BR-17 (unchanged) | Backend test: `<` in bio rejected with the specific message |
| FR-4 | Q5=A | Backend test: over-long / angle-bracket skill rejected |
| FR-6, FR-7 | Q2=A | Manual: counter reads and blocks; frontend test if a pure helper is extracted |
| FR-8 | Q3=C | Manual: a multi-line bio shows line breaks on both pages |
| FR-9, FR-10, FR-11 | User follow-up 2026-08-11 | Manual: a failed save shows a prominent, announced, human-readable error; over-limit is caught inline before save |
| DR-1 | Q1, Q4 | Contract gate stays green |

---

## 7. Follow-up recorded

The dropped-`details` bug still exists in **identity-access, announcements, settings, and one events handler** (Q4=A scoped this fix to member-profiles). Every validation error in those services remains unreadable. Logged for a future change.
