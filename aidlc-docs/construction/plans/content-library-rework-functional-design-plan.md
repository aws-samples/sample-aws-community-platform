# Functional Design Plan — Content Library Rework

## Unit: content-library-rework
**Stories**: US-2.19 (updated), US-2.20 (reworked), US-2.22, US-2.23, US-2.24, US-2.25, US-2.26
**Service**: Events service (extended with new `library` module)
**Dependencies**: Contributions service (Path 2 opt-in), Frontend

---

## Part 1 — Clarifying Questions

Please answer each question by filling in the letter choice after the `[Answer]:` tag.

---

## Question 1
**Path 2 integration — how does the Contributions service notify the Library when a curator opts in?**

The contribution approval currently lives in `services/contributions/src/`. When a CL/UGL approves and ticks "Add to Library", we need the Library module to create a resource. Two options:

A) **Direct API call from the approval UI**: The frontend makes two calls — one to `POST /contributions/{id}/approve` and one to `POST /library` — independently. The Library resource is created client-side at approval time. Simple, but if the second call fails the Library entry is silently missed.

B) **EventBridge event**: The Contributions service publishes a `ContributionApproved` event (already done for points). The Library module adds a consumer that listens for this event and, when the payload includes `addToLibrary: true`, creates the Library resource server-side. Reliable, decoupled, consistent with the platform event pattern.

C) **Synchronous server-side call**: The Contributions approval handler makes a direct HTTP call to the Library API when `addToLibrary: true`. Tightly coupled but atomic within the approval flow.

D) Other (please describe after [Answer]: tag below)

[Answer]: B

---

## Question 2
**Topics autocomplete — how should existing tags be served to the frontend?**

When a curator types in the Topics field, the UI needs to show matching existing tags as suggestions.

A) **Dedicated `GET /library/tags?prefix=serv` endpoint**: Returns distinct lowercase tags matching the prefix, sourced from a `TAGS#ALL` singleton item in the library table that is updated on every resource write (add/edit/delete). O(1) read, cheap write overhead.

B) **Inline in the resources query**: No separate endpoint. The `GET /library` search response includes a `suggestedTopics` list in the envelope, populated lazily. Simpler but couples tag discovery to search.

C) **Tags returned as part of `GET /library/meta`**: A metadata endpoint returns available filters (distinct formats + distinct topics) in one call, loaded once when the Library page opens.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 3
**Path 1 (event auto-promotion) — what happens to the Library resource if a material is later deleted from the event?**

After completion, event materials can still be added or removed (BR-M1). If a material that was auto-promoted gets deleted from the event, should the Library resource:

A) **Be automatically removed** — the Library entry is deleted when the event material is deleted. Keeps Library in sync with the source event.

B) **Remain in the Library** — deletion from the event does not affect the Library. The resource is now "orphaned" from its source but remains discoverable. Curators can delete manually via US-2.25 if needed.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 4
**Path 1 — what happens when a material is added to an already-Completed event and it passes scanning?**

Currently BR-M1 allows adding materials to Completed events. After the rework, when such a material passes GuardDuty scanning, should it:

A) **Automatically be added to the Library** — consistent with Path 1 auto-promotion logic (same trigger: clean material on completed event).

B) **Not be auto-promoted** — only materials present at the moment of completion are auto-promoted. Post-completion additions require a curator to manually add via Path 3.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 5
**Format derivation for Path 1 (event materials) — how should format be determined?**

Event materials have a `contentType` of Slides, PDF, Doc, Recording, or Link. The new Library formats are PPT, Video, Link, Word. We need a mapping:

A) **Direct mapping** — Slides→PPT, Recording→Video, Link→Link, PDF→PDF (keep as-is and add PDF to the format enum), Doc→Word. If the content type doesn't map cleanly, default to the closest match.

B) **Derive from file extension** — inspect the `s3Key` filename extension at promotion time (`.pptx`→PPT, `.mp4`→Video, `.docx`→Word, `.pdf`→PDF). Falls back to contentType mapping if extension is ambiguous.

C) Other (please describe after [Answer]: tag below)

[Answer]: C — reuse event contentType enum directly (Slides, PDF, Doc, Recording, Link). No mapping needed.

---

## Question 6
**Pagination and ordering — how should Library search results be ordered?**

A) **Newest first** (by `addedAt` descending) — most recently added resources appear first. Consistent with the existing Content Library behavior.

B) **Relevance first** — keyword matches in the title rank higher than matches in description. Implemented in-memory after the index query.

C) **Source-grouped** — event materials first, then member contributions, then curator-direct, within each group sorted newest first.

D) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 7
**UGL scope on curation — can a UGL add/edit/delete resources that were contributed by members of OTHER groups, or only their own group's resources?**

The Library is community-wide (all resources visible to all), but curation rights could be scoped.

A) **Any UGL can curate any resource** — since the Library is community-wide, any UGL can edit/delete any resource regardless of which group the original content came from. Simpler, consistent with CL behavior.

B) **UGL can only curate resources they added or that originated from their group** — a UGL cannot edit/delete a resource that a UGL from another group added directly, or a member from another group contributed. More protective but more complex.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Question 8
**Contribution approval UI change — where exactly does the "Add to Library" option appear?**

A) **Inline in the existing approval modal** — the current contribution approval form gets a new collapsible section "Add to Content Library" with the description, format, and topics fields. One modal, one submit.

B) **As a separate step/screen after approval** — approve first (existing flow unchanged), then a follow-up prompt "Would you like to add this to the Content Library?" opens a second form. Two-step but keeps the approval flow uncluttered.

C) Other (please describe after [Answer]: tag below)

[Answer]: A

---

## Part 2 — Execution Checklist (to be completed after questions are answered)

- [x] Step 1: Analyze all question answers and resolve ambiguities
- [x] Step 2: Define business rules BR-LIB-A/V/P/S/T/C/X
- [x] Step 3: Define domain entities (Resource E1, TagRegistry E2)
- [x] Step 4: Define business logic model (three entry paths, search/filter flow, tag autocomplete flow, curation flow)
- [x] Step 5: Define frontend components (ContentLibraryPage, ResourceCard, AddResourceModal, TopicTagInput, CurationPanel)
- [x] Step 6: Create `business-rules.md`
- [x] Step 7: Create `domain-entities.md`
- [x] Step 8: Create `business-logic-model.md`
- [x] Step 9: Create `frontend-components.md`
- [x] Step 10: Update aidlc-state.md
