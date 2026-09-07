"""Contract-wide hygiene gates over contracts/services/*/openapi.yaml.

Why this exists: PyYAML resolves a duplicate mapping key by silently keeping the
LAST one. Redocly (used by frontend/scripts/generate-api-client.mjs) rejects it
outright. Nothing in the repo sat between those two behaviours, so a duplicated
`requestBody` in contributions-scoring survived review, quietly narrowed the
documented body for decideSubmission by seven fields, and killed type generation
for every service ordered after it -- the generator walks the directory
alphabetically and aborts the whole run on the first parse failure.

Every tool that reads these files agrees they must parse strictly. This asserts
that in the Python suite, which is the gate that runs on every change.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "services"


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader, but a duplicate mapping key is an error rather than a
    last-one-wins overwrite."""


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                f"duplicate key {key!r} (PyYAML would silently keep the last one)",
                key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def _contracts():
    return sorted(p for p in CONTRACTS.glob("*/openapi.yaml"))


def test_contracts_exist():
    assert _contracts(), f"no contracts found under {CONTRACTS}"


@pytest.mark.parametrize("path", _contracts(), ids=lambda p: p.parent.name)
def test_contract_has_no_duplicate_keys(path):
    """A duplicate key does not fail loudly -- it changes the contract's meaning
    and breaks codegen for unrelated services. Fail here instead."""
    try:
        yaml.load(path.read_text(), Loader=_StrictLoader)
    except yaml.constructor.ConstructorError as err:
        mark = err.problem_mark
        pytest.fail(
            f"{path.relative_to(CONTRACTS.parents[1])}: {err.problem} "
            f"at line {mark.line + 1} column {mark.column + 1}")


@pytest.mark.parametrize("path", _contracts(), ids=lambda p: p.parent.name)
def test_every_operation_has_a_unique_operation_id(path):
    """Duplicate operationIds are the other way codegen silently drops routes."""
    spec = yaml.load(path.read_text(), Loader=_StrictLoader)
    seen: dict[str, str] = {}
    for route, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for verb, op in methods.items():
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            op_id = op["operationId"]
            where = f"{verb.upper()} {route}"
            assert op_id not in seen, (
                f"{path.parent.name}: operationId {op_id!r} used by both "
                f"{seen[op_id]} and {where}")
            seen[op_id] = where
