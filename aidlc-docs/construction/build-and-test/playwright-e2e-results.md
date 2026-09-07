# Playwright MCP — Live E2E Test Results

**Target:** https://EXAMPLE.cloudfront.net
**Date:** 2026-08-12
**Scope:** CommunityLeader, UserGroupLeader (x2), Member (x4). Administrator excluded per instruction.
**Method:** Interactive Playwright MCP against the live deployment. Accessibility-snapshot driven; network 4xx/5xx checked per page.

## Accounts under test
| Role | Email | Notes |
|------|-------|-------|
| CommunityLeader | user@example.com | community-wide |
| UserGroupLeader | user@example.com | leads "AWS Kolkata UG" |
| UserGroupLeader | user@example.com | leads "AWS Bangalore UG" |
| Member | user@example.com | member of no group |
| Member | user@example.com | member of no group |
| Member | user@example.com | member of no group |
| Member | user@example.com | member of no group |

## Legend
PASS = rendered expected content, no errors. FAIL = error/empty/wrong state or 4xx/5xx. SKIP = not applicable to role. BLOCKED = could not reach.

---

## Results log
(filled in as tests run)

| # | Role | Area / Route | Test | Result | Notes |
|---|------|--------------|------|--------|-------|
| 1 | CL | /auth (login) | US-1.2 email+password sign-in | PASS | No OTP challenge (not due this interval); landed on Community Dashboard |
| 2 | CL | /auth (logout) | US-1.3 sign out | PASS | Returned to auth screen; Self-Registration tab visible (self-reg enabled) |
| 3 | CL | / (Community Dashboard) | Landing + analytics render | PASS | KPIs, membership growth, tier dist, by-group, certs, pillars, top contributors, leaderboard all rendered; no errors |
| 4 | CL | /groups (User Groups) | List groups + Join Requests tabs | PASS | API returns 2 groups; table renders both; "Join Requests 2". (Initial "Showing 0" was pre-load race, resolved on wait) |
| 5 | CL | /events | Events list + filters + Calendar/Manage/Content Library tabs | PASS | Filters (status/type/quarter) and tabs render |
| 6 | CL | /forums | Forum discussions/channels | PASS | Serverless Guild, #General channel, post "Cold start tips?" (1 of 1) |
| 7 | CL | /scoring-framework | Activity types / event points / tiers | PASS | Pillars, activities (incl. custom "the developer Test Upskilling Activity"), edit/delete controls |
| 8 | CL | /certifications | Pending / Definitions / Ledger / Revoke tabs | PASS | Pending empty (0, plausibly correct); Definitions shows 2 defs incl. "AWS Certified Advanced Networking - Specialty" |
| 9 | CL | /contributions | Approvals + Point Ledger tabs | PASS | Pending Approvals 0 of 0; Adjust points control present |
| 10 | CL | /directory | Member Directory list | PASS | "Showing 16" after load; role/group filters + Export CSV present (slow load >3s) |
| 11 | CL | /announcements | Announcements list + moderation | PASS | New Announcement + "Show all (moderation)" control; 0 of 0 |
| 12 | CL | /whats-new | External AWS feed | PASS | Feed loaded with category facets (Bedrock, CloudWatch, DynamoDB, EC2...) after ~several s |
| 13 | CL | /file-sharing | File sharing (leader-only) | PASS | Slot creation / external upload link UI renders |

**CL observations:**
- **No session persistence:** the auth token is in-memory for the tab only. A full page reload or deep-link to any route drops to the login screen (matches apiClient code comment). Consequence: route-guard negative tests (e.g. CL → /admin/users redirect) can't be exercised via deep-link — they land on login first, not the client-side guard.
- **Slow first-paint:** several pages show "Loading…"/"Showing 0" for 2–5s before data resolves. Not a failure, but user-visible latency worth noting.

