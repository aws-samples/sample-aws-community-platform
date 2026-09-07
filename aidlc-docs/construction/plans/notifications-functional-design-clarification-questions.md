# Functional Design Clarifications — Unit 10: Notifications

> ## ⏸️ PARKED 2026-08-05 — unit restarts from Requirements Analysis
>
> Kept because the analysis below is the raw material for that requirements pass. See the banner in `notifications-functional-design-plan.md` for why the unit was stepped back.
>
> **Decisions reached in chat before parking** (carry forward as *input*, not as approved design):
> - **Fan-out shape — user approved**: two stages. One message per domain event → Resolver (resolves type, checks the admin switch, pages the audience, enqueues batches of ~100) → Deliverer (BatchWriteItem for in-portal rows, one SES send per recipient) with reserved concurrency pinned to the SES rate, a DLQ on both queues, and idempotency keyed on `(eventId, recipientId, channel)`. No channel split. 13k recipients → ~130 stage-2 messages.
> - **Recipient delivery — my recommendation reversed mid-discussion, undecided**: the size-bounded hybrid in C3 was withdrawn after three findings — (a) there is **no service-to-service auth path** in this codebase (Member Profiles' fan-out forwards the caller's JWT; a background consumer has no caller and every route sits behind the Cognito authorizer), (b) **two of the four audience kinds have no endpoint to page** — "all former members of a restored group" has no listing at all (`membershipHistory` is per-member) and `listRsvps` has no cursor or yes-only filter, (c) **the publisher already owns the audience locally**. Revised proposal: audience always inline, capped at ~200 recipients per event, publisher emits N events for a large audience (13k → 65 events ≈ 7 batched `PutEvents` calls), with the chunking loop in the publisher's **async consumer** rather than its request handler so redelivery retries it and a mid-loop failure cannot leave a partial fan-out behind a completed user action. The alternative — descriptor + Resolver paging — remains open but requires adding a service-principal auth pattern to the platform, which is a deliberate platform decision, not a Notifications detail.
> - Everything else in this file (C1 template ownership, C2b bulk send, C4/C4b panel semantics, C5a–C5d the US-8.7 withdrawal) is **still open**.

Round 2. Answers recorded in `notifications-functional-design-plan.md`: **Q1 A · Q4 A · Q6 A · Q7 A · Q8 A · Q10 A · Q11 A** (accepted, no follow-up needed).

Four items need resolution before artifacts can be generated:

| Item | Your answer | Why it's back |
|---|---|---|
| **Q2** template ownership | "Tell me more about B" | Deep dive below (C1) |
| **Q3** pipeline shape | "pros and cons for both… 13,000+ users per event notification" | Analysis below (C2) — **the 13k figure invalidates parts of Q3 A *and* of Q8 A**, see C2 + C3 |
| **Q5** panel semantics | "Need more discussion" | Analysis below (C4) |
| **Q9** preferences | "Users will not [have] any notification preference. Admin will setup the notification preference at the system wide." | Requirement change — withdraws US-8.7. Scope confirmation below (C5) |

**Verified platform limits used throughout** (checked against AWS docs today, not from memory):
- **SQS**: max message size **256 KB**.
- **EventBridge `PutEvents`**: total request must be **< 1 MB** (≤ 10 entries; a single entry may use the full 1 MB).
- **SES**: sandbox = **200 messages / 24 h, 1 msg/sec**. Quotas count **per recipient**, not per message. AWS explicitly recommends **one `SendEmail` call per recipient** (a multi-recipient call fails as a whole). `SendBulkEmail` accepts at most **50 destinations** per call and requires a stored or inline template.
- **DynamoDB**: `BatchWriteItem` = **25 items** per call. **Lambda**: **15-minute** max execution.

---

## C1 — Q2 revisited: what moving template ownership to Notifications (option B) actually costs

### What exists in Settings today
| Piece | Detail |
|---|---|
| Contract | `GET /settings/email-templates`, `PUT /settings/email-templates/{id}` |
| Code | `services/settings/src/email_template_service.py` (~45 lines: list + update, Administrator-only, publishes `SettingsChanged` with `emailTemplateId`) |
| Data | `DEFAULT_TEMPLATES` in `models.py` — **3 templates** (`tpl-welcome`, `tpl-approved`, `tpl-tier`), each `{id, name, subject, body}`. Repo falls back to defaults for any id not overridden in the table |
| UI | Admin Email Templates screen (a `DataTable` in `admin.tsx`) with an edit modal |
| Gap vs US-8.5 | 19 of 22 templates missing · **no `enabled` toggle** · no preview · no placeholder documentation |

