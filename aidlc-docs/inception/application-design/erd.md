# Entity-Relationship Diagrams (ERD) — AWS Community Portal

Data model as Mermaid `erDiagram`, **grouped by service**. Because the architecture is **microservices with table-per-service** (Q5=B), each service owns its own entities/tables — there are **no cross-service foreign keys**. Attributes that reference another service (e.g., `member_id`, `group_id`) are **soft references** (marked `FK` with a `"ref <Service>"` comment) resolved via APIs/events, not database joins.

Notes:
- This is a logical model for design; concrete DynamoDB key/GSI design (single-table-per-service, partition/sort keys) is done in per-unit Functional/Infrastructure Design.
- Derived/read-only stores (Analytics projections, Search vectors) are noted but not modeled as relational tables.
- Cardinality: `||--o{` = one-to-zero-or-many, `||--||` = one-to-one, `}o--o{` = many-to-many.

---

## 1. Identity & Access Service
Owns users (portal records projected from Cognito), groups, memberships, membership history, join requests, and leader assignments. Local-admin credentials live in Secrets Manager; audit logs in CloudWatch (not modeled).

```mermaid
erDiagram
    USER ||--o{ GROUP_MEMBERSHIP : has
    USER_GROUP ||--o{ GROUP_MEMBERSHIP : contains
    USER ||--o{ JOIN_REQUEST : submits
    USER_GROUP ||--o{ JOIN_REQUEST : receives
    USER ||--o{ GROUP_LEADER : leads
    USER_GROUP ||--o{ GROUP_LEADER : led_by
    USER ||--o{ MEMBERSHIP_EVENT : generates
    USER_GROUP ||--o{ MEMBERSHIP_EVENT : records

    USER {
        string user_id PK "Cognito sub"
        string email UK
        string first_name
        string last_name
        string role
        string account_type
        string status
        string city
        string country
        string professional_role
        bool aws_project
        string time_zone
    }
    USER_GROUP {
        string group_id PK
        string name
        string description
        bool approval_required
        string status
        datetime created_at
        datetime soft_deleted_at
    }
    GROUP_MEMBERSHIP {
        string membership_id PK
        string user_id FK
        string group_id FK
        datetime joined_at
        bool active
    }
    MEMBERSHIP_EVENT {
        string event_id PK
        string user_id FK
        string group_id FK
        string type
        datetime occurred_at
    }
    JOIN_REQUEST {
        string request_id PK
        string user_id FK
        string group_id FK
        string message
        string status
        datetime requested_at
    }
    GROUP_LEADER {
        string group_id FK
        string user_id FK
        datetime assigned_at
    }
```

---

## 2. Member Profiles & Directory Service
Owns the member profile record (identity fields are Cognito-owned, projected). Semantic-search vectors live in OpenSearch (not relational).

```mermaid
erDiagram
    MEMBER_PROFILE {
        string user_id PK "ref Identity"
        string display_name
        string bio
        string avatar_url
        string skills
        string city
        string country
        string professional_role
        bool aws_project
        string time_zone
        datetime updated_at
    }
```

---

## 3. Events Service
Owns events (and recurrence series), RSVPs, materials, presenter/organizer designations, attendance, and event-scoped upload links.

```mermaid
erDiagram
    EVENT_SERIES ||--o{ EVENT : expands_to
    EVENT ||--o{ RSVP : has
    EVENT ||--o{ EVENT_MATERIAL : has
    EVENT ||--o{ EVENT_DESIGNATION : has
    EVENT ||--o{ ATTENDANCE : records
    EVENT ||--o{ UPLOAD_LINK : has

    EVENT {
        string event_id PK
        string title
        string description
        string type
        string delivery_mode
        string scope
        string group_id FK "ref Identity, nullable"
        string creator_id FK "ref Identity"
        string series_id FK "nullable"
        datetime start_at
        int duration_min
        string location
        string status
    }
    EVENT_SERIES {
        string series_id PK
        string frequency
        date start_date
        date end_date
    }
    RSVP {
        string rsvp_id PK
        string event_id FK
        string member_id FK "ref Identity"
        string response
        datetime created_at
    }
    EVENT_MATERIAL {
        string material_id PK
        string event_id FK
        string name
        string content_type
        int size_bytes
        string s3_key_or_url
    }
    EVENT_DESIGNATION {
        string designation_id PK
        string event_id FK
        string member_id FK "ref Identity"
        string designation_role "presenter or organizer"
    }
    ATTENDANCE {
        string attendance_id PK
        string event_id FK
        string member_id FK "ref Identity"
        string source
        datetime confirmed_at
    }
    UPLOAD_LINK {
        string link_id PK
        string event_id FK
        string token UK
        string s3_prefix
        datetime expires_at
        int max_size_bytes
        string created_by FK "ref Identity"
        bool revoked
    }
```

