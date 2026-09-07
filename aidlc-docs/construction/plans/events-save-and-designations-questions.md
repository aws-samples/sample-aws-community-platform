# Events Save Fix + Designation Pickers — Clarification Questions

Please answer by filling in the letter after each [Answer]: tag.

## Question 1
The UGL save failure is reproduced and understood (the UI never sends the led
group). The Community Leader path, however, ACCEPTS the exact frontend payload
locally (201), and the deployed IAM covers the create path. What did you see
when the save failed as a Community Leader?

A) An error banner in the modal saying "User Group Leaders can only create events for the group they lead" (would mean the CL's role claim is wrong live — separate defect)

B) An error banner saying "startsAt must be in the future" (time-picker issue, UI should surface the constraint)

C) A generic error ("An unexpected error occurred" / "Could not reach the server") — needs a live log check after redeploy of the fix

D) The save appeared to succeed but the event never showed in the list

E) I only tested as UGL / don't remember the CL error exactly

F) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
How should EXTERNAL presenters travel in the API contract? The current frozen
contract has `presenters: string[]` (user ids).

A) Additive: keep `presenters: string[]` for portal users and add a new `externalPresenters: string[]` (names). Nothing existing breaks; mock regen is additive. (RECOMMENDED)

B) Reshape: `presenters` becomes an array of objects `{userId?, externalName?}` — cleaner long-term but a breaking contract change (v3) touching mock, gate and any consumer

C) Other (please describe after [Answer]: tag below)

[Answer]:A

## Question 3
Points eligibility (BR-P3: only Members earn; external presenters never earn)
needs the designee's REAL role. Today the service defaults everyone to "Member"
(= everyone eligible), which is a latent defect. Where should the role come from?

A) Server-side lookup at designation time — Events calls the directory (`GET /members/{id}`) forwarding the caller's JWT, same fan-out pattern Member Profiles already uses; on lookup failure the designation is stored but marked NOT eligible with reason "role unverified" (fail-closed for points). (RECOMMENDED)

B) Same server-side lookup, but on failure default to Member/eligible (fail-open — matches today's behavior, risks awarding a leader)

C) Trust the role sent by the frontend picker (no extra call, but any caller can mark anyone eligible — not recommended)

D) Other (please describe after [Answer]: tag below)

[Answer]:A
