# Personas — AWS Community Portal

Per the approved plan (Q4 = A), the persona catalog covers the four mutually-exclusive portal roles. Roles are **independent — no inheritance** (a Community Leader does not inherit Member permissions). A user holds exactly one role at a time. Authoritative permissions live in `requirements/Role-and-Permission-Mapping.md`.

> Note: Several stories are triggered by the **System** (scheduled jobs: Cognito sync, certification expiry, tier calculation, AI insights) or involve an **external upload-link recipient** (unauthenticated). Per Q4 = A these are not modeled as separate personas; they are captured as system/actor context within the relevant stories.

---

## P1 — Administrator
- **Who**: Platform operator. May be the built-in **local** Administrator account (portal-managed credentials, not in Cognito) and/or a Cognito user promoted to Administrator.
- **Goals**: Keep the platform configured and secure; manage users (roles, group assignment), system settings, integrations (MS Teams, Bedrock model, SES, What's New feed), email templates, and audit configuration.
- **Does NOT**: Participate in community activities — no joining groups, events, forums, certifications, contributions, analytics dashboards, leaderboards, announcements, or member home. Receives only transactional account/security emails.
- **Key concerns**: Bootstrap from day one; onboard users (self-registration allow-list, bulk import); cut off access quickly (disable user, OTP interval); compliance/audit.

## P2 — Community Leader
- **Who**: Owns community-wide activities. Multiple users may hold this role simultaneously with identical community-wide permissions.
- **Goals**: Create/manage user groups, assign User Group Leaders, run events (community-wide and any group), define the scoring framework and certifications, moderate all forums, post announcements, and view community-wide + group analytics (incl. AI reporting).
- **Does NOT**: Join groups (cross-group access without membership); earn points (earning is a Member activity).
- **Key concerns**: Community health/engagement, fair recognition, coverage when a leader is unavailable, no group left leaderless.

## P3 — User Group Leader (UGL)
- **Who**: Leads exactly **one** user group; scoped strictly to that group. A group may have multiple UGLs; a person leads at most one group.
- **Goals**: Manage the led group's forums (structure + moderation), events, certification/contribution reviews, join-request approvals, point adjustments, group announcements, and group analytics.
- **Does NOT**: Edit group configuration (name/description/leaders/approval flag — Community Leader only); belong to or participate in any other group; earn points or submit certifications/contributions anywhere.
- **Key concerns**: Efficient review queues, group engagement, timely join-request handling.

## P4 — Member
- **Who**: Standard community participant. Default role for all self-registered / imported / synced users.
- **Goals**: Join/leave groups, browse/RSVP events, participate in forums, submit certifications and evidence-based contributions, track per-group points/tiers, view leaderboards, manage profile and notification preferences, use the help assistant and What's New feed.
- **Does NOT**: Manage groups, events, framework, or moderate (beyond own content and accepted-answer on own posts).
- **Key concerns**: Recognition (points/tiers/badges per group), discovering events/content, getting timely notifications in their own time zone.

---

## Persona → Module participation (high level)

| Module | Administrator | Community Leader | User Group Leader | Member |
|---|:--:|:--:|:--:|:--:|
| 1 Auth & Authz | ✅ (manage) | ✅ (groups) | ✅ (led group) | ✅ (join/participate) |
| 2 Events | ⚙️ integrations only | ✅ | ✅ (led group) | ✅ |
| 3 Member Mgmt | ✅ (identity list) | ✅ | ✅ (group) | ✅ |
| 4 Forums | ❌ | ✅ (all) | ✅ (led group) | ✅ |
| 5 Certifications | ❌ | ✅ | ✅ (verify) | ✅ (claim) |
| 6 Contributions | ❌ | ✅ (framework) | ✅ (review) | ✅ (earn/submit) |
| 7 Analytics | ❌ | ✅ | ✅ (group) | ❌ |
| 8 Cross-cutting | ✅ (settings) | ✅ | ✅ | ✅ |
| 9 Help Assistant | ✅ | ✅ | ✅ | ✅ |
| 10 Announcements | ❌ | ✅ | ✅ (led group) | ✅ (view) |
| 11 What's New | ⚙️ configure only | ✅ | ✅ | ✅ |

⚙️ = configuration only, no participation.
