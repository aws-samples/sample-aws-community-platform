"""FileShareService tests (US-8.13, reworked 2026-08-04 — one link = one file slot;
fresh 1h presigned PUT minted at Copy-Link time; curl-only upload; no expiry)."""
import pytest
from _conventions.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from conftest import BUCKET_NAME


def _create(ctx, folder="event-materials", file_name="deck.pdf", actor="u-cl", role="CommunityLeader"):
    return ctx.file_share_service.create_link(
        {"folder": folder, "fileName": file_name}, actor=actor, role=role)


def _s3_event(detail_type, key, *, size=0, time="2026-08-04T10:00:00Z", event_id=None):
    """An EventBridge envelope shaped like an S3 notification. Keys arrive
    URL-encoded from S3."""
    from urllib.parse import quote_plus
    return {
        "id": event_id or f"evt-{detail_type}-{key}-{time}",
        "detail-type": detail_type,
        "source": "aws.s3",
        "time": time,
        "detail": {"bucket": {"name": BUCKET_NAME},
                   "object": {"key": quote_plus(key, safe="/"), "size": size}},
    }


# ---------- create ----------

def test_create_slot_as_community_leader(ctx):
    out = _create(ctx)
    assert out["folder"] == "event-materials"
    assert out["fileName"] == "deck.pdf"
    assert out["key"] == "event-materials/deck.pdf"
    assert out["revoked"] is False
    assert "url" not in out  # nothing long-lived is stored or returned at creation


def test_create_slot_as_user_group_leader(ctx):
    out = _create(ctx, actor="u-ugl", role="UserGroupLeader")
    assert out["createdBy"] == "u-ugl"


def test_create_rejects_member_role(ctx):
    with pytest.raises(ForbiddenError):
        _create(ctx, actor="u-mem", role="Member")


def test_create_rejects_bad_folder_chars(ctx):
    with pytest.raises(ValidationError):
        _create(ctx, folder="bad/folder")


def test_create_rejects_filename_with_slash(ctx):
    with pytest.raises(ValidationError):
        _create(ctx, file_name="a/b.pdf")


def test_create_requires_filename(ctx):
    with pytest.raises(ValidationError):
        ctx.file_share_service.create_link({"folder": "x"}, actor="u-cl", role="CommunityLeader")


def test_create_duplicate_filename_in_folder_conflicts(ctx):
    _create(ctx)
    with pytest.raises(ConflictError):
        _create(ctx, actor="u-ugl", role="UserGroupLeader")  # any leader, same folder+file


def test_create_same_filename_other_folder_ok(ctx):
    _create(ctx)
    out = _create(ctx, folder="other-folder")
    assert out["key"] == "other-folder/deck.pdf"


def test_create_conflicts_with_existing_s3_object(ctx, aws):
    aws.s3.put_object(Bucket=BUCKET_NAME, Key="event-materials/deck.pdf", Body=b"x")
    with pytest.raises(ConflictError):
        _create(ctx)


def test_deactivated_slot_still_holds_the_name(ctx):
    """Behavior change 2026-08-04 (perf rework): a DEACTIVATED slot keeps its
    claim. Freeing it let two records own one S3 key — the newer slot's upload
    would overwrite the file the deactivated slot still serves via Open, and the
    S3 event consumer could not resolve the key to a single slot. Delete frees
    the name (and removes the file)."""
    link = _create(ctx)
    ctx.file_share_service.revoke_link(link["id"], actor="u-cl", role="CommunityLeader")
    with pytest.raises(ConflictError) as err:
        _create(ctx)
    assert "deactivated" in str(err.value.message).lower()


def test_create_records_creator_email(ctx):
    out = ctx.file_share_service.create_link(
        {"folder": "f", "fileName": "d.pdf"}, actor="u-cl", role="CommunityLeader",
        actor_email="Leader@Example.com")
    assert out["createdByEmail"] == "Leader@Example.com"


# ---------- list ----------

def test_list_links_cl_sees_all(ctx):
    _create(ctx, folder="a", file_name="1.pdf")
    _create(ctx, folder="b", file_name="2.pdf", actor="u-ugl", role="UserGroupLeader")
    out = ctx.file_share_service.list_links(actor="u-cl", role="CommunityLeader")
    assert out["count"] == 2


def test_list_links_reports_stored_uploaded_flag(ctx):
    """`uploaded` is a STORED field written by the S3 event consumer (perf
    rework 2026-08-04) — the listing no longer inspects the bucket."""
    a = _create(ctx, folder="f", file_name="present.pdf")
    _create(ctx, folder="f", file_name="missing.pdf")
    ctx.file_share_events.handle(_s3_event("Object Created", "f/present.pdf", size=7))
    out = ctx.file_share_service.list_links(actor="u-cl", role="CommunityLeader")
    flags = {i["fileName"]: i["uploaded"] for i in out["items"]}
    assert flags == {"present.pdf": True, "missing.pdf": False}
    assert a["id"]  # slot ids intact


