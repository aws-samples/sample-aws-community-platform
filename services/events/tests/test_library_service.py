"""Unit tests for LibraryService — Content Library rework (US-2.20/2.22–2.26)."""
import pytest
from unittest.mock import MagicMock, patch
from _conventions.errors import ForbiddenError, NotFoundError, ValidationError

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def make_principal(role="Member", user_id="usr-1", name="Alice", groups=None, led=None):
    p = MagicMock()
    p.role = role
    p.user_id = user_id
    p.name = name
    p.member_group_ids = groups or ["g-1"]
    p.led_group_id = led
    return p


def make_cl():
    return make_principal(role="CommunityLeader", user_id="usr-cl")


def make_ugl():
    return make_principal(role="UserGroupLeader", user_id="usr-ugl", led="g-1")


def make_member():
    return make_principal(role="Member", user_id="usr-m1")


def make_admin():
    return make_principal(role="Administrator", user_id="usr-adm")


def _make_service():
    from library_service import LibraryService
    repo = MagicMock()
    events_repo = MagicMock()
    storage = MagicMock()
    storage.presign_get.return_value = "https://s3/presigned"
    storage.presign_put.return_value = "https://s3/put-presigned"
    repo.get_all_tags.return_value = {"serverless", "containers", "security"}
    repo.query_page.return_value = ([], None)
    repo.get_by_contribution_id.return_value = None
    svc = LibraryService(repo, events_repo, storage)
    return svc, repo, events_repo, storage


# ---------------------------------------------------------------------------
# Search (BR-LIB-S1..S10)
# ---------------------------------------------------------------------------

class TestSearch:

    def test_search_first_no_filters_returns_empty(self):
        svc, repo, *_ = _make_service()
        result = svc.search(principal=make_member(), filters={}, limit=10, cursor=None)
        assert result == {"items": [], "count": 0}
        repo.query_page.assert_not_called()

    def test_search_with_keyword_queries_index(self):
        svc, repo, *_ = _make_service()
        repo.query_page.return_value = ([{
            "id": "lib-1", "title": "Serverless Guide", "description": "A guide",
            "format": "Doc", "topics": ["serverless"], "source": "event-material",
            "submittedBy": "usr-x", "addedAt": "2026-08-01T00:00:00Z",
        }], None)
        result = svc.search(principal=make_member(), filters={"q": "serverless"}, limit=10, cursor=None)
        assert result["count"] == 1
        assert result["items"][0]["title"] == "Serverless Guide"

    def test_search_matches_description(self):
        svc, repo, *_ = _make_service()
        repo.query_page.return_value = ([{
            "id": "lib-1", "title": "Guide", "description": "Deep dive into Lambda",
            "format": "Doc", "topics": [], "source": "curator-direct",
            "submittedBy": "usr-x", "addedAt": "2026-08-01T00:00:00Z",
        }], None)
        result = svc.search(principal=make_member(), filters={"q": "lambda"}, limit=10, cursor=None)
        assert result["count"] == 1

    def test_administrator_denied(self):
        svc, *_ = _make_service()
        with pytest.raises(ForbiddenError):
            svc.search(principal=make_admin(), filters={"q": "test"}, limit=10, cursor=None)

    def test_format_filter(self):
        svc, repo, *_ = _make_service()
        all_rows = [
            {"id": "1", "title": "A", "description": "a", "format": "Slides",
             "topics": [], "source": "event-material", "submittedBy": "x", "addedAt": "2026-01-01"},
            {"id": "2", "title": "B", "description": "b", "format": "PDF",
             "topics": [], "source": "event-material", "submittedBy": "x", "addedAt": "2026-01-01"},
        ]
        # Simulate query_page applying the predicate
        def mock_query_page(*, limit, cursor, predicate=None):
            rows = [r for r in all_rows if predicate is None or predicate(r)]
            return rows, None
        repo.query_page.side_effect = mock_query_page
        result = svc.search(principal=make_member(), filters={"format": "Slides"}, limit=10, cursor=None)
        assert result["count"] == 1
        assert result["items"][0]["format"] == "Slides"

    def test_source_filter(self):
        svc, repo, *_ = _make_service()
        all_rows = [
            {"id": "1", "title": "A", "description": "a", "format": "Doc",
             "topics": [], "source": "event-material", "submittedBy": "x", "addedAt": "2026-01-01"},
            {"id": "2", "title": "B", "description": "b", "format": "Doc",
             "topics": [], "source": "curator-direct", "submittedBy": "x", "addedAt": "2026-01-01"},
        ]
        def mock_query_page(*, limit, cursor, predicate=None):
            rows = [r for r in all_rows if predicate is None or predicate(r)]
            return rows, None
        repo.query_page.side_effect = mock_query_page
        result = svc.search(principal=make_member(), filters={"source": "curator-direct"}, limit=10, cursor=None)
        assert result["count"] == 1
        assert result["items"][0]["source"] == "curator-direct"

    def test_topic_filter(self):
        svc, repo, *_ = _make_service()
        all_rows = [
            {"id": "1", "title": "A", "description": "a", "format": "Doc",
             "topics": ["serverless"], "source": "event-material", "submittedBy": "x", "addedAt": "2026-01-01"},
            {"id": "2", "title": "B", "description": "b", "format": "Doc",
             "topics": ["containers"], "source": "event-material", "submittedBy": "x", "addedAt": "2026-01-01"},
        ]
        def mock_query_page(*, limit, cursor, predicate=None):
            rows = [r for r in all_rows if predicate is None or predicate(r)]
            return rows, None
        repo.query_page.side_effect = mock_query_page
        result = svc.search(principal=make_member(), filters={"topic": "serverless"}, limit=10, cursor=None)
        assert result["count"] == 1
        assert "serverless" in result["items"][0]["topics"]

    def test_invalid_format_rejected(self):
        svc, *_ = _make_service()
        with pytest.raises(ValidationError):
            svc.search(principal=make_member(), filters={"format": "Hologram"}, limit=10, cursor=None)

    def test_invalid_source_rejected(self):
        svc, *_ = _make_service()
        with pytest.raises(ValidationError):
            svc.search(principal=make_member(), filters={"source": "magic"}, limit=10, cursor=None)

    def test_presigned_url_generated_for_clean_files(self):
        svc, repo, _, storage = _make_service()
        repo.query_page.return_value = ([{
            "id": "lib-1", "title": "Slides", "description": "desc", "format": "Slides",
            "topics": [], "source": "event-material", "submittedBy": "x",
            "addedAt": "2026-01-01", "s3Key": "library/lib-1/slides.pptx", "scanState": "Clean",
        }], None)
        result = svc.search(principal=make_member(), filters={"format": "Slides"}, limit=10, cursor=None)
        assert "downloadUrl" in result["items"][0]
        storage.presign_get.assert_called_once()

    def test_no_presigned_url_for_pending_scan(self):
        svc, repo, _, storage = _make_service()
        repo.query_page.return_value = ([{
            "id": "lib-1", "title": "Slides", "description": "desc", "format": "Slides",
            "topics": [], "source": "event-material", "submittedBy": "x",
            "addedAt": "2026-01-01", "s3Key": "library/lib-1/slides.pptx", "scanState": "PendingScan",
        }], None)
        result = svc.search(principal=make_member(), filters={"format": "Slides"}, limit=10, cursor=None)
        # PendingScan items are not in GSI1 so query_page returns none — simulate by checking service logic
        # In practice query_page would return empty for PendingScan (GSI1 is sparse)
        # This test validates the serializer doesn't add downloadUrl for non-clean
        assert "downloadUrl" not in result["items"][0] if result["items"] else True


