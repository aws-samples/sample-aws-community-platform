# Contract Test Instructions — AWS Community Portal

**Generated**: 2026-08-05

## Why this is the primary gate

Every service in this system is self-contained with **no shared library** (FQ1), and
collaboration happens through versioned contracts in `/contracts`. The contract gate is
therefore the mechanism that keeps 12 independently-deployable services compatible, and it
is the stage that gates a mock→real swap in each service's pipeline.

## Run it

```bash
make contract-tests SVC=events      # one service
make contract-tests-all             # every service
```

## Measured results (2026-08-05)

| Service | Result |
|---|---|
| analytics | 5/5 |
| announcements | 5/5 |
| certifications | 9/9 |
| contributions-scoring | 14/14 |
| **events** | **28/28** |
| forums | 24/24 |
| help-assistant | 1/1 |
| identity-access | 27/27 |
| member-profiles | 5/5 |
| notifications | 4/4 |
| search | 1/1 |
| settings | 12/12 |

**12/12 services pass.**

## What it asserts

`platform/contract-tests/harness.py` probes every operation in a service's OpenAPI and
checks that:

* the response body validates against the operation's declared schema for the returned
  status (via `jsonschema`, with `components` made resolvable);
* an unimplemented operation returns **501**, never a 5xx;
* a protected operation rejects an unauthenticated request.

## What it does *not* assert — read this before trusting it

The default invoker targets the service's **generated mock**, not the real handler:

```python
from mock_handler import handler
results = run_suite(openapi, lambda event: handler(event, None))
```

So a green gate proves the **contract is self-consistent and mock-satisfiable**. It does
not prove the real service matches its contract. Two consequences worth internalising:

1. **The real handler is validated post-deploy**, by pointing the same harness at the live
   endpoint (the pipeline's contract-test stage). Locally, real-handler behaviour is
   covered by that service's unit tests instead.
2. **Contract shapes are sometimes constrained by what the generic mock can produce.** Two
   accommodations exist in the Events contract and are documented inline:
   * `PUT /events/{id}/designations` returns `DesignationsAck` — the same payload as
     `listDesignations`, but with no required fields, because the mock's generic *update*
     shape returns a single object rather than a list.
   * `PUT /events/{id}/materials/{materialId}` carries `x-mock-collection: materials`,
     because without it the mock derives the collection from the first path segment
     (`events`) and echoes an event row that cannot satisfy `Material.name`. The gate
     caught exactly that.

   Both are honest accommodations of the test harness, not weakened APIs — but a reader
   should know why the schemas look asymmetric.

## After any contract change

```bash
make generate-mocks SVC=<service>       # regenerate mock handler + operation map
python3 infra/tools/gen_api_edge.py     # regenerate the API Gateway route table
make contract-tests SVC=<service>
make contract-tests-all                 # confirm no sibling broke
```

Two hard rules here:

* **`infra/api-edge.yaml` routes are generated — never hand-edit them.** The generator maps
  each first URL segment to exactly one service and calls `raise SystemExit` on collision.
* **Path ordering in the contract matters.** The generated mock matches routes
  first-wins, so literal segments (`/events/recurring`, `/events/calendar`,
  `/events/content-library`) must stay ahead of `/events/{id}`. The Events contract carries
  a comment saying so.

## Adding a public (unauthenticated) base path

Unauthenticated surfaces are enumerated in `PUBLIC_BASES` inside
`infra/tools/gen_api_edge.py`:

```python
PUBLIC_BASES = {"auth", "public", "event-uploads"}
```

A base path cannot be shared between services, so an unauthenticated route cannot hide
under an authenticated base path — which is why the Events external-upload mint claims its
own `/event-uploads` rather than living under Settings-owned `/public`. Adding an entry
here is a deliberate expansion of public attack surface and should be treated as a
security-relevant change, not a routing detail.

## Schemathesis

`make bootstrap` installs `schemathesis` and the harness docstring notes it as the
complement for property-based fuzzing of implemented operations. **It is not currently
wired into any target**, so no fuzzing has been run. Wiring it in is a reasonable
follow-up; until then, do not describe the contract gate as fuzz-tested.
