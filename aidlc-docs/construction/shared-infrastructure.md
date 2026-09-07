# Shared Infrastructure — AWS Community Portal

Owned by **Unit 1 (Platform & Delivery)**; consumed by all service units. These are the Foundation + API Edge resources; service `-data`/`-app` stacks receive references as **Parameters** (D1 — never `Fn::ImportValue`).

## Foundation stack (`infra/foundation.yaml`)
| Resource | Config | Notes |
|---|---|---|
| **VPC** | /16 CIDR, **2 AZs** | new VPC (Q3=A) |
| **Public subnets** (x2) | /20 | host NAT |
| **Private subnets** (x2) | /20 | host Lambdas (P-NETWORK) |
| **NAT Gateway** | **single** (dev); `NatPerAz` parameter → per-AZ for customer/prod | Q3=A |
| **Gateway VPC endpoints** | **S3, DynamoDB** | free; high-traffic data plane stays private (Q4=C) |
| **Egress** | all other AWS + third-party calls via **NAT over TLS** | Q4=C, AC-4 (no interface endpoints Phase 1) |
| **Cognito user pool** | strong password policy, email verification, advanced security, custom-auth trigger hooks reserved | Q8=A(NFR); logic wired by Identity unit |
| **EventBridge bus** | single shared bus | per-consumer rules added by service stacks |
| **KMS** | AWS-managed keys | AC-2 (no CMK) |
| **Observability baseline** | central log groups, X-Ray, alarm **SNS topic** (`OpsEmail` param subscription) | Q6=A |
| **Tags** | `Project=community-portal`, `Unit`, `Stage`, `ManagedBy=sam` | Q9=A |

**Outputs** (passed as Parameters to service stacks): `VpcId`, `PrivateSubnetIds`, `UserPoolId`, `UserPoolClientId`, `EventBusName`, `RestApiId`, `RootResourceId`, `OpsAlarmTopicArn`, `LogRetentionDays`.

## API Edge stack (`infra/api-edge.yaml`)
| Resource | Config |
|---|---|
| **API Gateway (REST)** | single API; **one stage per env** (`dev` / customer `prod`); Lambda **proxy** integration; access + execution logging (SECURITY-02) |
| **Cognito authorizer** | JWT authN at edge |
| **Throttling + usage plans** | shared rate-limit ceiling (SECURITY-11; WAF omitted AC-1) |
| **CloudFront + S3 (SPA)** | static hosting; security headers (SECURITY-04); asset caching (P-CACHE) |

## Environments (Q1=B)
- **Dev account only** for construction; all per-service pipelines deploy here.
- **Release validation** performed in the dev account (no separate staging — residual risk RR-1: less pristine than a clean account).
- **Customer** installs the tagged release into **their own account/region** via the root template.
- `Stage` parameter distinguishes `dev` vs customer `prod`.

## Accepted exceptions / risks
- **AC-4 (SECURITY-07 documented exception)**: NAT-only egress for non-gateway AWS services. Gateway endpoints (S3, DynamoDB) retained for high-traffic data plane; remaining AWS calls via NAT over TLS. Mandatory network controls (private subnets, NAT-not-IGW, deny-by-default, no public inbound except CloudFront/API 443) all met. Interface endpoints addable later without redesign.
- **RR-1**: No staging account (Q1=B) — release validated in dev; slightly less representative of a pristine customer install.

---

## Shared community S3 bucket (`FileShareBucket`, Foundation)
Added for Settings' US-8.13 external file sharing (2026-08-02) and now shared with a second consumer.

| Property | Config |
|---|---|
| Public access | fully blocked; all access via short-lived presigned URLs, never a bucket policy |
| Encryption | SSE (AWS-managed); TLS enforced |
| Versioning | enabled |
| Notifications | **`EventBridgeConfiguration` on the default bus** — deliberately not a direct S3→Lambda notification, which would name a consumer and close a circular dependency with this stack |
| Deletion policy | Retain |

### Consumers and prefix ownership
| Consumer | Prefixes | Added |
|---|---|---|
| **Unit 11 Settings** (US-8.13) | leader-created folders at the bucket root | 2026-08-02 |
| **Unit 4 Events** (US-2.15, US-2.21) | `events/<eventId>/materials/`, `events/<eventId>/uploads/` | 2026-08-05 (Infrastructure Design) |
| **Unit 6 Certifications** (US-5.4/5.1) | `certifications/evidence/`, `certifications/badges/` | 2026-08-06 (Infrastructure Design) |

**Scan-result rules must be prefix-filtered too (Unit 6 finding F-B, extends F3).** The GuardDuty MalwareProtectionPlan emits verdicts for the whole bucket, and Events' original scan rule matched ALL of them. With a second scan-gating consumer (Certifications), each service's scan rule now filters `detail.s3ObjectDetails.objectKey` on its own prefix — the mirror of the object-event rule discipline. Likewise Settings' object-rule exclusion is now a list: `anything-but: {prefix: ["events/", "certifications/"]}` (finding F-A). Any future consumer of this bucket must add BOTH its object-rule prefix filter and its scan-rule prefix filter, and extend Settings' exclusion list.

**Prefix isolation is mandatory, not stylistic (finding F3).** Because notifications are enabled bucket-wide, every consumer's EventBridge rule must filter on its own key prefix. Settings' original rule filtered only on bucket name, so once Events began writing to the same bucket, Settings' consumer would have received every Events object event, looked for a `FILEKEY` pointer that does not exist, and consumed an idempotency record per event. Functionally tolerant, operationally misleading. Both rules now carry prefix filters.

