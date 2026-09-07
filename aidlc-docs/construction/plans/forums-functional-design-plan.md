# Functional Design Plan — Unit 5: Forums

**Stage**: CONSTRUCTION → Functional Design · **Unit**: Forums (18 stories, US-4.1–4.18)
**Contract (frozen, to be amended additively)**: `contracts/services/forums/openapi.yaml` · **Permission spec**: `contracts/platform/permissions/role-permission-matrix.v1.json`

## Scope
Path bases `/forums`, `/channels`, `/posts`, `/replies`. Structure: `User Group → Forum(s) → Channel(s) → Posts → Replies`. Owns **Forums, Channels, Posts, Replies, Reactions, Follows, Reports** tables. Publishes `ForumPostCreated`, `ForumReplyCreated`, `PostDeleted`, `ForumChannelDeleted`, `MemberMentioned`, `PostReported`. Consumes `GroupHardDeleted` (Identity — remove content + search entries) and performs a **synchronous AI-Gateway dup-check** on post create (conditional, D3). Delegates semantic search + embeddings to **Search (Unit 13)** and duplicate detection to **AI Gateway (Unit 14)**, both conditional. **Administrators have no access to forums** (excluded from every forum operation, including read).

Stories: US-4.1 Create Forum · US-4.2 Create Channel · US-4.3 Edit forum/channel · US-4.4 Delete forum/channel · US-4.5 Create Post (+ LLM dup hold) · US-4.6 Reply · US-4.7 Edit own · US-4.8 Delete post/reply · US-4.9 @mention (access-scoped) · US-4.10 Mention notification · US-4.11 React · US-4.12 Browse · US-4.18 Channel post list · US-4.13 Semantic search · US-4.14 Pin · US-4.15 Accepted answer · US-4.16 Follow · US-4.17 Report/moderation.

## Established context (from artifacts + mockups — no question needed)
| Source | Fact that constrains this design |
|---|---|
| `role-permission-matrix.v1.json` | **CL**: create/edit/delete `forum-channel` **global**; create/reply/react/accept-answer/pin `post` global; edit `post` **own**; delete `post` **global**; moderate `forum-report` **global**; unflag-duplicate global. **UGL**: forum-channel create/edit/delete **group**; post create/reply/react global; edit own; delete/accept-answer/pin/moderate **group**. **Member**: create/reply/react post global; edit/delete/accept-answer **own**; follow/report/search/browse. **Administrator**: no forum entries → excluded. |
| use case 04 + stories | Full role model (Admin none; CL any group; UGL strictly one led group; Member in groups they belong to). Rich text (formatting, code, images ≤5). Newest-first default. "edited" indicator (no history). Points retained on delete. Reporter not notified (Phase 1). Reported content stays visible until a leader acts. |
| Mockups (member forums/channel/thread; leader forums; ugl forums + forum-moderation) | Browse = forums grouped by user-group, each channel shows **post count + last-activity**. Channel list = post rows with title, **snippet**, author, timestamp, reply count, reaction count, **badges: 📌 Pinned / ✓ Answered / edited / 🏷️ tags**; sort Newest/Most active/Most reactions/Unanswered; pagination + rows-select (US-8.9); channel-scoped semantic search; Follow channel + New Post. Thread = pinned block, main post (author + role badge + rich body + code block), **reactions row 👍 ❤️ 🎉 + ＋React with "on" state**, accepted-answer highlighted under post, threaded replies, per-reply "Mark accepted", Follow + Report, edit/delete own, reply composer with rich-text toolbar (B/I/code/link/🖼️ max 5/@Mention). Leader forums = Create-Forum modal (name, description, target group; "default General channel auto-created"), tabs **All Forums / Duplicate Flags(n) / Reported(n)**; per-channel edit/delete; Reported tab table = Content · Group · Reporter · Reason · **Delete/Dismiss**. Moderation = held duplicate post ("Held · not yet published") + similar posts with **% similarity** + **Publish anyway / Reject**; note: *"Duplicate analysis enabled by Administrator globally; when the LLM is unavailable, post submissions are rejected with a retry message."* |
| unit-of-work.md | Owns 7 tables; publishes the 6 events above; consumes `GroupHardDeleted`; AI dup-check sync via AI Gateway; search/dup delegated to 13/14 (conditional). |
| unit-of-work-dependency.md | Async events (EventBridge) for cross-service; **REST only for synchronous reads** — Forums → Identity (US-4.9 @mention scope) and → AI Gateway (dup-check). Search/AI stubbed via contracts until present; consumers degrade when disabled (D3). |
| FQ2 / precedent (Events, Member Profiles, Announcements) | JWT claims carry `sub`, role, `memberGroupIds`, `ledGroupId` — **but no display names** (the UUID-in-UI defect fixed by denormalizing names at write). Single-table DynamoDB per service; every listing is a Query (no Scan) — the lesson paid for twice (Member Directory rework, File Share live 500 on a missing GSI). Sanitize rich text on write (nh3) + DOMPurify client layer (Announcements precedent). |