### Option B — move it into Notifications
**Work required**: new `GET/PUT /notifications/templates{/id}` (the `/notifications` base path is already routed with a `{proxy+}`, so **no `api-edge.yaml` regeneration**); the 22 defaults + `enabled` flag + placeholder metadata land in Notifications' `models.py`; Administrator-only authz; the admin screen is repointed at the new routes; Settings' service code, tests, contract operations and repo methods are deleted.

**Pros**
- One owner for the 22 types. With Q7 = A (registry-driven engine) the registry, the templates and the `enabled` switches sit in **one process**, so the "the three lists cannot drift" requirement becomes an in-process unit test instead of a cross-service assertion.
- **No read dependency on Settings on the send path** — no cache, therefore no staleness window on a kill switch. That matters: an admin flipping a type off expects it to stop, and a 30 s cache means up to 30 s of further sends.
- Templates are notification-domain content. Settings stops accumulating other services' domains (it has already absorbed file sharing, branding, time zone, access policy).

**Cons**
- Deletes working, **deployed** code and reworks a **live** admin screen.
- Removing operations from a shipped service's contract is a breaking change. Precedent exists (Member Profiles removed `/admin/members`), so the mechanics are known, but it is still a contract deletion.
- Any template rows already edited in the live settings table must be migrated or accepted as lost (dev has almost certainly not edited any — verifiable before the change).
- Splits the admin's mental model: **sender** config (US-8.4) stays in Settings per US-8.3, while **templates** move.

### My recommendation changed because of your Q9 answer
Originally I recommended A. With per-user preferences withdrawn, **the admin's system-wide configuration becomes the only gate on every notification in the portal** — it stops being one small toggle beside a template and becomes the whole policy surface. Policy that decides whether a notification is delivered belongs in the service that delivers it.

**I now recommend B**, with sender settings (US-8.4) staying in Settings.

A) Keep Settings as the owner (original option A — extend to 22 templates + `enabled`, Notifications reads through a cached client)
B) **Move templates + per-type switches to Notifications** (recommended, per the reasoning above)
C) Move the switches to Notifications but leave template *content* editing in Settings (splits one record across two services — listed only to be explicit that I do not recommend it)

[Answer]: B

---

## C2 — Q3 revisited: 13,000 recipients per notification

This is the number that decides the architecture, so here is the arithmetic first.

### One community-wide notification, 13,000 recipients
| Work item | Volume | Consequence |
|---|---|---|
| Recipient list on the wire | 13,000 ids × ~40 B ≈ **520 KB** | **Exceeds SQS's 256 KB message limit.** EventBridge would accept it (< 1 MB), the SQS target would not. See C3 |
| Email sends | **13,000** `SendEmail` calls (quota counts per recipient) | At a typical production rate of ~14/sec ≈ **15.5 minutes** of sustained sending — **longer than a Lambda can live**. In the SES sandbox (1/sec, 200/day) it is impossible: 200 recipients, then rejections |
| In-portal rows | **13,000** writes ≈ **520** `BatchWriteItem` calls | Fine for on-demand DynamoDB; not fine inside one invocation alongside the email work |
| Retry blast radius | 1 message | If the single invocation dies at recipient 9,000, SQS redelivers the **whole** event — recipients 1–9,000 get a second email unless every send is individually idempotent |

**So Q3 option A as literally written does not survive this scale**, and neither does B: both describe *one consumer resolving and delivering an entire event*. The fix is not the channel split, it is a **second stage**.

### Option A2 — two-stage fan-out (what I recommend)
```
domain event ──EventBridge rule──▶ [Q1: notification-events] ──▶ Resolver Lambda
                                                                     │  resolves type, checks the
                                                                     │  admin switch, pages the
                                                                     │  recipient list
                                                                     ▼
                                              [Q2: notification-deliveries]  (1 msg per ~100 recipients)
                                                                     │
                                                                     ▼
                                                            Deliverer Lambda
                                                    BatchWriteItem in-portal rows (25/call)
                                                    SendEmail per recipient
                                                    ▼ DLQ on both queues
```
- Stage 1 handles **one** message per domain event and is short-lived: its only heavy work is paging the audience and enqueuing batches. 13,000 recipients → **130** stage-2 messages.
- Stage 2 messages are small, independently retryable, and idempotent per `(eventId, recipientId, channel)`. A failure re-sends **100** recipients' worth of work at most, and the idempotency store suppresses the duplicates within it.
- **Throughput is governed by reserved concurrency on the Deliverer**, sized to the SES rate. This is the only mechanism here that stops us from hammering SES and getting throttled: the backlog waits in SQS, which is what SQS is for.
- Both queues get a DLQ; Q4 = A (SQS-owned redrive, `maxReceiveCount = 4`) applies to stage 2, exactly as you approved.

