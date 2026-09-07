"""Event consumer tests (NFR-FO-MAINT-1 suite 4).

GroupHardDeleted → mark PURGING; GroupSoftDeleted → hide; GroupRestored → unhide.
All idempotent on redelivery.
"""
import json

import pytest
from conftest import bridge_event, proxy_event

from app import dispatch


class TestGroupHardDeleted:
    """GroupHardDeleted marks forums as PURGING (content invisible)."""

    def test_marks_forum_purging(self, ctx):
        # Create forum
        resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                                    body={"name": "Forum", "groupId": "g1"}), ctx)
        assert resp["statusCode"] == 201

        # Send GroupHardDeleted
        event = bridge_event("GroupHardDeleted", {"groupId": "g1"})
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200

        # Browse should return empty (forum is PURGING/hidden)
        resp = dispatch(proxy_event("GET", "/forums", role="Member", sub="m1", groups=["g1"]), ctx)
        body = json.loads(resp["body"])
        assert body["count"] == 0

    def test_idempotent_redelivery(self, ctx):
        resp = dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                                    body={"name": "Forum", "groupId": "g1"}), ctx)
        event = bridge_event("GroupHardDeleted", {"groupId": "g1"}, event_id="evt-dup")
        dispatch(event, ctx)
        # Redeliver same event
        resp = dispatch(event, ctx)
        assert resp["statusCode"] == 200  # no error, idempotent


class TestGroupSoftDeleted:
    """GroupSoftDeleted hides forums (reversible)."""

    def test_hides_forum(self, ctx):
        dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                             body={"name": "Forum", "groupId": "g1"}), ctx)
        event = bridge_event("GroupSoftDeleted", {"groupId": "g1"})
        dispatch(event, ctx)

        # Browse returns empty
        resp = dispatch(proxy_event("GET", "/forums", role="Member", sub="m1", groups=["g1"]), ctx)
        assert json.loads(resp["body"])["count"] == 0


class TestGroupRestored:
    """GroupRestored un-hides forums."""

    def test_restores_forum(self, ctx):
        dispatch(proxy_event("POST", "/forums", role="CommunityLeader", sub="cl1",
                             body={"name": "Forum", "groupId": "g1"}), ctx)
        # Hide
        dispatch(bridge_event("GroupSoftDeleted", {"groupId": "g1"}, event_id="e1"), ctx)
        # Verify hidden
        resp = dispatch(proxy_event("GET", "/forums", role="Member", sub="m1", groups=["g1"]), ctx)
        assert json.loads(resp["body"])["count"] == 0
        # Restore
        dispatch(bridge_event("GroupRestored", {"groupId": "g1"}, event_id="e2"), ctx)
        # Verify visible again
        resp = dispatch(proxy_event("GET", "/forums", role="Member", sub="m1", groups=["g1"]), ctx)
        assert json.loads(resp["body"])["count"] == 1