## Steps
- [x] 1. Analyze unit context (unit-of-work.md, story-map, use case 04, 18 stories US-4.1–4.18, frozen contract, permission matrix, all six mockups, dependency matrix, Events/Announcements/Member-Profiles precedents)
- [x] 2. Create this plan
- [x] 3. Generate context-appropriate questions (below, with `[Answer]:` tags)
- [x] 4. Store plan
- [x] 5. Collect + analyze answers (Round 1 + Round 2 brainstorming complete; all 12 resolved)
- [x] 6. Generate functional design artifacts (regenerated against final brainstormed decisions)
- [x] 7. Present completion message
- [x] 8. Await explicit approval (APPROVED 2026-08-08 — "PROCEED")
- [x] 9. Record approval + update aidlc-state.md

---

## Working decisions (subject to change during brainstorming)
Confirmed & stable: Q1 dup-detection OUT (DV-1) · Q2 N/A · Q3 A (@mention sync to Identity) · Q4 denorm name+role, no authorActive (DV-3) · **Q5 NO images in Phase 1 — Markdown body text/formatting/code/links only; drops ≤5-images from US-4.5 (DV-4); no S3 bucket / no malware scanning** · **Q6 DynamoDB stays primary store; keyword search implemented in-service via an inverted-index GSI (term→postId, no Scan); OpenSearch (Unit 13) remains the optional/cost-gated upgrade for rich/semantic search, fed as a projection and degrading to the keyword path when disabled. Rationale: forum load is read-heavy key-access (DynamoDB's strength, ~$0 idle); OpenSearch/Aurora carry always-on cost floors unjustified for a cost-sensitive portal** · **Q7 SINGLE reaction per member per target — choosing a new kind replaces the previous; can clear. Fixed set {upvote, like, heart, celebrate, insightful}; per-kind counters. Narrows US-4.11 "one or more" → one (DV-5)** · **Q8 FULL follow model — follow channel + post, auto-follow own posts, unfollow, "my follows" list (Follows table userId+targetType+targetId). Fan-out (channel→post-followers, post→reply-followers) delivered by Notifications (Unit 10, SQS-buffered); Forums emits the signal** · **Q9 group access from JWT claims (memberGroupIds/ledGroupId/role) — no local projection; zero hot-path calls; staleness bounded by token lifetime (US-1.32). CL any / UGL ledGroup / Member memberGroups / Admin denied** · **Q10 group delete — (A) `GroupSoftDeleted` → hide group forums, reversible on `GroupRestored` (consistent w/ Events/Announcements); (B) `GroupHardDeleted` → MARK-THEN-BACKGROUND cascade: synchronously mark forums deleted (instantly gone from all views), then delete underlying rows (channels/posts/replies/reactions/follows/reports) in resumable batches. All consumers idempotent on event id** · Q11 A (pin/accept) · **Q12 Reports TABLE (status Open→Dismissed/Actioned); moderationQueue = Open reports scoped to caller (CL all, UGL ledGroup); reportPost emits PostReported → Notifications bumps read-only review-count (US-8.6 Option 2A, not a stored notification); leader dismiss (content stays) or delete content (related reports→Actioned); reporter never notified**.
**Brainstorming COMPLETE (2026-08-08)** — all 12 questions resolved. Regenerating the 4 functional-design artifacts against these decisions.
| Q | Decision |
|---|---|
| Q1 Duplicate detection | **Out of scope (DV-1)** — no LLM dup-check/hold/publish-reject/dup-queue; posts publish immediately; AI-Gateway dependency removed. |
| Q2 Dup degrade | N/A (follows Q1). |
| Q3 @mention | **A** — `mentionSuggest` sync read to Identity, group-scoped; server re-validates mentions on submit. |
| Q4 Author denorm | Denormalize `authorName` + `authorRoleLabel` at write; **no `authorActive`/inactive badge (DV-3)**; no UserDeactivated/Reactivated consumption. |
| Q5 Body + images | Body = **Markdown** (sanitized on render); images ≤5 via **presigned S3 upload** (recommended A). |
| Q6 Search | Semantic **out of scope (DV-2)**; **literal keyword search kept** in-service (recommended A). |
| Q7 Reactions | **A** — multi-kind, fixed set {upvote, like, heart, celebrate, insightful}, per-kind counters. |
| Q8 Follow | **A** — follow channel + post, auto-follow own posts, unfollow, my-follows list. |
| Q9 Group access | **A** — from JWT claims (memberGroupIds/ledGroupId/role). |
| Q10 Group delete | **A** — hard-delete cascade + soft-delete hide/restore (consume GroupHardDeleted/GroupSoftDeleted/GroupRestored). |
| Q11 Pin/accept | **A** — pin toggle; accepted-answer set/clear. |
| Q12 Report/moderation | **A** — Reports table; dismiss/delete; scoped queue; read-only review count. |

**Deviations recorded** in `stories.md` (US-4.5, US-4.13), `unit-of-work.md` (Unit 5), `unit-of-work-dependency.md` (row 5), and `business-rules.md` (DV-1/DV-2/DV-3). Net effect: Forums has **no runtime dependency on Search (13) or AI Gateway (14)**.

---

## Proposed decisions (resolved from artifacts + precedent — flagged for review; override any at the gate)
These are the directions I will take unless you object. The genuinely open items are the numbered questions after this table.

| Ref | Area | Proposed decision |
|---|---|---|
| D1 | Authorization | In-service, fail-closed, from the permission matrix, split into **two orthogonal checks**: (a) **capability** (role may perform the action) and (b) **resource access** (caller can reach the forum's group). **Administrator → 403 on every forum op including reads/browse/search** (they do not participate). See Q9 for the resource-access source. |
| D2 | Ownership boundary | Forums owns its 7 tables only. It does **not** own identity, group membership, or group names — those come from JWT claims and denormalized-at-write display fields (Q3/Q4). No local membership projection unless Q9 says otherwise. |
| D3 | Async vs sync | Cross-service workflows are async events (publish the 6 events). The **only** synchronous outbound calls are (i) `mention-suggest` → Identity for @mention candidates (Q3) and (ii) dup-check → AI Gateway on post create (Q1/Q2). Notifications/Contributions/Search all react to published events. |
| D4 | Points fire on publish only | `ForumPostCreated` is emitted **only when a post becomes visible** (published) — never for a post still Held for duplicate review, and not for a Rejected post. `ForumReplyCreated` on reply create. This keeps Contributions auto-award (US-6.4) aligned with visible content. |
| D5 | Contract amendment | Extend **additively** — every new path lives under the already-routed `/forums`, `/channels`, `/posts`, `/replies` bases, so **no `gen_api_edge.py` regen** (Events/Announcements precedent). Expected additions: post-status fields + `publishPost`/`rejectPost` (Q1); `unpinPost`, clear-accepted (Q11); `followChannel` + unfollow + `GET /follows` (Q8); `dismissReport` (Q12); `unreact` or toggle semantics (Q7); richer `Post`/`Reply`/`Forum`/`Channel`/`Report` schemas (author name/role/active, counts, badges, timestamps, tags, snippet). Bump `forums/openapi.yaml` to v2.0.0. |
| D6 | Event schemas | Author the 6 published-event JSON Schemas under `contracts/services/forums/published-events/` (none exist yet), envelope-compliant (`event-envelope.v1.json`). |
| D7 | Single-table + no-Scan | One DynamoDB table, access patterns served by GSIs (channel→posts newest-first, post→replies, forum→channels, user→follows, group→reports/moderation). Every listing is a Query. GSI specifics are Infra-Design's call, but the functional access patterns are fixed here. |
| D8 | Rich text safety | Store a sanitized constrained-HTML subset, sanitize-on-write at the trust boundary (nh3), DOMPurify client defense-in-depth — identical to the shipped Announcements approach. (Image handling is Q5.) |

---

## Questions

Recommended option marked **(recommended)**. Answer each after its `[Answer]:` tag. Choose **X) Other** and describe if none fit.

## Question 1
**Duplicate-detection "hold for review" workflow + post status model (US-4.5, US-4.17 moderation, mockup `ugl/forum-moderation.html`).** The mockups show a submitted post flagged as a possible duplicate being **"Held · not yet published"** with similar posts + % similarity, awaiting a leader's **Publish anyway / Reject**. The frozen `createPost` returns a `Post` with no status, and there is no publish/reject op. How should this be modeled?

A) **(recommended)** Introduce a **post lifecycle status** (`Published` | `HeldForReview` | `Rejected`). `createPost` runs the dup-check (Q2): no strong duplicate → status `Published` immediately (emit `ForumPostCreated`); strong duplicate → status `HeldForReview` (no event, not shown in channel, appears only in the leaders' Duplicate-Flags queue with the similar-post matches + scores). Add additive `POST /posts/{id}/publish` (leader "Publish anyway" → Published, emit `ForumPostCreated`) and `POST /posts/{id}/reject` (leader → Rejected, soft-removed). Held posts are visible only to their author (as "pending review") and to moderating leaders.

B) No hold — always publish immediately; surface suspected duplicates as a **non-blocking warning** to the author at compose time and a leader flag afterward (dismiss-only, content stays live). Simpler, but contradicts the "held until publish/reject" mockups.