### Session persistence fix (Option A — sessionStorage) — re-verified 2026-08-12
| # | Role | Area | Test | Result | Notes |
|---|------|------|------|--------|-------|
| 14 | CL | Session | Reload on `/` stays authenticated | PASS | `cp.session` rehydrated from sessionStorage |
| 15 | CL | Session | Deep-link `/groups`, `/certifications` (full load) stays authenticated | PASS | No drop to login; header shows CommunityLeader |
| 16 | CL | Session | Reload on a deep route stays authenticated | PASS | |
| 17 | CL | Security | Token NOT on disk | PASS | Only `cp.session` in sessionStorage; localStorage has just `announce.dismissed` |
| 18 | CL | Route guard | Deep-link `/admin/users` redirects away | PASS | Lands on `/` (Community Analytics), admin not rendered |
| 19 | CL | Route guard | Deep-link `/admin/settings` redirects away | PASS | Lands on `/` |
| 20 | CL | Session | Logout clears stored session | PASS | sessionStorage keys emptied; returned to login |
| 21 | CL | Session | Deep-link after logout does NOT rehydrate | PASS | `/groups` shows login screen (no stale session) |

### CommunityLeader — write flows (Option A scope) 2026-08-12
| # | Role | Area | Test | Result | Notes |
|---|------|------|------|--------|-------|
| 22 | CL | /announcements | Create community-wide announcement | PASS | POST 201; appears in list "1 of 1" as Active; email left off |
| 23 | CL | /events | Create community-wide event (title/date/location/scope) | PASS | POST 201; required-field validation enforced; appears in Upcoming list |
| 24 | CL | /events | Edit event (title) | PASS | Edit modal pre-filled correctly; "Save Changes" persisted "(edited)" title |

_Test data left in place (labelled "[E2E]"): 1 announcement (expires 14 Aug), 1 event "[E2E] Playwright Test Event (edited)" (15 Sep). Non-destructive per Option A._

### UserGroupLeader #1 (user+ugl1 — leads "AWS Kolkata UG", 0 members) 2026-08-12
| # | Role | Area | Test | Result | Notes |
|---|------|------|------|--------|-------|
| 25 | UGL1 | /auth | Login (after password reset) | PASS | Landed on "AWS Kolkata UG — Dashboard" |
| 26 | UGL1 | / (Group Dashboard) | UGL landing renders group KPIs | PASS | Members 0 / events 0 / points 0 / pending 0 — matches empty group |
| 27 | UGL1 | /my-group | My Group (Overview/Points/Join Requests) | PASS | "Join Requests 2" pending; group details shown |
| 28 | UGL1 | /contributions | Leaderboard/Framework/Approvals/Ledger tabs | PASS | Scoped to led group; Framework shown read-only tab |
| 29 | UGL1 | /certifications | Verify/browse/submit-own claims | PASS | UGL-specific copy ("claims credited to the group you lead") |
| 30 | UGL1 | /forum-moderation | Forum Moderation | N/A (COMING SOON) | Deliberate placeholder route (ComingSoon in App.tsx), not a defect |
| 31 | UGL1 | /directory, /announcements, /events, /forums, /whats-new, /file-sharing | Read/navigation | PASS | Announcements scoped "Broadcast to your group" |
| 32 | UGL1 | /events | Create event (write) | PASS | Auto-scoped to led group (no scope dropdown — UGL leads one group); event created, list "Showing 3" |

Note: console 401 seen was the pre-reset UGL1 login attempt (stale), not a current error.

### UserGroupLeader #2 (user+ugl2 — leads "AWS Bangalore UG", 3 members) 2026-08-12
| # | Role | Area | Test | Result | Notes |
|---|------|------|------|--------|-------|
| 33 | UGL2 | /auth | Login | PASS | Landed on "AWS Bangalore UG — Dashboard" |
| 34 | UGL2 | / (Group Dashboard) | KPIs with real data | PASS | Members 3, Points 145 (2026-Q3), pending 0 |
| 35 | UGL2 | /my-group | Members list populated | PASS | Members 3, leader shown, group details |
| 36 | UGL2 | /contributions (Leaderboard) | Populated leaderboard/tiers/pillars | PASS | "the developer as Member One" 90 pts Gold; quarter/pillar filters present |

