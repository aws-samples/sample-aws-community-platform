# Community Portal — developer & release entrypoints (D5/D4).
.PHONY: bootstrap test lint security-scan build package clean generate-api-client

bootstrap:
	pip install pytest bandit cfn-lint jsonschema PyYAML boto3 ruff
	cd frontend && npm install

# Each service's tests run in their OWN pytest process: services are self-contained
# (no shared packaging, FQ1) and reuse the same top-level module names (models, app,
# repository, ...), so collecting two services' suites in one interpreter poisons
# imports (first `models` wins). Process isolation is the architectural fix.
test:
	python3 -m pytest platform -q
	@set -e; for d in services/*/tests; do \
		svc=$$(dirname $$d); \
		echo "== $$svc =="; \
		python3 -m pytest "$$svc" -q; \
	done
	@echo "== frontend =="
	cd frontend && npm test --silent

lint:
	ruff check .
	cfn-lint infra/*.yaml infra/services/*.yaml

# IaC security scan (NFR-MAINT-1). The --deny-list-path flag is REQUIRED: without
# it every rule documented in .cfn_nag_suppress.yaml is silently re-reported.
# Note cfn_nag needs Ruby >= 2.7 (`brew install ruby`); macOS system Ruby is 2.6.
security-scan:
	cfn_nag_scan --input-path infra --deny-list-path .cfn_nag_suppress.yaml

# Frontend API types from contracts
generate-api-client:
	cd frontend && npm run generate:api

# Build all Python service artifacts (dependency-complete) into dist/
build:
	python3 platform/build/package_all.py

# Package + validate the customer root template.
# `sam validate` needs a region even though it makes no AWS calls — without one
# it exits "AWS Region was not found", which made this target fail on any machine
# without a configured default profile (found during Build and Test, 2026-08-05).
# Override with:  make package AWS_REGION=eu-west-1
AWS_REGION ?= us-east-1
package:
	sam validate -t infra/root-template.yaml --region $(AWS_REGION)
	cfn-lint infra/root-template.yaml

clean:
	rm -rf dist .aws-sam **/__pycache__ .pytest_cache
	rm -rf services/*/build
