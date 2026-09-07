# End-to-End Test Instructions — AWS Community Portal

**Generated**: 2026-08-05

## Status

**No automated E2E suite exists.** No Playwright/Cypress harness is committed and nothing
in CI drives a browser. What follows is the manual walkthrough that has been used per unit
at deploy time (recorded in `audit.md`), written down so it is repeatable, plus a proposed
shape for automating it.

## Personas to walk

The portal is role-shaped throughout, so a single happy path proves very little. Four
walks are needed, and the differences between them are the point.

| Persona | Sees Events? | Key differences |
|---|---|---|
| Community Leader | yes | Scope column in the list; group filter on the calendar; can create community-wide events; Content Library spans all groups |
| User Group Leader | yes | No Scope column; readonly scope field on create; no calendar group filter; Content Library is own group + community-wide |
| Member | yes | Card grid with status tabs; no management controls anywhere |
| Administrator | **no** | No Events nav item; a direct `/events` URL is refused |

## Walk 1 — Community Leader, full event lifecycle

1. Sign in as a Community Leader. Confirm **Events** appears in the sidebar.
2. `/events` → the management table renders with search, status/type filters, a **Scope**
   column, Rows selector and Prev/Next.
3. **Create Event** → fill title, description, type, delivery mode (Virtual), an
   `https://` join link, date/time, duration, Scope = Community-wide. Publish. Expect the row to appear with an `Upcoming` badge.
4. Try to create a Virtual event with an `http://` link. Expect an inline validation error,
   not a server round-trip failure.
5. **Create a recurring series**: toggle Recurring, choose Weekly, a 4-week range, a time
   of day. Publish. Expect a `Recurring` row; expand it and expect individual occurrences
   indented beneath, each with its own Manage/Edit/Cancel.
6. Try a Daily series spanning a year. Expect a clear rejection naming the 104-occurrence
   cap — not a timeout, and no partial series left behind.
7. Cancel one occurrence. Confirm the dialog explains that RSVPs are notified and the event
   stays visible; confirm siblings are untouched.
8. **Manage** an event → five stat cards, then walk all five tabs (Attendance, RSVP List,
   Materials, MS Teams, Designations).
9. **Materials** → upload a PDF. Expect a `Scanning…` status, then `Clean` once GuardDuty
   reports. Add an external link. Try uploading a `.exe` and expect rejection **before**
   any upload begins.
10. **Designations** → designate a Member as presenter and a Community Leader as organizer.
    Expect the Member to show "earns points: Yes" and the leader to show the ineligibility
    reason inline.
11. **Upload link** → create one, copy the URL from the one-time panel, then revoke it.
12. Move the event's date into the past (or use a past event), then **Mark Completed**.
    Expect the confirmation to mention that eligible designees earn points now.
13. `/events/calendar` → Month/Week/List all render; chips navigate to the event; the group
    filter is present.
14. **Content Library** → nothing shows until Search is pressed; searching a word from the
    completed event's title returns its material with working open/download actions.

## Walk 2 — User Group Leader

Repeat the parts of Walk 1 that apply and confirm the differences:

* The create modal's Scope field is **readonly** and names the led group.
* Attempting an event for another group is refused server-side (the UI does not offer it).
* The list has **no Scope column**.
* The calendar has **no group filter**.
* A Community-Leader-created event scoped to the led group is still editable — this is
  US-2.4's explicit rule and the most commonly misunderstood one.

## Walk 3 — Member

1. `/events` → card grid, status tabs (Upcoming/Completed/Cancelled), search, type and
   delivery-mode filters, a Calendar view link. **No** Create button.
2. RSVP from a card → the card flips to `✓ You RSVP'd`.
3. Open an event → summary card, field grid, presenters with eligibility notes, materials
   with Download, RSVP panel with counts, points tag, and `Download .ics`.
4. Press **Download .ics** → a file downloads and opens in a calendar client with the right
   title, time and location.
5. Flip RSVP from Going to Not going → expect the message to say the event was removed from
   your calendar.
6. Confirm quarantined and still-scanning materials are **not** visible.
7. Confirm no Manage link and no management tabs anywhere.
8. Cancelled tab → cards render with a `Cancelled` badge and are not clickable.

## Walk 4 — Administrator (negative walk)

1. Sign in as an Administrator. Confirm the sidebar shows **no Events item**.
2. Navigate directly to `/events`. Expect a clear "Administrators do not participate in
   events" state, not a crash and not data.
3. Navigate directly to `/events/calendar` and `/events/<id>`. Same expectation.
4. Call the API directly with an admin token: `GET /events` → **403**;
   `GET /events/<id>` → **404** (visibility is evaluated before anything else).

This walk exists because "no nav item" is not a control. The server refusal is.

## Cross-service walk (once Unit 7 and Unit 10 are real)

Currently blocked: Contributions & Scoring and Notifications are still mocks, so the two
most visible end-to-end effects cannot be observed.

1. Apply attendance for a member → their points ledger and tier update in Contributions,
   and the value appears on their profile.
2. RSVP yes → a calendar invite email arrives with a valid `.ics` attachment.
3. Add a post-event material → RSVP'd members receive the notification email.
4. Create an event with "also post an announcement" → the announcement appears for the
   target audience.

Until then, the correct assertion is that the **events are published** (visible on the bus
or in the publisher's logs), which the unit tests already cover.

## Proposed automation (not built)

* Playwright under `tests/e2e/`, one spec per persona walk, driven by seeded personas from
  `infra/seed.yaml`.
* Run against the dev stack after deploy, gated behind an env var so it is skipped locally.
* Assert on the `data-testid` attributes already present throughout the Events UI —
  `create-event`, `events-search`, `status-tab-upcoming`, `rsvp-yes`, `tab-materials`,
  `designations-save`, `library-search-btn`, `cal-view-week` and so on. They were added for
  exactly this purpose.
* Keep the Administrator negative walk in the suite. It is the cheapest guard against an
  authorization regression reaching users.