C) Model status + queue now but treat Publish/Reject wording and the similar-post payload shape as Code-Generation details.

X) Other (describe after `[Answer]:`)

[Answer]: Make the duplicate check out of scipe for now.

## Question 2
**Dup-check enablement + degrade behavior (US-4.5, mockup note, D3 conditional AI).** Duplicate analysis is an **Administrator-controlled global toggle** (Settings, US-8.3) and runs via the conditional **AI Gateway (Unit 14)**. The moderation mockup states *"when the LLM is unavailable, post submissions are rejected with a retry message."* How should create-post behave across the toggle/availability combinations?

A) **(recommended)** Three-way: **(i) toggle OFF or AI Gateway disabled at deploy (D3)** → skip dup-check, publish immediately. **(ii) toggle ON + AI reachable** → run dup-check; hold on strong match (Q1). **(iii) toggle ON + AI momentarily unreachable** → **fail-closed**: reject the submission with a retryable error (matches the mockup; avoids publishing unvetted content while the check is expected). The toggle state is read from Settings (cached), the deploy-time availability from the AI-enabled condition.

B) Always fail-open — if the check can't run for any reason, publish anyway (never block the user). Contradicts the mockup's reject-with-retry.

C) Toggle ON always requires AI; if AI is disabled at deploy, treat dup-check as OFF (publish immediately) and only fail-closed on transient errors when AI is present.

