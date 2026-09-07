"""Repository (single-table DynamoDB) tests — moto-backed."""
from models import (
    MEVENT_JOINED,
    MEVENT_LEFT,
    ROLE_MEMBER,
    STATUS_ACTIVE,
    new_id,
    now_iso,
)


def _user(repo, email, role=ROLE_MEMBER):
    u = {"id": new_id("u"), "email": email, "firstName": "A", "lastName": "B",
         "role": role, "status": STATUS_ACTIVE}
    repo.put_user(u)
    return u


def test_put_get_user_and_email_lookup(repo):
    u = _user(repo, "jane@company.com")
    assert repo.get_user(u["id"])["email"] == "jane@company.com"
    assert repo.get_user_by_email("JANE@company.com")["id"] == u["id"]


def test_list_users_across_roles(repo):
    _user(repo, "m@company.com", ROLE_MEMBER)
    _user(repo, "cl@company.com", "CommunityLeader")
    emails = {u["email"] for u in repo.list_users()}
    assert {"m@company.com", "cl@company.com"} <= emails


def test_group_crud_and_listing(repo):
    repo.put_group({"id": "g-1", "name": "Cloud", "leaderIds": ["u-1"], "status": "Active"})
    assert repo.get_group("g-1")["name"] == "Cloud"
    assert any(g["id"] == "g-1" for g in repo.list_groups())


def test_membership_derivation(repo):
    m = _user(repo, "x@company.com")["id"]
    t1 = now_iso()
    repo.append_membership_event({"id": new_id("me"), "memberId": m, "groupId": "g-1",
                                  "type": MEVENT_JOINED, "at": t1})
    assert "g-1" in repo.current_groups_for_member(m)
    assert m in repo.current_members_of_group("g-1")
    # Leaving removes it — use a strictly later timestamp to guarantee ordering.
    from datetime import datetime, timezone, timedelta
    t2 = (datetime.fromisoformat(t1) + timedelta(seconds=1)).isoformat()
    repo.append_membership_event({"id": new_id("me"), "memberId": m, "groupId": "g-1",
                                  "type": MEVENT_LEFT, "at": t2})
    assert "g-1" not in repo.current_groups_for_member(m)


def test_join_request_pending_lookup(repo):
    repo.put_join_request({"id": "jr-1", "groupId": "g-2", "memberId": "u-9",
                           "status": "Pending", "requestedAt": now_iso()})
    assert repo.find_pending_request("g-2", "u-9")["id"] == "jr-1"


def test_otp_roundtrip_and_expiry(repo):
    from models import epoch
    repo.put_otp({"challengeId": "c-1", "userId": "u-1", "codeHash": "h",
                  "idToken": "header.payload.signature",
                  "expiresAt": epoch() + 300, "attempts": 0, "ttl": epoch() + 300})
    assert repo.get_otp("c-1")["userId"] == "u-1"
    # The whole OTP fix depends on this attribute surviving the round-trip.
    assert repo.get_otp("c-1")["idToken"] == "header.payload.signature"
    repo.put_otp({"challengeId": "c-2", "userId": "u-1", "codeHash": "h",
                  "expiresAt": epoch() - 1, "attempts": 0, "ttl": epoch() - 1})
    assert repo.get_otp("c-2") is None  # expired


# --- Paged admin user list (D-U1/D-U2, users pagination change 2026-08-03) ---

def _seed_users(repo, n, role="Member", status="Active", prefix="pu"):
    for i in range(n):
        repo.put_user({"id": f"{prefix}{i:03d}", "email": f"{prefix}{i:03d}@company.com",
                       "firstName": f"F{i:03d}", "lastName": "L", "role": role,
                       "status": status, "accountType": "cognito", "enabled": True})


def test_users_page_returns_limit_and_cursor(repo):
    _seed_users(repo, 7)
    rows, cursor = repo.list_users_page(limit=3)
    assert len(rows) == 3
    assert cursor is not None


def test_users_cursor_walks_all_partitions_without_overlap(repo):
    """No role filter -> fixed-order partition walk across roles (D-U1)."""
    _seed_users(repo, 4, role="Member", prefix="m")
    _seed_users(repo, 2, role="CommunityLeader", prefix="cl")
    _seed_users(repo, 1, role="Administrator", prefix="ad")
    seen, cursor = [], None
    for _ in range(10):
        rows, cursor = repo.list_users_page(limit=3, cursor=cursor)
        seen.extend(r["id"] for r in rows)
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == 7
    assert len(set(seen)) == 7
    # Partition order respected: all Administrators before CLs before Members.
    assert seen.index("ad000") < seen.index("cl000") < seen.index("m000")


def test_users_page_role_filter_single_partition(repo):
    _seed_users(repo, 3, role="Member", prefix="m")
    _seed_users(repo, 3, role="CommunityLeader", prefix="cl")
    rows, cursor = repo.list_users_page(role="CommunityLeader", limit=10)
    assert {r["id"] for r in rows} == {"cl000", "cl001", "cl002"}
    assert cursor is None


def test_users_page_status_and_keyword_post_filters(repo):
    _seed_users(repo, 4, prefix="a")
    _seed_users(repo, 2, status="Inactive", prefix="ina")
    rows, _ = repo.list_users_page(status="Inactive", limit=10)
    assert {r["id"] for r in rows} == {"ina000", "ina001"}
    rows2, _ = repo.list_users_page(keyword="a002@company", limit=10)
    assert {r["id"] for r in rows2} == {"a002"}


