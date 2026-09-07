"""Guards the public/private route split in gen_api_edge.py.

The whole security argument for GET /internal/settings is structural: the route
carries no Cognito authorizer, so if it were ever emitted into the internet-facing
API it would be an open read of admin config. These tests assert that cannot
happen, and that the public API's unauthenticated surface does not grow silently.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

yaml = pytest.importorskip("yaml")

TOOLS = pathlib.Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))

import gen_api_edge  # noqa: E402


class _CfnLoader(yaml.SafeLoader):
    """CloudFormation intrinsics (!Ref, !Sub) are not standard YAML tags."""


_CfnLoader.add_multi_constructor("!", lambda loader, suffix, node: {"__tag__": suffix})


@pytest.fixture(scope="module")
def apis():
    doc = yaml.load(gen_api_edge.build(), Loader=_CfnLoader)
    res = doc["Resources"]
    return (res["Api"]["Properties"]["DefinitionBody"]["paths"],
            res["PrivateApi"]["Properties"]["DefinitionBody"]["paths"])


def _bases(paths) -> set[str]:
    return {p.split("/")[1] for p in paths}


def test_private_only_bases_are_absent_from_the_public_api(apis):
    public, _ = apis
    for base in gen_api_edge.PRIVATE_ONLY_BASES:
        assert base not in _bases(public), (
            f"/{base} carries no authorizer and MUST NOT exist on the public API")


def test_private_only_bases_are_present_on_the_private_api(apis):
    _, private = apis
    for base in gen_api_edge.PRIVATE_ONLY_BASES:
        assert base in _bases(private)
        assert f"/{base}" in private
        assert f"/{base}/{{proxy+}}" in private


def test_the_two_apis_differ_by_exactly_the_private_only_bases(apis):
    public, private = apis
    extra = set(private) - set(public)
    expected = {f"/{b}" for b in gen_api_edge.PRIVATE_ONLY_BASES} | {
        f"/{b}/{{proxy+}}" for b in gen_api_edge.PRIVATE_ONLY_BASES}
    assert extra == expected
    assert not set(public) - set(private), "the private API must serve every public route"


def test_private_api_is_actually_private(apis):
    doc = yaml.load(gen_api_edge.build(), Loader=_CfnLoader)
    cfg = doc["Resources"]["PrivateApi"]["Properties"]["EndpointConfiguration"]
    assert cfg["Type"] == "PRIVATE"
    assert cfg["VPCEndpointIds"], "a PRIVATE API with no VPCE binding is unreachable"


def test_private_only_routes_carry_no_cognito_authorizer(apis):
    """Deliberate: the callers are same-account Lambdas with no JWT. Recorded as a
    test so it reads as a decision rather than an oversight."""
    _, private = apis
    for base in gen_api_edge.PRIVATE_ONLY_BASES:
        for path in (f"/{base}", f"/{base}/{{proxy+}}"):
            method = private[path]["x-amazon-apigateway-any-method"]
            assert "security" not in method


def test_public_and_private_only_base_sets_are_disjoint():
    assert not (gen_api_edge.PUBLIC_BASES & gen_api_edge.PRIVATE_ONLY_BASES)


def test_unauthenticated_public_surface_is_pinned(apis):
    """Any new unauthenticated internet route must land here deliberately."""
    public, _ = apis
    open_bases = {
        p.split("/")[1] for p, item in public.items()
        if "security" not in item.get("x-amazon-apigateway-any-method", {})
    }
    assert open_bases == {"auth", "public", "event-uploads"}


def test_generated_file_on_disk_is_current():
    """api-edge.yaml is generated and committed; a stale copy is what actually
    ships, so drift must fail here rather than at deploy time."""
    on_disk = (REPO / "infra" / "api-edge.yaml").read_text()
    assert on_disk == gen_api_edge.build(), (
        "infra/api-edge.yaml is stale — re-run: python3 infra/tools/gen_api_edge.py")