def test_list_links_makes_no_s3_calls(ctx, monkeypatch):
    """The whole point of the rework: page latency must not depend on how many
    folders the result set spans."""
    _create(ctx, folder="a", file_name="1.pdf")
    _create(ctx, folder="b", file_name="2.pdf")

    def _boom(*_a, **_k):
        raise AssertionError("list_links must not call S3")

    monkeypatch.setattr(ctx.storage, "list_folder", _boom)
    monkeypatch.setattr(ctx.storage, "list_top_level_folders", _boom)
    out = ctx.file_share_service.list_links(actor="u-cl", role="CommunityLeader")
    assert out["count"] == 2


def test_list_links_rejects_non_leader(ctx):
    """Members used to fall through to the non-CL branch and get an empty 200."""
    with pytest.raises(ForbiddenError):
        ctx.file_share_service.list_links(actor="u-mem", role="Member")


def test_list_links_ugl_sees_own_only(ctx):
    _create(ctx, folder="a", file_name="1.pdf")
    _create(ctx, folder="b", file_name="2.pdf", actor="u-ugl", role="UserGroupLeader")
    out = ctx.file_share_service.list_links(actor="u-ugl", role="UserGroupLeader")
    assert out["count"] == 1
    assert out["items"][0]["folder"] == "b"


# ---------- folders ----------

def test_list_folders_unions_records_and_bucket_prefixes(ctx, aws):
    _create(ctx, folder="from-record", file_name="a.pdf")
    aws.s3.put_object(Bucket=BUCKET_NAME, Key="from-bucket/old.txt", Body=b"x")
    out = ctx.file_share_service.list_folders(actor="u-cl", role="CommunityLeader")
    assert out["bucket"] == BUCKET_NAME
    assert "from-record" in out["folders"]
    assert "from-bucket" in out["folders"]


def test_list_folders_rejects_member(ctx):
    with pytest.raises(ForbiddenError):
        ctx.file_share_service.list_folders(actor="u-mem", role="Member")


# ---------- upload-url (Copy Link) ----------

def test_upload_url_returns_fresh_presign_and_curl(ctx):
    link = _create(ctx)
    out = ctx.file_share_service.get_upload_url(link["id"], actor="u-cl", role="CommunityLeader")
    assert out["key"] == "event-materials/deck.pdf"
    assert out["expiresInSeconds"] == 3600
    assert out["url"].startswith("https://")
    assert out["curl"].startswith('curl -X PUT --upload-file "deck.pdf" "https://')
    assert out["url"] in out["curl"]


def test_upload_url_is_never_stored_on_the_record(ctx):
    # The defect being fixed: the old model persisted a presigned URL at
    # creation. The record must carry no URL — every copy mints fresh.
    link = _create(ctx)
    ctx.file_share_service.get_upload_url(link["id"], actor="u-cl", role="CommunityLeader")
    stored = ctx.repo.get_file_share_link(link["id"])
    assert "url" not in stored


def test_upload_url_blocked_after_revoke(ctx):
    link = _create(ctx)
    ctx.file_share_service.revoke_link(link["id"], actor="u-cl", role="CommunityLeader")
    with pytest.raises(ForbiddenError):
        ctx.file_share_service.get_upload_url(link["id"], actor="u-cl", role="CommunityLeader")


def test_upload_url_ugl_cannot_use_others_slot(ctx):
    link = _create(ctx)  # created by u-cl
    with pytest.raises(ForbiddenError):
        ctx.file_share_service.get_upload_url(link["id"], actor="u-ugl", role="UserGroupLeader")


def test_upload_url_cl_can_use_any_slot(ctx):
    link = _create(ctx, actor="u-ugl", role="UserGroupLeader")
    out = ctx.file_share_service.get_upload_url(link["id"], actor="u-cl", role="CommunityLeader")
    assert out["fileName"] == "deck.pdf"


def test_upload_url_unknown_slot_raises_not_found(ctx):
    with pytest.raises(NotFoundError):
        ctx.file_share_service.get_upload_url("share-ghost", actor="u-cl", role="CommunityLeader")


# ---------- files (Open) ----------

def test_list_files_returns_objects_with_download_urls(ctx, aws):
    link = _create(ctx)
    aws.s3.put_object(Bucket=BUCKET_NAME, Key="event-materials/deck.pdf", Body=b"data")
    aws.s3.put_object(Bucket=BUCKET_NAME, Key="event-materials/extra.txt", Body=b"more")
    out = ctx.file_share_service.list_files(link["id"], actor="u-cl", role="CommunityLeader")
    assert out["count"] == 2
    names = {f["name"] for f in out["items"]}
    assert names == {"deck.pdf", "extra.txt"}
    assert all(f["downloadUrl"].startswith("https://") for f in out["items"])
    assert all(f["sizeBytes"] > 0 for f in out["items"])