---

## 4. Forums Service
Owns forums, channels, posts, replies, reactions, follows, and reports. Post/reply embeddings live in OpenSearch (not relational).

```mermaid
erDiagram
    FORUM ||--o{ CHANNEL : contains
    CHANNEL ||--o{ POST : contains
    POST ||--o{ REPLY : has
    POST ||--o{ REACTION : receives
    POST ||--o{ REPORT : flagged_by
    POST ||--o{ FOLLOW : followed_by

    FORUM {
        string forum_id PK
        string group_id FK "ref Identity"
        string name
        string description
    }
    CHANNEL {
        string channel_id PK
        string forum_id FK
        string name
        string description
    }
    POST {
        string post_id PK
        string channel_id FK
        string author_id FK "ref Identity"
        string title
        string body
        bool pinned
        string accepted_reply_id FK "nullable"
        string status
        datetime created_at
    }
    REPLY {
        string reply_id PK
        string post_id FK
        string author_id FK "ref Identity"
        string body
        datetime created_at
    }
    REACTION {
        string reaction_id PK
        string target_type
        string target_id
        string member_id FK "ref Identity"
        string kind
    }
    FOLLOW {
        string follow_id PK
        string member_id FK "ref Identity"
        string target_type
        string target_id
    }
    REPORT {
        string report_id PK
        string target_type
        string target_id
        string reporter_id FK "ref Identity"
        string reason
        string status
        datetime created_at
    }
```

---

## 5. Certifications Service
Owns certification definitions (per-cert points), member claims, and earned badges.

```mermaid
erDiagram
    CERTIFICATION ||--o{ CLAIM : claimed_via
    CERTIFICATION ||--o{ MEMBER_BADGE : granted_as

    CERTIFICATION {
        string cert_id PK
        string name
        string description
        string category
        string badge_image
        int points
        int expiry_period_months
        string status
    }
    CLAIM {
        string claim_id PK
        string cert_id FK
        string member_id FK "ref Identity"
        string credited_group_id FK "ref Identity"
        string evidence
        string notes
        string status
        datetime submitted_at
        datetime decided_at
        string decided_by FK "ref Identity, nullable"
    }
    MEMBER_BADGE {
        string badge_id PK
        string cert_id FK
        string member_id FK "ref Identity"
        datetime earned_at
        datetime expires_at
    }
```

---

## 6. Contributions & Scoring Service
System of record for the **append-only point ledger**. Framework config (activity types, event point values, tier thresholds), evidence submissions, and derived rollups. Balances/tiers are computed at runtime from the ledger (rollups are a derived cache).

```mermaid
erDiagram
    ACTIVITY_TYPE ||--o{ SUBMISSION : submitted_as
    SUBMISSION ||--o| POINT_LEDGER_ENTRY : yields_on_approval
    ACTIVITY_TYPE ||--o{ POINT_LEDGER_ENTRY : categorizes

    ACTIVITY_TYPE {
        string activity_id PK
        string name
        string description
        string pillar
        int points
        bool evidence_required
        bool active
    }
    EVENT_POINT_VALUE {
        string event_type PK
        int attendance_points
        int delivery_points
    }
    TIER_THRESHOLD {
        string tier_name PK
        int min_points
        string recognition_label
    }
    SUBMISSION {
        string submission_id PK
        string member_id FK "ref Identity"
        string group_id FK "ref Identity"
        string activity_id FK
        string description
        string evidence
        string status
        datetime submitted_at
        string decided_by FK "ref Identity, nullable"
    }
    POINT_LEDGER_ENTRY {
        string entry_id PK
        string member_id FK "ref Identity"
        string group_id FK "ref Identity"
        string activity_type
        string pillar
        int points
        string source
        date earned_date
        string quarter
        datetime created_at
    }
    ROLLUP {
        string member_id FK "ref Identity"
        string group_id FK "ref Identity"
        string quarter
        int total_points
        string tier
    }
```

