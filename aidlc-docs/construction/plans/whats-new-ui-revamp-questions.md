# What's New in AWS — UI Revamp Clarification Questions

Please answer each question by filling in the letter choice after the `[Answer]:` tag.
If none of the options match, choose the last option (Other) and describe your preference.
Let me know when you're done.

---

## Question 1
What is the primary feel you want for the revamped page?

A) Modern news/blog reader — larger visual cards with image-like category icons, clear visual hierarchy, feels like reading AWS news

B) Dashboard-style — tighter rows, high information density, feels efficient and scannable

C) Branded AWS-flavored — orange/amber AWS color accent throughout, AWS logo badge on items, feels like a first-party AWS feed widget embedded in the portal

D) Minimal clean refresh — keep the current card-list structure but polish spacing, typography, hover states, and transitions

E) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 2
What should happen to the item list layout?

A) Keep the current collapsible card list — just make each card more visually rich (better typography, gradient left-border accent, category badges improved)

B) Switch to a two-column card grid for wider screens (like a news feed), collapsing to one column on mobile

C) Switch to a magazine-style layout — first item featured/large at top, rest in a condensed list below

D) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 3
For category badges on feed items — what style do you prefer?

A) Color-coded by service domain (Compute = blue, Storage = green, Security = red, etc.) — use the portal's existing badge color variants

B) Single consistent accent color for all AWS category badges (AWS-orange tint or blue tint) — uniform look

C) Keep the current neutral grey badge — just make it slightly more refined (pill shape, a bit more padding)

D) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 4
What improvements do you want on the search/filter toolbar?

A) Keep the 2-field layout but make it visually polished — better border, focus ring, search icon inside the input, count of visible items shown (e.g., "24 announcements")

B) Add a third visual element — a "Sort by" control (Newest first / Oldest first) alongside search + category

C) Move the toolbar into a sticky header bar so it stays visible as the user scrolls the feed

D) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 5
What should the expanded item body look like when a user clicks to open an announcement?

A) Smooth animated slide-down (CSS max-height transition), a subtle top border separator, and a slightly tinted background for the body section

B) Open in a modal/drawer overlay instead of inline expansion — keeps the list visible while reading

C) Keep inline expansion but add a visual "reading pane" feel — wider body area, larger font, more whitespace

D) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 6
What is the scope of changes you want?

A) Frontend only — just `WhatsNewPage.tsx`, `FeedItemRow.tsx`, and `portal.css` (`.wn-*` styles). No new components, no new dependencies, no backend touch

B) Frontend + allow new small utility component(s) if needed (e.g., a dedicated `WhatsNewToolbar.tsx` or `FeedItemCard.tsx`) — still no backend/IaC

C) Other (please describe after [Answer]: tag below)

[Answer]: 

---

## Question 7
Should the page header area be revamped too?

A) Yes — give it an AWS-branded banner treatment: a gradient background strip with the 🆕 icon, title, and subtitle — clearly branded, visually distinct from other portal pages

B) Yes — just improve the existing `.page-head` with a slightly larger subtitle, maybe an icon, keeping it consistent with other portal pages

C) No — leave the page header as-is, focus only on the feed list and toolbar

D) Other (please describe after [Answer]: tag below)

[Answer]: 
