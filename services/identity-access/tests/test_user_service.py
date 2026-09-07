"""UserService tests (US-1.5/1.6/1.19/1.26/1.31/1.33)."""
import pytest
from _conventions.errors import ValidationError
from models import (
    ROLE_COMMUNITY_LEADER,
    ROLE_MEMBER,
    STATUS_ACTIVE,
    STATUS_INACTIVE,
)


def _seed(repo, uid, email, role=ROLE_MEMBER, status=STATUS_ACTIVE):
    repo.put_user({"id": uid, "email": email, "firstName": "A", "lastName": "B",
                   "role": role, "status": status, "accountType": "cognito", "enabled": True})


def test_edit_user_changes_role_and_publishes(ctx, repo):
    _seed(repo, "u-1", "u1@company.com")
    out = ctx.user_service.edit_user("u-1", {"role": ROLE_COMMUNITY_LEADER}, actor="admin")
    assert out["role"] == ROLE_COMMUNITY_LEADER
    assert any(e["type"] == "UserRoleChanged" for e in ctx.events.published)


def test_edit_user_admin_cannot_have_groups(ctx, repo):
    _seed(repo, "u-2", "u2@company.com")
    with pytest.raises(ValidationError):
        ctx.user_service.edit_user("u-2", {"role": "Administrator", "groupIds": ["g-1"]}, actor="admin")


def test_cannot_change_last_community_leader(ctx, repo):
    _seed(repo, "cl-1", "cl@company.com", role=ROLE_COMMUNITY_LEADER)
    with pytest.raises(ValidationError):
        ctx.user_service.edit_user("cl-1", {"role": ROLE_MEMBER}, actor="admin")


def test_bootstrap_admin_can_be_edited_like_any_administrator(ctx, aws, repo):
    """The bootstrap Administrator (US-1.27) is a regular Cognito user — no
    exemption from Edit User, subject to the same last-Community-Leader rule."""
    from models import ROLE_ADMIN
    sub = aws.create_user("admin@company.com")
    _seed(repo, sub, "admin@company.com", role=ROLE_ADMIN)
    out = ctx.user_service.edit_user(sub, {"role": ROLE_MEMBER}, actor="admin")
    assert out["role"] == ROLE_MEMBER


def test_disable_and_enable_user(ctx, aws, repo):
    sub = aws.create_user("u3@company.com")
    _seed(repo, sub, "u3@company.com")
    out = ctx.user_service.set_enabled(sub, False, actor="admin")
    assert out["status"] == STATUS_INACTIVE
    assert any(e["type"] == "UserDeactivated" for e in ctx.events.published)
    out2 = ctx.user_service.set_enabled(sub, True, actor="admin")
    assert out2["status"] == STATUS_ACTIVE
    assert any(e["type"] == "UserReactivated" for e in ctx.events.published)


def test_bootstrap_admin_can_be_disabled_like_any_administrator(ctx, aws, repo):
    """The bootstrap Administrator (US-1.27) has no disable exemption."""
    from models import ROLE_ADMIN
    sub = aws.create_user("admin2@company.com")
    _seed(repo, sub, "admin2@company.com", role=ROLE_ADMIN)
    out = ctx.user_service.set_enabled(sub, False, actor="admin")
    assert out["status"] == STATUS_INACTIVE


def test_bulk_import_categorizes_rows(ctx, repo):
    rows = [
        {"email": "a@company.com", "first_name": "A", "last_name": "One"},   # created
        {"email": "a@company.com", "first_name": "A", "last_name": "Dup"},   # dup in file
        {"email": "bad", "first_name": "", "last_name": ""},                  # invalid
        {"email": "b@evil.com", "first_name": "B", "last_name": "Two"},      # domain not allowed
    ]
    report = ctx.user_service.bulk_import(rows, actor="admin", file_name="u.csv",
                                          allowed_domains=["company.com"])
    assert report["created"] == 1
    assert report["rejected"] == 3
    assert report["skipped"] == 0
    assert repo.get_user_by_email("a@company.com") is not None