---

## 7. Analytics Service (read model)
Read-only projections fed from EventBridge + DynamoDB Streams into a separate analytics store (concrete service deferred to Infrastructure Design). Entities below are **derived** projections/caches, not authoritative tables.

```mermaid
erDiagram
    DASHBOARD_METRIC {
        string scope PK "community or group_id"
        string quarter PK
        int members
        int active_members
        int new_members
        int events_held
        int points_distributed
    }
    MEMBERSHIP_TIMESERIES {
        string scope PK
        string month PK
        int member_count
    }
    INSIGHT_CACHE {
        string insight_id PK
        string scope
        string text
        datetime generated_at
    }
```

---

## 8. Announcements Service
Owns announcements and per-member dismissals.

```mermaid
erDiagram
    ANNOUNCEMENT ||--o{ DISMISSAL : dismissed_by

    ANNOUNCEMENT {
        string announcement_id PK
        string author_id FK "ref Identity"
        string title
        string body
        string audience_type
        string target_group_ids "ref Identity, list"
        datetime expiry
        bool email_opt_in
        datetime created_at
    }
    DISMISSAL {
        string dismissal_id PK
        string announcement_id FK
        string member_id FK "ref Identity"
        datetime dismissed_at
    }
```

---

## 9. Notifications Service
Owns in-portal notifications and per-user preferences. Email is sent via SES (not stored).

```mermaid
erDiagram
    IN_PORTAL_NOTIFICATION {
        string notification_id PK
        string recipient_id FK "ref Identity"
        string type
        string body
        bool read
        datetime created_at
    }
    NOTIFICATION_PREFERENCE {
        string member_id PK "ref Identity"
        string opted_out_categories "list"
        datetime updated_at
    }
```

---

## 10. Platform / Settings Service
Owns system settings, email templates, and external file-share links.

```mermaid
erDiagram
    SETTING {
        string setting_key PK
        string section
        string value
        datetime updated_at
    }
    EMAIL_TEMPLATE {
        string template_id PK
        string notification_type
        string subject
        string body
    }
    FILE_SHARE_LINK {
        string link_id PK
        string owner_id FK "ref Identity"
        string folder_prefix
        string token UK
        datetime expires_at
        int max_size_bytes
        bool revoked
        datetime created_at
    }
```

---

## 11. Help Assistant Service
**No persistent entities.** Stateless conversational service; chat history is session-only (client-side). Grounding knowledge is derived from portal docs via the AI Gateway (and optionally the Search index) — no owned tables.

## Shared capabilities (non-relational)
- **Search Service** — owns an **Amazon OpenSearch Serverless** vector collection (member and forum embeddings). Not a relational store; documents keyed by `member_id` / `post_id` / `reply_id`.
- **AI Gateway Service** — stateless facade over Amazon Bedrock; no owned data.
- **What's New (Module 11)** — frontend-only; its only persisted config (feed URL + toggle) lives in the **Settings** service (`SETTING`).

---

## Cross-service reference summary
These IDs recur as **soft references** (no cross-DB FK); resolved via APIs/events:
| Reference | Owned by | Used by |
|---|---|---|
| `user_id` / `member_id` | Identity & Access | Members, Events, Forums, Certifications, Contributions, Announcements, Notifications, Settings |
| `group_id` | Identity & Access | Events, Forums, Certifications, Contributions, Announcements |
| `event_id` | Events | Contributions (via events), Content Library |
| `cert_id` | Certifications | Contributions (per-cert points on approval) |
| `post_id` / `reply_id` | Forums | Search (embeddings), Contributions (forum points) |
