# Unit of Work — Story Map (144 stories → units)

Companion to `unit-of-work.md` and `unit-of-work-dependency.md`. Every active story from `stories.md` is assigned to exactly one **owning unit**; cross-unit participants are noted. Module→unit mapping is 1:1 (stories.md was organized by module = bounded context).

## Coverage summary
| Unit | Owning module(s) | Stories | Count |
|---|---|---|---|
| 2 Identity & Access | M1 Auth & Authorization | US-1.2–1.21, 1.26–1.28, 1.30–1.34, **US-3.8, 3.9** | 30 |
| 3 Member Profiles | M3 Member Profiles | US-3.1–3.7, 3.10 (US-3.8/3.9 reassigned to Unit 2, 2026-08-02) | 8 |
| 4 Events | M2 Events & Meetups | US-2.1–2.21 | 21 |
| 5 Forums | M4 Forums | US-4.1–4.18 | 18 |
| 6 Certifications | M5 Certifications | US-5.1–5.10 | 10 |
| 7 Contributions & Scoring | M6 Contributions | US-6.1–6.18 | 18 |
| 8 Analytics | M7 Analytics | US-7.1–7.11 | 11 |
| 10 Notifications | M8 (notifications) | US-8.2, 8.4, 8.5, 8.6, 8.7, 8.15 | 6 |
| 11 Settings | M8 (settings) + M11 config | US-8.3, 8.13, 8.14 (+US-11.1, 11.6) | 3 (+2) |
| 12 Help Assistant | M9 Help | US-9.1–9.4 | 4 |
| 9 Announcements | M10 Announcements | US-10.1–10.5 | 5 |
| 15 Frontend SPA | M8 (frontend) + M11 UI | US-8.1, 8.8, 8.9 (+US-11.2–11.5, 11.7) | 3 (+5) |
| **Total** | | | **144** |

Units **1 (Platform & Delivery)**, **13 (Search)**, **14 (AI Gateway)** own no exclusive stories — they are the delivery substrate and shared enablers. Search enables US-3.5/US-4.13; AI Gateway enables US-4.5, US-7.7/7.8, US-9.x, and embeddings for US-3.5/4.13.

---

## Unit 2 — Identity & Access (28)
| Story | Title | Cross-unit participants |
|---|---|---|
| US-1.2 | Cognito login | Cognito (U1), SES (U10) |
| US-1.3 | Logout | — |
| US-1.4 | Sync users from Cognito | Cognito (U1) |
| US-1.5 | Assign role | 7, 6 (data handling) |
| US-1.6 | User deactivation | 10, 4, 7, 6 |
| US-1.7 | Create group | — |
| US-1.8 | Join group | — |
| US-1.9 | Leave group | 6, 7 |
| US-1.10 | Assign UGL | — |
| US-1.11 | Delete group | 4, 5, 7, 13, 10 |
| US-1.12 | RBAC enforcement | all (authZ pattern, U1 authorizer) |
| US-1.13 | Access audit log | U1 (CloudWatch) |
| US-1.14 | Toggle audit | 11 |
| US-1.15 | JIT provisioning | Cognito (U1) |
| US-1.16 | Group directory | — |
| US-1.17 | Remove member | 10 |
| US-1.18 | Edit group | — |
| US-1.19 | Reactivation | — |
| US-1.20 | Password reset (Cognito) | Cognito (U1) |
| US-1.21 | Review join requests | 10 |
| US-1.26 | Edit user (role & group) | 7, 6, 4 |
| US-1.27 | Built-in local admin | Secrets Manager |
| US-1.28 | Local admin reset | SES (U10), Secrets Manager |
| US-1.30 | Self-registration | Cognito (U1), 11 |
| US-1.31 | Bulk import | Cognito (U1) |
| US-1.32 | Periodic OTP re-verification | Cognito (U1), SES (U10) |
| US-1.33 | Disable/enable user | Cognito (U1), 10 |
| US-1.34 | Membership-event history | 8 |
| US-3.8 | Admin member list *(reassigned from Unit 3, 2026-08-02)* | — |
| US-3.9 | Export member list *(reassigned from Unit 3, 2026-08-02)* | S3 |

