"""Expiry (NFR-AN-MAINT-1 suite 3, BR-5/6): mandatory default +2d; clamp +90d;
expired excluded from panel + count but shown Expired in view=mine."""
from __future__ import annotations

from datetime import timedelta

import models
from _conventions.authz import Principal
from conftest import claims


def _cl(sub="ucl"):
    return Principal.from_claims(claims(sub, "CommunityLeader"))


def _member(sub="um", groups=None):
    return Principal.from_claims(claims(sub, "Member", groups or []))


def test_default_expiry_two_days(ctx):
    base = models.now()
    out = ctx.service.create({"title": "t", "target": {"scope": "community"}}, _cl())
    exp = models.parse_iso(out["expiresAt"])
    delta = exp - base
    assert timedelta(days=1, hours=23) < delta < timedelta(days=2, minutes=5)


def test_expiry_clamped_to_90_days(ctx):
    base = models.now()
    far = (base + timedelta(days=365)).isoformat()
    out = ctx.service.create({"title": "t", "target": {"scope": "community"}, "expiresAt": far}, _cl())
    exp = models.parse_iso(out["expiresAt"])
    assert exp <= base + timedelta(days=models.MAX_EXPIRY_DAYS, minutes=1)


def test_past_expiry_rejected(ctx):
    import pytest
    from _conventions.errors import ValidationError
    past = (models.now() - timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError):
        ctx.service.create({"title": "t", "target": {"scope": "community"}, "expiresAt": past}, _cl())


def test_expired_excluded_from_panel_but_shown_in_mine(ctx):
    # Create then force-expire the stored item directly.
    out = ctx.service.create({"title": "old", "target": {"scope": "community"}}, _cl())
    item = ctx.repo.get(out["id"])
    item["expiresAt"] = (models.now() - timedelta(hours=1)).isoformat()
    ctx.repo.put(item)

    panel = ctx.panel.panel(_member())
    assert panel["count"] == 0  # expired excluded from panel + count (BR-6)

    mine = ctx.service.list_mine(_cl())
    assert mine["count"] == 1
    assert mine["items"][0]["status"] == "Expired"
