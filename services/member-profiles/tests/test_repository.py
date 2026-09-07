"""ProfileRepository tests.

Covers DynamoDB-backed methods (put/get/all_profiles) and the OpenSearch
search_members method via a stub client injected at the _os_client() level.
"""
from __future__ import annotations

import base64
import json

import pytest

from _conventions.errors import ValidationError


# ---------------------------------------------------------------------------
# put_profile / get_profile
# ---------------------------------------------------------------------------

def test_put_and_get_profile(repo):
    repo.put_profile({"id": "u1", "firstName": "A", "lastName": "B",
                      "role": "Member", "status": "active", "groups": []})
    got = repo.get_profile("u1")
    assert got["firstName"] == "A"


def test_get_missing_profile_returns_none(repo):
    assert repo.get_profile("nope") is None


# ---------------------------------------------------------------------------
# all_profiles (CSV export / reindex scan)
# ---------------------------------------------------------------------------

def test_all_profiles_returns_every_profile(repo):
    repo.put_profile({"id": "u1", "firstName": "A", "lastName": "B",
                      "role": "Member", "status": "active", "groups": []})
    repo.put_profile({"id": "u2", "firstName": "C", "lastName": "D",
                      "role": "CommunityLeader", "status": "active", "groups": []})
    profiles = repo.all_profiles()
    assert {p["id"] for p in profiles} == {"u1", "u2"}


def test_all_profiles_includes_inactive(repo):
    """BR-8 — deactivated members are never hard-deleted."""
    repo.put_profile({"id": "u1", "firstName": "A", "lastName": "B",
                      "role": "Member", "status": "inactive", "groups": []})
    assert repo.all_profiles()[0]["status"] == "inactive"


# ---------------------------------------------------------------------------
# search_members — tested via a stub _os_client
# ---------------------------------------------------------------------------

def _make_docs(n):
    docs = []
    for i in range(n):
        docs.append({
            "id": f"u{i:03d}",
            "firstName": f"F{i:03d}",
            "lastName": "L",
            "email": f"u{i:03d}@x.com",
            "role": "Member",
            "status": "active",
            "groups": [],
            "groupIds": [],
            "firstNameNorm": f"f{i:03d}",
            "roleSortOrder": 2,
            "awsProjectSort": 0,
        })
    return docs


class _FakeOs:
    """Minimal OpenSearch stub for search_members tests."""

    def __init__(self, docs):
        self._docs = docs

    def search(self, index, body):  # noqa: ANN001
        size = body.get("size", 25)
        search_after = body.get("search_after")
        # Apply id terms filter if present
        filters = body.get("query", {}).get("bool", {}).get("filter", [])
        id_filter = None
        for f in filters:
            if "terms" in f:
                ids = f["terms"].get("id") or f["terms"].get("id.keyword")
                if ids:
                    id_filter = set(ids)
        docs = [d for d in self._docs if id_filter is None or d["id"] in id_filter]
        # Resume after cursor
        start = 0
        if search_after:
            last_id = search_after[-1]
            for idx, doc in enumerate(docs):
                if doc["id"] == last_id:
                    start = idx + 1
                    break
        page = docs[start: start + size]
        return {"hits": {"hits": [
            {"_source": d, "sort": [d["firstNameNorm"], d["id"]]} for d in page
        ]}}


def test_search_members_returns_empty_without_endpoint(repo):
    """Returns ([], None) when OPENSEARCH_ENDPOINT is unset."""
    items, cursor = repo.search_members(limit=5)
    assert items == []
    assert cursor is None


def test_search_members_paged_cursor_walks_all(repo):
    docs = _make_docs(7)
    repo._os_client = lambda: _FakeOs(docs)
    seen, cursor = [], None
    for _ in range(10):
        items, cursor = repo.search_members(limit=3, cursor=cursor)
        seen.extend(i["id"] for i in items)
        if cursor is None:
            break
    assert len(seen) == 7
    assert len(set(seen)) == 7


def test_search_members_last_page_no_cursor(repo):
    docs = _make_docs(4)
    repo._os_client = lambda: _FakeOs(docs)
    _, c1 = repo.search_members(limit=2)
    items2, c2 = repo.search_members(limit=2, cursor=c1)
    assert len(items2) == 2
    assert c2 is None


def test_search_members_id_filter(repo):
    docs = _make_docs(5)
    repo._os_client = lambda: _FakeOs(docs)
    items, _ = repo.search_members(id_filter={"u001", "u003"}, limit=10)
    assert {i["id"] for i in items} == {"u001", "u003"}


def test_search_members_invalid_cursor_raises_validation_error(repo):
    docs = _make_docs(3)
    repo._os_client = lambda: _FakeOs(docs)
    with pytest.raises(ValidationError):
        repo.search_members(limit=2, cursor="not!!base64")
