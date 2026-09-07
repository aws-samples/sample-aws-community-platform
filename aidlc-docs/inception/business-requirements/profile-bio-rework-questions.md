# Requirement Verification Questions — Profile bio: error message, size limit, counter, markup

**Change request (2026-08-11)**: "As member I am editing the profile. While saving got error 'Validation failed.'. This error message is meaningless. What is the bio field size limit. Put a counter like remaining 50 of 512 as user type or parse the content. Allow markup."

Answer each question by putting a letter after the `[Answer]:` tag.

---

## What I found before asking

### The meaningless message is a one-line bug, and the fix already exists in this repo

The server does produce a useful message. `require_str` raises a `ValidationError` carrying
`details: [{field: "bio", message: "length must be 1-500"}]`, and the SPA's `apiFetch` is
already written to append those details to what you see — the comment on that code even says
*"Validation failed." alone is useless*.

The details never arrive. `services/member-profiles/src/app.py` line 141 serialises only
`code` and `message`, dropping `details`:

```python
except AppError as err:
    return _resp(err.status, {"code": err.code, "message": err.message})
```

Two services already do it correctly — `certifications` and `contributions-scoring` both
spread `details` into the body. **Five do not**: member-profiles, identity-access,
announcements, settings, and one of two handlers in events. So every validation failure in
those five services shows you the same useless string. Question 4 asks how wide to go.

### The size limit is 500 — and it is accidental

Not 512. And no business rule, story or design document specifies 500 anywhere. It comes
from `bio` sharing one line with four short fields:

```python
if field in ("city", "country", "professionalRole", "bio", "avatar"):
    value = require_str(value, field, max_len=500) if value else value
```

So a bio is capped at the same length as a city name. The contract declares no `maxLength`
for `bio` and no `400` response at all for this endpoint.

### Your save may have failed for a different reason than length

`require_str` also rejects **any `<` or `>`** outright. If you typed markup, that is what
failed — and the message would have said `must not contain '<' or '>'` if details had been
sent. This is BR-17, which explicitly names `bio` as a field where HTML is rejected. Allowing
markup means amending that rule, which is why Question 3 exists rather than me just doing it.

### There is a proven markup pattern here already

Announcements store **Markdown verbatim** (no server-side sanitizer) and render it at the
display boundary with `markdown-it` configured `html: false` plus DOMPurify. Both libraries
are already dependencies. Bio currently renders as escaped plain text in two places — your
own profile and the member-detail page — and newlines collapse, so even paragraph breaks are
lost today.

### Two smaller things found on the way

- **`skills[]` is not validated at all.** No length check, no HTML check, despite BR-17
  naming it alongside `bio`. Question 5.
- **Failure modes are inconsistent**: announcements silently truncate at 20,000 characters,
  member-profiles rejects with 400 at 500. Whatever limit you pick, I would rather reject
  than silently discard your words, and the counter makes the limit visible before you hit it.

---

## Question 1
What should the bio size limit be? The counter you described says 512, but that number is
arbitrary if markup is allowed — Markdown syntax itself consumes characters, and a bio is
prose, not a city name.

A) **512** — as you described in the request

B) **2,000** — roughly 300 words; comfortable for a professional bio with a few Markdown links and a list

C) **5,000** — generous; effectively removes the limit as a practical concern while still bounding the payload

D) Keep **500** and only fix the message and add the counter

X) Other (please describe after [Answer]: tag below)

[Answer]: 2000

---

## Question 2
The counter. Where should it sit and what should it say?

A) Below the Bio field, live as you type: **"450 of 2000 remaining"** (your wording), turning amber near the limit and red when exceeded, with Save blocked while over

B) Same, but the field also **hard-stops** typing at the limit (browser `maxLength`), so it can never be exceeded

C) Counter only, no colour change and no Save block — the server still rejects

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 3
"Allow markup" — which kind?

A) **Markdown**, following the Announcements pattern exactly: stored verbatim, rendered with
   raw HTML disabled and sanitized with DOMPurify at display. `**bold**`, `_italic_`,
   `[links](url)`, lists. A typed `<script>` is inert text, never markup. The editor gets the
   same "Supports Markdown" hint the announcement composer has.

B) **Raw HTML**, sanitized on render with an allow-list of safe tags (the stricter policy
   already written for the AWS feed reader)

C) **Neither** — keep plain text, but preserve line breaks so paragraphs survive, and keep
   rejecting `<`/`>`

X) Other (please describe after [Answer]: tag below)

[Answer]: C

---

## Question 4
How widely should the dropped-`details` bug be fixed? This is the actual cause of the
meaningless message, and it affects far more than the bio field.

A) **member-profiles only** — smallest change, fixes the screen you reported

B) **All five services that drop it** (member-profiles, identity-access, announcements,
   settings, events) — one identical line each, copied from the two services that already do
   it right. Every validation error in the portal starts naming its field.

C) All five **plus** add `details` to the shared `Error` schema in the contracts, so the
   behaviour is contractual rather than incidental

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 5
`skills[]` items are currently not validated at all — any length, any content, including
`<script>`. BR-17 says they should be. Fix in this change?

A) Yes — validate each skill (length bound, and consistent with whatever Question 3 decides for markup)

B) No — log it as a separate follow-up

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 6
Bio is published to other services in the `MemberProfileUpserted` event, which the Search
service consumes for indexing. If bio becomes Markdown, search results and any future email
would carry raw `**asterisks**`.

A) Ship it — Search is still a mock service; note it as a known follow-up for whoever builds it

B) Also publish a plain-text version of the bio alongside the Markdown in the event, so
   consumers have a clean string to index

X) Other (please describe after [Answer]: tag below)

[Answer]: markdown not needed. use plian text

---

## Not asked, because it is not in question

- The **counter is a client-side aid**; the server limit remains the enforcement point (SECURITY-05).
- Rendering markup requires sanitization at the display boundary. That is not optional and
  not a choice — it applies to whichever option Question 3 selects.
- Bio renders in **two** places (own profile, member-detail page). Both change together;
  leaving one as plain text would be a bug.
