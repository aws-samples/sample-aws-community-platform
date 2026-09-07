# Reference Conventions (`platform/reference`)

Canonical **reference implementation** of the cross-cutting conventions every backend service needs. Per FQ1 there is **no shared library**: the scaffold generator (Step 7) **copies** these modules into each service (`services/<svc>/src/_conventions/`) so each service owns its copy. This directory is the single documented reference; regeneration realigns services, and contract tests + lint catch drift (P-CONVENTIONS).

Modules:
- `logger.py` — structured JSON logging + correlation id (SECURITY-03, NFR-OBS-1).
- `errors.py` — fail-closed error types + global handler + `error-response` mapping (SECURITY-15).
- `validation.py` — input validation helpers (SECURITY-05).
- `authz.py` — in-service authorization from the permission matrix (SECURITY-08, FQ3a).
- `envelope.py` — build/parse the versioned domain-event envelope.
- `idempotency.py` — consumer idempotency on the event `id` (P-IDEMPOTENCY).
- `config.py` — config from env/SSM + secrets via Secrets Manager (never plaintext).

These are intentionally dependency-light (stdlib + boto3 + optional AWS Lambda Powertools).