def test_list_files_allowed_on_deactivated_slot(ctx, aws):
    # Deactivation stops uploads but keeps files — owners can still view/download.
    link = _create(ctx)
    aws.s3.put_object(Bucket=BUCKET_NAME, Key="event-materials/deck.pdf", Body=b"data")
    ctx.file_share_service.revoke_link(link["id"], actor="u-cl", role="CommunityLeader")
    out = ctx.file_share_service.list_files(link["id"], actor="u-cl", role="CommunityLeader")
    assert out["count"] == 1


def test_list_files_ugl_cannot_view_others_slot(ctx):
    link = _create(ctx)  # created by u-cl
    with pytest.raises(ForbiddenError):
        ctx.file_share_service.list_files(link["id"], actor="u-ugl", role="UserGroupLeader")


# ---------- delete (hard delete: link + file) ----------

def test_delete_removes_record_and_file(ctx, aws):
    link = _create(ctx)
    aws.s3.put_object(Bucket=BUCKET_NAME, Key="event-materials/deck.pdf", Body=b"data")
    ctx.file_share_service.delete_link(link["id"], actor="u-cl", role="CommunityLeader")
    assert ctx.repo.get_file_share_link(link["id"]) is None  # row gone from listing
    keys = [o["Key"] for o in aws.s3.list_objects_v2(
        Bucket=BUCKET_NAME, Prefix="event-materials/").get("Contents", [])]
    assert "event-materials/deck.pdf" not in keys  # file gone from the bucket


def test_delete_works_when_no_file_was_uploaded(ctx):
    link = _create(ctx)
    ctx.file_share_service.delete_link(link["id"], actor="u-cl", role="CommunityLeader")
    assert ctx.repo.get_file_share_link(link["id"]) is None


def test_delete_ugl_cannot_delete_others(ctx):
    link = _create(ctx)  # created by u-cl
    with pytest.raises(ForbiddenError):
        ctx.file_share_service.delete_link(link["id"], actor="u-ugl", role="UserGroupLeader")


def test_delete_unknown_raises_not_found(ctx):
    with pytest.raises(NotFoundError):
        ctx.file_share_service.delete_link("share-ghost", actor="u-cl", role="CommunityLeader")


def test_delete_frees_the_filename_for_reuse(ctx):
    link = _create(ctx)
    ctx.file_share_service.delete_link(link["id"], actor="u-cl", role="CommunityLeader")
    out = _create(ctx)  # same folder + fileName, no conflict
    assert out["key"] == "event-materials/deck.pdf"


# ---------- revoke (Deactivate) ----------

def test_revoke_by_creator(ctx):
    link = _create(ctx, actor="u-ugl", role="UserGroupLeader")
    out = ctx.file_share_service.revoke_link(link["id"], actor="u-ugl", role="UserGroupLeader")
    assert out["revoked"] is True


def test_revoke_ugl_cannot_revoke_others(ctx):
    link = _create(ctx, actor="u-ugl-1", role="UserGroupLeader")
    with pytest.raises(ForbiddenError):
        ctx.file_share_service.revoke_link(link["id"], actor="u-ugl-2", role="UserGroupLeader")


def test_revoke_cl_can_revoke_any(ctx):
    link = _create(ctx, actor="u-ugl", role="UserGroupLeader")
    out = ctx.file_share_service.revoke_link(link["id"], actor="u-cl", role="CommunityLeader")
    assert out["revoked"] is True


def test_revoke_unknown_link_raises_not_found(ctx):
    with pytest.raises(NotFoundError):
        ctx.file_share_service.revoke_link("share-ghost", actor="u-cl", role="CommunityLeader")


# ---------- S3 event consumer (stored upload state, perf rework 2026-08-04) ----------

def test_object_created_stamps_upload_state(ctx):
    link = _create(ctx)
    ctx.file_share_events.handle(
        _s3_event("Object Created", "event-materials/deck.pdf", size=1234))
    stored = ctx.repo.get_file_share_link(link["id"])
    assert stored["uploaded"] is True
    assert int(stored["sizeBytes"]) == 1234
    assert stored["uploadedAt"] == "2026-08-04T10:00:00Z"


def test_object_deleted_clears_upload_state(ctx):
    link = _create(ctx)
    ctx.file_share_events.handle(_s3_event("Object Created", "event-materials/deck.pdf", size=9))
    ctx.file_share_events.handle(_s3_event("Object Deleted", "event-materials/deck.pdf"))
    stored = ctx.repo.get_file_share_link(link["id"])
    assert stored["uploaded"] is False
    assert "sizeBytes" not in stored
    assert "uploadedAt" not in stored


