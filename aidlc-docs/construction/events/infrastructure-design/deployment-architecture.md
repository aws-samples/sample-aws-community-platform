# Deployment Architecture — Unit 4: Events

**Stage**: CONSTRUCTION → Infrastructure Design · **Unit**: Events
Companion: `infrastructure-design.md`.

## Topology

```
                      CloudFront + S3 (SPA)
                              |
                    API Gateway REST (shared)
             +----------------+------------------+
             | /events  (Cognito authorizer)     |
             | /event-uploads  (NO authorizer)   |  <-- new, F1
             +----------------+------------------+
                              |  AWS_PROXY
                    +---------v----------+
                    |  Lambda events-dev |  python3.12, 512 MB, 60 s
                    |  handler app.handler|
                    +--+------+------+---+
                       |      |      |
      +----------------+      |      +------------------+
      v                       v                         v
DynamoDB events-<stage>   S3 community bucket     EventBridge platform bus
  GSI1 scope-date          events/<id>/materials/   9 published detail-types
  GSI2 user-rsvp           events/<id>/uploads/
  GSI3 content (sparse)          |
  GSI4 due (sparse)              | Object Created/Deleted (default bus, prefix events/)
  + events-idem-<stage>          | GuardDuty scan results
                                 v
                        EventBridge rules --> same Lambda
                        EventBridge Scheduler rate(5 min) --> same Lambda
                        EventBridge rule GroupSoftDeleted --> same Lambda
```

Text alternative: the SPA calls a shared API Gateway which proxies two base paths to a single Events Lambda — `/events` behind the Cognito authorizer and the new unauthenticated `/event-uploads`. That Lambda reads and writes one DynamoDB table with four GSIs plus an idempotency table, brokers presigned URLs into two prefixes of the shared community bucket, and publishes nine domain event types. Four inbound triggers besides the API converge on the same function: S3 object events (prefix-filtered), GuardDuty scan results, `GroupSoftDeleted`, and a five-minute scheduler.

## Stack composition
`infra/root-template.yaml` → `EventsData` (nested) → `EventsApp` (nested), with Foundation and ApiEdge outputs passed as Parameters. No `Fn::ImportValue` anywhere, per platform decision D1.

New parameters the root must pass to `EventsApp`: `FileShareBucketName`, `FileShareBucketArn`, `ApiBaseUrl`, `PublicUploadBaseUrl`, `EventBusArn`. The first two already flow to `SettingsApp`, so this is the same wiring, not a new pattern.

## Deployment sequence — GSIs must be staged (F2)

### Correction from the first real deployment attempt (2026-08-05)

**Do not create the indexes out of band and then deploy the finished template.** That was
tried first, on the assumption CloudFormation would see four matching indexes already
present and treat the Table as unchanged. It does not: CloudFormation diffs the new template
against **its own last-known template**, not against reality. It still saw "0 -> 4 GSIs",
batched four creations into a single `UpdateTable`, and failed:

```
Resource handler returned message: "Cannot perform more than one GSI creation
or deletion in a single update" (HandlerErrorCode: InvalidRequest)
```

The nested `EventsData` stack rolled back, which rolled the **whole root stack** back, so
nothing else in the deploy landed either — not the real handler, not Foundation's GuardDuty
plan, not the Settings prefix filter. Recovery meant deleting the four manually-created
indexes (one `UpdateTable` each) before CloudFormation could own them.

**Measured index timings on an EMPTY table** (`events-dev`, 0 items): GSI1 ~60 s,
GSI2 ~450 s, GSI4 ~170 s, GSI3 ~380 s. The "about four minutes" figure from the Settings
work is representative, but the spread is wide and unpredictable **even with no data to
backfill** — budget 2-8 minutes per index and do not assume an empty table is quick.

### The sequence that actually works

Let CloudFormation create every index. Edit `service-events-data.yaml` so it declares
**one more GSI than the last successful deploy**, deploy the root stack, wait for `ACTIVE`,
repeat. DynamoDB allows one GSI change per `UpdateTable`, and `events-<stage>` starts with
none, so that is four sequential root deployments:

