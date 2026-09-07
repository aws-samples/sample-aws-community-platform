"""GroupService tests (US-1.7–1.11/1.16–1.18/1.21/1.34)."""
import pytest
from _conventions.errors import NotFoundError, ValidationError
from models import ROLE_MEMBER, STATUS_ACTIVE


def _member(repo, uid, email):
    repo.put_user({"id": uid, "email": email, "firstName": "A", "lastName": "B",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})


def test_create_group_requires_leader(ctx):
    with pytest.raises(ValidationError):
        ctx.group_service.create_group({"name": "NoLeader"}, actor="cl")


def test_create_group_and_promote_leader(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    g = ctx.group_service.create_group(
        {"name": "Cloud", "leaderIds": ["u-l"], "approvalRequired": False}, actor="cl")
    assert g["leaderIds"] == ["u-l"]
    assert repo.get_user("u-l")["role"] == "UserGroupLeader"
    assert repo.get_user("u-l")["ledGroupId"] == g["id"]


def test_join_open_group_immediate(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group({"name": "Open", "leaderIds": ["u-l"]}, actor="cl")
    out = ctx.group_service.join_group(g["id"], "u-m")
    assert out["status"] == "joined"
    assert "u-m" in {m["id"] for m in ctx.group_service.list_group_members(g["id"])}


def test_join_approval_required_creates_request(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group(
        {"name": "Closed", "leaderIds": ["u-l"], "approvalRequired": True}, actor="cl")
    out = ctx.group_service.join_group(g["id"], "u-m")
    assert out["status"] == "requested"
    assert len(ctx.group_service.list_join_requests(g["id"])) == 1
    # No membership yet.
    assert "u-m" not in {m["id"] for m in ctx.group_service.list_group_members(g["id"])}


def test_approve_join_request_grants_membership(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group(
        {"name": "Closed", "leaderIds": ["u-l"], "approvalRequired": True}, actor="cl")
    req = ctx.group_service.join_group(g["id"], "u-m")
    ctx.group_service.decide_join_request(g["id"], req["requestId"], approve=True, actor="u-l")
    assert "u-m" in {m["id"] for m in ctx.group_service.list_group_members(g["id"])}


def test_reject_requires_reason(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group(
        {"name": "Closed", "leaderIds": ["u-l"], "approvalRequired": True}, actor="cl")
    req = ctx.group_service.join_group(g["id"], "u-m")
    with pytest.raises(ValidationError):
        ctx.group_service.decide_join_request(g["id"], req["requestId"], approve=False, actor="u-l")


def test_last_leader_cannot_leave(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    g = ctx.group_service.create_group({"name": "Solo", "leaderIds": ["u-l"]}, actor="cl")
    with pytest.raises(ValidationError):
        ctx.group_service.leave_group(g["id"], "u-l")


def test_leader_can_lead_only_one_group(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    ctx.group_service.create_group({"name": "G1", "leaderIds": ["u-l"]}, actor="cl")
    with pytest.raises(ValidationError):
        ctx.group_service.create_group({"name": "G2", "leaderIds": ["u-l"]}, actor="cl")


def test_soft_delete_hides_group(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    g = ctx.group_service.create_group({"name": "Temp", "leaderIds": ["u-l"]}, actor="cl")
    ctx.group_service.delete_group(g["id"], actor="cl")
    assert all(x["id"] != g["id"] for x in ctx.group_service.list_groups())
    with pytest.raises(NotFoundError):
        ctx.group_service.get_group(g["id"])
    assert any(e["type"] == "GroupSoftDeleted" for e in ctx.events.published)


def test_membership_history_records_events(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group({"name": "Hist", "leaderIds": ["u-l"]}, actor="cl")
    ctx.group_service.join_group(g["id"], "u-m")
    ctx.group_service.leave_group(g["id"], "u-m")
    hist = ctx.group_service.membership_history(member_id="u-m")
    types = [h["type"] for h in hist]
    assert "joined" in types and "left" in types


# ---------------- withdrawJoinRequest + myState (2026-08-04 addendum) ----------------

def _gated_group_with_request(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group(
        {"name": "Gated", "leaderIds": ["u-l"], "approvalRequired": True}, actor="cl")
    ctx.group_service.join_group(g["id"], "u-m")
    return g


def test_withdraw_pending_request(ctx, repo):
    g = _gated_group_with_request(ctx, repo)
    out = ctx.group_service.withdraw_join_request(g["id"], "u-m")
    assert out["status"] == "Withdrawn"
    # Gone from the leader queue.
    assert ctx.group_service.list_join_requests(g["id"]) == []


def test_withdraw_without_pending_request_raises_not_found(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group(
        {"name": "Gated", "leaderIds": ["u-l"], "approvalRequired": True}, actor="cl")
    with pytest.raises(NotFoundError):
        ctx.group_service.withdraw_join_request(g["id"], "u-m")


def test_withdraw_only_touches_own_request(ctx, repo):
    g = _gated_group_with_request(ctx, repo)  # u-m has the pending request
    _member(repo, "u-x", "x@company.com")
    with pytest.raises(NotFoundError):  # u-x has nothing to withdraw
        ctx.group_service.withdraw_join_request(g["id"], "u-x")
    assert len(ctx.group_service.list_join_requests(g["id"])) == 1  # u-m's request intact


def test_member_can_rerequest_after_withdraw(ctx, repo):
    g = _gated_group_with_request(ctx, repo)
    ctx.group_service.withdraw_join_request(g["id"], "u-m")
    out = ctx.group_service.join_group(g["id"], "u-m")
    assert out["status"] == "requested"


def test_my_state_annotation(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-l2", "l2@company.com")  # BR-G7 — one person leads one group
    _member(repo, "u-m", "m@company.com")
    open_g = ctx.group_service.create_group({"name": "OpenG", "leaderIds": ["u-l"]}, actor="cl")
    gated = ctx.group_service.create_group(
        {"name": "GatedG", "leaderIds": ["u-l2"], "approvalRequired": True}, actor="cl")
    ctx.group_service.join_group(open_g["id"], "u-m")   # instant member
    ctx.group_service.join_group(gated["id"], "u-m")    # pending request
    states = {g["name"]: g.get("myState") for g in ctx.group_service.list_groups(caller_id="u-m")}
    assert states == {"OpenG": "member", "GatedG": "requested"}
    # Without a caller, no annotation at all.
    assert all("myState" not in g for g in ctx.group_service.list_groups())
    # get_group carries the same annotation (group detail page).
    assert ctx.group_service.get_group(gated["id"], caller_id="u-m")["myState"] == "requested"


def test_my_state_cleared_after_withdraw(ctx, repo):
    g = _gated_group_with_request(ctx, repo)
    assert ctx.group_service.get_group(g["id"], caller_id="u-m")["myState"] == "requested"
    ctx.group_service.withdraw_join_request(g["id"], "u-m")
    assert ctx.group_service.get_group(g["id"], caller_id="u-m").get("myState") is None


# ---- Paged group member list (2026-08-05, 13k+ scale) ----

def _group_with_members(ctx, repo, count, leader="u-l"):
    _member(repo, leader, f"{leader}@company.com")
    g = ctx.group_service.create_group({"name": "Big", "leaderIds": [leader]}, actor="cl")
    for i in range(count):
        uid = f"u-m{i:04d}"
        repo.put_user({"id": uid, "email": f"m{i:04d}@company.com", "firstName": f"First{i:04d}",
                       "lastName": "Member", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
        ctx.group_service.join_group(g["id"], uid)
    return g


def test_member_list_includes_leader_with_role_in_group(ctx, repo):
    """Leadership is not membership (no join event), but the member screen lists
    the leader with a distinguishing roleInGroup (US-1.16)."""
    g = _group_with_members(ctx, repo, 2)
    items = ctx.group_service.list_group_members(g["id"])
    by_id = {m["id"]: m for m in items}
    assert by_id["u-l"]["roleInGroup"] == "UserGroupLeader"
    assert by_id["u-m0000"]["roleInGroup"] == "Member"
    # Leaders sort first so the cursor order is stable.
    assert items[0]["id"] == "u-l"


def test_member_page_returns_limit_and_cursor(ctx, repo):
    g = _group_with_members(ctx, repo, 5)  # 5 members + 1 leader = 6 rows
    page = ctx.group_service.list_group_members_page(g["id"], limit=2)
    assert [m["id"] for m in page["items"]] == ["u-l", "u-m0000"]
    assert page["count"] == 2
    assert page["cursor"]


def test_member_pages_cover_every_row_without_overlap(ctx, repo):
    g = _group_with_members(ctx, repo, 7)  # 8 rows total
    seen, cursor, pages = [], None, 0
    while True:
        page = ctx.group_service.list_group_members_page(g["id"], limit=3, cursor=cursor)
        seen.extend(m["id"] for m in page["items"])
        pages += 1
        cursor = page.get("cursor")
        if not cursor:
            break
        assert pages < 10, "cursor did not terminate"
    assert len(seen) == len(set(seen)) == 8
    assert pages == 3


def test_last_member_page_has_no_cursor(ctx, repo):
    g = _group_with_members(ctx, repo, 1)  # 2 rows, page size 5
    page = ctx.group_service.list_group_members_page(g["id"], limit=5)
    assert page["count"] == 2
    assert "cursor" not in page


def test_member_page_keyword_search_matches_profile_fields(ctx, repo):
    g = _group_with_members(ctx, repo, 4)
    page = ctx.group_service.list_group_members_page(g["id"], q="First0002")
    assert [m["id"] for m in page["items"]] == ["u-m0002"]
    # Email is searchable too.
    assert ctx.group_service.list_group_members_page(g["id"], q="m0003@company")["count"] == 1
    assert ctx.group_service.list_group_members_page(g["id"], q="nobody")["count"] == 0


def test_removed_member_leaves_the_page(ctx, repo):
    g = _group_with_members(ctx, repo, 3)
    ctx.group_service.remove_member(g["id"], "u-m0001", actor="cl")
    ids = [m["id"] for m in ctx.group_service.list_group_members_page(g["id"], limit=50)["items"]]
    assert "u-m0001" not in ids
    assert "u-m0000" in ids


def test_bad_member_cursor_is_validation_error_not_500(ctx, repo):
    g = _group_with_members(ctx, repo, 1)
    with pytest.raises(ValidationError):
        ctx.group_service.list_group_members_page(g["id"], cursor="!!!not-base64!!!")


def test_member_page_unknown_group_is_not_found(ctx):
    with pytest.raises(NotFoundError):
        ctx.group_service.list_group_members_page("g-missing", limit=5)


def test_stale_cursor_whose_member_left_still_advances(ctx, repo):
    """A member removed between page requests must not strand the caller: the
    walk resumes at the next id in order instead of raising."""
    g = _group_with_members(ctx, repo, 4)
    page1 = ctx.group_service.list_group_members_page(g["id"], limit=2)
    last_id = page1["items"][-1]["id"]
    ctx.group_service.remove_member(g["id"], last_id, actor="cl")
    page2 = ctx.group_service.list_group_members_page(g["id"], limit=2, cursor=page1["cursor"])
    ids = [m["id"] for m in page2["items"]]
    assert last_id not in ids
    assert ids and all(i > last_id for i in ids)


# ---- Membership projection + counter (2026-08-05, 13k+ scale) ----

def test_member_count_comes_from_the_counter_not_an_event_fold(ctx, repo):
    g = _group_with_members(ctx, repo, 3)
    assert repo.group_member_count(g["id"]) == 3
    assert ctx.group_service.get_group(g["id"])["memberCount"] == 3
    assert next(x for x in ctx.group_service.list_groups() if x["id"] == g["id"])["memberCount"] == 3


def test_counter_tracks_join_leave_and_remove(ctx, repo):
    g = _group_with_members(ctx, repo, 2)
    ctx.group_service.leave_group(g["id"], "u-m0000")
    assert repo.group_member_count(g["id"]) == 1
    ctx.group_service.remove_member(g["id"], "u-m0001", actor="cl")
    assert repo.group_member_count(g["id"]) == 0


def test_repeated_join_does_not_double_count(ctx, repo):
    """A duplicate start event must not inflate the counter — the conditional
    put is what makes the count exact rather than best-effort."""
    g = _group_with_members(ctx, repo, 1)
    ctx.group_service.join_group(g["id"], "u-m0000")  # already a member
    assert repo.group_member_count(g["id"]) == 1
    ids = [m["id"] for m in ctx.group_service.list_group_members_page(g["id"], limit=50)["items"]]
    assert ids.count("u-m0000") == 1


def test_end_event_for_a_non_member_cannot_drive_the_counter_negative(ctx, repo):
    g = _group_with_members(ctx, repo, 1)
    _member(repo, "u-outsider", "out@company.com")
    ctx.group_service.remove_member(g["id"], "u-outsider", actor="cl")
    assert repo.group_member_count(g["id"]) == 1


def test_projection_matches_the_event_log(ctx, repo):
    """The event log stays the source of truth; the projection must agree with
    replaying it (this is exactly what the backfill tool asserts)."""
    g = _group_with_members(ctx, repo, 4)
    ctx.group_service.leave_group(g["id"], "u-m0002")
    assert repo.current_members_of_group(g["id"]) == set(repo.derive_members_from_events(g["id"]))


def test_soft_delete_clears_the_projection_and_counter(ctx, repo):
    g = _group_with_members(ctx, repo, 3)
    ctx.group_service.delete_group(g["id"], actor="cl")
    assert repo.current_members_of_group(g["id"]) == set()
    assert repo.group_member_count(g["id"]) == 0


# ---- Joined column (mockup: UGL group) ----

def test_member_rows_carry_joined_at(ctx, repo):
    g = _group_with_members(ctx, repo, 2)
    rows = {m["id"]: m for m in ctx.group_service.list_group_members_page(g["id"], limit=50)["items"]}
    assert rows["u-m0000"]["joinedAt"]
    # The leader never joined (leadership is not membership) — no join date.
    assert "joinedAt" not in rows["u-l"]


def test_join_date_is_the_approval_moment_for_gated_groups(ctx, repo):
    """BR-G5 — the Joined column must show when the request was approved, not
    when it was made."""
    g = _gated_group_with_request(ctx, repo)
    req = ctx.group_service.list_join_requests(g["id"])[0]
    decided = ctx.group_service.decide_join_request(g["id"], req["id"], approve=True, actor="u-l")
    row = next(m for m in ctx.group_service.list_group_members_page(g["id"], limit=50)["items"]
               if m["id"] == "u-m")
    assert row["joinedAt"] >= decided["requestedAt"]


# ---- Paging with more than one leader (cursor block boundary) ----

def test_page_size_smaller_than_the_leader_block_still_advances(ctx, repo):
    """limit=1 with two leaders stops INSIDE the leader block. If the cursor
    forgot that, page 2 would resume in the member block and skip every member
    whose id sorts below the last leader's id."""
    _member(repo, "u-la", "la@company.com")
    _member(repo, "u-lb", "lb@company.com")
    g = ctx.group_service.create_group({"name": "TwoLeaders", "leaderIds": ["u-la"]}, actor="cl")
    ctx.group_service.assign_leader(g["id"], "u-lb", actor="cl")
    for uid in ("u-a", "u-z"):  # ids either side of the leader ids
        repo.put_user({"id": uid, "email": f"{uid}@company.com", "firstName": "F",
                       "lastName": "L", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
        ctx.group_service.join_group(g["id"], uid)

    seen, cursor, pages = [], None, 0
    while True:
        page = ctx.group_service.list_group_members_page(g["id"], limit=1, cursor=cursor)
        seen.extend(m["id"] for m in page["items"])
        pages += 1
        cursor = page.get("cursor")
        if not cursor or pages > 12:
            break
    assert seen == ["u-la", "u-lb", "u-a", "u-z"]


def test_leader_who_is_also_a_member_is_listed_once(ctx, repo):
    """A member promoted to leader keeps their join event, so they exist in both
    blocks — the member block must skip them."""
    _member(repo, "u-l", "l@company.com")
    _member(repo, "u-m", "m@company.com")
    g = ctx.group_service.create_group({"name": "Promo", "leaderIds": ["u-l"]}, actor="cl")
    ctx.group_service.join_group(g["id"], "u-m")
    ctx.group_service.assign_leader(g["id"], "u-m", actor="cl")
    ids = [m["id"] for m in ctx.group_service.list_group_members_page(g["id"], limit=50)["items"]]
    assert ids.count("u-m") == 1
    assert {m["id"]: m["roleInGroup"] for m in
            ctx.group_service.list_group_members_page(g["id"], limit=50)["items"]}["u-m"] == "UserGroupLeader"


def test_search_matches_a_leader_as_well_as_members(ctx, repo):
    g = _group_with_members(ctx, repo, 2)
    repo.put_user({**repo.get_user("u-l"), "firstName": "Priya", "lastName": "Nair"})
    assert [m["id"] for m in ctx.group_service.list_group_members_page(g["id"], q="priya")["items"]] == ["u-l"]


def test_search_key_refreshed_when_professional_role_changes(ctx, repo):
    g = _group_with_members(ctx, repo, 2)
    ctx.user_service.edit_user("u-m0001", {"professionalRole": "Solutions Architect"}, actor="admin")
    ids = [m["id"] for m in ctx.group_service.list_group_members_page(g["id"], q="solutions arch")["items"]]
    assert ids == ["u-m0001"]


# ---- Export path ----

def test_unpaged_listing_and_paged_walk_agree(ctx, repo):
    """CSV export walks the paged endpoint; it must produce the same set of rows
    as the full listing."""
    g = _group_with_members(ctx, repo, 6)
    full = [m["id"] for m in ctx.group_service.list_group_members(g["id"])]
    walked, cursor = [], None
    while True:
        page = ctx.group_service.list_group_members_page(g["id"], limit=2, cursor=cursor)
        walked.extend(m["id"] for m in page["items"])
        cursor = page.get("cursor")
        if not cursor:
            break
    assert walked == full


# ---- Join requests paging (US-1.21) ----

def test_join_requests_page_oldest_first_with_cursor(ctx, repo):
    _member(repo, "u-l", "l@company.com")
    g = ctx.group_service.create_group(
        {"name": "Gated", "leaderIds": ["u-l"], "approvalRequired": True}, actor="cl")
    for i in range(5):
        uid = f"u-r{i}"
        repo.put_user({"id": uid, "email": f"r{i}@company.com", "firstName": f"R{i}",
                       "lastName": "Req", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
        ctx.group_service.join_group(g["id"], uid)
    p1 = ctx.group_service.list_join_requests_page(g["id"], limit=2)
    assert p1["count"] == 2 and p1["total"] == 5 and p1["cursor"]
    p2 = ctx.group_service.list_join_requests_page(g["id"], limit=2, cursor=p1["cursor"])
    p3 = ctx.group_service.list_join_requests_page(g["id"], limit=2, cursor=p2["cursor"])
    ids = [r["id"] for r in p1["items"] + p2["items"] + p3["items"]]
    assert len(ids) == len(set(ids)) == 5
    assert "cursor" not in p3
    # Requester display names are resolved for the page.
    assert p1["items"][0]["memberName"]


# ---- Membership history paging (US-1.34) ----

def test_history_page_is_newest_first_and_pages_cleanly(ctx, repo):
    g = _group_with_members(ctx, repo, 3)
    ctx.group_service.leave_group(g["id"], "u-m0000")
    p1 = ctx.group_service.membership_history_page(group_id=g["id"], limit=2)
    assert p1["count"] == 2
    ats = [h["at"] for h in p1["items"]]
    assert ats == sorted(ats, reverse=True)
    seen, cursor, pages = [], p1.get("cursor"), 1
    seen.extend(h["id"] for h in p1["items"])
    while cursor and pages < 10:
        page = ctx.group_service.membership_history_page(group_id=g["id"], limit=2, cursor=cursor)
        seen.extend(h["id"] for h in page["items"])
        cursor = page.get("cursor")
        pages += 1
    assert len(seen) == len(set(seen)) == 4  # 3 joins + 1 leave
    assert p1["items"][0]["memberName"] and p1["items"][0]["groupName"]


def test_bad_history_cursor_is_validation_error_not_500(ctx, repo):
    g = _group_with_members(ctx, repo, 1)
    with pytest.raises(ValidationError):
        ctx.group_service.membership_history_page(group_id=g["id"], limit=2, cursor="nope")
