# NFR Design Plan — Unit 9: Announcements

**Stage**: CONSTRUCTION → NFR Design · **Unit**: Announcements
Inputs: approved `functional-design/` + `nfr-requirements/` artifacts. Realizes the NFR requirements as concrete patterns + logical components. No new external decisions were required — the NFR Requirements answers (Q1–Q6=A) already fixed the patterns (30s active-set cache, nh3 sanitize-on-write, DOMPurify client layer, 1.5s fail-closed directory timeout, idempotent consumers, PITR+TTL, no fan-out). Following the Events/Member-Profiles precedent, this stage proceeds with **no blocking questions**; judgement calls are flagged for gate review.

## Steps
- [x] 1. Analyze NFR requirements
- [x] 2. Create this plan
- [x] 3. Evaluate all question categories (resolved from approved artifacts — see below; no open questions)
- [x] 4. Store plan
- [x] 5. Collect/analyze answers (n/a — nothing open; judgement calls flagged for the gate)
- [x] 6. Generate artifacts (`nfr-design-patterns.md`, `logical-components.md`)
- [x] 7. Present completion message
- [x] 8. Await explicit approval (approved 2026-08-07)
- [x] 9. Record approval + update aidlc-state.md

## Question-category evaluation (all resolved from approved artifacts)
| Category | Resolution |
|---|---|
| **Resilience patterns** | Idempotent event consumers (idempotency table on envelope id, NFR-AN-REL-3); create-time `DirectoryClient` 1.5s **fail-closed** timeout (NFR-AN-REL-1); no synchronous dependency on Notifications/EventBridge for the panel (NFR-AN-REL-2); panel never 5xx on downstream failure (NFR-AN-REL-4). No circuit breaker needed (single optional lookup, not a fan-out). |
| **Scalability patterns** | **Fan-out-on-read** — post/edit/delete are O(1) writes at any audience size (BR-7); on-demand DynamoDB + Lambda concurrency; TTL keeps the table bounded (NFR-AN-DATA-3). No write amplification anywhere. |
| **Performance patterns** | 30s **warm-container cache** of the small active-announcement set; in-memory filter by claims+expiry+`groupHidden`; cache miss = one bounded query (NFR-AN-PERF-1). No provisioned concurrency (non-interactive-critical). |
| **Security patterns** | `nh3` **sanitize-on-write** (NFR-AN-SEC-1) + client **DOMPurify** (NFR-AN-SEC-2); fail-closed authz from the matrix incl. Administrator-denied-on-reads + author-only-edit + CL-moderation-delete + IDOR guard (NFR-AN-SEC-3/4); input validation + expiry clamp (NFR-AN-SEC-5); least-privilege IAM (NFR-AN-SEC-6); shared API GW throttling (NFR-AN-SEC-8). |
| **Logical components** | Router + validation + authz conventions (copied per-service, FQ1); `AnnouncementService`; `PanelQuery`; `Sanitizer` (nh3); `ActiveSetCache`; `DirectoryClient`; `event_consumer` (EventCreated + GroupSoftDeleted/GroupRestored); `EventPublisher` (AnnouncementPublished); `Repository` (single table + idempotency); `health`. No SQS/Step Functions/ElastiCache/WAF. |

## Judgement calls flagged for gate review
- **J1** — The panel's `ActiveSetCache` is **per-warm-container** (like Settings), so a just-posted/edited/deleted announcement can take up to the 30s TTL to appear/disappear in another container's cached panel. Acceptable for a broadcast panel (eventual within 30s); delete-for-everyone is still *authoritative* at the data layer immediately (the item is gone), the cache just lags reads. If stricter immediacy is wanted, drop the cache (NFR-AN-PERF Q2 option B) — flagged, not assumed.
- **J2** — `EventCreated` auto-post reuses the same create path incl. the `DirectoryClient` name lookup; for a burst of event creations this is one lookup each (memoisation not needed at announcement volumes, unlike Events' 104-occurrence designation case). Flagged in case a batch scenario is expected.
- **J3** — The active-set cache is keyed to hold **all** active announcements (community + all groups) per container, filtered per-caller in memory. At the expected scale (tens active) this is trivial; if a deployment ever had thousands of concurrently-active announcements the cache would be scoped by audience instead. Flagged as a scale assumption.
