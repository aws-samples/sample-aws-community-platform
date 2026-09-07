# Integration Test Instructions — Content Library Rework

## Overview

This rework spans three services (Events, Contributions, Frontend) and three infrastructure stacks. Integration tests validate the cross-service flows after deployment to dev.

---

## Scenario 1 — Path 1: Event Completion Auto-Promotes Materials

**Tests**: US-2.22, BR-LIB-P1/P2

**Setup**: Deploy Events service + library table

```bash
# 1. Create a past-dated event with description via API
POST /events
{
  "title": "Serverless Meetup",
  "description": "A recap of serverless best practices",
  "type": "Meetup", "deliveryMode": "Virtual",
  "startsAt": "<yesterday ISO>", "durationMinutes": 60,
  "location": "https://meet.example.com"
}

# 2. Add a material (link — no scan needed)
POST /events/{id}/materials
{ "name": "Slides", "kind": "link", "link": "https://slides.example.com" }

# 3. Complete the event
POST /events/{id}/complete

# 4. Search the Library — should return the material
GET /library?q=serverless

# Expected: 200 with 1 result, source=event-material
```

**Negative case — missing description blocks completion**:
```bash
POST /events/{id}/complete   # event has no description
# Expected: 400 { "code": "VALIDATION_ERROR", "message": "...description..." }
```

---

## Scenario 2 — Path 2: Contribution Approval Library Opt-In

**Tests**: US-2.24, BR-LIB-P7

**Setup**: Deploy Events + Contributions services; EventBridge rule active

```bash
# 1. Member submits a contribution
POST /contributions/submissions
{ "activity": "Blog Post", "groupId": "g-1", "description": "My AWS blog" }

# 2. CL/UGL approves with Library opt-in
POST /contributions/submissions/{id}/decide
{
  "decision": "approve",
  "addToLibrary": true,
  "libraryTitle": "My AWS Blog",
  "libraryDescription": "A post about serverless patterns",
  "libraryFormat": "Link",
  "libraryTopics": ["serverless"],
  "libraryUrl": "https://myblog.dev/aws-post"
}

# 3. Wait ~5s for EventBridge delivery, then search
GET /library?q=serverless&source=member-contribution

# Expected: 200 with 1 result, source=member-contribution, submittedByName=member name
```

**Verify EventBridge**:
```bash
# ContributionApproved event should appear in EventBridge CloudWatch logs
# Library consumer should appear in events-dev Lambda logs
aws logs filter-log-events --log-group-name /aws/lambda/events-dev \
  --filter-pattern "ContributionApproved"
```

---

## Scenario 3 — Path 3: Curator Direct Add

**Tests**: US-2.23

```bash
# CL adds a resource directly
POST /library
{
  "title": "AWS Well-Architected Framework Guide",
  "description": "Official AWS guide to building reliable, secure workloads",
  "format": "Link",
  "topics": ["architecture", "best-practices"],
  "url": "https://aws.amazon.com/architecture/well-architected/"
}

# Expected: 201 with resource id, source=curator-direct

# Search for it
GET /library?q=well-architected

# Expected: 200 with 1 result
```

---

## Scenario 4 — Auto-Removal on Material Delete

**Tests**: US-2.22, BR-LIB-P5

```bash
# 1. Complete event (auto-promotes materials — Scenario 1 setup)
# 2. Note the resource appears in Library
GET /library?q=serverless   # returns lib-xxx

# 3. Delete the source material from the event
DELETE /events/{eventId}/materials/{materialId}

# 4. Search Library again — resource should be gone
GET /library?q=serverless   # Expected: count=0
```

---

## Scenario 5 — Topics Autocomplete

**Tests**: US-2.26

```bash
# After resources with topics have been added:
GET /library/tags?prefix=ser

# Expected: { "tags": ["serverless"] }  (or other matching tags)
```

---

## Scenario 6 — Administrator Excluded

```bash
# Using Administrator JWT
GET /library?q=test

# Expected: 403 { "code": "FORBIDDEN" }
```

---

## Contract Tests

Run the existing contract test gate after deployment:

```bash
make contract-tests SVC=events
# Expected: all operations pass including new library routes

make contract-tests SVC=contributions-scoring
# Expected: all operations pass including ContributionApproved schema
```

---

## Deployment Verification Checklist

- [ ] `library-dev` table exists and is ACTIVE (`aws dynamodb describe-table --table-name library-dev`)
- [ ] `events-dev` table has GSI3 removed (verify via DescribeTable — only GSI1, GSI2, GSI4 present)
- [ ] `ContributionApprovedRule` EventBridge rule is ENABLED
- [ ] GuardDuty and S3 Object rules include `library/` prefix
- [ ] `/library` routes respond via API Gateway (401 without token, 200/4xx with token)
- [ ] Frontend `/content-library` page loads without error
- [ ] `📚 Content Library` nav item visible for Member, UGL, CL; absent for Administrator