# ---------------------------------------------------------------------------
# Path 1 — Event material auto-promotion (BR-LIB-P1/P2/P3)
# ---------------------------------------------------------------------------

class TestPath1Promotion:

    def test_promote_event_materials_promotes_clean_uploaded(self):
        svc, repo, events_repo, _ = _make_service()
        event = {"id": "ev-1", "title": "Meetup", "description": "Great meetup",
                 "createdBy": "usr-cl", "status": "Completed"}
        events_repo.list_materials.return_value = [{
            "id": "mat-1", "name": "Slides.pptx", "contentType": "Slides",
            "kind": "file", "uploaded": True, "scanState": "Clean",
            "s3Key": "events/ev-1/materials/Slides.pptx",
        }]
        repo.get_by_material_id.return_value = None
        count = svc.promote_event_materials(event)
        assert count == 1
        repo.put_resource.assert_called_once()
        resource = repo.put_resource.call_args[0][0]
        assert resource["title"] == "Slides.pptx"
        assert resource["source"] == "event-material"
        assert resource["description"] == "Great meetup"
        assert resource["materialId"] == "mat-1"

    def test_promote_skips_pending_scan(self):
        svc, repo, events_repo, _ = _make_service()
        event = {"id": "ev-1", "title": "Meetup", "description": "desc",
                 "createdBy": "usr-cl", "status": "Completed"}
        events_repo.list_materials.return_value = [{
            "id": "mat-1", "name": "File.pptx", "contentType": "Slides",
            "kind": "file", "uploaded": True, "scanState": "PendingScan",
        }]
        count = svc.promote_event_materials(event)
        assert count == 0
        repo.put_resource.assert_not_called()

    def test_promote_skips_quarantined(self):
        svc, repo, events_repo, _ = _make_service()
        event = {"id": "ev-1", "title": "T", "description": "d",
                 "createdBy": "usr-cl", "status": "Completed"}
        events_repo.list_materials.return_value = [{
            "id": "mat-1", "name": "Bad.pptx", "contentType": "Slides",
            "kind": "file", "uploaded": True, "scanState": "Quarantined",
        }]
        count = svc.promote_event_materials(event)
        assert count == 0

    def test_promote_single_material_idempotent(self):
        svc, repo, *_ = _make_service()
        repo.get_by_material_id.return_value = {"id": "lib-existing"}
        event = {"id": "ev-1", "title": "T", "description": "d",
                 "createdBy": "usr-cl", "status": "Completed"}
        mat = {"id": "mat-1", "name": "Slides.pptx", "contentType": "Slides",
               "kind": "file", "uploaded": True, "scanState": "Clean"}
        svc.promote_single_material(mat, event)
        repo.put_resource.assert_not_called()  # already exists

    def test_auto_removal_on_material_delete(self):
        svc, repo, *_ = _make_service()
        svc.remove_by_material_id("mat-1")
        repo.delete_by_material_id.assert_called_once_with("mat-1")

    def test_auto_removal_noop_if_not_in_library(self):
        svc, repo, *_ = _make_service()
        repo.delete_by_material_id.return_value = None  # no-op
        svc.remove_by_material_id("mat-999")
        repo.delete_by_material_id.assert_called_once()