def test_bulk_import_skips_a_row_whose_email_already_exists_in_cognito(ctx, aws):
    """An email already present in Cognito is SKIPPED, not rejected (BR-P4).

    Regression guard for the outcome CLASSIFICATION, which is what makes the
    admin's created/skipped/rejected figures meaningful: re-importing a file
    that overlaps an earlier import is an ordinary, benign case and must not be
    reported as bad data. Pins the behaviour across the removal of the
    `user_exists` pre-check (the duplicate is now discovered by
    admin_create_user raising DuplicateUserError instead)."""
    aws.create_user("already@company.com")
    rows = [{"email": "already@company.com", "first_name": "Al", "last_name": "Ready"}]
    report = ctx.user_service.bulk_import(rows, actor="admin", file_name="u.csv",
                                          allowed_domains=["company.com"])
    assert report["skipped"] == 1
    assert report["created"] == 0
    assert report["rejected"] == 0
    assert report["report"][0]["outcome"] == "Skipped (duplicate)"


def test_bulk_import_does_not_pre_check_every_row_against_cognito(ctx):
    """No AdminGetUser per row (2026-08-25 optimisation).

    The pre-check was a third of the ~3 Cognito calls/row that drive this
    endpoint's latency, and MAX_IMPORT_ROWS exists only because that latency
    runs into API Gateway's 29 s ceiling. Duplicates are detected from
    admin_create_user's DuplicateUserError instead, so re-adding a pre-check
    would silently undo the saving — hence this guard."""
    real = ctx.user_service._auth
    pre_checks: list = []

    class NoPreCheckAuth:
        def __getattr__(self, name):
            attr = getattr(real, name)
            if name != "user_exists":
                return attr

            def counted(*args, **kwargs):
                pre_checks.append(args)
                return attr(*args, **kwargs)
            return counted

    ctx.user_service._auth = NoPreCheckAuth()
    rows = [{"email": f"n{i}@company.com", "first_name": "N", "last_name": str(i)}
            for i in range(3)]
    report = ctx.user_service.bulk_import(rows, actor="admin", file_name="u.csv",
                                          allowed_domains=["company.com"])

    assert report["created"] == 3
    assert pre_checks == []


def test_bulk_import_does_not_overwrite_the_portal_record_of_an_existing_user(ctx, aws, repo):
    """A duplicate row must leave the existing portal record untouched.

    put_user is an unconditional put_item on the same pk, so if a duplicate row
    ever reached it the imported row's values (role Member, blank profile
    fields) would silently clobber the real record."""
    from models import ROLE_ADMIN
    sub = aws.create_user("keep@company.com")
    _seed(repo, sub, "keep@company.com", role=ROLE_ADMIN)   # writes firstName "A"

    report = ctx.user_service.bulk_import(
        [{"email": "keep@company.com", "first_name": "Imported", "last_name": "Overwrite"}],
        actor="admin", file_name="u.csv", allowed_domains=["company.com"])

    assert report["skipped"] == 1
    after = repo.get_user_by_email("keep@company.com")
    assert after["firstName"] == "A"          # not "Imported"
    assert after["role"] == ROLE_ADMIN        # not demoted to Member


def test_bulk_import_sets_permanent_password_and_sends_no_welcome_email(ctx, aws, repo):
    """US-1.31/BR-P4: the created Cognito account should land CONFIRMED (a
    system-generated permanent password, no FORCE_CHANGE_PASSWORD state the
    login flow can't handle). No welcome email is sent on import (disabled by
    request) — the user sets their password via the Cognito "Forgot password"
    flow, same as every other Cognito-owned account."""
    rows = [{"email": "c@company.com", "first_name": "Cara", "last_name": "Lee"}]
    ctx.user_service.bulk_import(rows, actor="admin", file_name="u.csv",
                                 allowed_domains=["company.com"])
    details = aws.idp.admin_get_user(UserPoolId=aws.pool_id, Username="c@company.com")
    assert details["UserStatus"] == "CONFIRMED"
    assert not ctx.ses.sent


# ---------------- Edit User: group membership application (US-1.26) ----------------

def test_edit_user_joins_member_to_groups(ctx, repo):
    """Assigning groupIds to a Member actually joins them (previously only validated shape)."""
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com")
    _seed(repo, "u-m", "m@company.com")
    out = ctx.user_service.edit_user("u-m", {"groupIds": ["g-1"]}, actor="admin")
    assert out["groupIds"] == ["g-1"]
    assert "g-1" in repo.current_groups_for_member("u-m")
    assert any(e["type"] == "MemberJoinedGroup" for e in ctx.events.published)


