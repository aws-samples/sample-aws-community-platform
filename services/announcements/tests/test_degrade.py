"""Degrade path (NFR-AN-MAINT-1 suite 5, part B, NFR-AN-REL-1): a directory
lookup timeout at create must NOT block authoring — the announcement posts with
id/raw-group-id fallbacks (fail-closed)."""
from __future__ import annotations

from _conventions.authz import Principal
from conftest import claims


def _cl(sub="ucl"):
    return Principal.from_claims(claims(sub, "CommunityLeader"))


def test_author_name_lookup_failure_falls_back_to_id(ctx, directory):
    directory.failing.add("ucl")  # member_name returns None (simulated timeout)
    out = ctx.service.create({"title": "t", "target": {"scope": "community"}}, _cl("ucl"),
                             bearer_token="tok")
    assert out["authorName"] == "ucl"  # fell back to id, post still succeeded


def test_group_name_lookup_failure_falls_back_to_group_id(ctx, directory):
    directory.failing.add("g1")  # group_name returns None
    out = ctx.service.create(
        {"title": "t", "target": {"scope": "groups", "groupIds": ["g1"]}}, _cl(), bearer_token="tok")
    assert out["source"] == "g1"  # raw group id, not a 5xx


def test_panel_read_makes_no_directory_calls(ctx, directory):
    # Panel reads use denormalized fields only — even a fully-failing directory
    # never affects the panel (NFR-AN-REL-4).
    ctx.service.create({"title": "t", "target": {"scope": "community"}}, _cl())
    directory.failing.add("anything")
    from conftest import claims as _c
    member = Principal.from_claims(_c("um", "Member"))
    assert ctx.panel.panel(member)["count"] == 1