### Member (user+blr4 — no group) 2026-08-12
| # | Role | Area | Test | Result | Notes |
|---|------|------|------|--------|-------|
| 37 | Member | /auth | Login | PASS | Landed on member dashboard with "Join a user group" onboarding |
| 38 | Member | / (Dashboard) | Member home + onboarding | PASS | Points this quarter 0; leaderboard/my-contributions tabs |
| 39 | Member | /events | Browse events (no create) | PASS | "Browse Events" + Calendar + Content Library; member-scoped copy |
| 40 | Member | /forums | View + New Post (no channel mgmt) | PASS | Serverless Guild discussions; "+ New Post" only |
| 41 | Member | /certifications | Catalog + My Submissions | PASS | Can browse catalog + submit claims |
| 42 | Member | /contributions | My Contributions | PASS | "No contributions yet — join a group" (correct, no group) |
| 43 | Member | /groups | Joinable groups list | PASS | Kolkata "Approval required", Bangalore joinable |
| 44 | Member | /directory | Member directory | PASS | "Showing 16" after load |
| 45 | Member | /whats-new | AWS feed | PASS | Feed + category facets |
| 46 | Member | /profile | View profile | PASS | Populated (name, email, location, role) |
| 47 | Member | /profile | Edit profile bio (write) | PASS | Bio persisted under "Bio & Skills" |
| 48 | Member | /events/:id | RSVP "Going" (write) | PASS | "You're going. A calendar invite has been sent." |

---

## Summary

**Roles covered:** CommunityLeader, UserGroupLeader x2 (empty + populated group), Member. Administrator excluded per instruction.

**Overall:** No functional defects found. All role landing pages, navigation, and role-scoped content render correctly. Write flows validated (announcement create; event create + edit; RSVP; profile edit) all persist via 201/200 with correct refetch.

