# Code Generation Summaries — Unit 1: Platform & Delivery

Markdown summaries of generated code (application code lives at the workspace root, per the code-location rules).

| Step | Summary | Workspace output |
|---|---|---|
| 1 | `step-01-structure.md` | `README.md`, `.gitignore`, `pyproject.toml`, `service-mode.json` |
| 2 | `step-02-contracts-platform.md` | `contracts/platform/*.json`, `contracts/README.md` |
| 3 | `step-03-reference.md` | `platform/reference/*.py` (+ tests) |
| 4-6 | `step-04-06-tooling.md` | `platform/fixtures/`, `platform/mock-factory/`, `platform/contract-tests/` (+ tests) |
| 7 | `step-07-15-scaffold-iac-build.md` | `platform/scaffold-generator/`, `platform/build/`, run_* CLIs |
| 8-12 | `step-07-15-scaffold-iac-build.md` | `infra/foundation.yaml`, `infra/api-edge.yaml`, `infra/seed.yaml`, `infra/pipelines/pipeline-template.yaml`, `infra/root-template.yaml` |
| 13 | `step-07-15-scaffold-iac-build.md` | `frontend/` (package.json, generate-api-client, apiClient.ts) |
| 14 | (this file) + `platform/README.md`, `contracts/README.md` | docs |
| 15 | `step-07-15-scaffold-iac-build.md` | `Makefile`, `platform/*/run_*.py`, `platform/build/package_all.py` |

## Test status (generated now, executed in Build & Test)
- `platform/reference/tests` — 12 pass
- `platform/fixtures/tests` — 4 pass
- `platform/mock-factory/tests` — 5 pass
- `platform/contract-tests/tests` — 4 pass
- `platform/scaffold-generator/tests` — 1 pass
- CFN YAML — 5 templates parse

Total: **26 Python tests pass**; IaC structurally valid.