## Unit 3 — Member Profiles & Directory (8)
| Story | Title | Cross-unit |
|---|---|---|
| US-3.1 | View my profile | 7 (rollup), 4/5/6 (basic activity counts) |
| US-3.2 | Edit my profile | 13 (index) |
| US-3.3 | View other profile | 6, 7, 4/5/6 (basic activity counts) |
| US-3.4 | Browse directory | — |
| US-3.5 | Search members | 13 Search, 14 AI |
| US-3.6 | Onboarding | 2 |
| US-3.7 | Welcome notification | 10 |
| US-3.10 | Activity summary (detailed, leader-only) | 4, 5, 7, 6 |

*US-3.8/3.9 reassigned to Unit 2 Identity & Access (2026-08-02): Identity's `GET /users` already serves these fields via GSI2; the shipped frontend and mockup already call it.*

## Unit 4 — Events (21)
| Story | Title | Cross-unit |
|---|---|---|
| US-2.1 | Create event | 2, 9 |
| ~~US-2.2~~ | ~~Set reminder~~ — REMOVED 2026-08-27 | — |
| US-2.3 | Recurring event | — |
| US-2.4 | Edit event | 10 |
| US-2.5 | Cancel event | 10 |
| US-2.6 | RSVP | 10 |
| US-2.7 | RSVP list | S3 |
| US-2.8 | Calendar invite (.ics) | 10 |
| US-2.9 | Calendar view | — |
| ~~US-2.10~~ | ~~Receive reminder~~ — REMOVED 2026-08-27 | — |
| US-2.11 | Teams config | 11 |
| US-2.12 | Teams attendance | MS Teams, 7 |
| US-2.13 | Browse events | — |
| US-2.14 | Event detail | — |
| US-2.15 | Materials | S3, 10 |
| US-2.16 | Manual attendance | 7 |
| US-2.17 | Configure event points | 7 |
| US-2.18 | Presenter/organizer points | 7 |
| US-2.19 | Mark completed | 7 |
| US-2.20 | Content Library | S3 |
| US-2.21 | Upload link | S3 |

## Unit 5 — Forums (18)
| Story | Title | Cross-unit |
|---|---|---|
| US-4.1 | Create forum | — |
| US-4.2 | Create channel | — |
| US-4.3 | Edit forum/channel | — |
| US-4.4 | Delete forum/channel | 13 Search |
| US-4.5 | Create post | 14 AI (dup), 13, 7 |
| US-4.6 | Reply | 7, 10 |
| US-4.7 | Edit post/reply | — |
| US-4.8 | Delete post/reply | 13 |
| US-4.9 | @mention | 2 (scope), 10 |
| US-4.10 | Mention notification | 10 |
| US-4.11 | React | — |
| US-4.12 | Browse forums | — |
| US-4.13 | Search posts | 13 Search, 14 AI |
| US-4.14 | Pin | — |
| US-4.15 | Accepted answer | — |
| US-4.16 | Follow | 10 |
| US-4.17 | Report/moderation | — |
| US-4.18 | Channel post list | — |

## Unit 6 — Certifications (10)
| Story | Title | Cross-unit |
|---|---|---|
| US-5.1 | Create cert (+expiry) | — |
| US-5.2 | Edit cert | — |
| US-5.3 | Deactivate cert | — |
| US-5.4 | Submit claim | — |
| US-5.5 | View submissions | — |
| US-5.6 | Verify claim | 7, 10 |
| US-5.7 | Pending verifications | — |
| US-5.8 | Revoke | 10 |
| US-5.9 | Display badges | 3 |
| US-5.10 | Catalog | — |

