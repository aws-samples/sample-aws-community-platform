# Unit 6 — Certifications: Functional Design Clarification Questions

Round-2 follow-ups to `certifications-functional-design-plan.md`. Your answers Q2/Q3/Q4/Q8/Q11 are locked in (A/A/A/B/A). Q6 is interpreted as: **the leader uploads a real badge picture** (mockup's "Upload image" button honored; the emoji-tile look in mockups is treated as placeholder art). Please answer the 6 questions below, then say "done".

---

## Clarification 1 — Q1 re-explained: the claim status name on the wire

**The issue, stated plainly.** When a leader approves a claim, the claim gets a status value. That value appears in TWO places that were built at different times and disagree on the word:

- The **requirements side** (use case 05, stories US-5.5/5.6, every mockup) calls the state **"Verified"** — e.g. the member's submissions table shows a green "Verified" badge.
- The **already-built software side** calls the same state **"Approved"**: the frozen API contract (`decision: approve`), the seed fixtures (`status: "Approved"`), the shipped CertificationsPage, and — most importantly — the **member-profiles service that is already deployed to AWS**, which calls `GET /certifications/claims?...&status=Approved` to power the directory's "holds certification X" filter.

This is purely a **naming choice for one enum value**; behavior is identical either way. But it must be picked consciously, because:

- If the wire value stays **"Approved"**: nothing deployed changes. The frontend simply displays the word "Verified" wherever the mockups do (a translation of one label).
- If the wire value becomes **"Verified"**: the deployed member-profiles service must be edited and redeployed in the same change (its `status=Approved` query would silently match nothing — the cert filter would break), and fixtures/contract/mock get renamed too.

### Question
Which word should the API/database use for an approved claim?

A) **"Approved"** on the wire; the UI shows "Verified" to match the mockups. (Recommended — zero risk to the deployed member-profiles service; users still see exactly what the mockups show.)

B) **"Verified"** on the wire; member-profiles is updated + redeployed in the same change.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Clarification 2 — Q5 follow-up: malware scanning of evidence files

Your Q5 answer is locked in as far as it goes: evidence files go to a **pre-configured S3 bucket**, and the system **renames the physical file to a unique name** (e.g. `{claimId}-{timestamp}.pdf`) before storing — the original filename is kept only as display metadata. Both are now design rules.

One part of the original question is still open: **malware scanning**. Evidence files are uploaded by members and then **opened by leaders** — an externally-supplied file served to a privileged user. For exactly this situation, the Events unit added **GuardDuty Malware Protection** to the foundation upload bucket: a file stays hidden until its scan verdict is "Clean"; infected files are quarantined. Reusing it here costs little (the scanning infrastructure exists; this unit adds its prefix + a verdict consumer). Skipping it means leaders open unscanned member uploads.

### Question
Should certification evidence files be malware-scanned before a reviewer can open them?

A) **Yes** — use the existing GuardDuty-protected bucket/pattern; a claim with an uploaded file becomes reviewable only after the file scans Clean; quarantined file = claim flagged, member asked to re-upload. (Recommended)

B) **No** — store directly in the pre-configured bucket without scanning; leaders open files as-is. (Accepted risk, recorded.)

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Clarification 3 — Q7 follow-up: does "no access" include the read-only catalog?

Your answer restates the requirement ("Administrators do not have access to certification management") — but the two options both satisfy that sentence, and they differ on ONE endpoint. The RBAC permission matrix (the transcribed source of truth from Role-and-Permission-Mapping.md) gives Administrator exactly one certifications row: **`browse certification-catalog`** — read-only viewing of what certifications exist. Everything else (queues, claims, definitions, revoke) is denied for Admin under either option.

### Question
May an Administrator view the read-only certifications catalog?

A) **Yes** — Admin can browse the catalog (as the permission matrix says), and gets 403 on every other certifications operation. "Management" means defining/verifying/revoking — not looking at the list. (Recommended — follows the RBAC source of truth.)

