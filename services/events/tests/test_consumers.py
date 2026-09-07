"""Event consumers: group soft-delete, S3 objects, GuardDuty scan results."""
from __future__ import annotations

from conftest import make_event, make_past_event

# --------------------------------------------------------- group soft-delete

def test_group_soft_delete_cancels_upcoming(ctx, cl):
    created = make_event(ctx, cl, groupId="g-serverless")
    ctx.group_consumer.handle({"id": "evt-1", "data": {"groupId": "g-serverless"}})
    assert ctx.repo.get_event(created["id"])["status"] == "Cancelled"


def test_group_soft_delete_is_idempotent(ctx, cl):
    """A redelivered event must be acknowledged without re-processing (BR-X4).
    Without the guard the second pass would attempt an illegal
    Cancelled -> Cancelled transition."""
    created = make_event(ctx, cl, groupId="g-serverless")
    envelope = {"id": "evt-dup", "data": {"groupId": "g-serverless"}}
    ctx.group_consumer.handle(envelope)
    ctx.group_consumer.handle(envelope)
    assert ctx.repo.get_event(created["id"])["status"] == "Cancelled"


def test_group_soft_delete_without_group_id_is_ignored(ctx):
    assert ctx.group_consumer.handle({"id": "evt-2", "data": {}})["cancelled"] == 0


# ------------------------------------------------------------------ S3 objects

def _s3_event(key: str, *, size: int = 2048, deleted: bool = False, event_id="evt-s3"):
    return {
        "id": event_id,
        "detail-type": "Object Deleted" if deleted else "Object Created",
        "detail": {"bucket": {"name": "community-files-test"},
                   "object": {"key": key, "size": size}},
    }


def test_object_created_stamps_the_material(ctx, cl):
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Slides.pptx", "sizeBytes": 10}, principal=cl)
    material = ctx.materials.add(
        event["id"], {"name": "Slides.pptx", "kind": "file", "s3Key": target["key"]},
        principal=cl)

    ctx.s3_consumer.handle(_s3_event(target["key"]))
    stored = ctx.repo.get_material(event["id"], material["id"])
    assert stored["uploaded"] is True
    assert int(stored["sizeBytes"]) == 2048


def test_object_deleted_clears_upload_state(ctx, cl):
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Slides.pptx", "sizeBytes": 10}, principal=cl)
    material = ctx.materials.add(
        event["id"], {"name": "Slides.pptx", "kind": "file", "s3Key": target["key"]},
        principal=cl)
    ctx.s3_consumer.handle(_s3_event(target["key"], event_id="a"))
    ctx.s3_consumer.handle(_s3_event(target["key"], deleted=True, event_id="b"))
    assert ctx.repo.get_material(event["id"], material["id"])["uploaded"] is False


def test_other_prefixes_are_ignored(ctx):
    """Settings' file-share folders live in the same bucket. The rule filters by
    prefix (F3), and this is the belt-and-braces check in code."""
    assert "ignored" in ctx.s3_consumer.handle(_s3_event("psa-assets/deck.pdf"))


def test_url_encoded_keys_are_decoded(ctx, cl):
    """S3 event keys are URL-encoded, so `My Slides.pptx` arrives as
    `My+Slides.pptx` and would never match the stored key without decoding."""
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "My Slides.pptx", "sizeBytes": 10}, principal=cl)
    material = ctx.materials.add(
        event["id"], {"name": "My Slides.pptx", "kind": "file", "s3Key": target["key"]},
        principal=cl)
    encoded = target["key"].replace(" ", "+")
    ctx.s3_consumer.handle(_s3_event(encoded))
    assert ctx.repo.get_material(event["id"], material["id"])["uploaded"] is True


def test_object_without_a_material_row_is_tolerated(ctx, cl):
    """An object can legitimately arrive before its metadata row is confirmed."""
    event = make_event(ctx, cl)
    result = ctx.s3_consumer.handle(
        _s3_event(f"events/{event['id']}/materials/orphan.pdf"))
    assert result["eventId"] == event["id"]


def test_upload_recorded_against_its_link(ctx, cl):
    event = make_event(ctx, cl)
    link = ctx.upload_links.create(event["id"], {"fileName": "deck.pdf"}, principal=cl)
    ctx.s3_consumer.handle(_s3_event(f"events/{event['id']}/materials/deck.pdf"))
    files = ctx.repo.list_uploaded_files(event["id"], link["id"])
    assert len(files) == 1
    assert files[0]["name"] == "deck.pdf"


# ----------------------------------------------------------- malware scanning

def _scan_event(key: str, status: str, event_id="evt-scan"):
    return {
        "id": event_id,
        "detail-type": "GuardDuty Malware Protection Object Scan Result",
        "detail": {"s3ObjectDetails": {"objectKey": key},
                   "scanResultDetails": {"scanResultStatus": status}},
    }


def test_clean_scan_marks_material_clean(ctx, cl):
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Slides.pptx", "sizeBytes": 10}, principal=cl)
    material = ctx.materials.add(
        event["id"], {"name": "Slides.pptx", "kind": "file", "s3Key": target["key"]},
        principal=cl)
    ctx.scan_consumer.handle(_scan_event(target["key"], "NO_THREATS_FOUND"))
    assert ctx.repo.get_material(event["id"], material["id"])["scanState"] == "Clean"


def test_threat_quarantines_material_and_raises_an_audit_event(ctx, cl, events):
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Slides.pptx", "sizeBytes": 10}, principal=cl)
    material = ctx.materials.add(
        event["id"], {"name": "Slides.pptx", "kind": "file", "s3Key": target["key"]},
        principal=cl)
    ctx.scan_consumer.handle(_scan_event(target["key"], "THREATS_FOUND"))
    assert ctx.repo.get_material(event["id"], material["id"])["scanState"] == "Quarantined"
    quarantine = [p for p in events.published
                  if p["data"].get("kind") == "material-quarantined"]
    assert quarantine


def test_scan_result_for_another_prefix_is_ignored(ctx):
    assert "ignored" in ctx.scan_consumer.handle(
        _scan_event("psa-assets/deck.pdf", "NO_THREATS_FOUND"))


# ---- Content Library scan promotion (regression: `state` used before assignment)
# The library/ branch referenced the verdict before it was computed, so a scan
# result for a curator/contribution upload raised NameError and the resource
# stayed PendingScan (invisible in search) forever. These lock the fix in.

def _library_consumer_with_mock():
    from unittest.mock import MagicMock
    from consumers import MalwareScanConsumer
    library = MagicMock()
    return MalwareScanConsumer(MagicMock(), MagicMock(), None, library), library


def test_library_prefix_clean_verdict_promotes_resource(ctx):
    consumer, library = _library_consumer_with_mock()
    result = consumer.handle(_scan_event("library/lib-123/deck.pdf", "NO_THREATS_FOUND"))
    library.update_scan_state.assert_called_once_with("lib-123", "Clean")
    assert result["scanState"] == "Clean"


def test_library_prefix_threat_quarantines_resource(ctx):
    consumer, library = _library_consumer_with_mock()
    result = consumer.handle(_scan_event("library/lib-9/evil.pdf", "THREATS_FOUND"))
    library.update_scan_state.assert_called_once_with("lib-9", "Quarantined")
    assert result["scanState"] == "Quarantined"