# ---------------------------------------------------------------------------
# Path 2 — Member contribution opt-in (BR-LIB-P7/P10/P11/P12)
# ---------------------------------------------------------------------------

class TestPath2ContributionOptIn:

    def _payload(self, add=True):
        return {
            "contributionId": "con-1", "memberId": "usr-m1", "memberName": "Alice",
            "approverId": "usr-cl", "approverName": "CL Bob",
            "addToLibrary": add,
            "libraryTitle": "My Blog Post", "libraryDescription": "An AWS story",
            "libraryFormat": "Link", "libraryTopics": ["aws", "serverless"],
            "libraryUrl": "https://blog.example.com/post",
        }

    def test_add_from_contribution_creates_resource(self):
        svc, repo, *_ = _make_service()
        repo.get_by_contribution_id.return_value = None
        svc.add_from_contribution(self._payload())
        repo.put_resource.assert_called_once()
        resource = repo.put_resource.call_args[0][0]
        assert resource["source"] == "member-contribution"
        assert resource["contributionId"] == "con-1"
        assert resource["submittedBy"] == "usr-m1"

    def test_add_from_contribution_noop_when_false(self):
        svc, repo, *_ = _make_service()
        svc.add_from_contribution(self._payload(add=False))
        repo.put_resource.assert_not_called()

    def test_add_from_contribution_idempotent(self):
        svc, repo, *_ = _make_service()
        repo.get_by_contribution_id.return_value = {"id": "lib-existing"}
        svc.add_from_contribution(self._payload())
        repo.put_resource.assert_not_called()

    def test_add_from_contribution_missing_description_raises(self):
        svc, repo, *_ = _make_service()
        repo.get_by_contribution_id.return_value = None
        p = self._payload()
        p["libraryDescription"] = ""
        with pytest.raises(ValidationError):
            svc.add_from_contribution(p)

    def test_add_from_contribution_link_without_https_raises(self):
        svc, repo, *_ = _make_service()
        repo.get_by_contribution_id.return_value = None
        p = self._payload()
        p["libraryUrl"] = "http://insecure.com"
        with pytest.raises(ValidationError):
            svc.add_from_contribution(p)


# ---------------------------------------------------------------------------
# Path 3 — Curator direct add (BR-LIB-P13/P14/P15/P16)
# ---------------------------------------------------------------------------