B) **No** — blanket 403 on the entire certifications service for Admin, and the matrix row is removed as an error (permission-matrix file edit, affects nothing else — no other service reads that row today).

C) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## Clarification 4 — Q8=B consequence: the already-expired-at-approval edge

You chose **B**: expiry counts from the **member-supplied "date earned"** (now becoming a structured, required-when-cert-expires field on the claim form, validated not-in-future), falling back to approval date when absent. Sensible — but it creates one edge the stories never contemplated:

A member earns a 3-year certification in **2022**, claims it in **2026**. Date earned + period = **already expired before the leader even reviews it**. What should happen?

A) **Block at submission**: if dateEarned + expiry period is already in the past, the claim form rejects with "This certification has already expired" — nothing enters the queue, no leader time spent. (Recommended — cleanest; the member learns immediately.)

B) Allow submission and approval; the badge is created and the very next daily sweep expires it (member gets approved-then-expired notifications minutes apart; points are still awarded and retained).

C) Allow submission; leader sees an "already expired" warning in the queue and decides (approve → immediate expiry, or reject).

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Clarification 5 — Q9 explained: how a revoke identifies WHAT is being revoked

**Background.** Revoke (US-5.8) removes one member's one earned certification. Since you chose Q2=A, an earned certification IS a claim row in Approved state, findable two equivalent ways: by the pair *(which certification, which member)* — unique because a member can hold a certification only once — or by the claim row's own id.

**What exists today (both halves wrong).** The contract's revoke operation lives under the **certification definition**: `POST /certifications/{certId}/revoke` with `memberId` optional in the body — so a request that forgets `memberId` is valid-per-contract but meaningless. The shipped UI is worse: its Revoke button sits on the catalog's **definition row** and sends no member at all. The mockup shows a third shape: a "Revoke a Certification" widget with **member search + reason** — but no way to choose which of that member's certifications to revoke. Every current representation is incomplete; that's why this question exists.

**The two ways to fix it:**

- **Option A — pair-addressed (keep the route, fix the body).** `POST /certifications/{certId}/revoke` with `memberId` and `reason` both **required**. Reads naturally as "revoke this certification from this member". UI flow: pick member → see their approved certifications → revoke one with reason. Contract change is a tightening of the existing op (no new route, no route-table regen).
- **Option B — claim-addressed (new route).** `POST /certifications/claims/{claimId}/revoke` — the claim id pins the exact row, the old definition-scoped route is deleted. Marginally purer REST, but it's a **breaking contract change** (new path + removed op), and leaders don't think in claim ids — the UI would resolve member+cert → claimId behind the scenes anyway, adding a lookup that Option A doesn't need.

Both end at the same database row with the same effects (badge removed, points retained, member notified with reason). A is less churn; B is more orthodox.

### Question
How should revoke be addressed?

A) **Pair-addressed**: keep `POST /certifications/{certId}/revoke`, make `memberId` + `reason` required; UI = member picker → their certifications → revoke with reason. (Recommended)

B) **Claim-addressed**: new `POST /certifications/claims/{claimId}/revoke`, retire the old route.

C) Other (please describe after [Answer]: tag below)

[Answer]: Explain the requirement.

---

## Clarification 5b (round 3) — the revoke requirement itself, explained plainly

**What US-5.8 "Revoke a Certification" is about, in everyday terms:**

The whole certifications feature works on trust: a member says "I earned AWS Solutions Architect Pro, here's my proof", a leader checks the evidence and approves it, and from that moment the member wears the badge on their profile and has received the certification's points. **Revoke is the undo lever for when that trust turns out to be misplaced or the situation changes.** Real occasions:

- The evidence later turns out to be fake or someone else's certificate.
- AWS de-certifies the person, or the leader learns the certification was refunded/invalidated.
- The badge was approved by mistake (wrong member, wrong certification).