| | Single-stage (Q3 A as written) | **Two-stage (A2)** | Channel-split (Q3 B) |
|---|---|---|---|
| 13k recipients in one event | ✗ exceeds the 15-min ceiling | ✓ bounded per message | ✗ same failure, twice |
| Retry blast radius | whole event (13k) | ~100 recipients | whole event, per channel |
| SES rate control | none | ✓ reserved concurrency | none |
| Bell latency vs a slow SES backlog | coupled | in-portal rows are written in the same stage-2 batch; still ahead of the email backlog because batches are processed in order of arrival | ✓ fully independent |
| Moving parts | 1 queue, 1 fn | 2 queues, 2 fns, 2 DLQs | 2 queues, 2 fns, 2 DLQs |
| Cost | lowest | +1 queue (negligible; SQS is fractions of a cent per million) | same as A2 |

**A2 + channel split (A3)** is the maximal option: stage 2 splits into an email queue and an in-portal queue (3 queues, 3 functions). It buys one thing — the bell stays instant even when a 13k email backlog is draining for 15 minutes. I do not think that is worth the third pipeline yet, because in-portal writes are ~40× faster than the SES sends they share a batch with, but it is a legitimate choice.

A) Single-stage, one queue (original Q3 A — **I advise against it at 13k**)
B) Channel-split, single-stage (original Q3 B — same scale problem)
C) **Two-stage fan-out, shared stage-2 pipeline (A2)** — recommended
D) Two-stage fan-out **plus** channel split (A3) — 3 queues, bell fully insulated from email backlog
E) Other (please describe)

[Answer]: C

### C2b — bulk send
`SendBulkEmail` (≤ 50 destinations/call) would cut 13,000 API calls to 260, but it requires the template to be **stored in SES or supplied inline**, and it does **not** reduce the quota consumption or the per-recipient rate ceiling — 50 destinations still count as 50. Using it would mean syncing our 22 templates into SES-managed templates and keeping them in sync on every admin edit.

A) **One `SendEmail` per recipient** (AWS's own recommendation; a failure is isolated to one recipient; no template sync) — recommended
B) `SendBulkEmail` in batches of 50 with SES-managed templates synced from our table on every edit
C) Other (please describe)

[Answer]: Need more discussion.

---

## C3 — Q8 needs an amendment that only surfaced from the 13k figure

You answered Q8 = A: *the publisher carries the recipient list in the event payload.* At 13,000 recipients that list is ~520 KB, which **exceeds SQS's 256 KB message limit** — the EventBridge rule would fail to deliver to the queue. Q8 A works for a reply notification (1 recipient) and breaks for a community-wide one.

A) **Hybrid, size-bounded** (recommended): the publisher inlines recipients when the audience is small (proposal: **≤ 200**), otherwise it sends an **audience descriptor** — e.g. `{kind: "event-rsvp-yes", eventId: "..."}`, `{kind: "group-members", groupId: "..."}`, `{kind: "community"}` — and the Resolver pages the list from the owning service through a cursor endpoint. The paging happens in stage 1, off the interactive path, and is retryable. Keeps the common case zero-dependency and the broadcast case bounded.
B) **Always a descriptor** — uniform code path, but every notification, even a single @mention, costs a cross-service read.
C) **Always inline, with the publisher chunking** — the publisher emits one event per 200 recipients (65 events for a 13k broadcast); no read dependency at all, but every publisher has to implement chunking and the event stream carries the audience.
D) Other (please describe)

[Answer]:

---

## C4 — Q5 revisited: the panel, the unread count, and "auto-discarded"

The three requirements in US-8.6 cannot all be literally true at once: a notification that has been *discarded* cannot be *counted* in "+N older". Something has to give. What differs between the options is **which** requirement is honoured literally.

Per-user volumes are modest even at community scale — a 13,000-recipient broadcast writes **one row per user**, not 13,000 rows for one user — so this is not a scale problem. It is a semantics problem, with one scale wrinkle: **mark-all-read** must be bounded, because a user returning after months could have thousands of unread rows and the mockup's "Mark all read" is a single click.

| | A — counter + TTL (recommended) | B — hard-trim beyond 20 | C — keep everything |
|---|---|---|---|
| Storage | every row kept until a **90-day TTL** | only the newest 20 unread survive | forever |
| `unreadCount` (the bell dot) | stored per-user counter, atomic `ADD` on write, decrement on read | count of stored rows (≤ 20, so the dot never exceeds 20) | count query, cost grows |
| `"+N older"` | `unreadCount − rows shown` — **accurate** | always **0** — the requirement becomes dead UI | accurate |
| "auto-discarded" | honoured as **expiry at 90 days** | honoured **literally** | **not** honoured |
| Read history | available until TTL | destroyed | permanent |
| Mark-all-read | bounded: reset the counter + flag rows in pages (background sweep for the tail) | trivial (≤ 20 rows) | unbounded without paging |

