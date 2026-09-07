# Forums — Domain Entities

**Unit**: 5 Forums · **Stage**: Functional Design · Technology-agnostic domain model.
Companion: `business-logic-model.md`, `business-rules.md`, `frontend-components.md`.

Structure: `User Group → Forum(s) → Channel(s) → Posts → Replies`. Identity/group data is **not owned** here — it arrives via JWT claims and is denormalized at write (BR-authZ, BR-denorm). No `authorActive` tracking (per decision Q4). No duplicate-detection / semantic-search state (out of scope, Q1/Q6).

---

## E1 — Forum
A discussion space owned by exactly one user group. A group may have multiple forums.

| Attribute | Type | Notes |
|---|---|---|
| `forumId` | string (ULID) | PK. |
| `groupId` | string | Owning user group (from creator's claim / target). Immutable after create. |
| `name` | string | Required. Editable (US-4.3). |
| `description` | string | Optional. Editable. |
| `createdBy` | string | Author `sub`. |
| `createdAt` / `updatedAt` | ISO-8601 | |
| `hidden` | bool | `true` when owning group is soft-deleted (Q10); excluded from all reads; reversible on `GroupRestored`. |
| `channelCount` | int | Denormalized counter (maintained on channel create/delete). |

- On create, a default **"General"** channel is auto-created (BR-2).
- Delete is a cascade (BR-11): removes channels → posts → replies → reactions → follows → reports.

## E2 — Channel
A topic subdivision within a forum. All group members may post in every channel (no leader-only channels, Phase 1).

| Attribute | Type | Notes |
|---|---|---|
| `channelId` | string (ULID) | PK. |
| `forumId` | string | Parent forum. |
| `groupId` | string | Denormalized from forum (for O(1) access checks + report scoping). |
| `name` | string | Required. Editable. `General` for the auto-created default. |
| `description` | string | Optional. |
| `createdBy` | string | |
| `createdAt` / `updatedAt` | ISO-8601 | |
| `hidden` | bool | Inherited from forum hide state (Q10). |
| `postCount` | int | Denormalized (US-4.12/4.18 "post count"). |
| `lastActivityAt` | ISO-8601 | Updated on any post/reply in the channel (US-4.12 "last activity"). |

## E3 — Post
A discussion thread root inside a channel.

| Attribute | Type | Notes |
|---|---|---|
| `postId` | string (ULID) | PK. |
| `channelId` / `forumId` / `groupId` | string | Denormalized ancestry for access checks, listing, and report scoping. |
| `authorId` | string | Creator `sub`. |
| `authorName` | string | **Denormalized at write** (Q4) — display name from a one-time Identity lookup at create; fail-closed to id. |
| `authorRoleLabel` | string | **Denormalized at write** from the caller's role claim (`Community Leader` / `User Group Leader` / `Member`). No lookup. |
| `title` | string | Required (US-4.5). |
| `body` | string | **Markdown** (Q5), sanitized on render. **No image attachments in Phase 1 (DV-4)** — text/formatting/code/links only. |
| `tags` | string[] | Optional labels shown in the list (mockup 🏷️). |
| `pinned` | bool | `true` if pinned (US-4.14). |
| `pinnedAt` | ISO-8601 \| null | Pin ordering (newest-first). |
| `acceptedReplyId` | string \| null | The accepted answer, if any (US-4.15); one at a time. |
| `edited` | bool | `true` after any edit (US-4.7). |
| `editedAt` | ISO-8601 \| null | "edited" indicator timestamp. |
| `replyCount` | int | Denormalized counter. |
| `reactionCounts` | map<kind,int> | Per-kind denormalized counters (Q7). |
| `createdAt` / `updatedAt` | ISO-8601 | Newest-first default sort key basis. |
| `deleted` | bool | Soft-removed marker (permanent to users; see BR-8 note). |

> **No `status` field / no `HeldForReview`** — duplicate detection is out of scope (Q1); every created post is immediately visible.

## E4 — Reply
A threaded response under a post.

| Attribute | Type | Notes |
|---|---|---|
| `replyId` | string (ULID) | PK. |
| `postId` / `channelId` / `groupId` | string | Denormalized ancestry. |
| `authorId` / `authorName` / `authorRoleLabel` | string | Same denorm rule as Post (Q4). |
| `body` | string | Markdown, sanitized on render. |
| `accepted` | bool | Mirror of the parent's `acceptedReplyId` for O(1) render (US-4.15). |
| `edited` / `editedAt` | bool / ISO | US-4.7. |
| `reactionCounts` | map<kind,int> | Per-kind counters (Q7). |
| `createdAt` / `updatedAt` | ISO-8601 | Threaded order = createdAt asc. |

- Deleting a post deletes its replies (BR-8). Deleting the accepted reply clears the parent's `acceptedReplyId`.

## E5 — Reaction
A member's **single** reaction on a post or reply. Identity of a reaction = `(userId, targetType, targetId)` — one row per user per target (DV-5).

| Attribute | Type | Notes |
|---|---|---|
| `userId` | string | Reactor `sub`. |
| `targetType` | enum `post` \| `reply` | |
| `targetId` | string | Post or reply id. |
| `kind` | enum | **Fixed set** (Q7): `upvote`, `like`, `heart`, `celebrate`, `insightful`. Unknown → rejected (BR-16). |
| `createdAt` / `updatedAt` | ISO-8601 | |

- **One reaction per member per target (DV-5).** Choosing a different `kind` **replaces** the previous; re-selecting the same kind (or an explicit clear) removes it. Per-kind counters on the target are the read source (no reaction scan on list/thread); replacing decrements the old kind and increments the new atomically.

## E6 — Follow
A per-user subscription to a channel or a post (US-4.16). Identity = `(userId, targetType, targetId)`.

| Attribute | Type | Notes |
|---|---|---|
| `userId` | string | |
| `targetType` | enum `channel` \| `post` | |
| `targetId` | string | |
| `createdAt` | ISO-8601 | |

- Auto-created on the author's own post at post-create (BR-17). Follow drives notification fan-out (delivered by Notifications; email per US-8.7).

## E7 — Report
A member's report of a post/reply for leader moderation (US-4.17).

| Attribute | Type | Notes |
|---|---|---|
| `reportId` | string (ULID) | PK. |
| `targetType` | enum `post` \| `reply` | |
| `targetId` | string | |
| `groupId` | string | Denormalized for queue scoping (UGL → own group; CL → all). |
| `reporterId` | string | |
| `reason` | string \| null | Optional (US-4.17). |
| `status` | enum `Open` \| `Dismissed` \| `Actioned` | `Actioned` when the content is deleted; `Dismissed` by a leader. |
| `createdAt` / `resolvedAt` | ISO-8601 | |
| `resolvedBy` | string \| null | Leader `sub`. |

- Reporter is **not** notified of the outcome (Phase 1, BR-24). Content stays visible until a leader acts (BR-25).

---

## Relationships
```
UserGroup (owned by Identity, referenced by groupId)
   1───* Forum
            1───* Channel
                     1───* Post
                              1───* Reply
Post/Reply 1───* Reaction   (by userId, per kind)
Channel/Post 1───* Follow    (by userId)
Post/Reply 1───* Report
```

## Ownership boundary
Forums owns E1–E7. It does **not** own users, roles, or group membership (JWT claims), nor group display names (denormalized at write, or resolved for the create-time author-name lookup only). Points are owned by Contributions (Forums only emits `ForumPostCreated`/`ForumReplyCreated`). No Search/embedding or AI/duplicate state (out of scope). **No S3 / image storage (DV-4).** Keyword search is served from a DynamoDB **inverted-index GSI** (term→postId), not a separate store (Q6).