| Step | Adds | Why this order |
|---|---|---|
| D1 | GSI1 scope-date | every listing depends on it; nothing else works first |
| D2 | GSI2 user-rsvp | member's own RSVPs and Member Profiles' activity fan-out |
| D3 | GSI4 due-schedule | ~~reminders can be written but not swept until this exists~~ — **moot since 2026-08-27**, reminders removed and GSI4 is now unused |
| D4 | GSI3 publishable-content | Content Library; last because it needs a backfill |

**The stack reaching `UPDATE_COMPLETE` is not the readiness signal.** This was verified the hard way during the Settings file-share work: the root stack reported `UPDATE_COMPLETE` while the new index was still `CREATING`, and a Query against a backfilling index fails. That index took about four minutes. Each step here must poll `DescribeTable` until the index status is `ACTIVE` before the next deployment or any smoke test.

GSI3 additionally needs a **backfill**: existing materials on completed events have no `gsi3pk` attribute, so they are invisible to the Content Library until a one-off pass writes the key for those that qualify (`Clean` material on a `Completed` event). Same shape as the pointer/stamp backfill already run for File Share.

## Full deployment order

1. **Contract** — add the additive operations and the `/event-uploads` path; regenerate the mock.
2. **Generator** — add `event-uploads` to `PUBLIC_BASES` in `gen_api_edge.py`; regenerate `api-edge.yaml`.
3. **Foundation** — GuardDuty Malware Protection plan + role; lifecycle rules for `events/*/uploads/`.
4. **Settings app stack** — add the key-prefix filter to its S3 rule (F3), so it stops receiving Events' object events.
5. **Events data stack** — D1 → D2 → D3 → D4, waiting for `ACTIVE` between each.
6. **GSI3 backfill** — one-off script over existing materials.
7. **Events app stack** — handler switch, memory/timeout, IAM, three rules, one schedule, four alarms.
8. **Root template** — new parameter wiring.
9. **`service-mode.json`** — `events: complete`.

Steps 1–2 and 3–4 are independent of each other; 5 must complete before 7, since the real handler queries indexes the mock never touched.

## Rollback
Platform default: redeploy the previous stack version. Two asymmetries to note.

**GSIs do not roll back usefully.** Removing an index is another one-at-a-time `UpdateTable` and destroys the backfill. If the app stack must be rolled back, leave the indexes in place — they are additive and the mock handler ignores them. Rolling back the *handler* (step 7) is the effective rollback for this unit.

**The public route rollback is a generator rerun**, not a stack edit: remove `event-uploads` from `PUBLIC_BASES`, regenerate, deploy. Any upload links already issued stop working, which is the intended fail-closed direction.

## Cost delta (dev scale)
DynamoDB on-demand plus four GSIs (index writes are the main increment; GSI3/GSI4 are sparse and small), Lambda invocations including 288 sweep runs per day, S3 storage and requests, and **GuardDuty Malware Protection for S3 charged per GB scanned** — the only materially new line item, and the one the user accepted with decision N1. No NAT, no OpenSearch, no WAF, no provisioned concurrency.

## Verification before declaring the unit deployed
1. `DescribeTable` shows all four indexes `ACTIVE`.
2. GSI3 backfill report: items scanned, keys written, items skipped.
3. Authenticated smoke: create → RSVP → material upload → attendance apply → complete, checking published events arrive on the bus.
4. Public smoke: mint an upload URL with a valid token, then confirm `404` for an unknown token, an expired token, and a revoked token — all three indistinguishable in the response.
5. Prefix isolation: upload under `events/`, confirm the Events consumer stamps it and Settings' consumer does **not** log it.
6. Malware path: upload the EICAR test file and confirm the material lands `Quarantined`, stays hidden from members, and raises the alarm.
8. Contract gate green; `make test` and `make lint` clean repo-wide.

Step 6 matters most — it is the only end-to-end proof that decision N1 actually gates visibility rather than merely being configured.