A) **Stored counter + 90-day TTL**; "auto-discarded" means TTL expiry, the panel shows 20 and reports the true remainder. Mark-all-read resets the counter immediately and sweeps the rows in bounded pages, so the bell responds instantly even with thousands unread — recommended
B) Hard-trim to the newest 20 unread at write time (literal reading; "+N older" always renders 0 and history is unrecoverable)
C) Keep everything, no TTL, count on read
D) Other (please describe)

[Answer]:

### C4b — TTL length
90 days is a proposal, not a requirement from any story. Notification rows are small; the cost difference between 90 and 365 days is negligible at this volume.

A) 90 days · B) 180 days · C) 365 days · D) No TTL (keep forever) · E) Other

[Answer]:

---

## C5 — Q9: confirming the scope of the requirement change

Your answer withdraws per-user notification preferences. That is a real requirement change with a wide blast radius, so I want it recorded precisely before I design to it — the same way US-1.27/US-1.28 and the Settings audit-logging removal were handled.

**What I understand you to mean**: US-8.7 is withdrawn. No user (Member, UGL, CL) chooses anything. The Administrator configures notification delivery **system-wide, per notification type**, and that configuration is the only gate.

**What follows if that is right**
- **US-8.7 is tombstoned.** The opt-out/mandatory category split disappears entirely — with no per-user choice, "mandatory" has no meaning.
- **The Preferences screen loses its Notifications tab.** `singletons.tsx` currently renders 9 opt-out toggles plus 4 "Always on" rows; those go. The **Time Zone** card stays (US-8.14, owned by Settings). The screen is still called Preferences and still has a reason to exist.
- **`GET/PUT /notifications/preferences` are removed from the contract.** Zero risk — Notifications is still a mock, nothing real depends on them.
- **The gate chain collapses from two independent gates to one.** Every "admin switch first, user preference second" rule in US-8.2/8.5/8.7/8.15 reduces to the admin switch alone. Those stories need that sentence struck.
- The three mockups `{member,ugl,leader}/notifications-prefs.html` become stale by design; I will note them as superseded rather than build them.

### C5a — Confirm the withdrawal
A) **Yes — US-8.7 withdrawn as described above** (tombstone the story, remove the routes, remove the tab, keep Time Zone)
B) Yes to admin-managed system-wide config, but **keep** the per-user screen as read-only so users can *see* what they will receive
C) No — I meant something narrower (please describe)

[Answer]:

### C5b — Which channels can the Administrator control?
US-8.6 currently states in-portal notifications can never be muted. If the admin now owns all delivery policy, that guarantee is a decision rather than a given.

A) **Email only** — the admin switch stays email-only and in-portal is always delivered, preserving US-8.6 as written (recommended: the bell is the user's only record of what happened to them, and silently dropping it leaves no trace anywhere)
B) **Email and in-portal** — the admin can disable either channel per type; US-8.6's "cannot be muted" is amended
C) Other (please describe)

[Answer]:

### C5c — Granularity of the admin configuration
A) **Per notification type** — 22 email types (23 rows including the in-portal-only one), one `enabled` toggle each, exactly as US-8.5 already describes. The US-8.15 role matrix stays hardcoded as the recipient rule and is **not** admin-editable — it is a leak-prevention invariant, not a preference (recommended)
B) **Per type × per role** — the admin can also decide, say, that UGLs stop receiving event reminders. Makes the recipient matrix configurable, which means it can be misconfigured into a leak
C) **Per type × per channel** (pairs with C5b = B)
D) Other (please describe)

[Answer]:

### C5d — Where does the Administrator manage it?
This depends on your C1 answer and is the last piece.

A) **Beside each template on one screen** — the type list, its template, and its toggle in one place, which is what US-8.5 describes ("shown next to its template"). Location follows C1: the Settings Email Templates screen if C1 = A, a Notifications-owned admin screen if C1 = B (recommended)
B) **A separate "Notification Delivery" admin screen** listing all 23 types and their switches, with templates edited elsewhere
C) Other (please describe)

[Answer]:

---

**Recommended set**: C1 **B** · C2 **C** · C2b **A** · C3 **A** · C4 **A** · C4b **A** · C5a **A** · C5b **A** · C5c **A** · C5d **A**. Reply "all recommended" to accept, or answer individually.