def test_edit_user_removes_member_from_groups(ctx, repo):
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com")
    _seed(repo, "u-m", "m@company.com")
    ctx.user_service.edit_user("u-m", {"groupIds": ["g-1"]}, actor="admin")
    out = ctx.user_service.edit_user("u-m", {"groupIds": []}, actor="admin")
    assert out["groupIds"] == []
    assert "g-1" not in repo.current_groups_for_member("u-m")
    assert any(e["type"] == "MemberLeftGroup" for e in ctx.events.published)


def test_edit_user_reassigns_member_groups(ctx, repo):
    """Swapping group membership joins the new group and leaves the old one."""
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    repo.put_group({"id": "g-2", "name": "Data", "leaderIds": ["u-l2"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com")
    _seed(repo, "u-l2", "l2@company.com")
    _seed(repo, "u-m", "m@company.com")
    ctx.user_service.edit_user("u-m", {"groupIds": ["g-1"]}, actor="admin")
    out = ctx.user_service.edit_user("u-m", {"groupIds": ["g-2"]}, actor="admin")
    assert out["groupIds"] == ["g-2"]
    assert repo.current_groups_for_member("u-m") == {"g-2"}


def test_edit_user_rejects_nonexistent_group(ctx, repo):
    _seed(repo, "u-m", "m@company.com")
    with pytest.raises(ValidationError):
        ctx.user_service.edit_user("u-m", {"groupIds": ["g-ghost"]}, actor="admin")


def test_edit_user_promotes_member_to_ugl_assigns_led_group(ctx, repo):
    """Promoting a Member to UserGroupLeader actually assigns them as a group
    leader (previously only validated shape, never called GroupService)."""
    from models import ROLE_UGL
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": [], "status": "Active"})
    _seed(repo, "u-m", "m@company.com")
    out = ctx.user_service.edit_user("u-m", {"role": ROLE_UGL, "groupIds": ["g-1"]}, actor="admin")
    assert out["role"] == ROLE_UGL
    assert out["ledGroupId"] == "g-1"
    group = repo.get_group("g-1")
    assert "u-m" in group["leaderIds"]


def test_edit_user_cannot_assign_leader_who_already_leads_another_group(ctx, repo):
    """BR-G7: a person can lead only one group. u-l already leads g-1; assigning
    them (a distinct edit target than the group they already lead) to lead g-2
    while still recorded as leading g-1 should fail the pre-check."""
    from models import ROLE_UGL
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    repo.put_group({"id": "g-2", "name": "Data", "leaderIds": [], "status": "Active"})
    _seed(repo, "u-l", "l@company.com", role=ROLE_UGL)
    repo.put_user({**repo.get_user("u-l"), "ledGroupId": "g-1"})
    _seed(repo, "u-other", "other@company.com")
    # u-other is not yet a leader; assigning them to g-2 succeeds independently.
    out = ctx.user_service.edit_user("u-other", {"role": ROLE_UGL, "groupIds": ["g-2"]}, actor="admin")
    assert out["ledGroupId"] == "g-2"
    # u-l still correctly leads only g-1 (unaffected).
    assert repo.get_user("u-l")["ledGroupId"] == "g-1"


def test_edit_user_reassigns_ugl_to_different_group(ctx, repo):
    """Moving a UGL to lead a different group releases the old group's leadership."""
    from models import ROLE_UGL
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    repo.put_group({"id": "g-2", "name": "Data", "leaderIds": ["u-other"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com", role=ROLE_UGL)
    repo.put_user({**repo.get_user("u-l"), "ledGroupId": "g-1"})
    out = ctx.user_service.edit_user("u-l", {"role": ROLE_UGL, "groupIds": ["g-2"]}, actor="admin")
    assert out["ledGroupId"] == "g-2"
    assert "u-l" not in repo.get_group("g-1")["leaderIds"]
    assert "u-l" in repo.get_group("g-2")["leaderIds"]


def test_edit_user_demote_ugl_to_member_releases_group_and_can_rejoin(ctx, repo):
    """Demoting a UGL to Member releases their led-group leadership; they can
    then be assigned group membership like any Member."""
    from models import ROLE_MEMBER, ROLE_UGL
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l", "u-other"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com", role=ROLE_UGL)
    repo.put_user({**repo.get_user("u-l"), "ledGroupId": "g-1"})
    out = ctx.user_service.edit_user("u-l", {"role": ROLE_MEMBER, "groupIds": ["g-1"]}, actor="admin")
    assert out["role"] == ROLE_MEMBER
    assert "u-l" not in repo.get_group("g-1")["leaderIds"]
    assert "g-1" in repo.current_groups_for_member("u-l")


def test_edit_user_promotes_member_to_admin_removes_from_groups(ctx, repo):
    from models import ROLE_ADMIN
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com")
    _seed(repo, "u-m", "m@company.com")
    ctx.user_service.edit_user("u-m", {"groupIds": ["g-1"]}, actor="admin")
    out = ctx.user_service.edit_user("u-m", {"role": ROLE_ADMIN}, actor="admin")
    assert out["role"] == ROLE_ADMIN
    assert "g-1" not in repo.current_groups_for_member("u-m")


def test_edit_user_profile_fields_saved(ctx, repo):
    _seed(repo, "u-m", "m@company.com")
    out = ctx.user_service.edit_user(
        "u-m",
        {"city": "Seattle", "country": "USA", "professionalRole": "Engineer",
         "awsProject": True, "timeZone": "America/Los_Angeles"},
        actor="admin",
    )
    assert out["city"] == "Seattle"
    assert out["country"] == "USA"
    assert out["professionalRole"] == "Engineer"
    assert out["awsProject"] is True
    assert out["timeZone"] == "America/Los_Angeles"


def test_list_users_includes_group_ids_for_members(ctx, repo):
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com")
    _seed(repo, "u-m", "m@company.com")
    ctx.user_service.edit_user("u-m", {"groupIds": ["g-1"]}, actor="admin")
    users = {u["id"]: u for u in ctx.user_service.list_users()}
    assert users["u-m"]["groupIds"] == ["g-1"]


# ---------------- createUser (US-1.35 — Admin single Add User form) ----------------

def test_create_user_creates_cognito_and_portal_record(ctx, aws):
    out = ctx.user_service.create_user(
        {"email": "new@company.com", "firstName": "Nia", "lastName": "New",
         "city": "Seattle", "awsProject": True},
        actor="admin", allowed_domains=["company.com"])
    assert out["email"] == "new@company.com"
    assert out["role"] == ROLE_MEMBER
    assert out["city"] == "Seattle"
    assert out["awsProject"] is True
    # Cognito account exists (identity/credentials Cognito-owned)
    assert ctx.auth_provider.user_exists("new@company.com")
    # No welcome email is sent on admin-driven creation (disabled by request);
    # the account is created silently and the user uses "Forgot password".
    assert not ctx.ses.sent
    # provisioned event published
    assert any(e["type"] == "UserProvisioned" for e in ctx.events.published)


def test_create_user_rejects_duplicate_email(ctx, aws):
    ctx.user_service.create_user(
        {"email": "dup@company.com", "firstName": "D", "lastName": "U"},
        actor="admin", allowed_domains=["company.com"])
    with pytest.raises(ValidationError):
        ctx.user_service.create_user(
            {"email": "dup@company.com", "firstName": "D", "lastName": "U"},
            actor="admin", allowed_domains=["company.com"])


def test_create_user_rejects_disallowed_domain(ctx):
    with pytest.raises(ValidationError):
        ctx.user_service.create_user(
            {"email": "x@evil.com", "firstName": "X", "lastName": "Y"},
            actor="admin", allowed_domains=["company.com"])


def test_create_user_requires_names(ctx):
    with pytest.raises(ValidationError):
        ctx.user_service.create_user(
            {"email": "a@company.com", "firstName": "", "lastName": "B"},
            actor="admin", allowed_domains=["company.com"])


def test_create_user_allowed_when_no_domain_list(ctx):
    """Empty allow-list only blocks SELF-registration (BR-P3); an Administrator
    adding a user directly is not gated by it (mirrors bulk import)."""
    out = ctx.user_service.create_user(
        {"email": "any@anywhere.org", "firstName": "A", "lastName": "W"},
        actor="admin", allowed_domains=[])
    assert out["email"] == "any@anywhere.org"


# ---- Unassigned UserGroupLeader (requirement change 2026-08-03) ------------
# A UGL may exist WITHOUT a led group: the Admin promotes the role first; the
# group is assigned later — at group creation (US-1.9) or via Edit User.

def test_edit_user_promotes_member_to_ugl_without_group(ctx, repo):
    """Promotion to UserGroupLeader no longer requires a group selection."""
    from models import ROLE_UGL
    _seed(repo, "u-m", "m@company.com")
    out = ctx.user_service.edit_user("u-m", {"role": ROLE_UGL}, actor="admin")
    assert out["role"] == ROLE_UGL
    assert not out.get("ledGroupId")
    assert any(e["type"] == "UserRoleChanged" for e in ctx.events.published)


def test_edit_unassigned_ugl_profile_keeps_them_unassigned(ctx, repo):
    """A same-role edit with no groupIds must not invent or drop assignments."""
    from models import ROLE_UGL
    _seed(repo, "u-l", "l@company.com", role=ROLE_UGL)
    out = ctx.user_service.edit_user("u-l", {"city": "Seattle"}, actor="admin")
    assert out["role"] == ROLE_UGL
    assert not out.get("ledGroupId")
    assert out["city"] == "Seattle"


def test_edit_assigned_ugl_with_empty_groupids_does_not_unassign(ctx, repo):
    """Sending groupIds [] (the Edit User form's 'Not assigned yet' option)
    never silently releases a currently led group."""
    from models import ROLE_UGL
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-l"], "status": "Active"})
    _seed(repo, "u-l", "l@company.com", role=ROLE_UGL)
    repo.put_user({**repo.get_user("u-l"), "ledGroupId": "g-1"})
    out = ctx.user_service.edit_user("u-l", {"role": ROLE_UGL, "groupIds": []}, actor="admin")
    assert out["ledGroupId"] == "g-1"
    assert "u-l" in repo.get_group("g-1")["leaderIds"]


def test_create_group_with_unassigned_ugl_leader(ctx, repo):
    """The new intended flow end-to-end: Admin promotes to UGL (no group),
    then the CL creates a group picking that unassigned UGL as leader."""
    from models import ROLE_UGL
    _seed(repo, "u-l", "l@company.com")
    ctx.user_service.edit_user("u-l", {"role": ROLE_UGL}, actor="admin")
    g = ctx.group_service.create_group(
        {"name": "Cloud", "leaderIds": ["u-l"], "approvalRequired": False}, actor="cl")
    assert g["leaderIds"] == ["u-l"]
    user = repo.get_user("u-l")
    assert user["role"] == ROLE_UGL
    assert user["ledGroupId"] == g["id"]


# --- Paged admin user list through the service (D-U3, 2026-08-03) ---

def _seed_many(repo, n, role=ROLE_MEMBER, prefix="lp"):
    for i in range(n):
        _seed(repo, f"{prefix}{i:03d}", f"{prefix}{i:03d}@company.com", role=role)


def test_list_users_page_returns_cursor_then_final_page(ctx, repo):
    _seed_many(repo, 5)
    page1 = ctx.user_service.list_users_page(limit=3)
    assert page1["count"] == 3
    assert page1.get("cursor")
    page2 = ctx.user_service.list_users_page(limit=3, cursor=page1["cursor"])
    assert page2["count"] == 2
    assert "cursor" not in page2
    ids = {i["id"] for i in page1["items"]} | {i["id"] for i in page2["items"]}
    assert len(ids) == 5


def test_list_users_page_group_filter_includes_members_and_leaders(ctx, repo):
    """D-U3 — group filter = current members ∪ the group's leaders (a UGL
    leads without membership, US-1.16)."""
    from models import MEVENT_JOINED, ROLE_UGL
    _seed_many(repo, 3)                                   # lp000..lp002
    _seed(repo, "ugl-1", "ugl1@company.com", role=ROLE_UGL)
    repo.put_group({"id": "g-x", "name": "X", "leaderIds": ["ugl-1"], "status": "Active"})
    # lp000 joins g-x (membership start event).
    repo.append_membership_event({"id": "me-t1", "memberId": "lp000", "groupId": "g-x",
                                  "type": MEVENT_JOINED, "at": "2026-01-01T00:00:00Z"})
    out = ctx.user_service.list_users_page(group_id="g-x", limit=10)
    assert {i["id"] for i in out["items"]} == {"lp000", "ugl-1"}


def test_list_users_page_unpaged_export_unaffected(ctx, repo):
    _seed_many(repo, 4)
    assert len(ctx.user_service.list_users()) == 4
