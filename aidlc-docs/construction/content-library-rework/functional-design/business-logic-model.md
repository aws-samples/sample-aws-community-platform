# Business Logic Model — Content Library Rework

---

## Overview

The Library module is a new Python module (`library_service.py`, `library_repository.py`)
inside the Events service Lambda. It owns the `library-${Stage}` DynamoDB table and exposes
routes under `/library`. It is triggered by three entry paths and serves a single search
interface to all authenticated non-Administrator users.

---

## Entry Path 1 — Event Material Auto-Promotion

### Trigger points (two)

**Trigger A — Event completion**
```
event_service.complete(event_id, principal)
  └── transitions event status to Completed
  └── calls library_service.promote_event_materials(event)
        └── for each material in repo.list_materials(event_id):
              if material.scanState == Clean
              AND (material.kind == 'link' OR material.uploaded == True):
                library_service._create_from_material(material, event)
```

**Trigger B — Scan result clears a material on a completed event**
```
MalwareScanConsumer.handle(envelope)
  └── sets scanState = Clean on material
  └── if event.status == Completed:
        library_service.promote_single_material(material, event)
          └── library_service._create_from_material(material, event)
```

### `_create_from_material(material, event)` logic
```
resource = {
    id:              new_id('lib'),
    title:           material['name'],
    description:     event['description'],      # guaranteed non-empty (BR-L2-DESC)
    format:          material['contentType'],   # direct copy, no mapping
    topics:          [],                        # no topics on auto-promotion
    source:          'event-material',
    scope:           'COMMUNITY',
    s3Key:           material.get('s3Key'),
    url:             material.get('link'),
    scanState:       'Clean',                   # only Clean materials reach here
    submittedBy:     event['createdBy'],
    submittedByName: event.get('createdByName', event['createdBy']),
    addedBy:         'system',
    addedAt:         now_iso(),
    eventId:         event['id'],
    eventTitle:      event['title'],
    materialId:      material['id'],
    contributionId:  None,
}
# Idempotent: check if resource with same materialId already exists before writing
if not library_repo.get_by_material_id(material['id']):
    library_repo.put_resource(resource)
    library_repo.add_tags([])          # no tags on Path 1
```

### Auto-removal on material deletion
```
MaterialService.remove(event_id, material_id, principal)
  └── [existing: delete S3 object, delete material row]
  └── [NEW] library_service.remove_by_material_id(material_id)
        └── library_repo.delete_by_material_id(material_id)   # no-op if not in Library
```

---

## Entry Path 2 — Member Contribution Opt-In (EventBridge Consumer)

### Consumer flow
```
ContributionApprovedConsumer.handle(envelope)
  └── extract: contributionId, memberId, memberName,
               addToLibrary, title, description, format, topics, url/s3Key
  └── if not addToLibrary: return (no-op)
  └── idempotency check: library_repo.get_by_contribution_id(contributionId)
        └── if exists: return (already processed — redelivery)
  └── validate: description required, format valid, url https:// if Link
  └── resource = {
          id:              new_id('lib'),
          title:           title,
          description:     description,         # curator-entered at approval
          format:          format,
          topics:          [t.strip().lower() for t in topics],
          source:          'member-contribution',
          scope:           'COMMUNITY',
          url:             url or None,
          s3Key:           s3Key or None,
          scanState:       'Clean' if format == 'Link' else 'PendingScan',
          submittedBy:     memberId,
          submittedByName: memberName,
          addedBy:         approverId,          # from envelope
          addedAt:         now_iso(),
          eventId:         None,
          eventTitle:      None,
          materialId:      None,
          contributionId:  contributionId,
      }
  └── library_repo.put_resource(resource)
  └── library_repo.add_tags(resource['topics'])
```

### ContributionApproved payload extension (additions to existing event)
```json
{
  "contributionId": "con-abc123",
  "memberId": "usr-xyz",
  "memberName": "Jane Doe",
  "addToLibrary": true,
  "libraryTitle": "Serverless Patterns Guide",
  "libraryDescription": "A practical guide to serverless patterns on AWS...",
  "libraryFormat": "Doc",
  "libraryTopics": ["serverless", "lambda", "patterns"],
  "libraryUrl": null,
  "libraryS3Key": "library/con-abc123/serverless-patterns.docx"
}
```

---

## Entry Path 3 — Curator Direct Add

### API flow
```
POST /library
  └── authZ: role must be CL or UGL (BR-LIB-A3)
  └── validate all fields (BR-LIB-V1..V6)
  └── normalize topics: [t.strip().lower() for t in body.get('topics', [])]
  └── deduplicate topics: list(set(topics))
  └── for file formats: mint presigned PUT URL (same pattern as event materials)
  └── resource = {
          id:              new_id('lib'),
          title:           body['title'],
          description:     body['description'],
          format:          body['format'],
          topics:          normalized_topics,
          source:          'curator-direct',
          scope:           'COMMUNITY',
          url:             body.get('url'),
          s3Key:           derived_s3_key,      # library/<id>/<filename>
          scanState:       'Clean' if format == 'Link' else 'PendingScan',
          submittedBy:     principal.user_id,
          submittedByName: principal.name,
          addedBy:         principal.user_id,
          addedAt:         now_iso(),
          eventId:         None,
          eventTitle:      None,
          materialId:      None,
          contributionId:  None,
      }
  └── library_repo.put_resource(resource)
  └── library_repo.add_tags(normalized_topics)
  └── return resource_public(resource)
        # for file formats: include presignedUploadUrl in response
        # (client uploads directly to S3, same as event materials)
```