X) Other (describe after `[Answer]:`)

[Answer]: N/A

## Question 3
**@mention candidate source + scope (US-4.9 — the documented `REST → Identity` dependency).** Autocomplete must be **restricted to those who can access the post**: the forum group's members + that group's UGL(s) + any CL — "a mention can never link a recipient to an inaccessible post." Display names are not in JWT claims. Where do candidates come from?

A) **(recommended)** `mentionSuggest` performs a **synchronous read to Identity** (forwarding the caller's JWT), scoped to the post's group: returns group members + the group's UGL(s) + CLs matching the query, each with `{userId, displayName}`. No local user projection. This is the single REST read the dependency matrix anticipates for Forums. Mentions store `userId` (resolved to a profile link on render); the mentioned set is validated server-side on submit against the same access rule (defense against a client mentioning an out-of-group user).

B) Maintain a **local member projection** in Forums by consuming Identity's membership events, and resolve/validate mentions against it (no per-keystroke cross-service call). More moving parts; adds consumed events beyond `GroupHardDeleted`.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 4
**Author display name + inactive badge denormalization (US-4.18 rows, US-4.13 "deactivated users' posts remain searchable with inactive badge", thread author + role badge).** Every post/reply row shows the author's **name** and sometimes a **role badge**; search results and lists must show an **inactive badge** for deactivated authors. Claims carry no names. How are these resolved?

A) **(recommended)** **Denormalize at write**: when a post/reply is created, store `authorName` and `authorRoleLabel` (role label from the caller's own role claim — no lookup) on the item. Maintain `authorActive` by **consuming Identity's `UserDeactivated`/`UserReactivated`** events and flipping the flag on that author's items (or, cheaper, resolve active-state at read via a small cached lookup). Lists/threads/search then need **zero per-row cross-service calls**. Fail-closed to id if a name is ever missing.

B) Store only `authorId`; the **frontend** resolves names/badges from data it already holds. Smallest backend but the SPA rarely holds arbitrary authors' names, and search spans groups.

