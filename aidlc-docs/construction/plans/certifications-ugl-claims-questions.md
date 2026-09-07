# Certifications — UGL Claims Change Request: Clarification Questions

**Context**: You asked that a User Group Leader (UGL) be able to (a) see the Certificate Catalog like Members, (b) claim a certificate, (c) never approve their own claim — it must be approved by a Community Leader (CL), and (d) have three tabs on the Certifications page: **Pending Verifications**, **Catalog**, **My Submissions**.

Before implementing, I need to resolve a few conflicts with how the Certifications service works today. Please answer each question by putting a letter after the `[Answer]:` tag.

**Current state that matters:**
- The UGL **Catalog** tab already ships (read-only) — this change adds a **My Submissions** tab and enables **claiming**.
- Today, claiming is **Member-only** (rule BR-A3). CL/UGL/Admin cannot submit claims, hold badges, or earn points.
- A claim is always **credited to one group** (`creditedGroupId`), and today you can only credit a group **you are a member of** (BR-C3). Leadership is **not** membership — a UGL leads a group but is not necessarily a "member" of it.
- Claims are **routed to a verification queue purely by credited group** (BR-V1). A UGL's queue shows claims credited to the group they lead. So if a UGL credits their own led group, their claim would land in **their own** queue.
- There is already a rule that the decider cannot be the claim owner (BR-V5), but that only blocks the button — it does not by itself hide the claim from the owner's queue or route it elsewhere.

---

## Question 1
When a UGL claims a certificate, which group should the claim be **credited to** (this drives points attribution and which queue it enters)?

A) The group the UGL **leads** (their led group) — even though leadership isn't the same as membership

B) A group the UGL is a **member** of — same as Members do today; UGL must pick from groups they've joined (claim blocked if they've joined none)

C) The UGL **chooses** from a combined list of their led group **plus** any groups they've joined

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 2
You said a UGL cannot approve their own claim and it must be a CL. How should a UGL's own claim be handled in the verification queues?

A) A UGL's own claim is **hidden from their own Pending Verifications queue** and is approvable **only by a CL** (CL sees all claims already). This is the cleanest way to guarantee "never self-approve."

B) The claim **stays visible** in the UGL's own queue (so they can see its status) but the approve/reject actions are **disabled** for them; only a CL can decide it

C) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## Question 3
Today only Members earn **points** on approval (points feed the contribution leaderboard). When a UGL's claim is approved, should it **earn points** the same way?

A) Yes — a UGL's approved claim earns points exactly like a Member's (credited to the chosen group)

B) No — UGLs can hold the certificate/badge but their approved claims earn **zero** points

C) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## Question 4
Today only Members get **verified badges shown on their profile** (US-5.9). Should a UGL's approved certifications also appear as **badges on their profile**?

A) Yes — approved certs show as badges on the UGL's profile, same as Members

B) No — UGLs can claim and be verified, but no profile badge is displayed

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 5
Should the UGL's **My Submissions** tab have the same capabilities Members have — submit with evidence (URL or file upload), withdraw a pending claim, resubmit after rejection, and see rejection reasons?

A) Yes — full parity with the Member My Submissions experience

B) Submit and view only — no withdraw/resubmit

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 6
A UGL will now have **three** tabs (Pending Verifications, Catalog, My Submissions), while a Member has two (Catalog, My Submissions) and a CL has two (Pending Verifications, Definitions). Which tab should the UGL land on by **default** when opening the Certifications page?

A) Pending Verifications (their leadership duty first — matches the CL landing tab)

B) Catalog

C) My Submissions

D) Other (please describe after [Answer]: tag below)

[Answer]: A
