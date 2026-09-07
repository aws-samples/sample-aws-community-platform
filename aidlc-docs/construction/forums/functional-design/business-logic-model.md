# Forums — Business Logic Model

**Unit**: 5 Forums · **Stage**: Functional Design. Technology-agnostic behavior model. Companion: `domain-entities.md` (E1–E7), `business-rules.md` (BR-1..30), `frontend-components.md`.

## Purpose & boundary
Threaded group-scoped discussions: forums → channels → posts → replies, with reactions, @mentions, pinning, accepted answers, following, member reporting + leader moderation, and literal keyword search. Administrators are excluded entirely (BR-1). Identity/membership come from JWT claims; display names are denormalized at write. **Out of scope (approved deviations):** LLM duplicate detection (DV-1), semantic/vector search (DV-2 — keyword via inverted-index GSI instead), and image uploads (DV-4). Reactions are single-per-member (DV-5). So this unit has **no runtime dependency on AI Gateway (Unit 14) or Search (Unit 13)** and **no S3 bucket**.

## Actors
CL (any group) · UGL (strictly their one led group) · Member (their groups) · Administrator (no access). Cross-service participants: Identity & Access (Unit 2 — @mention candidate read + group-lifecycle events), Contributions (Unit 7 — consumes post/reply events for auto-award), Notifications (Unit 10 — delivers mention/reply/follow signals + routes the moderation review-count).

---

## Core workflows

### W1 — Browse forums & channels (US-4.12)
Input: caller claims. Resolve accessible groups (BR-3): CL→all, UGL→ledGroup, M→memberGroups, A→403. Return each accessible, non-hidden forum with its channels; each channel shows `postCount` + `lastActivityAt`. No cross-service calls.

### W2 — View a channel (post list) (US-4.18)
List posts in a channel (access-checked). Pinned posts first (`pinnedAt` desc), then by chosen sort — default newest (`createdAt` desc), plus most-active (`lastActivity`/`replyCount`), most-reactions (sum of `reactionCounts`), unanswered (`acceptedReplyId == null` and `replyCount == 0`). Each row: title, snippet (derived from body), `authorName`, timestamp, `replyCount`, reaction total, badges (Pinned / Answered / edited), tags. Pagination + rows-per-page (US-8.9). All fields are on the item (no fan-out).

### W3 — Open a thread (US-4.18 → post + replies)
Return the post, its accepted reply (if any) highlighted, and threaded replies (`createdAt` asc). Bodies are Markdown, sanitized on render (BR-19). Reaction states for the caller are derived from Reaction items; counts from the target counters.

### W4 — Create post (US-4.5)
Access check (BR-3) → validate `title`+`body` → sanitize/persist Markdown (text/formatting/code/links; no images, DV-4) → write inverted-index terms for keyword search (BR-29) → **publish immediately** (no dup hold, DV-1) → increment channel `postCount`, set `lastActivityAt` → auto-follow author (BR-17) → validate & record mentions (BR-21) → emit `ForumPostCreated` (+`MemberMentioned` per mention). Contributions auto-awards on the event (US-6.4).

### W5 — Reply (US-4.6)
Access check → persist reply → increment post `replyCount` + channel `lastActivityAt` → record mentions → notify post author + post-followers (BR-22) → emit `ForumReplyCreated` (+`MemberMentioned`).

### W6 — Edit / delete content (US-4.7/4.8)
Edit: author-only (BR-5); set `edited`+`editedAt`. Delete: author/CL(any)/UGL(group) (BR-5); cascade replies+reactions+follows+reports (BR-11); points retained (BR-12); emit `PostDeleted`. Deleting the accepted reply clears the parent pointer (BR-15).

### W7 — React (US-4.11, DV-5)
`setReaction{kind}` with kind in the fixed set (BR-16); **one reaction per member per target** — set/replace the caller's reaction, atomically decrementing the previous kind's counter and incrementing the new; re-selecting the same kind or clearing removes it.