def test_consumer_decodes_url_encoded_keys(ctx):
    """S3 URL-encodes keys in notifications; a fileName may contain spaces."""
    link = _create(ctx, file_name="quarterly report.pdf")
    ctx.file_share_events.handle(
        _s3_event("Object Created", "event-materials/quarterly report.pdf", size=5))
    assert ctx.repo.get_file_share_link(link["id"])["uploaded"] is True


def test_consumer_ignores_unclaimed_key(ctx):
    """An object with no owning slot (pre-rework upload) is not an error."""
    ctx.file_share_events.handle(_s3_event("Object Created", "orphan/thing.bin", size=3))


def test_consumer_tolerates_deleted_slot(ctx):
    """Delete releases the pointer AFTER the record, so an event can arrive for a
    key whose slot is already gone."""
    link = _create(ctx)
    ctx.repo.delete_file_share_link(link["id"])
    ctx.file_share_events.handle(_s3_event("Object Created", "event-materials/deck.pdf", size=1))


def test_consumer_drops_stale_created_event(ctx):
    """At-least-once, unordered delivery: a delayed duplicate must not resurrect
    superseded state."""
    link = _create(ctx)
    ctx.file_share_events.handle(_s3_event(
        "Object Created", "event-materials/deck.pdf", size=200, time="2026-08-04T12:00:00Z"))
    ctx.file_share_events.handle(_s3_event(
        "Object Created", "event-materials/deck.pdf", size=100, time="2026-08-04T09:00:00Z"))
    assert int(ctx.repo.get_file_share_link(link["id"])["sizeBytes"]) == 200


# ---------- pagination (Phase C) ----------

def test_cl_listing_paginates_with_cursor(ctx):
    for i in range(5):
        _create(ctx, folder="f", file_name=f"{i}.pdf")
    first = ctx.file_share_service.list_links(actor="u-cl", role="CommunityLeader", limit=2)
    assert first["count"] == 2 and first["cursor"]
    second = ctx.file_share_service.list_links(
        actor="u-cl", role="CommunityLeader", limit=2, cursor=first["cursor"])
    assert second["count"] == 2
    ids = {i["id"] for i in first["items"]} | {i["id"] for i in second["items"]}
    assert len(ids) == 4  # no overlap between pages


def test_ugl_listing_paginates_over_gsi1(ctx):
    for i in range(3):
        _create(ctx, folder="f", file_name=f"{i}.pdf", actor="u-ugl", role="UserGroupLeader")
    _create(ctx, folder="f", file_name="other.pdf")  # another leader's slot
    page = ctx.file_share_service.list_links(actor="u-ugl", role="UserGroupLeader", limit=2)
    assert page["count"] == 2 and page["cursor"]
    rest = ctx.file_share_service.list_links(
        actor="u-ugl", role="UserGroupLeader", limit=2, cursor=page["cursor"])
    assert rest["count"] == 1 and not rest.get("cursor")
    assert all(i["createdBy"] == "u-ugl" for i in page["items"] + rest["items"])


def test_last_page_has_no_cursor(ctx):
    _create(ctx, folder="f", file_name="only.pdf")
    out = ctx.file_share_service.list_links(actor="u-cl", role="CommunityLeader", limit=25)
    assert out["count"] == 1 and "cursor" not in out


def test_invalid_cursor_is_a_client_error(ctx):
    with pytest.raises(ValidationError):
        ctx.file_share_service.list_links(
            actor="u-cl", role="CommunityLeader", limit=10, cursor="!!!not-base64!!!")


def test_cursor_cannot_name_arbitrary_attributes(ctx):
    import base64
    import json
    forged = base64.urlsafe_b64encode(json.dumps({"evil": "x"}).encode()).decode()
    with pytest.raises(ValidationError):
        ctx.file_share_service.list_links(
            actor="u-cl", role="CommunityLeader", limit=10, cursor=forged)


def test_upload_url_is_sigv4(ctx):
    """Regression shared with Events (2026-08-07): the default boto3 presign is
    legacy SigV2, which signs Content-Type as empty — any client that sends a
    Content-Type header (every browser, curl with --data-binary) gets 403
    SignatureDoesNotMatch. This flow survived only because `curl -T` sends no
    Content-Type."""
    from urllib.parse import parse_qs, urlparse

    link = _create(ctx)
    out = ctx.file_share_service.get_upload_url(link["id"], actor="u-cl", role="CommunityLeader")
    q = parse_qs(urlparse(out["url"]).query)
    assert q.get("X-Amz-Algorithm") == ["AWS4-HMAC-SHA256"]