def test_users_page_id_filter_fills_page(repo):
    """Fetch-until-full: id_filter shrinks matches but the page still fills."""
    _seed_users(repo, 10)
    wanted = {f"pu{i:03d}" for i in (1, 3, 5, 7)}
    rows, cursor = repo.list_users_page(id_filter=wanted, limit=3)
    assert len(rows) == 3
    rows2, cursor2 = repo.list_users_page(id_filter=wanted, limit=3, cursor=cursor)
    assert len(rows2) == 1
    assert cursor2 is None
    assert {r["id"] for r in rows} | {r["id"] for r in rows2} == wanted


def test_users_page_invalid_cursor_raises(repo):
    import pytest
    from _conventions.errors import ValidationError
    with pytest.raises(ValidationError):
        repo.list_users_page(limit=3, cursor="garbage!!")


def test_users_page_cursor_role_mismatch_raises(repo):
    import pytest
    from _conventions.errors import ValidationError
    from repository import encode_user_cursor
    _seed_users(repo, 2)
    bad = encode_user_cursor({"role": "Member", "id": "pu000"})
    with pytest.raises(ValidationError):
        repo.list_users_page(role="CommunityLeader", limit=3, cursor=bad)


# ---- Current-membership projection (2026-08-05, 13k+ scale) ----

def test_projection_written_by_append_membership_event(repo):
    m = _user(repo, "p1@company.com")["id"]
    repo.append_membership_event({"id": new_id("me"), "memberId": m, "groupId": "g-p",
                                  "type": MEVENT_JOINED, "at": now_iso()})
    row = repo.get_group_member("g-p", m)
    assert row and row["memberId"] == m and row["joinedAt"]
    assert repo.group_member_count("g-p") == 1
    repo.append_membership_event({"id": new_id("me"), "memberId": m, "groupId": "g-p",
                                  "type": MEVENT_LEFT, "at": now_iso()})
    assert repo.get_group_member("g-p", m) is None
    assert repo.group_member_count("g-p") == 0


def test_search_key_denormalised_for_pushdown_filtering(repo):
    """The keyword filter is a DynamoDB contains() against this attribute, which
    is what stops a search from reading every member's profile."""
    u = _user(repo, "ada@company.com")
    repo.put_user({**u, "firstName": "Ada", "lastName": "Lovelace",
                   "professionalRole": "Principal Engineer"})
    repo.append_membership_event({"id": new_id("me"), "memberId": u["id"], "groupId": "g-s",
                                  "type": MEVENT_JOINED, "at": now_iso()})
    key = repo.get_group_member("g-s", u["id"])["searchKey"]
    assert "ada" in key and "ada@company.com" in key
    rows, _ = repo.group_members_page("g-s", limit=10, keyword="principal")
    assert [r["memberId"] for r in rows] == [u["id"]]
    assert repo.group_members_page("g-s", limit=10, keyword="nomatch")[0] == []


def test_group_members_page_reports_has_more(repo):
    for i in range(5):
        uid = f"pm-{i}"
        repo.put_user({"id": uid, "email": f"pm{i}@company.com", "firstName": "P",
                       "lastName": "M", "role": ROLE_MEMBER, "status": "Active"})
        repo.append_membership_event({"id": new_id("me"), "memberId": uid, "groupId": "g-h",
                                      "type": MEVENT_JOINED, "at": now_iso()})
    rows, has_more = repo.group_members_page("g-h", limit=2)
    assert len(rows) == 2 and has_more
    rows, has_more = repo.group_members_page("g-h", limit=2, after_member_id=rows[-1]["memberId"])
    assert len(rows) == 2 and has_more
    rows, has_more = repo.group_members_page("g-h", limit=2, after_member_id=rows[-1]["memberId"])
    assert len(rows) == 1 and not has_more


def test_list_groups_with_counts_returns_both_in_one_pass(repo):
    repo.put_group({"id": "g-c1", "name": "One", "leaderIds": [], "status": "Active"})
    repo.put_group({"id": "g-c2", "name": "Two", "leaderIds": [], "status": "Active"})
    u = _user(repo, "c1@company.com")["id"]
    repo.append_membership_event({"id": new_id("me"), "memberId": u, "groupId": "g-c1",
                                  "type": MEVENT_JOINED, "at": now_iso()})
    groups, counts = repo.list_groups_with_counts()
    assert {g["id"] for g in groups} >= {"g-c1", "g-c2"}
    assert counts.get("g-c1") == 1
    assert counts.get("g-c2", 0) == 0


def test_put_group_cannot_clobber_the_member_counter(repo):
    """The counter deliberately lives on its own item: put_group() does a full
    put_item, so a counter on the META row would be wiped by any group edit."""
    repo.put_group({"id": "g-k", "name": "Keep", "leaderIds": [], "status": "Active"})
    u = _user(repo, "k@company.com")["id"]
    repo.append_membership_event({"id": new_id("me"), "memberId": u, "groupId": "g-k",
                                  "type": MEVENT_JOINED, "at": now_iso()})
    group = repo.get_group("g-k")
    group["name"] = "Renamed"
    repo.put_group(group)
    assert repo.group_member_count("g-k") == 1


def test_derive_members_from_events_is_the_repair_path(repo):
    u = _user(repo, "r@company.com")["id"]
    repo.append_membership_event({"id": new_id("me"), "memberId": u, "groupId": "g-r",
                                  "type": MEVENT_JOINED, "at": now_iso()})
    # Simulate a projection that drifted (e.g. a table deployed before the
    # projection existed) and confirm the event log can rebuild it.
    repo.delete_group_member("g-r", u)
    assert repo.current_members_of_group("g-r") == set()
    assert set(repo.derive_members_from_events("g-r")) == {u}