C) Denormalize `authorName`/`authorRoleLabel` at write; compute the inactive badge by a **read-time batch lookup** to Identity for the authors on the page (no deactivation-event consumption). Fresh, but adds cross-service latency to every list.

X) Other (describe after `[Answer]:`)

[Answer]: Need not to show authorActive

## Question 5
**Rich-text body storage + image handling (US-4.5 "rich text… images; max 5 images/post in S3").** Body safety is settled (D8: sanitized constrained HTML on write + DOMPurify). The open part is **images**: the frozen `createPost` accepts only `{title, body}`. How are the ≤5 images handled?

A) **(recommended)** **Direct-to-S3 via presigned PUT**, same pattern as Events materials: client requests up to 5 presigned upload URLs (additive `POST /posts/images/presign`), uploads directly to a Forums-owned S3 prefix, then submits the post whose sanitized HTML body references the returned S3 object URLs (served via CloudFront). Server enforces the ≤5 cap and allowed image content-types; keeps large binaries off the Lambda/API path.

B) Accept base64-inlined images in the JSON body (no S3 round-trip). Simple but bloats items/payloads and risks DynamoDB item-size limits — not viable for images.

C) Defer image upload to a later iteration; Phase-1 posts are text/formatting/links/code only (no image attach), body still sanitized HTML.

X) Other (describe after `[Answer]:`)

[Answer]: Rich-text is markup

## Question 6
**Semantic search + indexing + delete cascade (US-4.13, US-4.4, US-4.8, US-1.11; Search = conditional Unit 13).** Search is delegated to OpenSearch via Unit 13, which is D3-conditional. How much is in scope for Forums' functional design, and how does it degrade?

A) **(recommended)** In scope now as **contract + event integration, degrade-aware**: on post create/edit (published only), Forums **publishes index events** (`ForumPostCreated`/an edit variant) that Search consumes to (re)embed; on delete (post/reply US-4.8, forum/channel US-4.4, group hard-delete US-1.11) Forums **publishes `PostDeleted`/`ForumChannelDeleted`** so Search removes embeddings. `searchForum`/channel-scoped search calls Search when **enabled**; when Search is **disabled (D3)** it **degrades to a keyword query** over the service's own table (title/snippet contains, filtered by group/forum/channel/author/date) — never a 501 for the user. Filters (group/forum/channel/author/date) and result fields (title, snippet, author, channel, timestamp, relevance, inactive badge) are defined here.

B) Model only the "call Search when enabled, else 501/coming-soon" path (no keyword fallback); rely purely on Search for all query capability.

C) Defer search entirely to when Unit 13 is real; Forums ships create/read/moderate only for now.

X) Other (describe after `[Answer]:`)

[Answer]: out of scope Semantic search

## Question 7
**Reaction model + toggle semantics (US-4.11, thread mockup 👍 ❤️ 🎉 + ＋React).** US-4.11: "add **one or more** reactions… remove their own reaction." The contract has `toggleReaction {kind}`. What is the model?

A) **(recommended)** A user may hold **multiple distinct reaction kinds simultaneously** on one post/reply, but **one of each kind** (idempotent). `toggleReaction{kind}` flips that (user, target, kind) on/off. **Allowed kinds = a fixed enumerated set**: `upvote`, `like`, plus a small emoji set (`heart`, `celebrate`, `insightful`) — server rejects unknown kinds. Counts per kind are maintained as denormalized counters on the target (transactional increment/decrement) so list/thread reads need no reaction scan.

B) One reaction per user per target (choosing a new kind replaces the old). Simpler counts, but contradicts "one or more reactions."

C) Free-form kind string (any emoji) rather than an enumerated set.

X) Other (describe after `[Answer]:`)

[Answer]: explain

## Question 8
**Follow model (US-4.16 — follow channel OR post; auto-follow own posts; manage followed items).** The contract has only `followPost` (no channel-follow, no unfollow, no list). Model?

A) **(recommended)** A **Follows** table keyed by `(userId, targetType∈{channel,post}, targetId)`. Additive ops: `POST /channels/{id}/follow` + `POST /posts/{id}/follow` as **toggles** (or explicit `DELETE` to unfollow), and `GET /follows` to view/manage. **Auto-follow**: creating a post auto-adds a follow on it; (optional) posting in a channel does not auto-follow the channel. Follow drives notifications: new post in a followed channel → notify channel followers; new reply on a followed post → notify post followers (in-portal always; email per US-8.7 prefs, delivered by Notifications). Following is per-user, isolated.

