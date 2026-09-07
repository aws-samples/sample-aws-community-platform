"""Materials, the malware-scan gate, and the Content Library (US-2.15/2.20)."""
from __future__ import annotations

import pytest
from _conventions.errors import ConflictError, ValidationError
from conftest import make_event, make_past_event


def _file_material(ctx, event_id, cl, name="Slides.pptx"):
    target = ctx.materials.upload_url(
        event_id, {"fileName": name, "sizeBytes": 1024}, principal=cl)
    return ctx.materials.add(event_id, {"name": name, "kind": "file",
                                        "s3Key": target["key"]}, principal=cl)


# ---------------------------------------------------------------- upload gate

def test_upload_url_rejects_disallowed_extension(ctx, cl):
    """BR-M4 — validation happens BEFORE minting, so a disallowed type never
    receives an upload target at all."""
    event = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.materials.upload_url(event["id"], {"fileName": "payload.exe", "sizeBytes": 10},
                                 principal=cl)


def test_upload_url_rejects_oversized_file(ctx, cl):
    event = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.materials.upload_url(
            event["id"], {"fileName": "big.mp4", "sizeBytes": 600 * 1024 * 1024},
            principal=cl)


def test_upload_url_rejects_path_separators(ctx, cl):
    event = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.materials.upload_url(
            event["id"], {"fileName": "../../etc/passwd.pdf", "sizeBytes": 10},
            principal=cl)


def test_upload_url_key_is_scoped_to_the_event(ctx, cl):
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Agenda.pdf", "sizeBytes": 100}, principal=cl)
    assert target["key"] == f"events/{event['id']}/materials/Agenda.pdf"
    assert target["url"].startswith("https://")


# -------------------------------------------------------------------- add/edit

def test_link_material_needs_https(ctx, cl):
    event = make_event(ctx, cl)
    with pytest.raises(ValidationError):
        ctx.materials.add(event["id"], {"name": "Rec", "kind": "link",
                                        "link": "http://insecure.test/x"}, principal=cl)


def test_file_material_derives_key_from_name(ctx, cl):
    """2026-08-12 security fix: s3Key is derived server-side, never client-supplied."""
    event = make_event(ctx, cl)
    mat = ctx.materials.add(event["id"], {"name": "Slides.pptx", "kind": "file"},
                            principal=cl)
    # s3Key is internal (not in the public response) — read from the repo directly.
    stored = ctx.repo.list_materials(event["id"])
    file_mat = [m for m in stored if m.get("name") == "Slides.pptx"][0]
    assert file_mat["s3Key"] == f"events/{event['id']}/materials/Slides.pptx"


def test_duplicate_material_name_is_conflict(ctx, cl):
    event = make_event(ctx, cl)
    ctx.materials.add(event["id"], {"name": "Agenda", "link": "https://e.test/a"},
                      principal=cl)
    with pytest.raises(ConflictError):
        ctx.materials.add(event["id"], {"name": "Agenda", "link": "https://e.test/b"},
                          principal=cl)


def test_link_material_is_immediately_clean(ctx, cl):
    """A link has no bytes in the bucket, so there is nothing to scan."""
    event = make_event(ctx, cl)
    material = ctx.materials.add(event["id"], {"name": "Repo", "link": "https://e.test/r"},
                                 principal=cl)
    assert material["scanState"] == "Clean"
    assert material["uploaded"] is True


def test_file_material_starts_pending_scan(ctx, cl):
    event = make_event(ctx, cl)
    material = _file_material(ctx, event["id"], cl)
    assert material["scanState"] == "PendingScan"


def test_replaced_file_returns_to_pending_scan(ctx, cl):
    """Replacement means new bytes, so the previous clean verdict no longer
    applies."""
    event = make_event(ctx, cl)
    material = _file_material(ctx, event["id"], cl)
    ctx.repo.set_material_scan_state(event["id"], material["id"], "Clean")
    updated = ctx.materials.replace(
        event["id"], material["id"],
        {"name": "Slides.pptx", "s3Key": f"events/{event['id']}/materials/Slides.pptx"},
        principal=cl)
    assert updated["scanState"] == "PendingScan"


