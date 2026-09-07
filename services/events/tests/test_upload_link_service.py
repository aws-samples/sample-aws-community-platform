"""Event-scoped external upload slots (US-2.21, reworked 2026-08-13).

One slot = one file. No tokens, no portal API endpoint — the CL/UGL uses
Copy Link to mint a fresh presigned S3 PUT URL (60-min), then shares it with
the external contributor who PUTs directly to S3.
"""
from __future__ import annotations

import pytest
from _conventions.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from conftest import make_event


def _create(ctx, cl, event_id, file_name="deck.pdf", **kw):
    return ctx.upload_links.create(event_id, {"fileName": file_name, **kw}, principal=cl)


def test_create_returns_the_slot(ctx, cl):
    event = make_event(ctx, cl)
    created = _create(ctx, cl, event["id"])
    assert created["fileName"] == "deck.pdf"
    assert created["uploaded"] is False
    assert created["revoked"] is False


def test_s3_key_is_derived_from_event_and_filename(ctx, cl):
    event = make_event(ctx, cl)
    created = _create(ctx, cl, event["id"], file_name="slides.pptx")
    assert created["s3Key"] == f"events/{event['id']}/materials/slides.pptx"


def test_duplicate_filename_rejected(ctx, cl):
    event = make_event(ctx, cl)
    _create(ctx, cl, event["id"], file_name="deck.pdf")
    with pytest.raises(ConflictError):
        _create(ctx, cl, event["id"], file_name="deck.pdf")


def test_duplicate_with_existing_material_rejected(ctx, cl):
    event = make_event(ctx, cl)
    ctx.materials.add(event["id"], {"name": "existing.pdf", "kind": "link",
                                     "link": "https://example.com"}, principal=cl)
    with pytest.raises(ConflictError):
        _create(ctx, cl, event["id"], file_name="existing.pdf")


def test_copy_link_returns_presigned_put_and_curl(ctx, cl):
    event = make_event(ctx, cl)
    created = _create(ctx, cl, event["id"], file_name="slides.pdf")
    result = ctx.upload_links.get_upload_url(event["id"], created["id"], principal=cl)
    assert result["url"].startswith("https://")
    assert result["fileName"] == "slides.pdf"
    assert "curl" in result
    assert "slides.pdf" in result["curl"]
    assert result["expiresInSeconds"] == 3600


def test_copy_link_on_revoked_slot_denied(ctx, cl):
    event = make_event(ctx, cl)
    created = _create(ctx, cl, event["id"])
    ctx.upload_links.revoke(event["id"], created["id"], principal=cl)
    with pytest.raises(ForbiddenError):
        ctx.upload_links.get_upload_url(event["id"], created["id"], principal=cl)


def test_revoked_slot_listed_as_revoked(ctx, cl):
    event = make_event(ctx, cl)
    created = _create(ctx, cl, event["id"])
    ctx.upload_links.revoke(event["id"], created["id"], principal=cl)
    listed = ctx.upload_links.list_for_event(event["id"], principal=cl)
    assert listed["items"][0]["revoked"] is True


def test_path_traversal_rejected(ctx, cl):
    event = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        _create(ctx, cl, event["id"], file_name="../../evil.txt")


def test_create_and_revoke_are_audited(ctx, cl, events):
    event = make_event(ctx, cl)
    created = _create(ctx, cl, event["id"])
    ctx.upload_links.revoke(event["id"], created["id"], principal=cl)
    audited = [p for p in events.published if p["data"].get("audit")]
    kinds = {p["data"]["kind"] for p in audited}
    assert kinds == {"upload-link-created", "upload-link-revoked"}
