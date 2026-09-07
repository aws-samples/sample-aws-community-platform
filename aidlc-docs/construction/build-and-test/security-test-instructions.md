# Security Test Instructions — AWS Community Portal

**Generated**: 2026-08-05
**Extension**: Security Baseline (SECURITY-01..15) is **enabled** for this project.

## Status summary

| Check | State |
|---|---|
| `ruff` (includes flake8-bandit `S` rules) | **run, clean** repo-wide |
| `cfn-lint` on every template | **run, clean** |
| `bandit` static scan | **NOT RUN** — listed in `make bootstrap` but not installed in the environment used for this stage |
| Dependency vulnerability scan | **NOT RUN** — no tool wired into a target |
| SBOM generation | **NOT RUN** — required by SECURITY-10 for production deployments |
| Authorization tests | **run** — `services/events/tests/test_authz.py`, plus per-service equivalents |
| Malware-scan path (EICAR) | **NOT RUN** — requires a deployed bucket with GuardDuty |
| Penetration testing | **NOT RUN** — Operations-phase activity |

Three of those are gaps against an enabled baseline rather than deliberate omissions, and
they are listed as follow-ups at the end rather than quietly passed over.

## 1. Static analysis

```bash
ruff check .                    # clean as of 2026-08-05
pip install bandit && bandit -q -r services/*/src -x '*/tests/*'
```

`ruff`'s configuration includes the `S` (flake8-bandit) rules, so a subset of bandit's
findings are already enforced on every run. The codebase carries explicit
`# noqa: S310` markers where `urllib` is used with a scheme that is validated immediately
beforehand — those are deliberate and annotated, not suppressions of unexamined risk.

## 2. Dependency and supply chain (SECURITY-10)

```bash
for f in services/*/requirements.txt; do echo "== $f"; cat "$f"; done
cd frontend && npm audit --omit=dev
```

Policy already in force:

* All Python pins are **exact** (`boto3==1.34.162`, `aws-lambda-powertools==2.43.1`) — no
  ranges, by policy.
* **No `xlsx`/SheetJS anywhere.** It was uninstalled during the Identity & Access bulk-import
  work over unpatched high-severity CVEs, and both later features that wanted spreadsheet
  import (Identity bulk import, Events attendance import) are **CSV-only** as a result. If
  a future change reintroduces it, that is a security regression, not a convenience.
* Unit 4 added **zero** new runtime dependencies: recurrence, RFC 5545 rendering, CSV
  parsing, token generation and the cross-service fan-out are all stdlib.

Not yet automated: a scanner (`pip-audit` or equivalent) and SBOM generation. Both are
required by SECURITY-10 for production and are listed as follow-ups.

## 3. Authorization testing (SECURITY-08)

The most valuable security tests in the repo are the authorization matrices, because the
rules are non-obvious in two directions.

```bash
python3 -m pytest services/events/tests/test_authz.py -v
```

Assertions worth knowing about:

| Behaviour | Why it is easy to get wrong |
|---|---|
| **Administrators are denied on every `/events` operation, including reads** | The permission matrix has zero event entries for that role. Someone will eventually "helpfully" grant read access. Enforced once at the router boundary so a new operation cannot leak by omission. |
| **Out-of-scope events return 404, not 403** | A 403 confirms the event exists. The test asserts the response is indistinguishable from a genuinely absent id. |
| **A creator demoted to Member keeps edit/cancel rights** | Required by US-2.4. It is the only place a Member-role principal passes a leader-only check, and it looks like a privilege-escalation bug unless you know the rule. |
| **A demoted leader does *not* gain blanket group powers** | The escape hatch above is scoped to ownership only — asserted separately so the two cannot be conflated. |

Manual probes against a deployed stack:

```bash
# Administrator must be refused even on a plain read
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $ADMIN_TOKEN" "$API/events"      # expect 403

# A member outside the group must not learn the event exists
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $OTHER_MEMBER" "$API/events/$ID" # expect 404

# A member must not read the per-member RSVP list
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $MEMBER" "$API/events/$ID/rsvps" # expect 403
```

## 4. The unauthenticated write path (SECURITY-08/11)

`POST /event-uploads/{token}` is the portal's **only unauthenticated write endpoint**. It
deserves specific attention.