def test_post_event_material_notifies(ctx, cl, events):
    """BR-M5 — only POST-event materials notify; pre-event uploads are routine
    preparation and would spam RSVPs."""
    event = make_past_event(ctx, cl)
    ctx.materials.add(event["id"], {"name": "Recording", "link": "https://e.test/rec"},
                      principal=cl)
    assert events.of_type("MaterialsAdded")


def test_pre_event_material_does_not_notify(ctx, cl, events):
    event = make_event(ctx, cl)
    ctx.materials.add(event["id"], {"name": "Agenda", "link": "https://e.test/a"},
                      principal=cl)
    assert events.of_type("MaterialsAdded") == []


# ----------------------------------------------------------------- scan gate

def test_pending_material_hidden_from_members(ctx, cl, member):
    event = make_event(ctx, cl)
    _file_material(ctx, event["id"], cl)
    assert ctx.materials.list_for_event(event["id"], principal=member)["count"] == 0


def test_pending_material_visible_to_managers(ctx, cl):
    """A manager can see it so somebody who can act on the problem knows it
    exists."""
    event = make_event(ctx, cl)
    _file_material(ctx, event["id"], cl)
    assert ctx.materials.list_for_event(event["id"], principal=cl)["count"] == 1


def test_quarantined_material_hidden_from_members(ctx, cl, member):
    event = make_event(ctx, cl)
    material = _file_material(ctx, event["id"], cl)
    ctx.repo.set_material_scan_state(event["id"], material["id"], "Quarantined")
    assert ctx.materials.list_for_event(event["id"], principal=member)["count"] == 0


def test_clean_material_gets_a_download_url(ctx, cl, member, aws):
    event = make_event(ctx, cl)
    material = _file_material(ctx, event["id"], cl)
    ctx.repo.set_material_scan_state(event["id"], material["id"], "Clean")
    ctx.repo.set_material_upload_state(event["id"], material["id"],
                                       size_bytes=1024, uploaded_at="2027-06-01T00:00:00Z")
    listed = ctx.materials.list_for_event(event["id"], principal=member)
    assert listed["items"][0]["downloadUrl"].startswith("https://")


# ----------------------------------------------------------------- removal

def test_remove_deletes_object_then_row(ctx, cl, aws):
    event = make_event(ctx, cl)
    material = _file_material(ctx, event["id"], cl)
    aws.s3.put_object(Bucket=aws.bucket, Key=material["id"] and
                      f"events/{event['id']}/materials/Slides.pptx", Body=b"x")
    ctx.materials.remove(event["id"], material["id"], principal=cl)
    assert ctx.repo.get_material(event["id"], material["id"]) is None


def test_remove_unknown_material_is_not_found(ctx, cl):
    from _conventions.errors import NotFoundError
    event = make_event(ctx, cl)
    with pytest.raises(NotFoundError):
        ctx.materials.remove(event["id"], "mat-nope", principal=cl)


def test_materials_frozen_on_cancelled_event(ctx, cl):
    event = make_event(ctx, cl)
    ctx.event_service.cancel(event["id"], principal=cl)
    with pytest.raises(ConflictError):
        ctx.materials.add(event["id"], {"name": "X", "link": "https://e.test/x"},
                          principal=cl)


def test_materials_can_be_added_after_completion(ctx, cl):
    """BR-M1 — post-event recordings are the main use case, so a completed event
    must still accept materials."""
    event = make_past_event(ctx, cl)
    ctx.event_service.complete(event["id"], principal=cl)
    added = ctx.materials.add(event["id"], {"name": "Recording", "link": "https://e.test/r"},
                              principal=cl)
    assert added["postEvent"] is True


# --------------------------------------------- presign scheme (2026-08-07 fix)

