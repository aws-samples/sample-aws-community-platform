# Requirements — AWS Community Portal

## 1. Intent Analysis

| Attribute | Assessment |
|---|---|
| **User Request** | "Build the application with the requirements mentioned in requirements folder using AI-DLC" |
| **Request Type** | New Project (greenfield) |
| **Scope Estimate** | System-wide — full multi-module platform |
| **Complexity Estimate** | Complex — 11 functional modules, RBAC, AI/ML, analytics pipeline, ~150+ user stories |
| **Requirements Depth** | Comprehensive |
| **Source of truth** | `requirements/usecases/*.md` (11 modules), `requirements/non-functional-requirements.md`, `requirements/Role-and-Permission-Mapping.md`, and HTML mockups in `requirements/mockup/` |

The `requirements/` folder is an already-detailed, internally reconciled specification (see the 41+ resolved issues in the Role-and-Permission-Mapping). This document does **not** restate every use case; it captures the intent analysis, the build/technical decisions confirmed with the user, a consolidated requirements summary, and the security/resiliency compliance posture. The authoritative functional detail remains in `requirements/usecases/`.

---

## 2. Confirmed Build & Technical Decisions

| Area | Decision | Source |
|---|---|---|
| Build scope | Full end-to-end — all 11 modules | Q4 = A |
| Deployment target | IaC only (not deployed by AI); application code locally testable | Q5 = A |
| IaC tooling | AWS CloudFormation + AWS SAM | Q6 |
| Backend runtime | Polyglot on AWS Lambda — Python, Node.js, or Rust; specific language per service decided at Construction (Code Generation) | Q7 |
| API style | REST via Amazon API Gateway (REST API) | Q9 |
| Frontend | Static SPA hostable on Amazon S3 + CloudFront (React + Vite) | Q8 |
| UI fidelity | Functional guide — reproduce flows/features with a clean component-based design system | Q10 = B |
| DR strategy | Backup & Restore; RTO/RPO in hours | Resiliency Q1 = A |
| Regional topology | Single-region, multi-AZ (serverless multi-AZ by default) | Resiliency Q2 = A |
| Change management | Exempt (documented rationale below) | Resiliency Q3 = C |
| Incident response | Propose lightweight IR + Correction of Errors (COE) process | Resiliency Q4 = B |
| CI/CD | Out of scope for this run — manual `sam deploy`/CloudFormation; pipeline deferred | Resiliency Q5 = C |

**Change-management exemption rationale**: This engagement produces IaC and application code that are not deployed to a production environment by AI-DLC. No live/shared environment is affected during this run, so a formal change-management process is not applicable here. If/when the portal is promoted to a real environment, a change-management process should be adopted at that time.

---

## 3. Functional Requirements (Consolidated by Module)

Authoritative detail lives in the referenced use-case files. Summary of scope:

### Module 1 — Authentication & Authorization (`usecases/01-authentication-and-authorization.md`)
- Amazon Cognito user pool as identity/credential owner; email + password sign-in with periodic email OTP re-verification.
- Built-in **local Administrator** account (portal-managed credentials, independent of Cognito) for bootstrap; portal-local password reset for it; Cognito hosted forgot-password for Cognito users.
- Self-registration (allowed-email-domain allow-list) OR Administrator bulk import (CSV/XLSX → Cognito) — JIT provisioning as Member on first login; portal record reconciled idempotently.
- Four mutually-exclusive roles with **no inheritance**: Administrator, Community Leader, User Group Leader, Member. RBAC enforced server-side per the Role-and-Permission-Mapping.
- User groups: create/edit/soft-delete (2-week purge), join/leave, assign/remove User Group Leaders, per-group join-timestamp history (append-only membership events). Disable/enable users. Access audit logging (toggle, 12-month retention).

### Module 2 — Events & Meetups (`usecases/02-events-and-meetups.md`)
- Community-wide and group-scoped events; create/edit/cancel/complete, recurring events, materials, RSVP, calendar view.
- MS Teams integration (attendance via email matching with review-and-adjust), manual attendance, presenter designation, Content Library search over past-event content, event-scoped external upload links.

### Module 3 — Member Management (`usecases/03-member-management.md`)
- Own profile view/edit; community profile view (with contributions, display-only score rollup) for non-Admin roles; member directory (identity-only for Admin); semantic member search (Bedrock embeddings); admin user list + export (identity/role/group/status only); activity summary for leaders.

### Module 4 — Forums & Discussions (`usecases/04-forums-and-discussions.md`)
- Forums/channels (group-scoped), posts/replies, edit/delete (own; leaders moderate), @mentions (access-restricted), reactions, accepted answers, follow, report/moderation queue, pin, semantic forum search, LLM duplicate detection support. Embeddings removed on deletion.

### Module 5 — Certifications (`usecases/05-certifications.md`)
- Certification/badge definitions (per-cert point value), claim submission, verification routing to credited-group leader, catalog, badges on profile, revoke/deactivate, pending-queue reassignment on leader change.

