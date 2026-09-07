# Certifications Service (Unit 6)

Real Python service for the Certifications bounded context. Owns certification
definitions, claims (the claim IS the earned badge — single lifecycle entity),
credited-group verification, claim-addressed revocation, the daily expiry job,
and badge display data. Fifth real service, after Identity & Access, Member
Profiles, Settings and Events.

**Stories**: US-5.1 – US-5.10 (all 10). **Paths**: `/certifications`.
**Contract**: `contracts/services/certifications/openapi.yaml` v2.0.0 (13 ops;
breaking change from v1: revoke is `POST /certifications/claims/{id}/revoke`).
**Published events**: `contracts/services/certifications/published-events/certification-lifecycle.v1.json`
(Approved · Rejected · Revoked · ExpiringSoon · Expired — Approved drives
Contributions' auto-award, US-6.5).

## Shape

One Lambda (`app.handler`), three dispatch branches:

| Branch | Trigger | Module |
|---|---|---|
| HTTP | API GW (Cognito authorizer) | `app.py` route table → OP_AUTHZ gate → services |
| Events | Identity `MemberLeftGroup`/`MemberRemoved`; GuardDuty scan verdicts (rule prefix-filtered to `certifications/`) | `consumers.py` |
| Scheduler | daily expiry sweep (06:00 UTC) · 15-min scan watchdog | `expiry_service.py` |

Modules: `models.py` (statuses, expiry arithmetic, the three privacy
serializers), `authz.py` (OP_AUTHZ map + blanket Administrator 403 — D7),
`repository.py` (single table, 3 GSIs incl. the shared sparse EXPIRY|SCANWATCH
sweep index, CLAIMSLOT duplicate guard, no scans), `providers.py`
(EventPublisher, S3Broker with presigned-POST 5 MB door, fail-closed
IdentityClient, Metrics), `definition_service.py`, `claim_service.py`,
`verification_service.py`, `revocation_service.py`, `upload_service.py`.

## Rules that surprise people

- **Administrators get 403 on EVERYTHING, including catalog browse** (D7 — the
  permission matrix's Admin row was removed as a transcription error).
- **Only Members submit claims / hold badges** (BR-A3). Leaders verify.
- **The wire status is `Approved`; the UI renders "Verified"** (D1 — the
  deployed member-profiles fan-out queries `status=Approved`).
- **Points are frozen onto the claim at approval** (BR-V6) — re-pricing a
  definition never changes what was awarded; **revoke/expiry never reverse
  points** (the events carry `pointsReversed: false` explicitly).
- **Duplicate rule is community-wide** and enforced by a conditional-write slot
  item, not a query (BR-C2) — terminal states (Rejected/Withdrawn/Revoked/
  Expired) free it for resubmission.
- **A claim with an uploaded file is not reviewable until GuardDuty says Clean**
  (BR-V3); badge images reach the public SPA bucket only after a Clean verdict
  (copy-then-stamp, N3=B).
- **UGL queue scope fails closed**: unresolvable led group ⇒ deny, never
  "all groups" (BR-A4).
- **Expiry anchors on the member-supplied `dateEarned`** (D8), frozen at
  approval; already-expired claims are blocked at submission (422) and an
  approval that would be born expired is refused (409, BR-V7).

## Dev

```
python3 -m pytest services/certifications      # 92 tests (3 mandatory suites incl.
                                               # authz matrix / lifecycle / fail-closed)
make contract-tests SVC=certifications         # 13/13 against the regenerated mock
python3 infra/tools/stage_gsis.py certifications 1   # GSI staging (deploy: 1; 1 2; 1 2 3)
```

Deployment order + verification checklist:
`aidlc-docs/construction/certifications/infrastructure-design/deployment-architecture.md`
(3 staged GSI deploys — DescribeTable-until-ACTIVE, stack status is NOT the
readiness signal; cross-unit rule edits deploy BEFORE this service writes any
object; EICAR test is the only real proof the scan gate works).
