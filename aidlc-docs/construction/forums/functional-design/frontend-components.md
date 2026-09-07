# Forums — Frontend Components

**Unit**: 5 Forums · **Stage**: Functional Design. React + Vite SPA (feature folder `src/features/forums/`). Role-aware (Member / UGL / CL; Administrator never sees Forums). Mirrors the shipped mock UI (member forums/channel/forum-thread; leader forums; ugl forums + forum-moderation). Markdown bodies rendered with **DOMPurify** sanitization (BR-19). No duplicate-flag UI (DV-1); search box is **literal keyword** (DV-2); no inactive-author badge (DV-3); **no image attach/upload in the composer (DV-4)**; reactions are **single-per-member** (DV-5).

## API client surface (frozen contract + additive v2.0.0)
`browseForums`, `createForum`, `editForum`, `deleteForum`, `createChannel`, `editChannel`, `deleteChannel`, `listPosts`, `getPost`, `createPost`, `editPost`, `deletePost`, `listReplies`, `createReply`, `editReply`, `deleteReply`, `setReaction` (single-per-member, +clear), `acceptAnswer` (+clear via `replyId:null`), `pinPost` (toggle), `followPost`/`followChannel` (toggle) + `unfollow` + `listFollows`, `reportPost`, `dismissReport` (additive), `moderationQueue`, `mentionSuggest`, `searchForum`. All treat `501` as "coming soon" per the SPA convention. *(No image-upload endpoint — DV-4.)*

---

## Component hierarchy

### ForumsBrowsePage (US-4.12) — `member/forums.html`, `leader/forums.html`, `ugl/forums.html`
- Props: `role`, `accessibleGroups`.
- Renders per-group forum cards; each channel row → name, `postCount`, `lastActivityAt`, link to channel.
- **Leader/UGL controls** (role-gated): `＋ Create Forum` (CL) / `＋ Create Channel`, per-channel `Edit`/`Delete`, `Edit Forum`. Member sees read-only rows.
- Hosts `KeywordSearchBar` (group filter for CL/Member-multi-group; fixed group for UGL).
- **No Duplicate-Flags tab** (DV-1). Leader "Reported" queue lives in `ModerationPage`.
- State: `forums[]`, `loading`, modal toggles.

### ChannelPage (US-4.18) — `member/channel.html`
- Props: `channelId`, `role`.
- `PostList` (paginated, US-8.9 rows-select) with `SortSelect` (Newest / Most active / Most reactions / Unanswered). Pinned rows rendered first with the Pinned badge.
- `PostRow`: title, snippet, `authorName`, timestamp, `replyCount`, reaction total, badges (📌 Pinned / ✓ Answered / edited), tags.
- Actions: `＋ New Post` (opens `PostComposer`), `🔔 Follow channel` (toggle), channel-scoped `KeywordSearchBar`.
- Leader inline controls per row (pin/unpin, delete) gated by `canModerate(role, groupId)`.

### ThreadPage (US-4.5/4.6/4.7/4.8/4.11/4.14/4.15/4.16/4.17) — `member/forum-thread.html`
- Props: `postId`, `role`, `currentUserId`.
- `PinnedBanner` (if pinned). `PostCard`: author + `authorRoleLabel` badge, timestamp, Markdown body (sanitized, no images — DV-4), `ReactionBar`, `FollowButton`, `ReportButton`, author `Edit`/`Delete`.
- `AcceptedAnswerCard` highlighted directly under the post (if `acceptedReplyId`).
- `ReplyList` → `ReplyCard` (author, timestamp, body, `ReactionBar`, `Mark accepted` [author/leader], `Report`, author edit/delete).
- `ReplyComposer` = `RichTextToolbar` (B / I / code / link / @Mention — no image button, DV-4) + Markdown `textarea` + `MentionAutocomplete`.

### PostComposer / ForumModal / ChannelModal
- `PostComposer`: title input + Markdown editor (no image upload, DV-4) + `MentionAutocomplete`. Submits `createPost`; **no duplicate-warning step** (DV-1) — publishes on submit.
- `ForumModal` (CL): name, description, target group select; note "default General channel auto-created".
- `ChannelModal` (CL/UGL): forum (readonly for UGL = their group), name, description.

### ModerationPage (US-4.17) — `leader/forums.html` (Reported tab), `ugl/forum-moderation.html`
- `moderationQueue` scoped to role. Table/cards: reported content, group, reporter, reason, date.
- Actions per row: `Dismiss` (→ `dismissReport`) or `Delete` (→ `deletePost`/`deleteReply`).
- **No duplicate-hold section** (DV-1) — the mockup's "held/publish/reject" panel is not built; the page shows only reported items.
- Nav review-count badge (read-only, US-8.6 Option 2A), sourced from Open report count.

### Shared components
- `ReactionBar`: fixed kinds `upvote/like/heart/celebrate/insightful` with counts; **single-select** — the caller's one current reaction is highlighted; picking another replaces it, re-clicking clears (`setReaction`).
- `MentionAutocomplete`: debounced `mentionSuggest?q=`; lists `{userId, displayName}`; inserts an `@name` token bound to `userId`.
- `FollowButton`: toggle for post/channel; reflects follow state.
- `KeywordSearchBar`: query + filters (group/forum/channel/author/date); calls `searchForum`; `SearchResults` show title, snippet, author, channel, timestamp (no relevance %, no inactive badge).
- `MarkdownView`: renders sanitized Markdown (DOMPurify).
- `FollowsManager` (US-4.16): "my follows" list from `listFollows`, unfollow inline.

## State management
- Server state via the shared API client + query cache; optimistic toggles for reactions/pins/follows with rollback on error.
- Role capability helpers (`canManageForum`, `canModerate`, `canPin`, `canAccept`) derived from role + `groupId` claims — UI hides controls the server would 403 (defense-in-depth, not the authority; server enforces BR-1..5).

## Form validation
- Post: `title` required, `body` non-empty (no image attachments, DV-4).
- Forum/channel: `name` required.
- Mentions: only selectable candidates from `mentionSuggest` (server re-validates, BR-21).

## API integration map
| Component | Calls |
|---|---|
| ForumsBrowsePage | `browseForums`, `createForum/editForum/deleteForum`, `createChannel/editChannel/deleteChannel` |
| ChannelPage | `listPosts`, `followChannel`, `searchForum`, `pinPost`, `deletePost` |
| ThreadPage | `getPost`, `listReplies`, `createReply`, `editPost/editReply`, `deletePost/deleteReply`, `setReaction`, `acceptAnswer`, `followPost`, `reportPost` |
| PostComposer | `createPost`, `mentionSuggest` |
| ModerationPage | `moderationQueue`, `dismissReport`, `deletePost/deleteReply` |
| FollowsManager | `listFollows`, `unfollow` |

## Role visibility summary
| Screen | Member | UGL (led group) | CL | Admin |
|---|---|---|---|---|
| Browse / channel / thread | own groups | led group + manage | all groups + manage | none (BR-1) |
| Create/edit/delete forum/channel | — | led group | any | — |
| Pin / accepted (others') / moderate | accept own post only | led group | any | — |
| Post / reply / react / follow / report | ✓ (their groups) | ✓ | ✓ | — |
