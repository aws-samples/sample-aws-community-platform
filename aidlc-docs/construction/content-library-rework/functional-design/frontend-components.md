# Frontend Components — Content Library Rework

---

## Component Hierarchy

```
App.tsx
  └── /content-library  →  ContentLibraryPage
        ├── LibrarySearchBar        (keyword + filters)
        ├── LibraryResultsList
        │     └── LibraryResourceCard  (per result)
        └── LibraryAddResourceModal  (CL/UGL only)

ContributionsPage (existing, approval modal)
  └── ApproveContributionModal (existing)
        └── [NEW] LibraryOptInSection  (CL/UGL only, collapsible)
              └── TopicTagInput        (shared component)

ContentLibraryPage (curator management view)
  └── LibraryResourceCard
        └── [curator actions: Edit / Delete]
  └── EditResourceModal  (CL/UGL only)
        └── TopicTagInput
```

---

## ContentLibraryPage

**Route**: `/content-library`
**Visible to**: Member, UGL, CL (hidden from Administrator — nav item not rendered)

### State
```typescript
term: string                    // keyword input (live)
submittedTerm: string | null    // null = search-first gate not yet passed
format: string                  // '' = all
topic: string                   // '' = all
source: string                  // '' = all
cursorStack: (string | null)[]  // [null] initially; push on Next, pop on Prev
```

### Behavior
- Nothing fetched until `submittedTerm !== null` (search-first, BR-LIB-S1)
- Format, topic, source filters trigger immediate re-search (reset cursor stack)
- Keyword only fires on Enter or Search button click
- Fetches `GET /library?q=...&format=...&topic=...&source=...&limit=10&cursor=...`
- "Add to Library" button visible only to CL/UGL → opens `LibraryAddResourceModal`

### Props
```typescript
role: 'CommunityLeader' | 'UserGroupLeader' | 'Member'
```

---

## LibrarySearchBar

Renders the search controls row.

### Props
```typescript
term: string
format: string
topic: string
source: string
onTermChange: (v: string) => void
onSearch: () => void
onFormatChange: (v: string) => void
onTopicChange: (v: string) => void
onSourceChange: (v: string) => void
resultCount: number | null
```

### Elements
- Text input: `placeholder="🔍 Search title or description…"`, Enter triggers `onSearch`
- Search button: `🔍 Search`
- Format select: All formats | Slides | PDF | Doc | Recording | Link
- Source select: All sources | Event Material | Member Contribution | Curator Direct
- Topic input: `TopicTagInput` in filter mode (single-tag filter, not multi-tag add)
- Result count: faint small text when results present

---

## LibraryResourceCard

Renders one search result or one item in the curator management list.

### Props
```typescript
resource: LibraryResource
isCurator: boolean          // CL or UGL — shows edit/delete actions
onEdit?: (id: string) => void
onDelete?: (id: string) => void
```

### Layout
```
[ format icon ] [ title ]                    [ Download / Open link ]
                [ format badge ] [ topics ]
                ─────────────────────────────
                [ description excerpt ]
                [ attribution line ]
                [ source badge ]
```

### Attribution line
- `event-material`: `📅 {eventTitle} · {addedAt date}`
- `member-contribution`: `👤 {submittedByName} · Community Contribution`
- `curator-direct`: `🏷️ Curated by {submittedByName}`

### Download / Open link
- File resource + `scanState == Clean` + `downloadUrl`: shows `⬇ Download` button
- File resource + `scanState == PendingScan`: shows `⏳ Scan in progress` (disabled)
- File resource + `scanState == Quarantined`: hidden (never returned by search, curators see in management view only)
- Link resource: shows `🔗 Open link` (opens in new tab)

### Curator actions (isCurator only)
- `✏️ Edit` → opens `EditResourceModal`
- `🗑️ Delete` → inline confirm → `DELETE /library/{id}`

---

## LibraryAddResourceModal

**Visible to**: CL, UGL only
**Triggered by**: "Add to Library" button on `ContentLibraryPage`