def test_upload_url_is_sigv4_and_signs_the_declared_length(ctx, cl):
    """Regression for the live UGL 403 (2026-08-07): the default boto3 presign
    is legacy SigV2, which signs Content-Type as EMPTY into the string-to-sign.
    Browsers always send the file's Content-Type on a fetch PUT of a File body,
    so every browser upload got 403 SignatureDoesNotMatch (curl -T sends no
    Content-Type, which is why curl-based checks never caught it). A SigV4 URL
    validates only the headers it signed — and the declared size is now one of
    them, so the pre-mint cap is enforced by the URL itself."""
    from urllib.parse import parse_qs, urlparse

    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Deck.pptx", "sizeBytes": 42 * 1024 * 1024},
        principal=cl)
    q = parse_qs(urlparse(target["url"]).query)
    assert q.get("X-Amz-Algorithm") == ["AWS4-HMAC-SHA256"], (
        "presigned PUT must be SigV4 — a SigV2 URL 403s any client that sends "
        "a Content-Type header, i.e. every browser")
    signed = (q.get("X-Amz-SignedHeaders") or [""])[0].split(";")
    assert "content-length" in signed


# ------------------------------------- confirm-time upload race (2026-08-07 fix)

def _put_object(aws, key: str, size: int) -> None:
    import boto3
    boto3.client("s3", region_name="us-east-1").put_object(
        Bucket=aws.bucket, Key=key, Body=b"x" * size)


def test_add_stamps_uploaded_when_the_object_beat_the_confirm(ctx, aws, cl):
    """Regression for the live Member-cannot-download defect (2026-08-07): the
    browser PUT completes BEFORE the confirm POST, so S3's Object Created event
    can arrive while no material row exists — the consumer drops it and no
    second event ever comes. The confirm step must discover the already-landed
    object itself, or the material stays uploaded=false (and undownloadable)
    forever. The stamped size must be S3's, not the client's declaration."""
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Deck.pptx", "sizeBytes": 999}, principal=cl)
    _put_object(aws, target["key"], 4096)  # actual object: a different size

    material = ctx.materials.add(
        event["id"], {"name": "Deck.pptx", "kind": "file", "s3Key": target["key"]},
        principal=cl)
    assert material["uploaded"] is True
    assert material["sizeBytes"] == 4096  # S3's truth, not the declared 999

    # Once the scan verdict lands, the member-facing listing must offer a URL.
    ctx.repo.set_material_scan_state(event["id"], material["id"], "Clean")
    listed = ctx.materials.list_for_event(event["id"], principal=cl)["items"]
    assert listed[0]["downloadUrl"].startswith("https://")


def test_add_without_a_landed_object_still_defers_to_the_consumer(ctx, cl):
    """The other ordering is unchanged: confirm first, object event later."""
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Later.pdf", "sizeBytes": 10}, principal=cl)
    material = ctx.materials.add(
        event["id"], {"name": "Later.pdf", "kind": "file", "s3Key": target["key"]},
        principal=cl)
    assert material["uploaded"] is False
    assert material["sizeBytes"] is None


# ------------------------------- reserve-then-confirm race (2026-09-04 fix)

def test_upload_url_reserves_the_material_row_before_the_upload(ctx, cl):
    """The row must exist as soon as the URL is minted — before the browser PUT —
    so an Object Created event or a fast GuardDuty verdict has somewhere to land.
    Previously the row was created only by the confirm call, after the upload."""
    event = make_event(ctx, cl)
    ctx.materials.upload_url(
        event["id"], {"fileName": "Slides.pptx", "sizeBytes": 10}, principal=cl)
    stored = ctx.repo.list_materials(event["id"])
    reserved = [m for m in stored if m.get("name") == "Slides.pptx"]
    assert len(reserved) == 1
    assert reserved[0]["kind"] == "file"
    assert reserved[0]["uploaded"] is False
    assert reserved[0]["scanState"] == "PendingScan"
    assert reserved[0]["s3Key"] == f"events/{event['id']}/materials/Slides.pptx"