IAM must be prefix-scoped for the same reason: Settings holds `s3:DeleteObject` on `/*`, so without conditions two services could delete each other's objects. Events is scoped to `${FileShareBucketArn}/events/*`.

### Malware scanning (added 2026-08-05, Unit 4 decision N1)
`AWS::GuardDuty::MalwareProtectionPlan` on this bucket, placed in **Foundation** because the bucket owner should own its protection — putting it in a consumer stack would make coverage depend on which consumer deployed last. Scan results are delivered to EventBridge; each consumer subscribes for its own prefix and gates content visibility on a clean result. Settings' file-share uploads gain coverage as a side effect. Charged per GB scanned — the only materially new cost line in Unit 4.

### Lifecycle (added 2026-08-05)
`events/*/uploads/` objects expire after 180 days; incomplete multipart uploads are aborted after 7 days.

## SPA bucket (`SpaBucket`, API Edge) — runtime writers
Owned by Unit 1 (API Edge stack); primary content is the seed-published SPA bundle. The install-time publisher (`spa_deploy_handler.py`) is **upload-only on Create/Update** (it never prunes), so runtime-written prefixes survive SPA redeploys; it empties the bucket only on stack Delete.

| Writer | Prefix | Purpose | Added |
|---|---|---|---|
| **Unit 6 Certifications** (scan-verdict consumer) | `badges/` | scan-Clean badge images served as static CloudFront assets (N3=B); keys unique per upload so no cache invalidation is ever needed | 2026-08-06 (Infrastructure Design) |

Any future runtime writer must use its own prefix, prefix-scoped IAM, and only ever write scan-Clean content — this bucket is world-readable via CloudFront by design.

## SPA bucket (`SpaBucket`, API Edge) — runtime `badges/` prefix
Added 2026-08-06 (Unit 6, decision N3=B): scan-Clean certification badge images are copied by the certifications service into `SpaBucket/badges/*` and served as static CloudFront assets (world-readable by design, no PII). Facts verified in the repo: the seed's `spa_deploy_handler.py` is **upload-only on Create/Update** (never prunes), so runtime-written `badges/*` survives SPA redeploys; the OAI bucket policy already grants GetObject on `/*`; badge keys are unique per upload so the deploy-time `/*` invalidation is harmless. Certifications holds `s3:PutObject` scoped to `badges/*` only. Rule for future units: the SPA bucket may host runtime-written public assets ONLY under a service-owned prefix with prefix-scoped IAM, and only for scanned, non-private content.

## Public (unauthenticated) base paths at the API edge
`infra/tools/gen_api_edge.py` maps each first URL segment to exactly one service and **hard-fails on collision**, so a base path cannot be shared. Unauthenticated paths are enumerated in the generator's `PUBLIC_BASES` set.

These routes are reachable by **anyone on the internet with no credential**. Every field in their responses is therefore public. Before adding a field to a response served from one of these base paths, assume an anonymous attacker reads it (see Finding F2 below).

| Base path | Owner | Purpose | Added |
|---|---|---|---|
| `/auth` | Identity & Access | login, register, OTP, password reset | initial |
| `/public` | Settings | pre-login settings read (`GET /public/settings`) | 2026-08-02 |
| `/event-uploads` | **Events** | token-authorized presigned-PUT mint for US-2.21 external uploads | 2026-08-05 (finding F1) |

## Private-only base paths

`PRIVATE_ONLY_BASES` in the same generator lists base paths emitted **only** into the private REST API. They are absent from the internet-facing API entirely — not merely unadvertised. Like `PUBLIC_BASES` they carry **no Cognito authorizer**, because the callers are same-account Lambdas making service-to-service HTTP calls with no JWT to present; the control is network reachability, not a token. The private API is `Type: PRIVATE`, bound to the execute-api interface endpoint, with a resource policy denying any principal not arriving through that VPCE.

| Base path | Owner | Purpose | Added |
|---|---|---|---|
| `/internal` | Settings | service-to-service read of admin config that must not be disclosed pre-login (`GET /internal/settings`) | 2026-08-28 |

**Finding F2 (2026-08-28)**: `/public/settings` was returning `allowedEmailDomains`, `otpIntervalDays` and `defaultTimezone` to anonymous internet callers. Nothing pre-login read them — `AuthScreen.tsx` destructures only `selfRegistrationEnabled`, `communityName`, `logoUrl` — but an unauthenticated route is a **published** route, so the allow-list (which corporate domains may self-register: targeting recon) and the OTP re-verification interval (how long a departed employee's access persists) were world-readable. The fields moved to `/internal/settings` and `PUBLIC_FIELDS` was trimmed to the three the login screen renders.

Two lessons encoded as tests in `infra/tools/tests/test_gen_api_edge_route_split.py`:
1. The unauthenticated **public** surface is pinned to `{auth, public, event-uploads}`, so widening it fails a test rather than passing review.
2. A private-only base appearing on the public API fails a test — the security argument is structural, so it is asserted structurally.

A corollary worth stating plainly: **a route being unauthenticated makes every field in its response public**, no matter which client happens to read it. Field-level review belongs on the projection (`PUBLIC_FIELDS`), not on the caller.

**Finding F1**: Unit 4's functional design originally specified `POST /public/event-uploads/{token}`, which is not deployable — `/public` is already claimed by Settings and the generator aborts on collision. Nor can an unauthenticated route hide under an authenticated base path, because the authorizer is applied per base path and hand-editing generated routes is forbidden. Events therefore claims its own public base path. Any future unauthenticated endpoint must likewise claim a distinct base path and be added to `PUBLIC_BASES` deliberately, which is the desired friction for adding public surface.
