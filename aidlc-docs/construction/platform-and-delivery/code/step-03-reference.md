# Code Summary — Step 3: Reference Conventions

Canonical cross-cutting conventions in `platform/reference/` — **copied per service** by the scaffold generator (not a shared library, FQ1).

Created:
- `logger.py` — JSON logging + correlation id + secret/PII redaction (SECURITY-03).
- `errors.py` — `AppError` hierarchy (Validation/Unauthorized/Forbidden/NotFound/NotImplemented501), `to_response` (error-response contract), `global_handler` decorator (fail-closed, SECURITY-15).
- `authz.py` — `Principal.from_claims` + `Authorizer` enforcing `global/own/group` scope from the permission matrix (SECURITY-08, FQ3a).
- `envelope.py` — build/parse the versioned event envelope.
- `idempotency.py` — `IdempotencyStore.run_once` via DynamoDB conditional put + TTL (P-IDEMPOTENCY).
- `validation.py` — type/length/format/enum + XSS-safe string checks + body-size limit (SECURITY-05).
- `config.py` — env / SSM / Secrets Manager access; `semantic_search_enabled()` (Q10).

Tests (`platform/reference/tests/`): authz (global/own/group + deny), validation+envelope, idempotency (run-once/duplicate-skip). **12 tests pass** (`pytest`).

Note: imported as the `reference` package (no top-level `platform` package) to avoid shadowing the stdlib `platform` module; matches how they're copied into `services/<svc>/src/_conventions/`.

Status: Step 3 complete.