### W8 — @mention (US-4.9/4.10)
`mentionSuggest?q=` → synchronous Identity read (caller's JWT), scoped to the post's group → candidates {group members + group UGL(s) + any CL} matching `q`, each `{userId, displayName}`. On submit, server re-validates each mentioned id against the same access rule (BR-21). Each valid mention → email + in-portal notification (BR-23) + `MemberMentioned`.

### W9 — Pin / accepted answer (US-4.14/4.15)
Pin: toggle by CL(any)/UGL(group) (BR-14), no notification. Accept: author/CL/UGL sets one reply accepted, clearing any previous (BR-15); no points.

### W10 — Follow (US-4.16)
Toggle follow on a channel or post; auto-follow own posts (BR-17). `GET /follows` lists the caller's follows. Followed activity → notification fan-out (Notifications delivers; email per US-8.7).

### W11 — Report & moderate (US-4.17)
`reportPost{reason?}` → create Report(status=Open) → emit `PostReported` (Notifications bumps the group leaders' read-only review-count, US-8.6 Option 2A — not a stored notification). `moderationQueue` → Open reports scoped to caller (CL all, UGL own group). Leader **dismiss** (Report→Dismissed, content stays) or **delete content** (via W6; related reports→Actioned). Reporter never notified (BR-24).

### W12 — Keyword search (US-4.13, DV-2)
`searchForum?q=&filters` → tokenize the query, **Query the inverted-index GSI** per term (`term→postId`) and intersect (never a Scan, BR-29), access-scoped (BR-3), hidden/deleted excluded, filters group/forum/channel/author/date; results: title, snippet, author, channel, timestamp. No embeddings/ranking/AI. Channel view offers a channel-scoped variant. OpenSearch (Unit 13) is the optional upgrade path.

### W13 — Group lifecycle consumers (US-1.11, Q10)
`GroupHardDeleted` → **mark forums deleted synchronously (instant hide), then background-batch delete** the underlying rows, resumable (BR-27). `GroupSoftDeleted` → set forums `hidden` (BR-28). `GroupRestored` → clear `hidden`. All idempotent on event id.

---

## Events

### Published (envelope-compliant; schemas authored under `contracts/services/forums/published-events/`)
| Event | Trigger | Primary consumer |
|---|---|---|
| `ForumPostCreated` | Post published (W4) | Contributions (auto-award US-6.4), Notifications |
| `ForumReplyCreated` | Reply created (W5) | Contributions, Notifications |
| `MemberMentioned` | Validated mention (W8) | Notifications (email + in-portal) |
| `PostReported` | Report filed (W11) | Notifications (review-count routing to group UGL + CLs) |
| `PostDeleted` | Post deleted (W6) | (retained for downstream/audit; no Search consumer post-DV-2) |
| `ForumChannelDeleted` | Forum/channel deleted (W6) | (retained; no Search consumer post-DV-2) |

### Consumed
| Event | Source | Action |
|---|---|---|
| `GroupHardDeleted` | Identity | Cascade purge group content (BR-27) |
| `GroupSoftDeleted` | Identity | Hide group forums (BR-28) |
| `GroupRestored` | Identity | Un-hide (BR-28) |

> Dropped vs original plan: no synchronous **AI-Gateway** dup-check call (DV-1); no **Search** index events / embedding lifecycle (DV-2); no `UserDeactivated`/`UserReactivated` consumption (DV-3).

## Synchronous outbound calls (the only ones)
- **Identity** — `mentionSuggest` candidate lookup (W8), forwarding the caller's JWT. Non-critical: if it fails, autocomplete degrades to empty (the member can still post without mentioning).

## Data-integrity & degrade notes
- Every listing is a keyed query (no Scan) — pinned/newest/most-active/unanswered are index-ordered or in-memory sorted over a bounded channel page.
- Counters (`postCount`, `replyCount`, `reactionCounts`, `channelCount`, `lastActivityAt`) are denormalized and updated transactionally with the write that changes them — reads never recount.
- Cascades (W6/W13) are the only multi-item writes; batched, idempotent, and safe to resume.
- Degrade: Identity mention lookup down → empty suggestions (post still works). Contributions/Notifications down → events buffer on the bus (async, eventually consistent); Forums never blocks on them.

## Traceability (18/18 stories)
US-4.1→W1/BR-6 · US-4.2→BR-7 · US-4.3→BR-8 · US-4.4→W6/BR-11 · US-4.5→W4 · US-4.6→W5 · US-4.7→BR-13 · US-4.8→W6/BR-11 · US-4.9→W8/BR-21 · US-4.10→BR-23 · US-4.11→W7/BR-16 · US-4.12→W1 · US-4.13→W12/BR-29 (DV-2) · US-4.14→W9/BR-14 · US-4.15→W9/BR-15 · US-4.16→W10/BR-18 · US-4.17→W11 · US-4.18→W2.