### Module 6 — Member Contribution Tracking (`usecases/06-member-contribution-tracking.md`)
- **Append-only point ledger** (immutable entries; balances/tiers always derived at runtime, never frozen). Seeded default scoring framework; auto-tracked + evidence-required activities; approve/reject; per-group tiers (Gold/Silver/Bronze/Rising); manual adjustments (may go negative); per-group leaderboards; group/community summaries. Trailing 8-quarter selector.

### Module 7 — Analytics Dashboard (`usecases/07-analytics-dashboard.md`)
- Community-wide and group dashboards, charts, CSV exports, **AI reporting agent** (Bedrock) and AI suggested insights. Fed by DynamoDB Streams → rollups (hot read paths) + separate queryable analytics store (service choice deferred to design).

### Module 8 — Cross-Cutting Concerns (`usecases/08-cross-cutting-concerns.md`)
- Member home dashboard; email (SES) + in-portal notifications and preferences; per-user and system-default time zone; admin settings panel; email sender settings + templates; external file-share links (S3 upload folders).

### Module 9 — Help Assistant (`usecases/09-help-assistant.md`)
- Conversational Bedrock-backed assistant answering questions about portal functionality (all roles).

### Module 10 — Announcements (`usecases/10-announcements.md`)
- Community-wide and group-scoped announcements; create/edit/delete (scoped), moderation delete, audience-scoped viewing, dismiss.

### Module 11 — What's New in AWS Feed (`usecases/11-whats-new-aws-feed.md`)
- Admin-configurable feed URL + enable/disable; community-wide feed view, search/filter by category, expand/open original. Consumes a CORS-enabled feed server (that server is out of scope). Client-side HTML sanitization required for feed `<description>`.

---

## 4. Non-Functional Requirements

Authoritative detail in `requirements/non-functional-requirements.md`. Key targets:

- **Performance**: CRUD/nav < 500ms p95; semantic search < 2s p95; analytics load < 3s p95; help assistant deferred.
- **Scalability**: 10,000–12,000 members; 5,000 concurrent users; serverless auto-scaling (Lambda, DynamoDB on-demand). Analytics via Streams-maintained rollups + separate analytics store.
- **Availability**: No formal SLA for Phase 1; serverless multi-AZ. **DR = Backup & Restore, single-region multi-AZ** (confirmed).
- **Security**: Cognito + RBAC defined; Security Baseline extension **enabled** (see §6). Data encryption, input validation/sanitization (incl. externally-sourced HTML), WAF, rate limiting details in design.
- **Data retention**: Audit logs 12 months; soft-deleted groups 2 weeks; all else indefinite.
- **Browser support**: Latest 2 versions of Chrome/Firefox/Safari/Edge; no IE11.
- **Responsive**: Desktop/tablet/mobile browser; no native app.
- **Language**: English-only (no i18n).
- **AI/ML**: Amazon Bedrock; admin-configurable model ID; duplicate detection fails closed; insights show stale-with-timestamp on failure.
- **Email**: Amazon SES; exponential backoff up to 3 retries / 15 min, then discard.
- **Accessibility**: WCAG out of scope for Phase 1.
- **Concurrency**: Last-write-wins universally (no optimistic locking Phase 1).
- **Monitoring, deployment**: Deferred to design (this run: manual deploy, pipeline deferred).

---

## 5. Constraints, Assumptions & Out-of-Scope

**Constraints**
- AWS serverless only (Lambda/DynamoDB/Cognito/API Gateway/S3/CloudFront/Bedrock/SES).
- Backend is polyglot (Python, Node.js, or Rust per service; language decided at Construction); IaC in CloudFormation + SAM; frontend static SPA (React + Vite).

**Assumptions**
- "Framework hostable on S3" interpreted as a static-built SPA (React + Vite) served via S3 + CloudFront.
- Mockups are behavioral/visual references, not code to ship (fidelity level B).
- No live AWS deployment performed by AI; artifacts are deployable by the user.