def test_verdict_arriving_before_confirm_is_not_lost(ctx, aws, cl):
    """THE bug this fix exists for. GuardDuty scans on the PUT; for a small file
    the verdict can arrive (and be consumed) BEFORE the confirm POST runs. With
    the row reserved at upload_url time, the verdict lands on it — and the later
    confirm must NOT reset scanState back to PendingScan."""
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Deck.pptx", "sizeBytes": 10}, principal=cl)
    _put_object(aws, target["key"], 4096)

    # Verdict is delivered through the real consumer BEFORE confirm — it finds
    # the reserved row (no more "unknown material" drop).
    ctx.scan_consumer.handle(
        {"id": "evt-race", "detail-type": "GuardDuty Malware Protection Object Scan Result",
         "detail": {"s3ObjectDetails": {"objectKey": target["key"]},
                    "scanResultDetails": {"scanResultStatus": "NO_THREATS_FOUND"}}})
    stored = [m for m in ctx.repo.list_materials(event["id"]) if m["name"] == "Deck.pptx"][0]
    assert stored["scanState"] == "Clean", "verdict must land on the reserved row"

    # The confirm arrives late and must PRESERVE the Clean verdict while stamping
    # uploaded — not clobber it back to PendingScan.
    material = ctx.materials.add(
        event["id"], {"name": "Deck.pptx", "kind": "file", "s3Key": target["key"]},
        principal=cl)
    assert material["scanState"] == "Clean"
    assert material["uploaded"] is True
    assert material["sizeBytes"] == 4096


def test_re_requesting_the_upload_url_reuses_the_reserved_row(ctx, cl):
    """A retry (same file re-picked) must not orphan a second row."""
    event = make_event(ctx, cl)
    a = ctx.materials.upload_url(
        event["id"], {"fileName": "Slides.pptx", "sizeBytes": 10}, principal=cl)
    b = ctx.materials.upload_url(
        event["id"], {"fileName": "Slides.pptx", "sizeBytes": 20}, principal=cl)
    assert a["materialId"] == b["materialId"]
    assert len([m for m in ctx.repo.list_materials(event["id"])
                if m["name"] == "Slides.pptx"]) == 1


def test_upload_url_conflicts_with_an_existing_link_name(ctx, cl):
    """A name already owned by a link cannot be reused for a file upload."""
    event = make_event(ctx, cl)
    # A link may carry any name, including one that looks like a filename.
    ctx.materials.add(event["id"], {"name": "Deck.pdf", "link": "https://e.test/d"},
                      principal=cl)
    with pytest.raises(ConflictError):
        ctx.materials.upload_url(event["id"], {"fileName": "Deck.pdf", "sizeBytes": 10},
                                 principal=cl)


def test_upload_url_conflicts_with_an_already_uploaded_file(ctx, aws, cl):
    """Once a file with this name is uploaded, the name is taken — a second
    upload_url for it is a conflict, not a silent overwrite."""
    event = make_event(ctx, cl)
    target = ctx.materials.upload_url(
        event["id"], {"fileName": "Deck.pptx", "sizeBytes": 10}, principal=cl)
    _put_object(aws, target["key"], 512)
    ctx.materials.add(event["id"], {"name": "Deck.pptx", "kind": "file",
                                    "s3Key": target["key"]}, principal=cl)
    with pytest.raises(ConflictError):
        ctx.materials.upload_url(event["id"], {"fileName": "Deck.pptx", "sizeBytes": 10},
                                 principal=cl)


def test_replace_stamps_uploaded_but_scan_state_is_still_pending(ctx, aws, cl):
    """replace() has the same race; new bytes still need a new verdict.
    2026-08-12: s3Key is derived server-side from the material name (security fix)."""
    event = make_event(ctx, cl)
    original = _file_material(ctx, event["id"], cl, name="V1.pptx")
    # The replaced file's key is derived from its name; upload the bytes there.
    replace_key = f"events/{event['id']}/materials/V1.pptx"
    _put_object(aws, replace_key, 2048)

    updated = ctx.materials.replace(
        event["id"], original["id"], {"newFile": True},
        principal=cl)
    assert updated["uploaded"] is True
    assert updated["sizeBytes"] == 2048
    assert updated["scanState"] == "PendingScan"
