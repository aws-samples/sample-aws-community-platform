# Requirement Verification Questions — Adjust Points screen rework (US-6.15)

**Change request (2026-08-11)**: "As CL and UGL, when I navigate to Contributions > Approvals > Adjust Point. The Screen needs rework — Member should be searchable, Group which the member belongs to should be populated and selectable, Quarter should be a dropdown list, Point delta (+/-) should accept only +/- sign followed by number."

Please answer each question by putting a letter after the `[Answer]:` tag. If none of the options fit, pick the "Other" option and describe what you want.

---

## What I found before asking (context for your answers)

**The screen today** (`ContributionsPage.tsx`, `Approvals()`): the `± Adjust points` button opens a generic form with **six free-text boxes** — Member ID, Member name, Group, Quarter, Point delta, Reason. Nothing is a dropdown, nothing is searchable, and nothing is validated in the browser. A leader has to know and hand-type the internal `m-…` member id and `g-…` group id, which are ids the UI deliberately never shows anywhere else.

**A live defect, worth flagging before we design anything.** The shared form component only converts checkbox and tag fields; every other field is submitted as a **string**. The backend requires `delta` to be a real integer. So `delta` arrives as `"10"` and the API rejects it with a 400 validation error — **manual point adjustment currently fails for every leader, every time, on the deployed app**. The existing backend tests pass `delta` as a Python integer straight into the service, which is why they are green and the bug survived. Your request to constrain the delta field fixes this as a side effect; I want it on the record as a defect rather than buried in a UI change.

**What the backend already enforces** (no change needed to any of these): CL may adjust any group, UGL only their own group; delta must be non-zero and within ±100000; quarter must be one of the current + previous 7 quarters; reason is mandatory (≤1000 chars); the entry is appended to an immutable ledger with the adjustor's id, and a negative adjustment is allowed to push a total below zero on purpose (BR-J3).

**What already exists to build on**: a searchable people picker used by Events and the certification-revoke flow (it can already be scoped to a single group), a quarter helper producing the canonical `YYYY-Qn` list newest-first, and directory search results that already carry each member's groups — so the group dropdown needs no extra API call.

**One gap I did not invent.** US-6.15 has two halves: a free ± adjustment, *and* "the adjustor selects the specific point entry to delete". The second half is fully built and tested in the backend (`GET /contributions/ledger`, `POST /contributions/adjustments/reverse`, single-use guard) but has **no UI whatsoever** — the SPA never calls either route. Question 7 asks whether closing that belongs in this change.

---

## Question 1
Member search scope — who can a leader find in the member search box?

A) CL searches every member in the community; UGL searches **only members of the group they lead** (the search itself is scoped, so an out-of-scope member is never even offered)

B) Both CL and UGL search the whole community; a UGL who picks a member outside their group gets a clear error on submit (server already returns 403)

C) Both search the whole community, but for a UGL the out-of-scope results are shown greyed out and not selectable

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 2
The Group dropdown is populated from the groups the selected member belongs to. What should happen when the member belongs to **more than one** group?

A) Dropdown lists all their groups with **no default** — the leader must consciously pick which group's points are being adjusted

B) Dropdown lists all their groups with the **first one preselected** for speed

C) Dropdown lists all their groups; for a **UGL** it is preselected and locked to the group they lead (a UGL has only one legitimate choice anyway), while a **CL** must pick

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 3
What should happen when the selected member belongs to **no group at all**?

A) Block it — show "This member is not in any user group, so there is no group to adjust points for" and disable Save

B) Allow a community-wide adjustment with no group (points recorded against no group)

C) Allow it but require the leader to pick any group from the full group list

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 4
The Quarter dropdown. The backend accepts the current quarter plus the previous 7 (BR-J4).

A) List all 8, newest first, with the current quarter preselected and labelled "(current)" — matches the quarter pickers already on the My Contributions and Leaderboard tabs

B) List all 8 with no preselection, so the leader must choose deliberately

C) List only the current and previous quarter (tighten the window beyond what the backend allows)

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 5
"Point delta should accept only +/- sign followed by number." Is the **sign mandatory**?

A) Sign is **mandatory** — `+10` and `-5` are valid; a bare `10` is rejected with a message asking for an explicit sign. Nothing but sign-then-digits can be typed into the field.

B) Sign is **optional** — `10` is accepted and treated as `+10`; `-5` subtracts. Only digits and a leading sign can be typed.

C) No free typing at all — a separate **Add / Subtract** toggle plus a digits-only amount box, so a sign mistake is impossible

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 6
Should the form show the member's **current points** for the chosen group and quarter, and the **resulting total**, before the leader saves?

A) Yes — show current total and the projected total after the adjustment (makes an accidental sign error visible before it is written to the immutable ledger)

B) No — keep the form minimal, just the five inputs

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 7
The missing half of US-6.15 (see the gap noted above): the ability to **pick a specific existing point entry and reverse it**, instead of typing a free ± amount. The backend for this is already built, tested and deployed; only the UI is missing.

A) In scope now — add a member's point-history list to this screen with a "Reverse this entry" action alongside the free ± adjustment

B) Out of scope — keep this change to the four items I asked for; log the reverse-entry UI as a separate follow-up

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 8
The reworked form will no longer be a generic modal, so there is room for guidance. Should it state the consequences of an adjustment?

A) Yes — a short note that the adjustment is permanent (append-only, cannot be edited or deleted), that the member is notified in-portal, and that a negative adjustment may take a total below zero

B) No note — keep it clean

X) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Not asked, because they are already settled

These are recorded decisions I will follow rather than re-open:

- **Authorization** stays exactly as built and deployed — CL any group, UGL their led group only, enforced server-side (BR-A5, SECURITY-08). The UI scoping in Question 1 is a usability layer on top of that check, never a replacement for it.
- **Ledger immutability** (BR-J1), **single-use reversal** (BR-J2), **no floor at zero** (BR-J3) and the **8-quarter window** (BR-J4) are unchanged.
- **RTO/RPO, DR strategy, CI/CD, rollback and deployment style** are already fixed project-wide (Backup & Restore + DynamoDB PITR; CloudFormation/SAM via `infra/deploy.sh`), so the Resiliency Baseline questions are answered and not repeated here.
- **Quarter format** stays the canonical `YYYY-Qn` used by every service.
