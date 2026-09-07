# Platform & Delivery (Unit 1)

The delivery substrate that makes the whole product buildable and shippable via one CloudFormation entry point. Cross-cutting conventions live here and are copied per service; the services deploy themselves.

## Contents
| Dir | What |
|---|---|
| `reference/` | Canonical cross-cutting conventions (logger, errors, authz, validation, envelope, idempotency, config). **Copied per service** — not a shared library (FQ1). |
| `build/` | `package_all.py`: dependency-complete artifacts into `dist/` (D4). |
| `seed/` | (custom-resource Lambdas for install-time seeding — authored with the seed stack). |

## Common commands
```bash
make bootstrap                      # install tooling (Python + frontend)
make test                           # run all Python tests
make generate-api-client            # frontend TS types from contracts
make build && make package          # dist/ artifacts + validate root template
```

## How a service is built
1. Author `contracts/services/<svc>/openapi.yaml` (+ published events) — the contract is the source of truth.
2. Implement the service in `services/<svc>/src/` behind its API Gateway routes, copying `reference/` conventions into `src/_conventions/`.
3. Add pytest suites under `services/<svc>/tests/`.
4. `make build && make package` produces the deployable artifacts; the service deploys via its CloudFormation `-data`/`-app` stacks.
5. Status is recorded in `service-mode.json`.

## Conventions consistency (FQ1)
No shared runtime library. `reference/` is the single documented implementation; each service copies it into `services/<svc>/src/_conventions/`. Lint + tests catch drift.