**Out of Scope (Phase 1)**
- The external CORS-enabled "What's New" feed server (Module 11 consumes it only).
- SSO/SAML/OIDC federation (removed per resolved issue #19).
- Native mobile app, i18n, WCAG compliance, application-level rate limiting on posts/submissions, active-session force-revocation, member hard-delete.
- CI/CD pipeline (deferred), multi-region DR.

---

## 6. Security Baseline Compliance (Requirements Stage)

Security Baseline is **enabled**. At the Requirements stage, rules are evaluated for whether requirements adequately provide for them; concrete enforcement is verified in Design/Code stages.

| Rule | Status @ Requirements | Note |
|---|---|---|
| SECURITY-01 Encryption at rest/in transit | Compliant (planned) | Required for DynamoDB, S3, Cognito; TLS everywhere. To be enforced in IaC. |
| SECURITY-02 Access logging on intermediaries | Compliant (planned) | API Gateway access/exec logs, CloudFront logs required in design. |
| SECURITY-03 Application logging | Compliant (planned) | Structured logging to CloudWatch; no PII/secrets. |
| SECURITY-04 HTTP security headers | Compliant (planned) | CSP/HSTS/X-Content-Type-Options/etc. via CloudFront response headers policy. |
| SECURITY-05 Input validation | Compliant (planned) | REST inputs validated; externally-sourced HTML sanitized (Module 11). |
| SECURITY-06 Least-privilege IAM | Compliant (planned) | Per-function scoped roles in SAM/CFN. |
| SECURITY-07 Restrictive network config | N/A / Compliant | Serverless (no VPC/SG by default); revisit if VPC introduced for analytics store. |
| SECURITY-08 App-level access control | Compliant (planned) | Server-side RBAC per Role-and-Permission-Mapping; object-level checks; scoped CORS; JWT validation. |
| SECURITY-09 Hardening/misconfig | Compliant (planned) | S3 public access blocked; generic errors; no defaults. |
| SECURITY-10 Supply chain | Compliant (planned) | Per-language lockfiles pinned (Cargo.lock / package-lock.json / Poetry or pip lockfile); vuln scanning (cargo-audit, npm audit, pip-audit) per language in build instructions; SBOM. |
| SECURITY-11 Secure design | Compliant (planned) | Auth/authz isolated modules; rate limiting at API Gateway; misuse cases in design. |
| SECURITY-12 Auth & credential mgmt | Compliant (planned) | Cognito password policy + OTP; local admin secret in Secrets Manager; MFA for admin considered. |
| SECURITY-13 Integrity verification | Compliant (planned) | SRI for any external scripts; safe deserialization; auditable critical changes. |
| SECURITY-14 Alerting & monitoring | Compliant (planned) | CloudWatch alarms for auth/authz failures; append-only audit log; ≥90-day retention (12-month for audit). |
| SECURITY-15 Exception handling / fail-safe | Compliant (planned) | Fail-closed (matches Bedrock duplicate-detection rule); global error handling; generic user errors. |

No blocking security findings at the Requirements stage.

---

## 7. Resiliency Baseline Compliance (Requirements Stage)

Resiliency Baseline is **enabled**. User decisions captured this stage:

| Rule | Status @ Requirements | Note |
|---|---|---|
| RESILIENCY-01 Critical workload ID | Compliant (planned) | Criticality/impact/dependency mapping to be documented in Application Design. |
| RESILIENCY-02 Availability/recovery targets | **Compliant** | User set RTO/RPO = hours → Backup & Restore. No formal SLA Phase 1. |
| RESILIENCY-03 Change management | **N/A (exempt)** | User selected exempt; rationale documented in §2. |
| RESILIENCY-04 Automated deploy/rollback | Deferred | User: no CI/CD this run; manual `sam deploy`; rollback = redeploy prior IaC version. Pipeline deferred. |
| RESILIENCY-05 Monitoring/alerting | Compliant (planned) | CloudWatch metrics/logs; X-Ray tracing for multi-Lambda flows; dashboards in design. |
| RESILIENCY-06 Health checks | Compliant (planned) | Health endpoints; deep checks for downstream deps in design. |
| RESILIENCY-07 Resiliency monitoring | Compliant (planned) | Alarms for DynamoDB throttling, DLQ depth, backup failures; quota monitoring. |
| RESILIENCY-08 Multi-zone/region | **Compliant** | Single-region multi-AZ (serverless default) confirmed by user. |
| RESILIENCY-09 Auto-scaling/capacity | Compliant (planned) | Serverless auto-scale; Lambda concurrency limits; service-quota review (Lambda concurrency, API rate) in design. |
| RESILIENCY-10 Dependency isolation/circuit breaking | Compliant (planned) | Timeouts on all external calls (Bedrock/SES/Teams); graceful degradation (stale insights, fail-closed dup detection). |
| RESILIENCY-11 DR strategy selection | **Compliant** | Backup & Restore documented; failover = redeploy IaC + restore. |
| RESILIENCY-12 Backup & replication | Compliant (planned) | DynamoDB PITR + on-demand backups; S3 versioning; encrypted backups; retention per NFR. |
| RESILIENCY-13 Failover/recovery procedures | Compliant (planned) | Restore runbook to be authored in Infrastructure Design/Build-and-Test. |
| RESILIENCY-14 Chaos/DR testing | Deferred to Operations | Capture restore-test scenarios at design time. |
| RESILIENCY-15 Incident response | **Compliant (planned)** | User chose "propose lightweight IR + COE" — to be authored in NFR/Infra Design. |

No blocking resiliency findings at the Requirements stage.

---

## 8. Key Requirements Summary

- A full 11-module AWS Community Portal, serverless, single-region multi-AZ, Backup & Restore DR.
- Polyglot Lambdas (Python/Node.js/Rust — language chosen per service at Construction) behind API Gateway REST; React+Vite static SPA on S3/CloudFront; CloudFormation + SAM IaC.
- Cognito-based auth with a bootstrap local Administrator; strict, non-inheriting RBAC across 4 roles.
- Append-only point ledger with runtime-derived per-group tiers; Streams-fed rollups + analytics store.
- Bedrock-powered semantic search, duplicate detection, AI reporting, and help assistant; SES email.
- Security and Resiliency baselines enforced as cross-cutting constraints; property-based testing skipped.