class TestPath3CuratorDirect:

    def test_cl_can_add_link(self):
        svc, repo, *_ = _make_service()
        result = svc.add({
            "title": "Useful Link", "description": "A great AWS resource",
            "format": "Link", "topics": ["aws"], "url": "https://aws.amazon.com",
        }, principal=make_cl())
        assert result["source"] == "curator-direct"
        assert result["title"] == "Useful Link"
        repo.put_resource.assert_called_once()

    def test_ugl_can_add(self):
        svc, repo, *_ = _make_service()
        svc.add({
            "title": "T", "description": "D", "format": "Link",
            "url": "https://example.com",
        }, principal=make_ugl())
        repo.put_resource.assert_called_once()

    def test_member_cannot_add(self):
        svc, *_ = _make_service()
        with pytest.raises(ForbiddenError):
            svc.add({
                "title": "T", "description": "D", "format": "Link",
                "url": "https://example.com",
            }, principal=make_member())

    def test_missing_description_rejected(self):
        svc, *_ = _make_service()
        with pytest.raises(ValidationError):
            svc.add({"title": "T", "description": "", "format": "Link",
                     "url": "https://example.com"}, principal=make_cl())

    def test_invalid_format_rejected(self):
        svc, *_ = _make_service()
        with pytest.raises(ValidationError):
            svc.add({"title": "T", "description": "D", "format": "Video3D",
                     "url": "https://example.com"}, principal=make_cl())

    def test_link_without_https_rejected(self):
        svc, *_ = _make_service()
        with pytest.raises(ValidationError):
            svc.add({"title": "T", "description": "D", "format": "Link",
                     "url": "http://insecure.com"}, principal=make_cl())

    def test_file_resource_returns_presigned_upload_url(self):
        svc, repo, _, storage = _make_service()
        result = svc.add({
            "title": "Slides", "description": "Workshop slides", "format": "Slides",
            "fileName": "slides.pptx", "sizeBytes": 1024,
        }, principal=make_cl())
        assert "presignedUploadUrl" in result
        storage.presign_put.assert_called_once()


# ---------------------------------------------------------------------------
# Curation — edit and delete (BR-LIB-C1/C3)
# ---------------------------------------------------------------------------

class TestCuration:

    def _resource(self):
        return {
            "id": "lib-1", "title": "Old Title", "description": "Old desc",
            "format": "Doc", "topics": ["aws"], "source": "curator-direct",
            "submittedBy": "usr-cl", "addedAt": "2026-01-01",
        }

    def test_cl_can_edit(self):
        svc, repo, *_ = _make_service()
        repo.get_resource.return_value = self._resource()
        svc.edit("lib-1", {"title": "New Title"}, principal=make_cl())
        repo.put_resource.assert_called_once()

    def test_ugl_can_edit_any_resource(self):
        svc, repo, *_ = _make_service()
        repo.get_resource.return_value = self._resource()
        svc.edit("lib-1", {"description": "Updated"}, principal=make_ugl())
        repo.put_resource.assert_called_once()

    def test_member_cannot_edit(self):
        svc, *_ = _make_service()
        with pytest.raises(ForbiddenError):
            svc.edit("lib-1", {"title": "X"}, principal=make_member())

    def test_edit_nonexistent_raises_404(self):
        svc, repo, *_ = _make_service()
        repo.get_resource.return_value = None
        with pytest.raises(NotFoundError):
            svc.edit("lib-999", {"title": "X"}, principal=make_cl())

    def test_cl_can_delete(self):
        svc, repo, *_ = _make_service()
        repo.get_resource.return_value = self._resource()
        svc.remove("lib-1", principal=make_cl())
        repo.delete_resource.assert_called_once_with("lib-1")

    def test_ugl_can_delete_any_resource(self):
        svc, repo, *_ = _make_service()
        repo.get_resource.return_value = self._resource()
        svc.remove("lib-1", principal=make_ugl())
        repo.delete_resource.assert_called_once()

    def test_member_cannot_delete(self):
        svc, *_ = _make_service()
        with pytest.raises(ForbiddenError):
            svc.remove("lib-1", principal=make_member())

    def test_delete_nonexistent_raises_404(self):
        svc, repo, *_ = _make_service()
        repo.get_resource.return_value = None
        with pytest.raises(NotFoundError):
            svc.remove("lib-999", principal=make_cl())


# ---------------------------------------------------------------------------
# Tags (BR-LIB-T1..T3)
# ---------------------------------------------------------------------------

class TestTags:

    def test_get_tags_with_prefix(self):
        svc, repo, *_ = _make_service()
        repo.get_all_tags.return_value = {"serverless", "security", "containers", "sagemaker"}
        result = svc.get_tags(principal=make_member(), prefix="se")
        assert set(result["tags"]) == {"serverless", "security"}

    def test_get_tags_no_prefix_returns_all_capped_100(self):
        svc, repo, *_ = _make_service()
        repo.get_all_tags.return_value = {f"tag{i}" for i in range(150)}
        result = svc.get_tags(principal=make_member(), prefix="")
        assert len(result["tags"]) <= 100

    def test_administrator_denied_tags(self):
        svc, *_ = _make_service()
        with pytest.raises(ForbiddenError):
            svc.get_tags(principal=make_admin(), prefix="")

    def test_add_updates_tag_registry(self):
        svc, repo, *_ = _make_service()
        svc.add({
            "title": "T", "description": "D", "format": "Link",
            "topics": ["Serverless", "AWS"], "url": "https://example.com",
        }, principal=make_cl())
        repo.add_tags.assert_called_once()
        # Tags are normalized to lowercase
        call_args = repo.add_tags.call_args[0][0]
        assert "serverless" in call_args
        assert "aws" in call_args
