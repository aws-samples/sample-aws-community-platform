# Certifications — "Revoke a Certification" as a Tab: Clarification Questions

**Your request**: "Revoke a Certification" should be a separate Tab for CL and UGL.

**What's true today** (so the change is clear):
- Revoke is **Community-Leader-only** (a deliberate earlier decision, BR-R1/D9). User Group Leaders **cannot** revoke anything today.
- The revoke widget currently lives **inside the CL "Definitions" tab** (member search → pick one of their verified certs → reason → revoke). Points already awarded are retained.
- The backend revoke has **no group scoping** — it trusts the CL-only gate. Verification, by contrast, scopes a UGL to claims **credited to the group they lead** (404 on anything outside it).

Giving UGLs a Revoke tab therefore grants them a new capability, and I need to pin down its scope. Please answer with a letter after each `[Answer]:`.

---

## Question 1
Should User Group Leaders actually be able to **revoke** certifications (a new capability), and if so, scoped how?

A) Yes — a UGL can revoke, but **only** certifications **credited to the group they lead** (claims outside their group return 404, exactly like their verification scope). Recommended — consistent with how UGLs already verify.

B) Yes — a UGL can revoke **any** approved certification community-wide (same power as a CL).

C) No — keep revoke CL-only; do **not** add a Revoke tab for UGLs (only the CL gets the new tab).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 2
A UGL can now hold their own certifications. Should a UGL be able to **revoke their own** approved certification?

A) No — a UGL cannot revoke their own certification; only a Community Leader can (mirrors "can't approve your own claim").

B) Yes — a UGL may revoke their own certification.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 3
On the UGL Revoke tab, the **member search** should show:

A) Only members whose certifications are **credited to the UGL's led group** (a scoped search); picking a member lists only that group's revocable certifications.

B) All members (global search), but revoking only works for certifications credited to the led group — a member with none in that group simply shows "no revocable certifications here."

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 4
For the **Community Leader**, should the existing revoke widget **move out** of the Definitions tab into its own Revoke tab?

A) Yes — move it. Definitions keeps only create/edit/deactivate; revoke lives on its own tab.

B) No — leave it on Definitions **and** also add a separate tab (revoke appears in two places).

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 5
Tab **label and placement**. (CL would then have: Pending Verifications · Definitions · Revoke; UGL: Pending Verifications · Catalog · My Submissions · Revoke.)

A) Label the tab **"Revoke"**, placed last.

B) Label it **"Revoke a Certification"**, placed last.

C) Other (please describe label/position after [Answer]: tag below)

[Answer]: A