---

## Search Flow

```
GET /library?q=serverless&format=Doc&topic=lambda&source=member-contribution&limit=10&cursor=...
  └── authZ: Administrator → 403
  └── if no q AND no format AND no topic AND no source: return {items:[], count:0}  (BR-LIB-S1)
  └── validate: format enum, source enum, limit 1..50
  └── needle = q.lower() if q else None
  └── predicate(row):
        if format and row['format'] != format: return False
        if source and row['source'] != source: return False
        if topic and topic not in row.get('topics', []): return False
        if needle:
          haystack = (row.get('title','') + ' ' + row.get('description','')).lower()
          if needle not in haystack: return False
        return True
  └── rows, next_cursor = library_repo.query_page(
            limit=limit, cursor=cursor, predicate=predicate)
      # query_page: GSI query on COMMUNITY partition, ScanIndexForward=False (newest first)
      # predicate applied in-memory as rows come back
  └── for each row:
        if row['format'] != 'Link' and row.get('s3Key') and row['scanState'] == 'Clean':
          row['downloadUrl'] = storage.presign_get(row['s3Key'], expires_in=DOWNLOAD_URL_SECONDS)
  └── return {items: [resource_public(r) for r in rows], count: len(rows),
               cursor: next_cursor}
```

---

## Tags Autocomplete Flow

```
GET /library/tags?prefix=ser
  └── authZ: Administrator → 403
  └── prefix = (query_param or '').strip().lower()
  └── tag_set = library_repo.get_all_tags()   # single GetItem on TAGS#ALL
  └── if prefix:
        matches = [t for t in tag_set if t.startswith(prefix)]
      else:
        matches = list(tag_set)[:100]          # cap at 100 when no prefix
  └── return {'tags': sorted(matches)}
```

---

## Curation Flows

### Edit resource
```
PUT /library/{id}
  └── authZ: CL or UGL only
  └── existing = library_repo.get_resource(id)
  └── if not existing: 404
  └── validate editable fields (title, description, format, topics, url)
  └── new_topics = [t.strip().lower() for t in body.get('topics', existing['topics'])]
  └── updated = {**existing,
          title:       body.get('title', existing['title']),
          description: body.get('description', existing['description']),
          format:      body.get('format', existing['format']),
          topics:      list(set(new_topics)),
          url:         body.get('url', existing['url']),
          updatedAt:   now_iso(),
      }
  └── library_repo.put_resource(updated)
  └── library_repo.add_tags(updated['topics'])   # add any new tags to TAGS#ALL
  └── return resource_public(updated)
```

### Delete resource
```
DELETE /library/{id}
  └── authZ: CL or UGL only
  └── existing = library_repo.get_resource(id)
  └── if not existing: 404
  └── library_repo.delete_resource(id)
  └── # S3 object is NOT deleted (BR-LIB-C3)
  └── # TAGS#ALL is NOT immediately updated (lazy — BR-LIB-T4)
  └── return 204
```

---

## Serialization — `resource_public(resource, download_url=None)`

```python
def resource_public(resource: dict, download_url: str | None = None) -> dict:
    out = {
        'id':              resource['id'],
        'title':           resource['title'],
        'description':     resource['description'],
        'format':          resource['format'],
        'topics':          resource.get('topics', []),
        'source':          resource['source'],
        'submittedBy':     resource['submittedBy'],
        'submittedByName': resource.get('submittedByName'),
        'addedAt':         resource['addedAt'],
    }
    # Source-specific attribution fields
    if resource['source'] == 'event-material':
        out['eventId']    = resource.get('eventId')
        out['eventTitle'] = resource.get('eventTitle')
    # Download or open-link
    if download_url:
        out['downloadUrl'] = download_url
    elif resource.get('url'):
        out['url'] = resource['url']
    # Scan state (omit for links — always clean)
    if resource['format'] != 'Link':
        out['scanState'] = resource.get('scanState', 'PendingScan')
    return out
```

---

## Module Structure (new files)

```
services/events/src/
  library_service.py       # LibraryService class — all three paths + search + curation
  library_repository.py    # LibraryRepository — DynamoDB access for library table
  library_consumers.py     # ContributionApprovedConsumer (Path 2)

services/events/src/app.py
  # New routes added:
  # GET  /library
  # GET  /library/tags
  # POST /library
  # PUT  /library/{id}
  # DELETE /library/{id}

services/events/src/material_service.py
  # remove() extended: auto-delete Library resource on material delete (BR-LIB-P5)

services/events/src/event_service.py
  # complete() extended: enforce description mandatory + trigger Path 1 promotion

services/events/src/consumers.py
  # MalwareScanConsumer.handle() extended: trigger Path 1 promotion for completed events
```

---

## Removed from existing implementation

| What | Where | Why |
|---|---|---|
| `content_library()` method | `material_service.py` | Replaced by `library_service.py` |
| `query_content_page()` | `repository.py` | Replaced by `library_repository.py` |
| `_apply_content_index()` | `repository.py` | GSI3 machinery removed |
| `refresh_content_index()` | `repository.py` | GSI3 machinery removed |
| `gsi3pk`, `gsi3sk` attributes | `repository.py` | GSI3 removed from Events table |
| `contentLibrary` operation | `app.py` | Route removed |
| `ContentLibraryTab` component | `EventsPage.tsx` | Replaced by `ContentLibraryPage.tsx` |