## Unit 7 — Contributions & Scoring (18)
| Story | Title | Cross-unit |
|---|---|---|
| US-6.1 | Configure framework | — |
| US-6.2 | View framework | — |
| US-6.3 | Auto-award attendance | 4 |
| US-6.4 | Auto-award forum | 5 |
| US-6.5 | Auto-award cert | 6 |
| US-6.6 | Submit evidence | — |
| US-6.7 | View submissions | — |
| US-6.8 | Approve/reject | 10 |
| US-6.9 | Pending submissions | — |
| US-6.10 | Points & tier | — |
| US-6.11 | Tier standings | — |
| US-6.12 | Tier badge (runtime) | 10 |
| US-6.13 | Group summary | — |
| US-6.14 | Community summary | S3 |
| US-6.15 | Adjust points | 10 |
| US-6.16 | Leaderboard | — |
| US-6.17 | Auto-award delivery | 4 |
| US-6.18 | Auto-award organizing | 4 |

## Unit 8 — Analytics (11)
| Story | Title | Cross-unit |
|---|---|---|
| US-7.1 | Community dashboard | 9 |
| US-7.2 | Group dashboard | 2 (history) |
| US-7.3 | Membership growth | 2 (US-1.34) |
| US-7.4 | Points chart | 7 |
| US-7.5 | Attendance chart | 4 |
| US-7.6 | Cert progress | 6 |
| US-7.7 | AI reporting | 14 AI |
| US-7.8 | AI insights | 14 AI |
| US-7.9 | Export contributions | 7, S3 |
| US-7.10 | Export members | 3, S3 |
| US-7.11 | Export events | 4, S3 |

## Unit 9 — Announcements (5)
| Story | Title | Cross-unit |
|---|---|---|
| US-10.1 | Create | 10 |
| US-10.2 | Target | — |
| US-10.3 | Manage | — |
| US-10.4 | View panel | 8 / Home |
| US-10.5 | Dismiss | — |

## Unit 10 — Notifications (6)
| Story | Title | Cross-unit |
|---|---|---|
| US-8.2 | Email notifications | SES, publishers (2,4,5,6,7,9) |
| US-8.4 | Email sender | SES, 11 |
| US-8.5 | Email templates | 11 |
| US-8.6 | In-portal notifications | publishers |
| US-8.7 | Notification prefs | — |
| US-8.15 | Recipient matrix | all publishers |

## Unit 11 — Settings (3 + 2 What's New config)
| Story | Title | Cross-unit |
|---|---|---|
| US-8.3 | Admin settings | consumers (2,4,5,10,14,15) |
| US-8.13 | File sharing | S3 |
| US-8.14 | Time zone | 2 |
| US-11.1 | Configure What's New feed | 15 (frontend consumes) |
| US-11.6 | What's New disabled behavior | 15 |

## Unit 12 — Help Assistant (4)
| Story | Title | Cross-unit |
|---|---|---|
| US-9.1 | Access assistant | 14 AI |
| US-9.2 | Ask functionality | 14 AI |
| US-9.3 | Scope limitation | — |
| US-9.4 | Knowledge base | 14 AI, (13 Search) |

## Unit 15 — Frontend SPA (3 + 5 What's New UI)
| Story | Title | Cross-unit |
|---|---|---|
| US-8.1 | Home dashboard | 9, 4, 5, 7 |
| US-8.8 | Responsive web | — |
| US-8.9 | Configurable data tables | — |
| US-11.2 | What's New nav item | 11 (config) |
| US-11.3 | What's New detail page | — |
| US-11.4 | What's New search/filter | — |
| US-11.5 | What's New item details | — |
| US-11.7 | Client-side feed load | external RSS |

---

## Verification
- **Total assigned**: 28+10+21+18+10+18+11+6+3+4+5+3 = 137 exclusively-owned + 7 What's New (US-11.1,11.6 → Settings; US-11.2–11.5,11.7 → Frontend) = **144**. ✅
- **Tombstoned/removed** (excluded, not implemented): US-1.1, US-1.22–1.24, US-1.29, US-1.25 — omitted per `stories.md`.
- **100% of active stories mapped**; no story unassigned; no story in two owning units (cross-unit noted as participants only).
