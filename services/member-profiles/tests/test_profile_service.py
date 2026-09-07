"""ProfileService tests — US-3.1/3.2/3.3, incl. the degrade-path suite
(NFR-MP-MAINT-1): simulated downstream failure -> 200 with empty section."""
import pytest
from _conventions.errors import ForbiddenError, NotFoundError, ValidationError
from profile_service import ProfileService


def _seed(repo, member_id="u1"):
    repo.put_profile({"id": member_id, "firstName": "Alex", "lastName": "Morgan",
                      "email": "alex@x.com", "role": "Member", "status": "active", "groups": []})


def test_get_own_profile_merges_fan_out(repo, fan_out, events):
    _seed(repo)
    fan_out.responses = {
        "contributions": {"points": 113, "quarter": "2026-Q2", "tier": "Gold", "groupId": "g1"},
        "events": {"count": 28}, "forums": {"count": 64}, "certifications": {"count": 4},
    }
    svc = ProfileService(repo, fan_out, events)  # events not used on get
    out = svc.get_own_profile("u1")
    assert out["rollup"]["points"] == 113
    assert out["activitySummary"]["eventsAttended"] == 28
    assert out["activitySummary"]["forumPosts"] == 64


def test_get_own_profile_degrades_when_fan_out_fails(repo, fan_out, events):
    """BR-9 — a downstream failure omits that section, never raises."""
    _seed(repo)
    fan_out.failing = {"contributions", "events", "forums", "certifications"}
    svc = ProfileService(repo, fan_out, events)
    out = svc.get_own_profile("u1")  # must not raise
    assert out["rollup"] is None
    assert out["activitySummary"]["eventsAttended"] == 0


def test_update_own_profile_publishes_event(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    out = svc.update_own_profile("u1", {"city": "Seattle", "bio": "hi", "skills": ["Lambda"]})
    assert out["city"] == "Seattle"
    assert len(events.published) == 1
    assert events.published[0]["type"] == "MemberProfileUpserted"


def test_update_own_profile_never_edits_identity_fields(repo, fan_out, events):
    """BR-2 — email/role are Identity-owned; updateOwnProfile ignores attempts to set them."""
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    svc.update_own_profile("u1", {"email": "hacker@evil.com", "role": "Administrator", "city": "NYC"})
    profile = repo.get_profile("u1")
    assert profile["email"] == "alex@x.com"
    assert profile["role"] == "Member"
    assert profile["city"] == "NYC"


def test_get_member_forbidden_for_administrator(repo, fan_out, events):
    """BR-4 — Administrators cannot open the community profile view."""
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(ForbiddenError):
        svc.get_member("u1", principal_role="Administrator")


def test_get_member_not_found(repo, fan_out, events):
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(NotFoundError):
        svc.get_member("nope", principal_role="Member")


def test_get_member_read_only_no_edit_path(repo, fan_out, events):
    """BR-5 — getMember has no corresponding write; only the read path exists."""
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    assert not hasattr(svc, "update_member")


# --- bio & skills validation (US-3.2 rework 2026-08-11) -----------------------

def test_bio_accepts_up_to_2000(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    out = svc.update_own_profile("u1", {"bio": "x" * 2000})
    assert out["bio"] == "x" * 2000


def test_bio_over_2000_rejected_with_details(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(ValidationError) as exc:
        svc.update_own_profile("u1", {"bio": "x" * 2001})
    # The detail names the field and the limit — this is what makes the message
    # readable once app.py serialises details.
    assert exc.value.details == [{"field": "bio", "message": "length must be 1-2000"}]


def test_bio_rejects_angle_brackets(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(ValidationError) as exc:
        svc.update_own_profile("u1", {"bio": "hi <script>"})
    assert exc.value.details == [{"field": "bio", "message": "must not contain '<' or '>'"}]


def test_short_fields_still_capped_at_500(repo, fan_out, events):
    """The bio split must not loosen the short-text fields."""
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(ValidationError) as exc:
        svc.update_own_profile("u1", {"city": "x" * 501})
    assert exc.value.details == [{"field": "city", "message": "length must be 1-500"}]


def test_skill_item_too_long_rejected(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(ValidationError) as exc:
        svc.update_own_profile("u1", {"skills": ["ok", "x" * 61]})
    assert exc.value.details == [{"field": "skills", "message": "length must be 1-60"}]


def test_skill_item_rejects_angle_brackets(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(ValidationError):
        svc.update_own_profile("u1", {"skills": ["<script>"]})


def test_skills_must_be_a_list(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    with pytest.raises(ValidationError) as exc:
        svc.update_own_profile("u1", {"skills": "Lambda"})
    assert exc.value.details == [{"field": "skills", "message": "must be a list"}]


def test_empty_bio_clears_without_error(repo, fan_out, events):
    _seed(repo)
    svc = ProfileService(repo, fan_out, events)
    out = svc.update_own_profile("u1", {"bio": ""})
    assert out["bio"] == ""