**Verified behaviors of note:**
- Session persistence fix (Option A / sessionStorage) works: survives reload + deep-link, cleared on logout, token not on disk.
- Route guards enforce role scoping (CL/Member blocked from /admin/*; redirect to landing).
- UGL event scope auto-fixed to the single led group (no scope picker).
- /forum-moderation is an intentional "Coming soon" placeholder (not a defect).

**Recurring non-defect observation:** first paint on data pages shows "Loading…"/"Showing 0" for ~2–5s before data resolves — user-visible latency, not a failure.

**Write flows present but NOT exercised** (to limit live-data mutation): certification claim submit (Member), forum new post, join-group request, CL contribution approvals + adjust-points (no pending items existed), certification define, scoring-activity add, group create, join-request approval. Can exercise on request.

**Test data left in place (labelled "[E2E]"):** 1 community announcement (expires 14 Aug), 1 community event "[E2E] Playwright Test Event (edited)", 1 Kolkata event "[E2E] UGL1 Kolkata Test Event", 1 profile bio edit on user+blr4, 1 RSVP (blr4 → community workshop). All non-destructive; can be cleaned up on request.

---

## Cleanup of first-pass test data (2026-08-12)
| Item | Action | Result |
|------|--------|--------|
| RSVP (blr4 → community workshop) | Set "Not going" | Reverted |
| Profile bio (blr4) | Cleared | Reverted |
| `[E2E]` announcement | Delete | Removed |
| `[E2E] Playwright Test Event` | Cancel | Cancelled (no UI hard-delete for events) |
| `[E2E] UGL1 Kolkata Test Event` | Cancel | Cancelled |

Note: events have no hard-delete in the UI — "Cancel" is terminal (Cancelled badge), matching pre-existing cancelled tombstones. Cancelled `[E2E]` events remain visible under "All statuses".

---

## Cross-role data propagation validation (2026-08-12)

### Scenario A — Announcement propagation
| Step | Role | Action | Result |
|------|------|--------|--------|
| A1 | CL | Post community-wide announcement "[E2E] Community broadcast" | PASS (201, listed) |
| A2 | Member (blr4) | View dashboard announcements widget | PASS — broadcast visible, badge "1" |
| A3 | Member (blr4) | /announcements page | Members get "Coming soon" placeholder here; they consume via dashboard (consistent with member nav having no Announcements link) |

### Scenario B — Join request + approval propagation
| Step | Role | Action | Result |
|------|------|--------|--------|
| B1 | Member (blr4) | Request to join "AWS Kolkata UG" (approval-required) | PASS — "Request sent"; group shows "Requested" |
| B2 | UGL1 | Join Requests queue shows blr4's request | PASS — request visible (queue 2→3) |
| B3 | UGL1 | Approve blr4 | Member added; Kolkata count 0→ (see incident) |

**INCIDENT (tester error, corrected):** the approval automation's fallback confirm-click hit a second Approve button, so a **pre-existing pending request from "the developer as Member One" was also approved** (Kolkata jumped to 2 members). I removed "the developer as Member One" from the group to restore state (now 1 member = blr4). 
- **Not fully reversible:** their original *pending join request* was consumed by the approval and is gone; they received approve + remove emails. They would need to re-request to restore their prior pending state.
- Root cause: using a `.last()` fallback click on action buttons. Fixed approach: scope confirms to the dialog only.

**Minor UI bug observed:** members table header read "Showing 1–3 of 2 members" (off-by-one; leader row counted inconsistently).

**Residual test data:** blr4 is now a member of "AWS Kolkata UG" (intended test artifact, not yet cleaned).

### Scenario D — Event visibility propagation
| Step | Role | Action | Result |
|------|------|--------|--------|
| D1 | UGL1 | Create event scoped to Kolkata "[E2E] Kolkata Members Event" | PASS (created) |
| D2 | Member (blr4, Kolkata member) | Sees the Kolkata event in Events list | PASS |
| D2b | Member (blr4) | Groups page shows Kolkata as "Joined" (Leave button) | PASS — membership propagated |

### Scenario C — Certification claim → verify → points (flagship cross-role chain)
| Step | Role | Action | Result |
|------|------|--------|--------|
| C1 | Member (blr4) | Submit cert claim (Advanced Networking) crediting Kolkata, evidence link | PASS — appears in My Submissions |
| C2 | UGL1 | Claim appears in Pending Verifications queue | PASS — routed to led-group leader |
| C3 | UGL1 | Approve claim (confirm dialog) | PASS — queue → 0 |
| C4 | UGL1 | Kolkata leaderboard reflects award | PASS — "25 pts · Kolkata · 🥉 Bronze" |
| C5 | Member (blr4) | Dashboard + My Contributions reflect points | PASS — "POINTS THIS QUARTER 25"; Lifetime 25 / Q3 25 (Kolkata) |

**Cross-role propagation confirmed end-to-end for announcements, events, membership, and the full certification→points→tier chain.**

### Scenario E — Forum post — ❌ DEFECT FOUND
| Step | Role | Action | Result |
|------|------|--------|--------|
| E1 | Member (blr4) | Create forum post in channel c-general | POST **201** but post **never appears** in the channel (still "1 of 1" after reload) |

**Analysis — Forums appears to still be MOCK-backed in this deployment:**
- Forums reads return **seed/fixture data** that does NOT match the real deployment: forum "Serverless Guild", channel "c-general", post "Cold start tips?" by author `u-mem-1` (a fixture id, not a real Cognito sub). The real groups are Kolkata/Bangalore — there is no "Serverless Guild".
- POST /channels/c-general/posts returns 201 (a create ack) but GET /channels/c-general/posts keeps returning only the fixture post (`count: 1`).
- This matches the mock runtime's behavior exactly (create → synthetic 201; list → fixtures). **Likely the Forums service is not the real service in this environment** (contrary to "all real services deployed"), or has a read/write store mismatch. Recommend verifying the Forums stack's service-mode.

### Scenario F — Manual point adjustment
| Step | Role | Action | Result |
|------|------|--------|--------|
| F1 | UGL1 | Adjust +5 pts for blr4 (Kolkata, Q3), with reason | PASS — "Adjustment recorded" |
| F2 | UGL1 | Point Ledger tab shows entries | PASS — "Manual Adjustment" + "Certification" entries listed |
| F3 | UGL1 | Leaderboard total updates | PASS — blr4 now "30 pts · Kolkata · 🥉 Bronze" (25 cert + 5 adjustment) |

Note: Point Ledger + Certification Ledger enhancements (the ones absent from stories.md) are functional and display correctly.

---

## Cross-role validation — summary

| Flow | Chain | Result |
|------|-------|--------|
| Announcement | CL post (community) → Member dashboard widget | PASS |
| Join + approval | Member request → UGL queue → approve → membership + count | PASS (see incident above) |
| Event | UGL group event → group member's Events list | PASS |
| Certification → points | Member claim → UGL verify/approve → +25 pts → tier, leaderboard, member dashboard & contributions | PASS |
| Manual adjustment | UGL +5 → Point Ledger + leaderboard (30 pts) | PASS |
| Forum post | Member post → channel list | **FAIL — Forums appears mock-backed; POST 201 but post not persisted; reads show fixture data (Serverless Guild / u-mem-1)** |

### Key defects / findings
1. **Forums service appears NOT to be the real service** in this deployment (serves seed fixtures; writes 201 but don't persist). Highest-priority item to verify.
2. **Off-by-one in group members count** ("Showing 1–3 of 2 members").
3. Tester incident (corrected): an extra pre-existing join request from "the developer as Member One" was approved then the member removed; their pending request is consumed (not restorable) and they were emailed.

### Residual data from this pass (persistent; some NOT reversible by design)
- blr4 is a **member of Kolkata** (reversible: Leave/Remove).
- blr4 holds the **AWS Certified Advanced Networking** badge + **25 pts**, plus a **+5 manual adjustment** (30 pts total). Point-ledger entries are **permanent by design** (offset only, cannot be deleted) — not cleanly reversible.
- `[E2E] Kolkata Members Event` (Upcoming, Kolkata).
- `[E2E] Community broadcast` announcement (CL, community).
- "the developer as Member One" removed from Kolkata (see incident).

---

## Dashboard numeric reconciliation (CL Community Analytics, 2026-Q3)

Verified aggregate KPIs against expected values after the write scenarios (blr4: joined Kolkata; +25 cert; +5 adjustment = 30 pts).

| Metric | Shown | Expected | Verdict |
|--------|-------|----------|---------|
| Points Distributed (live) | 175 | 145 + 30 = 175 | ✅ correct |
| Members by group (live-ish) | Bangalore 3 / Kolkata 1 / none 6 | blr4 moved none→Kolkata | ✅ correct (sums to 10) |
| Events by group (live, excl cancelled) | Kolkata 1 / Bangalore 1 / Community 1 | new Kolkata event counted; cancelled excluded | ✅ correct |
| Certification Snapshot | Advanced Networking ×1 | blr4's approved claim | ✅ correct |
| Leaderboard (Kolkata) | blr4 30 pts Bronze | 25 + 5 | ✅ correct |
| **Points by Pillar** | 100+0+30+35 = **165** | should equal 175 | ⚠️ **DISCREPANCY — 10 pts unaccounted** |
| Active Members (nightly) | 2 (20%) | should be 3 (30%) | ⏳ stale (nightly, as of 07:30) |
| Tier Distribution (nightly) | Gold1/Silver1/Bronze0 | should show Bronze 1 | ⏳ stale — inconsistent w/ live leaderboard showing blr4 Bronze |
| Top Contributors (nightly) | morning snapshot | — | ⏳ stale |

### Finding — Points by Pillar does not reconcile with Points Distributed
- Pillar breakdown sums to **165** but headline total is **175**. Gap = **10** = manual point adjustments, which carry **no pillar** (the adjust-points form has no pillar field) yet are counted in the community total and leaderboard.
- Pre-existing: same gap was 5 (pillars 140 vs total 145) before this test → grew to 10 after the +5 adjustment. So this is a standing behavior, not introduced by rendering.
- Impact: the pillar chart can't be reconciled against the headline "Points Distributed". Recommend either attributing adjustments to a pillar/"Other" bucket or annotating the chart that it excludes manual adjustments.

### Note on live vs nightly
Membership / active / tier / top-contributor tiles are nightly-computed ("Updated nightly"); points-distributed, by-group, events, leaderboard are live. Same-day writes create a temporary inconsistency between the live leaderboard (blr4 = Bronze) and the nightly Tier Distribution (Bronze 0) until the overnight batch runs. Expected by design, but worth being aware of when validating.

---

## Input validation & message-clarity checks (representative sample, 2026-08-12)

| Test | Field/Form | Input | Result | Message quality |
|------|-----------|-------|--------|-----------------|
| Special chars / XSS | Event → Title | `E2E Probe <b>x</b>` | Rejected (server) | ✅ **Clear**: "Validation failed. Title: must not contain '<' or '>'" (names field + rule) |
| Length / boundary | Announcement → Title (320 chars) and/or Expiry > 90 days | over-limit | Rejected (HTTP 400) | ❌ **Unclear**: only "Validation failed." — no field, no limit, no fix. API body = `{"code":"VALIDATION_ERROR","message":"Validation failed."}` (no `details`) |
| Required fields | Event/Announcement | — | Publish/Post **not disabled**; validated server-side on submit | ⚠️ No inline/client-side validation; user learns of errors only after submitting |

### Findings
1. **Inconsistent validation-error quality across services.** The **Events** service returns detailed field-level errors ("Title: must not contain '<' or '>'"); the **Announcements** service returns a generic "Validation failed." with no field/limit/reason. The frontend (apiClient) is built to append per-field `details[]` when present — Announcements simply doesn't return them. Recommend Announcements (and any other terse services) return structured `details[]` like Events does.
2. **Angle-bracket blocking** on titles is enforced server-side (good anti-injection default), with a clear message.
3. **No client-side/inline validation** — submit buttons stay enabled on invalid input; all validation is server-round-trip. Consider inline hints for length/format/required.

### Success/failure message clarity (observed during the run — these are GOOD, specific, not "done"/"error")
- "Request sent — a leader needs to approve it." (join request)
- "You're going. A calendar invite has been sent." (RSVP)
- "RSVP updated. The event has been removed from your calendar." (RSVP undo)
- "Adjustment recorded for the developer BLR Four" (points adjustment)
- Cancel event confirm: "…the event stays visible with a Cancelled badge. This cannot be undone."

### NOT yet tested (coverage gaps to flag)
Bio max-length (1–2000) live message, skills field, notes fields, whitespace-only/empty-trim, unicode/emoji, very-long body, negative/zero/º non-numeric point adjustments, password-policy messages, OTP code errors, duplicate-claim message, date-format edge cases. This was a representative sample, not exhaustive.

---

## Full form validation audit (all write forms, via authenticated API probes) — 2026-08-12

Method: drove each form's backing endpoint with invalid payloads (500-char values, angle brackets, bad formats/types) using the live session token, captured HTTP status + message + whether field-level `details[]` were returned. Invalid payloads are rejected (4xx) so no data is created — except where noted (Forums).

### Message clarity by form
| Form / endpoint | Bad input | Status | Message | Clarity |
|---|---|---|---|---|
| Event create `/events` | 500-char title | 400 | `title: length must be 1-200` | ✅ clear (field+limit) |
| Certification define `/certifications` | 500-char name + `<b>` | 400 | `name: length must be 1-120` | ✅ clear |
| Cert claim `/certifications/claims` | bad ids/date/url | 400 | `certId: must be a string` | ✅ clear (field name internal) |
| Point adjustment `/contributions/adjustments` | points="abc" | 400 | `delta: must be an integer` | ✅ clear (field name internal) |
| Contribution submission `/contributions/submissions` | bad group | 400 | `groupId: must be a group you belong to` | ✅ clear |
| Profile update `/members/me` | 3000-char bio; `<b>` role | 400 | `bio: length must be 1-2000`; `professionalRole: must not contain '<' or '>'` | ✅ clear |
| **Announcement create `/announcements`** | 500-char title | 400 | `Validation failed.` (no details) | ❌ **generic** |
| **Group create `/groups`** | 500-char name + `<b>` | 400 | `Validation failed.` (no details) | ❌ **generic** |
| **Self-registration `/auth/register`** | invalid email, empty last name | 400 | `Validation failed.` | ❌ **generic** |
| **Login `/auth/login`** | invalid email, empty pw | 400 | `Validation failed.` | ❌ generic (acceptable for enumeration, but no format hint) |
| **Password reset `/auth/reset` + confirm** | invalid email; weak password | 400 | `Validation failed.` | ❌ generic (no password-policy guidance) |
| **Scoring activity `/contributions/framework`** | points="abc", bad pillar | **500** | `An unexpected error occurred.` | ❌ **BUG — server error on bad input (should be 400)** |
| **Forum create `/forums`** | 500-char + `<b>` name | **201** | — created | ❌ **NO validation** |
| **Channel create `/forums/x/channels`** | 500-char name, non-existent forum `x` | **201** | — created | ❌ **NO validation / no parent check** |
| **Forum post `/channels/x/posts`** | 500-char title, non-existent channel `x` | **201** | — created | ❌ **NO validation / no parent check** |
| **Notification prefs `/notifications/preferences`** | `{bogus:true}` | **200** | — accepted | ⚠️ accepts unknown payload silently |
| Settings update `/settings` (as CL) | — | 403 | `Only Administrators can change settings.` | ✅ clear authz msg |

### Issues found (prioritized)
1. **BUG — Scoring Framework activity returns HTTP 500 on invalid input** (non-numeric points / invalid pillar). Unhandled exception instead of a 400 validation error. Highest priority.
2. **Forums service performs NO input validation** — accepts 500-char + angle-bracket names AND non-existent parent forum/channel IDs, all returning 201. Consistent with earlier finding that Forums appears mock-backed. (This probe may have created orphan mock forum/channel/post records; they don't surface on reads.)
3. **Inconsistent validation-message quality across services.** Clear field-level detail: Events, Certifications, Contributions, Member-profiles. Generic "Validation failed." with no field/reason: **Announcements, Groups (identity-access), Auth (register/login/reset)**. The frontend already renders `details[]` when present — these services just don't send them.
4. **Password reset/confirm gives no password-policy guidance** ("Validation failed." on a weak password).
5. **Notification preferences** accepts an unknown/bogus payload with 200 (no schema validation feedback).

### Positives
- Angle-bracket (`<` `>`) injection is blocked with clear messages on Events, Certifications, Member-profiles.
- Exact length limits enforced & surfaced where detailed (event title 200, cert name 120, bio 2000).
- Authorization messages are clear and specific ("Only members can submit contributions.", "Only Administrators can change settings.").
- Success messages are specific (documented above), not "done".

### Not covered by this method (would need UI-level or more probes)
Client-side-only checks (reset password-mismatch inline, submit-button disabling), edit/PUT forms (event/announcement/email-template edit), file-share slot, group-join/RSVP/reject-reason, OTP code errors, whitespace-only/unicode/emoji specifics.

---

## Full lifecycle test: 4 members → join → certifications + contributions → UGL approvals (2026-08-12)

### Step 1 — Login all 4 members
| Member | Login | Result |
|--------|-------|--------|
| user+blr4 | ✅ | Already Kolkata member |
| user+blr2 | ✅ | — |
| user+test1 | ✅ | — |
| user+blr3 | ✅ | — |

### Step 2 — Join groups
| Member | Group | Method | Result |
|--------|-------|--------|--------|
| blr4 | Kolkata | (already member) | — |
| blr2 | Bangalore | Open join | ✅ 200 |
| test1 | Bangalore | Open join | ✅ 200 |
| blr3 | Kolkata | Request (approval-required) → UGL1 approved | ✅ 200 → Approved |

### Step 3 — Submit certifications + contributions (all 201)
| Member | Cert claimed | Contribution activity | Group | Cert status | Contrib status |
|--------|---|---|---|---|---|
| blr4 | Security Specialty | Blog / article | Kolkata | 201 ✅ | 201 ✅ |
| blr2 | Advanced Networking | Open-source | Bangalore | 201 ✅ | 201 ✅ |
| test1 | Security Specialty | Public speaking | Bangalore | 201 ✅ | 201 ✅ |
| blr3 | Advanced Networking | Reusable asset | Kolkata | 201 ✅ | 201 ✅ |

### Step 4 — UGL approvals (all 200)
| UGL | Group | Certs approved | Contributions approved |
|-----|-------|---|---|
| UGL1 | Kolkata | 2 (blr4 Security, blr3 Networking) | 2 (blr4 blog, blr3 reusable-asset) |
| UGL2 | Bangalore | 2 (blr2 Networking, test1 Security) | 2 (blr2 open-source, test1 speaking) |

### Step 5 — Verification: Leaderboards after approvals

**Kolkata (Q3 2026):**
| Rank | Member | Points | Tier |
|------|--------|--------|------|
| 1 | the developer BLR Four | 70 | Silver |
| 2 | the developer BLR Three | 37 | Bronze |

**Bangalore (Q3 2026):**
| Rank | Member | Points | Tier |
|------|--------|--------|------|
| 1 | the developer as Member One | 90 | Gold |
| 2 | (empty name) | 55 | Silver |
| 3 | the developer Test1 Member | 45 | Bronze |
| 4 | the developer BLR Two | 40 | Bronze |

### Issues found
1. ⚠️ **Bangalore rank 2 has an empty `memberName`** — the leaderboard renders a blank name for one member (55 pts, Silver). This is likely "the developer BLR One" whose profile `firstName`/`lastName` may not have been set, or a data-model gap. Should display at minimum the email or "Unknown".
2. All other data propagated correctly: cert approval → badge + 25 pts; contribution approval → activity points; leaderboard rankings and tier calculations are correct.
