# Forums — Business Rules

**Unit**: 5 Forums · **Stage**: Functional Design. Rules are technology-agnostic and enforced in-service, fail-closed. Cross-references: `domain-entities.md` (E1–E7), `business-logic-model.md`, permission matrix `contracts/platform/permissions/role-permission-matrix.v1.json`, stories US-4.1–4.18.

Legend: **A**=Administrator, **CL**=Community Leader, **UGL**=User Group Leader, **M**=Member.

---

## Authorization & access (two orthogonal checks — BR-1..5)

**BR-1 — Administrators are fully excluded.** A has **no** forum access whatsoever — no browse, read, search, post, react, follow, report, moderate, or manage. Every forum operation returns **403** for A, including read/GET (use case 04; matrix has zero forum entries for A).

**BR-2 — Capability vs resource-access are separate.** Every mutating/read op passes **both**: (a) **capability** — the role holds the action in the permission matrix; (b) **resource access** — the caller can reach the target's `groupId` (BR-3). Failing either → 403 (reads) / 403 (writes). Fail-closed on any missing claim.

**BR-3 — Group-access is derived from JWT claims** (Q9). For a target with owning `groupId`:
- **CL** → access to any group.
- **UGL** → access iff `groupId == ledGroupId`.
- **M** → access iff `groupId ∈ memberGroupIds`.
- **A** → never (BR-1).
No cross-service call on the hot path. A post/reply/channel resolves its `groupId` from the stored item.

**BR-4 — Forum/channel management scope (US-4.1–4.4).** Create/edit/delete forum & channel: **CL** any group; **UGL** only `ledGroupId`; **M** never; **A** never.

**BR-5 — Content-author rights (US-4.7/4.8).**
- Edit post/reply → **author only** (matrix `edit post/own`). Leaders may **not** edit others' content.
- Delete post/reply → **author** (own), **CL** any group, **UGL** own group, **A** never.

## Forum & channel lifecycle (BR-6..12)

**BR-6 — Forum create (US-4.1).** Requires `name` + target `groupId`; UGL's target forced to `ledGroupId` (a supplied other group → 403). A default **"General"** channel (E2) is auto-created atomically with the forum. Forum visible to all group members.

**BR-7 — Channel create (US-4.2).** Requires `name`; parent forum must be accessible (BR-3/BR-4). All group members may post in it (no leader-only channels, Phase 1).

**BR-8 — Edit forum/channel (US-4.3).** `name`+`description` only; existing posts unaffected; `groupId`/parent immutable.

**BR-9 — Post create (US-4.5).** Requires `title`+`body`; author must have group access (BR-3). Body stored as **Markdown** (Q5), sanitized on render (BR-19); **no image attachments in Phase 1 (BR-20/DV-4)**. Post is **immediately Published** (no duplicate hold — Q1). On create: increment channel `postCount`, set channel `lastActivityAt`, auto-follow the author on the post (BR-17), emit `ForumPostCreated` (BR-26).

**BR-10 — Reply create (US-4.6).** Requires `body`; group access required. Threaded under the post; increments post `replyCount` + channel `lastActivityAt`; notifies the post author and post-followers (BR-22); emits `ForumReplyCreated`.

**BR-11 — Delete cascade (US-4.4/4.8).** Deleting a **forum** deletes its channels → posts → replies → reactions → follows → reports. Deleting a **channel** deletes its posts (+ descendants). Deleting a **post** deletes its replies, reactions, follows, reports (BR-8-cascade). Confirmation + "all posts permanently deleted" warning required at the UI (US-4.4). Emit `ForumChannelDeleted` (forum/channel delete) and `PostDeleted` (post delete) for downstream consumers.

**BR-12 — Points are retained on delete (US-4.4/4.8).** Deleting content does **not** revoke previously awarded points; Forums emits no points-reversal. A leader may manually adjust via Contributions (US-6.15) out-of-band.

## Editing, pinning, accepted answer (BR-13..15)

**BR-13 — Edit indicator (US-4.7).** Editing sets `edited=true` + `editedAt`; only the latest version is kept (no history).

**BR-14 — Pin (US-4.14).** Pin/unpin is a **toggle** storing `pinnedAt`; **CL** any channel, **UGL** own group only; multiple pins per channel allowed, ordered `pinnedAt` desc, shown above regular posts; pin/unpin sends **no notification**.

**BR-15 — Accepted answer (US-4.15).** The **post author OR** **CL** (any) **OR** the group's **UGL** may set/clear. Setting a reply clears any previous (exactly one at a time); mirror `accepted` onto the reply. Clearing sets `acceptedReplyId=null`. Deleting the accepted reply clears it. **No points** awarded.

## Reactions & follows (BR-16..18)

**BR-16 — Reaction (US-4.11, Q7, DV-5).** `kind ∈ {upvote, like, heart, celebrate, insightful}`; unknown kind → 400. A user holds **at most one reaction per target**. `setReaction{kind}` sets/replaces the caller's reaction (replacing decrements the previous kind's counter and increments the new one atomically); re-selecting the same kind or an explicit clear removes it (decrement). Per-kind counters on the target are the read source (no reaction scan on lists/threads).

**BR-17 — Auto-follow own post (US-4.16).** Creating a post auto-creates a Follow(post) for the author. Posting/replying does not auto-follow the channel.