```bash
# Valid token -> 200 with a single-object presigned PUT
curl -s -X POST "$API/event-uploads/$TOKEN" -H 'Content-Type: application/json' \
  -d '{"fileName":"deck.pdf"}' | jq .

# Unknown, expired and revoked tokens must be INDISTINGUISHABLE (all 404, same message)
for t in "$UNKNOWN" "$EXPIRED" "$REVOKED"; do
  curl -s -X POST "$API/event-uploads/$t" -H 'Content-Type: application/json' \
    -d '{"fileName":"x.pdf"}' | jq -r '.message'
done | sort -u | wc -l    # expect exactly 1 distinct message

# Path traversal must be rejected
curl -s -X POST "$API/event-uploads/$TOKEN" -H 'Content-Type: application/json' \
  -d '{"fileName":"../../secrets.pdf"}' | jq -r .code    # expect VALIDATION_ERROR

# Write-only: there must be no read/list/delete verb on this path
for m in GET PUT DELETE; do
  curl -s -o /dev/null -w "$m %{http_code}\n" -X $m "$API/event-uploads/$TOKEN"
done   # expect 401/403/404 — never 200
```

Properties asserted at unit level in `test_upload_link_service.py`: the token is 32 bytes
of `secrets` randomness stored **hashed** and compared with `hmac.compare_digest`; the
plaintext is returned exactly once at creation; resolution is an O(1) pointer lookup rather
than a scan; expiry, revocation and a 100-upload cap are all enforced **at mint time**,
which is what makes revocation immediate for every future upload.

## 5. Input validation (SECURITY-05)

Covered by unit tests per service. For Events specifically: the eight event types and three
delivery modes as enums, title/description length caps, duration bounds, an `https://`
requirement on virtual join links (an `http://` join link for a private community event is
rejected rather than silently upgraded), ISO-8601 timestamps, recurrence completeness,
`limit` 1..200, cursor decodability with a **whitelisted attribute set** so a crafted cursor
cannot steer a query at another field, upload extension and size checked **before** a URL is
minted, and a required `email` column in the attendance CSV.

## 6. Storage and encryption (SECURITY-01/09)

Assert on a deployed environment:

```bash
aws s3api get-public-access-block --bucket $BUCKET            # all four true
aws s3api get-bucket-encryption --bucket $BUCKET              # SSE enabled
aws s3api get-bucket-versioning --bucket $BUCKET              # Enabled
aws dynamodb describe-table --table-name events-dev \
  --query 'Table.{SSE:SSEDescription.Status,PITR:BillingModeSummary}'
aws dynamodb describe-continuous-backups --table-name events-dev   # PITR ENABLED
```

PITR is **mandatory** for `events-<stage>`, not merely prudent: unlike Member Profiles (a
derived cache rebuildable by event replay) and Settings (small and re-enterable), this table
holds original records — events, RSVPs, attendance — with no upstream source of truth.

## 7. Least privilege (SECURITY-06)

The IAM shape worth verifying by hand, because moto does not enforce IAM and that gap has
already produced a live 502 in this project (Settings missing `s3:DeleteObject`):

* Events' S3 permissions are scoped to `${FileShareBucketArn}/events/*`, **not** `/*`.
  Settings holds `s3:DeleteObject` at `/*` on the same shared bucket, so without the prefix
  the two services could delete each other's objects.
* `s3:ListBucket` is conditioned on `s3:prefix: events/*`.
* `execute-api:Invoke` is scoped to the single Contributions method.
* DynamoDB Query permission explicitly includes `table/*/index/*` — a table ARN alone does
  not cover its indexes, and a Query would fail at runtime without it.

## 8. Malware scanning (SECURITY-13, decision N1)

Deployed-environment only:

1. Upload the **EICAR** test string as an event material.
2. Expect `scanState: PendingScan → Quarantined`, the material hidden from members, absent
   from the Content Library, and the `MalwareDetected` alarm firing.
3. Upload a benign PDF; expect `Clean`, and — if the event is `Completed` — appearance in
   the Content Library at that moment.

This is the only end-to-end evidence that N1 gates visibility rather than merely being
configured, which is why it is item 6 of 8 in the deployment verification list.

## Follow-ups (gaps against the enabled baseline)

1. **Install and run `bandit`** in the standard build environment, or remove it from
   `make bootstrap` and stop implying it runs.
2. **Wire a dependency vulnerability scanner** (`pip-audit`, `npm audit` in CI) into a
   Makefile target and the pipelines.
3. **Generate an SBOM** for production artifacts — explicitly required by SECURITY-10.
4. **Emit the custom metrics** behind four of the Events alarms
   (`PublicUpload4xx`, `AuthorizationFailures`, `MalwareDetected`,
   `ContributionsFanOutFailures`). The alarms exist and treat missing
   data as not-breaching, so today they cannot fire — an alarm that cannot fire is worse
   than no alarm, because it looks like coverage.
5. **Wire Schemathesis** into the contract gate for property-based fuzzing of implemented
   operations.