### Fields
```
Title *          text input, max 200
Description *    textarea, max 5000 (search corpus — label explains this)
Format *         select: Slides | PDF | Doc | Recording | Link
Topics           TopicTagInput (multi-tag)
URL              text input (shown only when Format = Link, required)
File             file picker (shown only when Format != Link)
```

### Behavior
- On submit: `POST /library`
- For file formats: response includes `presignedUploadUrl` → SPA uploads file directly to S3 (same pattern as event materials)
- Success: card appears at top of results list; modal closes
- Validation: client-side mirrors server-side rules (title required, description required, format required, url https:// for Link)

---

## EditResourceModal

**Visible to**: CL, UGL only
**Triggered by**: Edit action on `LibraryResourceCard`

### Fields (same as Add, minus file upload — BR-LIB-C2)
```
Title *          pre-filled
Description *    pre-filled
Format *         pre-filled
Topics           pre-filled (TopicTagInput)
URL              pre-filled (Link format only)
```

### Behavior
- On submit: `PUT /library/{id}`
- File replacement not supported — label explains "To replace the file, delete this resource and re-add"

---

## TopicTagInput

Shared component used in Add modal, Edit modal, and LibraryOptInSection.
Also used in single-filter mode on the search bar.

### Props
```typescript
value: string[]             // current tags
onChange: (tags: string[]) => void
mode: 'multi' | 'single'    // multi = add resource; single = filter
placeholder?: string
```

### Behavior (multi mode)
- Text input with autocomplete dropdown
- On type (debounced 300ms, min 2 chars): `GET /library/tags?prefix={input}`
- Suggestions shown as dropdown; click or Enter adds tag
- Tags displayed as removable chips below input
- Input lowercases on add
- Max 20 tags (BR-LIB-V4)

### Behavior (single mode — search filter)
- Same autocomplete, but selecting a tag sets the single filter value
- Displayed as a select-like input (current tag shown, clear button)

---

## LibraryOptInSection (inside ApproveContributionModal)

New collapsible section added to the existing contribution approval modal.

### Visibility
- Rendered only for CL and UGL
- Collapsed by default; toggle: `📚 Add to Content Library`

### Fields (shown when expanded)
```
Description *    textarea, max 5000 (pre-filled from contribution description if present)
Format *         select: Slides | PDF | Doc | Recording | Link
Topics           TopicTagInput (multi-tag)
URL              text input (shown only when Format = Link)
```

### Behavior
- When expanded and form filled: approval payload includes `addToLibrary: true` + library fields
- When collapsed / not filled: approval payload includes `addToLibrary: false`
- The approval submit button text changes to "Approve & Add to Library" when section is expanded and valid

---

## Route and Navigation Changes

### New route (App.tsx)
```typescript
<Route path="/content-library" element={<ContentLibraryPage role={role} />} />
```

### Navigation item
- Added to sidebar/nav for Member, UGL, CL
- Hidden for Administrator
- Label: `📚 Content Library`

### Removed
- `ContentLibraryTab` export and tab entry from `EventsPage.tsx`
- `tab === "library"` branch from EventsPage tab switcher
- `📚 Content Library` tab from Events page tab strip

---

## API Integration Points

| Component | Endpoint | When |
|---|---|---|
| ContentLibraryPage | `GET /library` | On search submit |
| TopicTagInput | `GET /library/tags?prefix=` | On keystroke (debounced) |
| LibraryAddResourceModal | `POST /library` | On form submit |
| EditResourceModal | `PUT /library/{id}` | On form submit |
| LibraryResourceCard | `DELETE /library/{id}` | On delete confirm |
| ApproveContributionModal | `POST /contributions/{id}/approve` | Unchanged; payload extended with `addToLibrary` fields |

---

## Type Definitions

```typescript
interface LibraryResource {
  id: string;
  title: string;
  description: string;
  format: 'Slides' | 'PDF' | 'Doc' | 'Recording' | 'Link';
  topics: string[];
  source: 'event-material' | 'member-contribution' | 'curator-direct';
  submittedBy: string;
  submittedByName?: string;
  addedAt: string;
  // Conditional
  eventId?: string;
  eventTitle?: string;
  downloadUrl?: string;
  url?: string;
  scanState?: 'PendingScan' | 'Clean' | 'Quarantined';
}
```