**BR-18 — Follow model (US-4.16, Q8).** Follow/unfollow a **channel** (new-post notifications) or a **post** (new-reply notifications) as a per-user toggle. `GET /follows` lists the caller's follows. Following is isolated per user. Delivery: in-portal always; email subject to US-8.7 (Notifications delivers — Forums only emits/derives the fan-out signal).

## Content safety (BR-19..21)

**BR-19 — Sanitize rich text (Security Baseline / SECURITY-05).** Post/reply body is Markdown; on render it is sanitized (DOMPurify client layer; server strips dangerous constructs at the trust boundary) — no script/handlers/`javascript:` URIs. Stored-XSS is prevented regardless of client.

**BR-20 — No image uploads in Phase 1 (US-4.5 deviation, DV-4).** Post/reply bodies are Markdown text/formatting/code/links only. No image attachments, no Forums-owned S3 bucket, no presigned upload, and therefore no member-supplied-file malware-scanning burden. (The "max 5 images/post in S3" clause is deferred.)

**BR-21 — @mention access invariant (US-4.9).** The mention autocomplete (`mentionSuggest`) returns only users who can access the post: the forum group's members + that group's UGL(s) + any CL. On submit, the server **re-validates** every mentioned `userId` against the same access rule and drops/blocks any that fail — a mention can never link a recipient to a post they cannot open.

## Notifications (BR-22..25) — Forums emits; Notifications (Unit 10) delivers

**BR-22 — Reply notifies author + followers (US-4.6/4.16).** A new reply notifies the post's author and the post's followers (in-portal + email-per-prefs). Self-actions do not notify self.

**BR-23 — Mention notifies (US-4.9/4.10).** Each validated mentioned member gets an email + in-portal notification with who/where/link; emit `MemberMentioned`.

**BR-24 — Reporter not notified (US-4.17).** The reporter receives no outcome notification (Phase 1).

**BR-25 — Report visibility (US-4.17).** Reported content stays visible until a leader acts (dismiss or delete).

## Events, group lifecycle, degrade (BR-26..30)

**BR-26 — Publish-time events.** `ForumPostCreated` fires when a post becomes visible (immediately, since there is no hold — Q1) — consumed by Contributions (auto-award, US-6.4) and Notifications. `ForumReplyCreated` on reply. `MemberMentioned`, `PostReported`, `PostDeleted`, `ForumChannelDeleted` per their triggers. All envelope-compliant.

**BR-27 — Group hard delete (US-1.11, Q10) — mark-then-background cascade.** On `GroupHardDeleted`: **synchronously mark** that group's forums deleted/hidden so they vanish from every view immediately, **then delete the underlying rows** (channels/posts/replies/reactions/follows/reports) in **resumable batches** (self-continuing worker) so a large group cannot exceed handler timeout/throughput or leave an unrecoverable half-deleted state. Emit `PostDeleted`/`ForumChannelDeleted` as content is removed. Idempotent on the event id; resumable if interrupted.

**BR-28 — Group soft delete / restore (Q10).** On `GroupSoftDeleted`, set `hidden=true` on that group's forums (hide cascades to reads); excluded from browse/read/search. On `GroupRestored`, clear `hidden`. Idempotent.

**BR-29 — Keyword search (US-4.13 deviation, Q6/DV-2).** Search is **literal keyword matching** served by a DynamoDB **inverted-index GSI** (title/body tokenized to normalized terms at write → `term→postId`), so a search is a **keyed Query on the term(s), never a Scan**; multi-term = query each term and intersect. Filters group/forum/channel/author/date; results show title, snippet, author, channel, timestamp. **No semantic ranking, embeddings, OpenSearch, or AI.** Access-scoped by BR-3 (a member only searches groups they can access). Hidden/deleted content excluded. **OpenSearch (Unit 13) remains the optional, cost-gated upgrade** for rich/semantic search (fed as a projection; degrade back to this keyword path when disabled).

**BR-30 — Duplicate detection removed (US-4.5 deviation, Q1).** No LLM duplicate analysis, no held-for-review posts, no Duplicate-Flags queue, no AI-Gateway call. All posts publish on submit.

---

## Deviations from source (recorded, user-approved via brainstorming 2026-08-08)
| Ref | Source | Deviation |
|---|---|---|
| DV-1 | US-4.5 | LLM duplicate detection + hold-for-review + Publish/Reject + Duplicate-Flags queue **removed** (Phase 1). Removes the AI-Gateway (Unit 14) runtime dependency. |
| DV-2 | US-4.13 | Semantic/vector search (OpenSearch + embeddings) **downgraded to literal keyword search** in-service via an inverted-index GSI. Removes the Search (Unit 13) + AI-Gateway embedding dependency at runtime; OpenSearch stays the optional/cost-gated upgrade. |
| DV-3 | US-4.13 / US-4.18 | **No `authorActive`/inactive badge** (Q4). Forums does not consume `UserDeactivated`/`UserReactivated`; author display is name + role label only. |
| DV-4 | US-4.5 | **No image uploads in Phase 1** (Q5). Bodies are Markdown text/formatting/code/links only; the "max 5 images/post in S3" clause is deferred → no S3 bucket, no malware scanning. |
| DV-5 | US-4.11 | **Single reaction per member per target** (Q7), replacing "one or more reactions." Choosing a new kind replaces the previous; fixed reaction set. |