**What the requirement says happens** (all fixed, not open questions):

- Only a **Community Leader** can do it (not UGLs, not Admins), on **any** member's earned certification.
- The CL must give a **reason** (free text — "Evidence found to be invalid", etc.).
- The **badge disappears** from the member's profile immediately.
- The **points the member earned stay** — the requirement explicitly says points are NOT reversed.
- The member is **notified** (email + in-portal) that it was revoked and why.
- Once revoked, the member is allowed to submit a **fresh claim** for that same certification later (the duplicate rule treats "revoked" like "rejected").

**A concrete walkthrough:** Dana (CL) learns Alex's "AWS DevOps Pro" credential link is dead and Credly has no record of it. Dana opens the Certifications screen, finds Alex's earned DevOps Pro badge, clicks Revoke, types "Credential could not be verified with the issuer", confirms. Alex's profile no longer shows the badge, Alex gets an email + bell notification with that reason, Alex's points are untouched, and Alex may resubmit with better evidence someday.

**The only thing still to decide** is a technical detail: when the frontend tells the backend "revoke it", how does the request name the thing being revoked? Since a member can hold a given certification only once, the two candidate address forms point at the exact same record:

- **Option A**: the request says *certification + member* ("revoke DevOps Pro from Alex") — this keeps the API route that already exists, just making both fields mandatory. Matches how a leader thinks about it.
- **Option B**: the request quotes the internal *claim record id* ("revoke claim #cl-7f3a") — a new route; the UI would have to look up that id first from the same certification+member pair anyway.

Either way, every user-visible behavior above is identical. A is less rework and reads like the sentence a leader would say; that's why it's recommended.

### Question (same decision, re-asked)
How should the revoke request identify the certification being revoked?

A) **Certification + member pair** — keep `POST /certifications/{certId}/revoke`, body requires `memberId` + `reason`. (Recommended)

B) **Claim record id** — new route `POST /certifications/claims/{claimId}/revoke`, old route removed.

C) Other (please describe after [Answer]: tag below)

[Answer]: I think B. is not it ?

---

## Clarification 6 — Q10 explained: which domain events this service publishes

**Background.** Services here never call the notification system directly — they **publish domain events** (facts like "claim approved") onto the shared event bus, and interested services subscribe. The planning docs reserved three events for Certifications: `CertificationApproved` (consumed by Contributions to auto-award points, and later by Notifications), `CertificationRevoked`, `CertificationExpired`.

**The gap.** The notification requirements (US-8.15 recipient matrix + US-5.1/5.6) require the member to be notified on **five** certification occasions: approved, **rejected**, revoked, **expiring soon (2 weeks before)**, expired. Two of those five have **no reserved event**. When the Notifications unit is eventually built, it can only react to events that producers actually publish — and the producer of "claim rejected" / "expiring soon" facts is THIS unit.

**Why decide now.** If Certifications publishes only 3 event types, then when Notifications is built, this service must be **modified and redeployed** to add the missing two — a cross-unit ripple. If it publishes all 5 from day one, Notifications finds every trigger already flowing and nothing here changes. Cost of publishing the extra two now: two small JSON schema files + two `publish()` calls at points the code already handles (the reject branch; the expiry sweep already computes the T-14 notice). Nothing consumes them until Notifications is real — unconsumed events are harmless.

*(Note: the T-14 "expiring soon" notice is required by US-5.1 regardless — the only question is whether it's emitted as a properly-schema'd event now, or retrofitted later.)*

### Question
Which event set should Certifications publish?

A) **All five**: Approved, Rejected, Revoked, ExpiringSoon, Expired — complete trigger surface, no future rework of this unit. (Recommended)

B) **Only the reserved three**: Approved, Revoked, Expired — Rejected/ExpiringSoon handled when Notifications is designed (accepting this unit gets reopened then).

C) Other (please describe after [Answer]: tag below)

[Answer]: A