B) Post-follow only (no channel follow) for Phase 1. Contradicts US-4.16.

X) Other (describe after `[Answer]:`)

[Answer]: expliain

## Question 9
**Resource-access guard source (US-4.5/4.12 — "must be able to access the forum's group").** The RBAC matrix grants the *capability* to post/reply/browse broadly, but actual access is group-scoped: a Member only in groups they belong to; a UGL only their led group; a CL any group; Admin none. Where does the caller's group set come from for this guard?

A) **(recommended)** From **JWT claims** (`memberGroupIds`, `ledGroupId`, role) — exactly as Events/Announcements resolve audience. Access check: CL → any group; UGL → `forum.groupId == ledGroupId`; Member → `forum.groupId ∈ memberGroupIds`; Admin → denied. Zero cross-service calls on the hot path. A post/channel/forum read resolves its owning `groupId` from the item and checks it against the caller's claim set.

B) Maintain a **local membership projection** (consume Identity membership events) and check against it. Adds consumed events + storage; only worth it if claims prove insufficient.

X) Other (describe after `[Answer]:`)

[Answer]: explain

## Question 10
**Group deletion handling — hard vs soft (US-1.11; unit-of-work says consume `GroupHardDeleted`).** Identity publishes both `GroupSoftDeleted` and `GroupHardDeleted`. unit-of-work lists only `GroupHardDeleted` for Forums (remove content + search entries). Should Forums also react to **soft** delete?

A) **(recommended)** Consume **`GroupHardDeleted`** → cascade-delete that group's forums/channels/posts/replies/reactions/follows/reports and emit `PostDeleted`/`ForumChannelDeleted` so Search purges embeddings (matches unit-of-work). **Also consume `GroupSoftDeleted`** → **hide** that group's forums from browse/read/search (reversible on `GroupRestored`), so a soft-deleted group's discussions disappear immediately without destroying data — mirroring the Events "cancel on soft-delete" and Announcements "hide on soft-delete" precedents. (Adds `GroupSoftDeleted`/`GroupRestored` to Consumes.)

B) Strictly follow unit-of-work: consume **only `GroupHardDeleted`** (hard cascade); ignore soft-delete (soft-deleted group's forums remain visible until hard delete). Fewer consumed events; but leaves visible content for a group that has been soft-removed.

X) Other (describe after `[Answer]:`)

[Answer]: Explain

## Question 11
**Pin and accepted-answer semantics (US-4.14, US-4.15).** Contract has `pinPost` and `acceptAnswer{replyId}` but no unpin/clear. Model?

A) **(recommended)** **Pin**: `pinPost` is a **toggle** (pin/unpin) storing `pinnedAt`; multiple pins per channel allowed, ordered by `pinnedAt` desc; pin/unpin emits **no notification**. **Accepted answer**: `acceptAnswer{replyId}` sets that reply accepted and **clears any previous** (one at a time); `acceptAnswer{replyId: null}` (or a `DELETE`) **clears**; author OR CL(any)/UGL(their group) may set/clear; **no points awarded**. Both stored as fields on the post/reply (no separate table).

B) Separate explicit `unpinPost` and `clearAcceptedAnswer` ops instead of toggles/null.

X) Other (describe after `[Answer]:`)

[Answer]: A

## Question 12
**Report + moderation queue model (US-4.17).** A report routes to the group's UGL + CLs; the queue shows content/reporter/reason/date; a leader **dismisses or deletes**; reporter not notified; content stays visible until action. Contract has `reportPost` + `moderationQueue` but no dismiss. Model?

A) **(recommended)** A **Reports** table; `reportPost{reason?}` creates a report with status `Open` and emits `PostReported` (Notifications routes the review-queue signal to the group's UGL + CLs — surfaced as the read-only bell count, US-8.6 Option 2A, **not** a stored notification). `moderationQueue` returns `Open` reports **scoped to the caller** (CL → all groups; UGL → led group only). Leader actions: **`POST /reports/{id}/dismiss`** (additive → status `Dismissed`, content stays) or **delete the content** via existing `deletePost`/`deleteReply` (which resolves the related reports → `Actioned`). Reporter is never notified (Phase 1).

B) Fold reports onto the post item (a reports list attribute) instead of a Reports table. Unbounded growth / item-size risk on a heavily reported post.

X) Other (describe after `[Answer]:`)

[Answer]: explain
