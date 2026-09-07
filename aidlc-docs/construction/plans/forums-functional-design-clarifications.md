# Forums Functional Design — Clarifications (Round 2)

You answered the 12 questions. This file (1) records what's now **locked**, (2) asks you to **confirm two answers** that were ambiguous, and (3) gives plain-language **explanations** for the five you marked "explain," restated simply so you can pick. Answer after each `[Answer]:` tag. When done, say "done" and I'll generate the functional-design artifacts.

---

## A. Locked from your answers (no action needed — listed for the record)
| Q | Your answer | What it means for the design |
|---|---|---|
| Q1 Duplicate detection | **Out of scope (Phase 1)** | No LLM dup-check, no "Held for review" status, no Publish/Reject flow, no Duplicate-Flags queue. **Every post publishes immediately.** Removes the synchronous AI-Gateway call entirely. *(Deviation from US-4.5 + the dup-flag mockups — recorded.)* |
| Q2 Dup-check degrade | **N/A** | Consistent with Q1 — nothing to degrade. |
| Q3 @mention source | **A** | `mentionSuggest` reads Identity synchronously (caller's JWT), scoped to the post's group; server re-validates the mentioned set on submit. |
| Q4 Author denorm | **Denormalize name + role label at write; do NOT track/show `authorActive`** | Store `authorName` + `authorRoleLabel` on each post/reply (from the caller's claims at create). **No inactive/deactivated badge, no consumption of UserDeactivated/UserReactivated.** |
| Q11 Pin / accepted answer | **A** | Pin = toggle (multiple pins, newest-first, no notification). Accepted answer = set one/clear previous; `null` clears; author or CL/UGL(their group); no points. |

---

## B. Please confirm (your answer was ambiguous)

## Question 5 — Rich-text body + images
You wrote **"Rich-text is markup."** I'll take that as: **the post/reply body is stored as Markdown** (sanitized on render with DOMPurify), not HTML. That's fine and simpler.

What I still need is the **image** decision (US-4.5 says "max 5 images per post in S3"), since Markdown by itself doesn't say where images live:

A) **(recommended)** Support up to **5 image uploads to a Forums-owned S3 bucket** (presigned PUT); the Markdown body references the returned image URLs (served via CloudFront). Server enforces the ≤5 cap + image content-types.

B) **External image URLs only** — members paste an image link in Markdown; no upload, no S3 bucket in this unit.

C) **No images in Phase 1** — body is Markdown text/formatting/code/links only (drops the ≤5-images requirement for now).

X) Other (describe after `[Answer]:`)

[Answer]: 

## Question 6 — Search (semantic is out; what about basic search?)
You wrote **"out of scope Semantic search."** So no OpenSearch, no embeddings, no AI. The remaining question is whether Forums still offers a **basic keyword search** (the mockups all show a search box on the forums/channel pages):

A) **(recommended)** **Keep a basic keyword search** over Forums' own data — match on post title/body text, with the group/forum/channel/author/date filters, results showing title, snippet, author, channel, timestamp. No relevance ranking, no embeddings. The search box in the mockups still works; it's just literal matching, not semantic.

B) **Defer search entirely** — no search endpoint in Phase 1; the search box is hidden / "coming soon" (endpoint returns 501). Forums ships browse + create + moderate only.

X) Other (describe after `[Answer]:`)

[Answer]: 

*(Either way this is a deviation from US-4.13's semantic-search mandate — recorded. Note: `ForumPostCreated`/`ForumReplyCreated` are still published regardless, because Contributions consumes them for point auto-award; they are not search-specific.)*

---

## C. Explanations for the ones you marked "explain" (re-answer below each)

## Question 7 — Reactions (explained)
The real question: **can one member put more than one kind of reaction on the same post, and do we fix the list of allowed reactions?** The thread mockup shows 👍 ❤️ 🎉 all on one post with counts.

A) **(recommended)** A member can add **several different reactions** to the same post/reply (e.g., both 👍 and ❤️), **one of each type**; clicking the same one again removes it. The allowed reactions are a **fixed list** the server knows (`upvote`, `like`, `heart`, `celebrate`, `insightful`) — anything else is rejected. We keep a running **count per reaction** on the post so reading a list/thread never has to recount.

B) **One reaction per member per post** — picking a new kind replaces the previous one (a single 👍-or-❤️ choice). Simpler, but the mockup shows multiple kinds at once.

C) **Any emoji allowed** (open-ended), not a fixed list.

X) Other (describe after `[Answer]:`)

[Answer]: 

## Question 8 — Follow / subscriptions (explained)
"Following" = choosing to be notified about future activity. US-4.16 wants two levels: follow a **whole channel** (told when any new post appears) or a **single post** (told when it gets new replies), plus auto-following posts you wrote, plus a place to see/manage what you follow.

A) **(recommended)** Full model: follow **channels and posts**, **auto-follow your own posts**, an "unfollow," and a **"my follows" list**. Stored in a small Follows table (one row per user+thing-followed). New activity on a followed item → in-portal notification always, email per the member's preferences (delivered by Notifications, not Forums).

B) **Follow individual posts only** in Phase 1 (no channel-level follow). Less than US-4.16 asks for.

X) Other (describe after `[Answer]:`)

[Answer]: 

## Question 9 — "Can this person access this group's forum?" (explained)
This is separate from role permissions. Even if your role *can* post, you can only act inside forums of groups you're actually in: a **Member** only in groups they belong to, a **UGL** only their one led group, a **CL** any group, an **Admin** none. The question is **where we get the caller's group list** to enforce that.

A) **(recommended)** Read it **straight from the login token (JWT)**, which already carries the user's group ids and role — no extra call to another service. Fast, and it's exactly how Events and Announcements already do it.

B) Keep **our own copy** of who-belongs-to-which-group by listening to Identity's membership events, and check against that copy. More moving parts; only worth it if the token proves insufficient.

X) Other (describe after `[Answer]:`)

[Answer]: 

## Question 10 — What happens to forums when a group is deleted (explained)
Identity can delete a group two ways: **soft** (reversible, just hidden) or **hard** (permanent). The question: does Forums react to both?

A) **(recommended)** On **hard delete**, permanently remove all that group's forums/channels/posts/replies/reactions/follows/reports. On **soft delete**, just **hide** the group's forums (and un-hide if the group is restored). Nothing from a removed group stays visible. *(With search now out of scope per Q6, there's no Search index to purge — this is purely internal cleanup + hide/restore.)*

B) **Only handle hard delete** (permanent removal). A soft-deleted group's forums stay visible until it's hard-deleted. Simpler, but leaves visible content for a group that was just removed.

X) Other (describe after `[Answer]:`)

[Answer]: 

## Question 12 — Reporting content + the moderation queue (explained)
A member can **report** a post/reply (with an optional reason). The group's **UGL and CLs** see a queue of reports and either **dismiss** them (content stays) or **delete** the content. The reporter is never told the outcome. The question is how we store and route this.

A) **(recommended)** A **Reports table**. Reporting creates an "Open" report and bumps the leaders' review-queue **count** (a read-only badge — not a real notification, no email). The moderation queue shows **Open** reports scoped to the leader (CL sees all groups; UGL only their group). A leader **dismisses** (report closed, content stays) or **deletes the content** (which also closes the related reports). Reporter not notified (Phase 1).

B) Attach reports **directly onto the post record** instead of a separate table. Risky — a heavily reported post's record grows unbounded.

X) Other (describe after `[Answer]:`)

[Answer]: 
