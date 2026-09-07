# Change: "My Group" for User Group Leaders + 13k-member scale

**Date**: 2026-08-05 · **Units**: 2 (Identity & Access), 15 (SPA)
**Plan**: `aidlc-docs/construction/plans/ugl-my-group-plan.md`
**Request**: replace the UGL's "User Groups" menu with "My Group", per the user
stories and `requirements/mockup/ugl/group.html`, keeping in mind that a member
list may hold 13,000+ records.

---

## What the request actually contained

Two changes of very different size. The nav/screen change is small. The scale
requirement exposed a real defect that the existing UI paging was hiding.

### The defect

`GroupDetailPage` already did server-side cursor pagination, so the member table
looked fine. The backend behind it did not:

```
list_group_members_page()
  -> _member_id_order()
       -> current_members_of_group()
            -> group_events()          # EVERY membership event the group ever had
  -> get_user(mid) per member id       # to apply the keyword filter
```

For a 13,000-member group, one page of 25 rows read 13,000+ event items and, with
a search term active, up to 13,000 additional `GetItem` calls. `list_groups()`
called the same fold **once per group in a loop**, so a single `GET /groups` folded
the entire community's membership history. The same shape appeared in three more
places: the membership-history view, the join-request list (which was also
truncating silently at DynamoDB's 1 MB Query page), and the unpaged CSV export
branch, which would additionally have exceeded API Gateway's 6 MB response limit.

## What changed

### Current membership is now materialised

```
GROUP#<groupId> / MEMBER#<memberId>   { memberId, groupId, joinedAt, searchKey }
GROUP#<groupId> / MEMBERCOUNT         { memberCount }
```

Written inside `repository.append_membership_event` — the one method every
membership mutation in the service already passes through (group_service,
user_service, seed, tests). Putting it there rather than in the callers means
there is one place it can be forgotten instead of four. The append-only event log
remains the source of truth; `derive_members_from_events()` rebuilds the
projection from it and is what the backfill tool runs.

Result: a page of the member list is one Query bounded by `limit`, plus one
profile read per row actually returned.

### Three decisions worth recording

**The counter is its own item, not an attribute on the group.** `put_group()` does
a full `put_item`, so a counter on the `META` row would be silently wiped by any
read-modify-write of the group — edit, assign leader, restore. It is maintained
with conditional writes (`attribute_not_exists` on join, `attribute_exists` on
leave), which makes it exact rather than best-effort: a duplicate join event
cannot inflate it and an end event for a non-member cannot drive it negative.
Both cases are tested.

**`searchKey` is denormalised so the keyword filter can be pushed into DynamoDB.**
Without it, matching a keyword requires reading every member's profile to test the
match — 13,000 `GetItem` calls for a query that matches nothing, which is worse
than no search at all. With a `contains()` FilterExpression, non-matching rows are
discarded server-side. Only `professionalRole` in that haystack can change after a
join (names and email are Cognito-owned and read-only in the portal), so
`edit_user` refreshes it.

**The member cursor carries two fields, `{m, ld}`.** The member screen lists the
group's leaders first and then members in id order, because leadership is not
membership — a UGL has no join event but must still appear in their group's member
list. A single-field cursor cannot distinguish "stopped inside the leader block"
from "stopped inside the member block", and resuming in the wrong one **silently
skips every member whose id sorts below the last leader's id**. This is not
theoretical: `test_page_size_smaller_than_the_leader_block_still_advances` fails
if the flag is removed. The pre-existing `{m}` form is still accepted.

### Also paged

- `GET /membership-history?groupId=` — `limit`/`cursor`, newest first, via GSI3 read backwards.
- `GET /groups/{id}/requests` — `limit`/`cursor`; the repository Query is now a
  full pagination loop (it was one page, so a long request history truncated).
- Group-member CSV export follows cursors client-side (`exportPagedCsv`).
- The points/tier leaderboard fetch behind the Points column is now bounded;
  rows outside the window show "—", the same degrade already used while
  contributions-scoring is a mock.

### Frontend

`UGL_NAV` is derived from `CL_NAV` with the single `/groups` entry replaced by
`My Group → /my-group`, matching the mockup, whose UGL sidebar contains no
"User Groups" item at all. New `MyGroupPage` built to the mockup: heading is the
group name, Overview / Join Requests tabs with a pending badge, Group Details and
Forums & Channels cards, members table with the previously-missing `Joined`
column, and both mockup footnotes. No Edit or Delete controls — US-1.18 makes
group configuration a Community Leader function, which the mockup states in its
own subtitle.

`ledGroupId` now comes back on the login/OTP response so the screen opens the
right group without a discovery round-trip (a UGL leads exactly one group, BR-G7).

The paging logic is shared with the CL's group screen via `lib/useGroupMembers`;
the two screens differ in layout, tabs, actions and permissions, so only that hook
is common.

---

## Deployed to dev — 2026-08-06

Account `123456789012` / `us-east-1` / stack `community-portal-dev`.

- Portal: **https://EXAMPLE.cloudfront.net**
- API: `https://EXAMPLE.execute-api.us-east-1.amazonaws.com/dev`

Order used (deliberately backfill-first): the projection rows are inert to the
previously deployed code, so writing them before switching the handler means
there is no window in which the portal reports zero members. The backfill was
re-run after the deploy to catch anything that changed during it; it reported
zero drift.

Live verification via `infra/tools/verify_my_group_deploy.py`, which invokes the
deployed Lambda directly with synthesised claims (the Cognito authorizer needs a
human password) — **28 checks across both live groups, all passing**: member
counts sourced from the new counter and agreeing with the event log, `joinedAt`
on every member row, `limit=1` cursor walks covering every row exactly once,
search pushdown returning a subset and zero for a non-match, newest-first history
paging, UGL scoping (403 for a group not led, 200 for the led group), malformed
cursor → 400, out-of-range limit → 400. Served bundle confirmed as the new one
and asserted to contain the My Group markup.

### Two deployment defects found, both mine

**1. The deploy would have silently shipped a stale UI.** The SPA is published by
a custom resource that uploads whatever is bundled at `./spa/` inside the seed
Lambda's own package. That directory is git-ignored and populated at deploy time
from `frontend/dist/` — and nothing was doing the copy. The first deploy therefore
reported `UPDATE_COMPLETE` with new Lambdas and **republished the previous
bundle**: `index-BHjg3WGp.js` was still being served while
`index-Lajurx7k.js` was the build. Caught by diffing the built, staged and served
asset hashes rather than by trusting the stack status. Fixed by adding an explicit
SPA staging step (`rsync --delete`, so a renamed asset cannot linger) to
`infra/tools/deploy.sh` as step 0, with the failure recorded in a comment.

This is the same failure shape as the Events fan-out timeout: everything reports
success and the feature simply is not there. Stack status is not a deployment
verification.

**2. The deploy procedure only existed as shell history.** The root template
references nested stacks by flat filename under `${TemplateBaseUrl}`, so every
nested template must already be in one S3 prefix with any `CodeUri` rewritten to
`s3://` — CloudFormation cannot resolve a relative path from a template it fetched
from S3. That is a per-template `sam package` followed by an upload, and it had
been done by hand, which is how the committed `.deploy-staging/` copies came to
exist. Now `infra/tools/deploy.sh`, with `TEMPLATES_ONLY=1` to stage without
deploying.

### Still outstanding

`infra/tools/live_forward_check.py` runs a join → approve → leave cycle through
the deployed Lambda to prove the counter is maintained **going forward** rather
than only populated by the backfill. It was interrupted by an expired AWS
token and has not completed. The risk it covers is narrow and partly retired
already: the logic is covered by unit tests, and the deploy-specific risk was IAM
(moto does not enforce it — this repo has already taken a live 502 that way),
which was checked directly: the execution role grants GetItem, PutItem,
UpdateItem, DeleteItem, Query and Scan on the table.

Authenticated end-to-end journeys through the browser still need a human with a
password.

## Migration note (how to re-run)

The dev table already holds membership events but no projection rows, so **every
group will report zero members until the backfill runs.** After deploying the new
handler:

```bash
python3 infra/tools/backfill_group_members.py --table identity-access-dev --dry-run
python3 infra/tools/backfill_group_members.py --table identity-access-dev
```

Idempotent, and also the repair path if a counter ever drifts. No schema change
and no new GSI, so there is no staged-index dance and no `-data` stack update —
the projection lives in the existing partition on existing keys.

Verified against a simulated pre-migration table: rebuild is correct, join dates
are preserved as the approval moment (BR-G5), a member who left is excluded, and
a second run changes nothing.

---

## Not done, deliberately

- **`listGroupMembers` / `getGroup` are absent from `OP_AUTHZ`**, so any
  authenticated user can read any group's member list. Recorded rather than
  changed: every role already holds `browse member-directory` at global scope, so
  the same member data is reachable by design, and adding a scope check here would
  restrict Member and Community Leader journeys the permission matrix permits.
  This belongs in its own review, not inside a UI change request.
- **Soft-deleting a group still writes one end event per member.** The member set
  now comes from the projection instead of an event fold, but it is still
  O(members) writes in a single invocation, which will not hold for a group of
  13,000.

## Verification

| Gate | Result |
|---|---|
| `pytest services/identity-access` | 164 passed (was 130; +34) |
| Full suite, one process per service | 572 passed (was 538), no regressions |
| `ruff check .` | clean |
| `cfn-lint` | clean |
| Contract gate | identity-access 27/27; all 12 services pass |
| `npm run build` | clean, 392.78 kB / 107.61 kB gzip |
| Backfill against a pre-migration table | rebuild correct + idempotent |
