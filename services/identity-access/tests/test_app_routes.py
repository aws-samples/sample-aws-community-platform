"""App router + in-service authZ tests (US-1.12; SECURITY-08)."""
import json

from models import ROLE_MEMBER, STATUS_ACTIVE


def _event(method, path, body=None, claims=None, qs=None):
    evt = {"httpMethod": method, "path": path,
           "body": json.dumps(body) if body is not None else None,
           "queryStringParameters": qs}
    if claims is not None:
        evt["requestContext"] = {"authorizer": {"claims": claims}, "identity": {"sourceIp": "1.2.3.4"}}
    return evt


def _member_claims(sub="u-m", role=ROLE_MEMBER):
    return {"sub": sub, "role": role, "account_type": "cognito"}

def _cl_claims(sub="u-cl"):
    return {"sub": sub, "role": "CommunityLeader", "account_type": "cognito"}


def test_login_route_public(ctx, aws, repo):
    from app import dispatch
    from models import now_iso
    sub = aws.create_user("dev@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "dev@company.com", "firstName": "Dev", "lastName": "User",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    resp = dispatch(_event("POST", "/auth/login",
                           {"email": "dev@company.com", "password": "Secret!123"}), ctx)
    assert resp["statusCode"] == 200
    assert "Access-Control-Allow-Origin" in resp["headers"]


def test_unknown_route_404(ctx):
    from app import dispatch
    assert dispatch(_event("GET", "/nope"), ctx)["statusCode"] == 404


def test_protected_route_requires_auth(ctx):
    from app import dispatch
    # listUsers without claims -> 401
    resp = dispatch(_event("GET", "/users"), ctx)
    assert resp["statusCode"] == 401


def test_member_cannot_create_group_403(ctx, repo):
    from app import dispatch
    resp = dispatch(_event("POST", "/groups", {"name": "X", "leaderIds": ["u-l"]},
                           claims=_member_claims()), ctx)
    assert resp["statusCode"] == 403


def test_admin_can_list_users(ctx, repo):
    from app import dispatch
    repo.put_user({"id": "u-1", "email": "a@company.com", "firstName": "A", "lastName": "B",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    resp = dispatch(_event("GET", "/users", claims={"sub": "admin-1", "role": "Administrator"}), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["count"] >= 1


def test_community_leader_can_create_group(ctx, repo):
    from app import dispatch
    repo.put_user({"id": "u-l", "email": "l@company.com", "firstName": "L", "lastName": "X",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    resp = dispatch(_event("POST", "/groups", {"name": "Cloud", "leaderIds": ["u-l"]},
                           claims={"sub": "cl-1", "role": "CommunityLeader"}), ctx)
    assert resp["statusCode"] == 201


def test_member_can_join_open_group(ctx, repo):
    from app import dispatch
    repo.put_user({"id": "u-l", "email": "l@company.com", "firstName": "L", "lastName": "X",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    g = ctx.group_service.create_group({"name": "Open", "leaderIds": ["u-l"]}, actor="cl")
    resp = dispatch(_event("POST", f"/groups/{g['id']}/join", {}, claims=_member_claims()), ctx)
    assert resp["statusCode"] == 200


def test_reset_password_route_public(ctx, aws):
    from app import dispatch
    aws.create_user("dev@company.com", "Secret!123")
    resp = dispatch(_event("POST", "/auth/reset", {"email": "dev@company.com"}), ctx)
    assert resp["statusCode"] == 200


def test_confirm_reset_password_route_public(ctx, aws):
    from app import dispatch
    aws.create_user("dev@company.com", "Secret!123")
    dispatch(_event("POST", "/auth/reset", {"email": "dev@company.com"}), ctx)
    code = aws.idp.forgot_password(ClientId=aws.client_id, Username="dev@company.com")[
        "ResponseMetadata"]["HTTPHeaders"]["x-moto-forgot-password-confirmation-code"]
    resp = dispatch(_event("POST", "/auth/reset/confirm",
                           {"email": "dev@company.com", "code": code, "newPassword": "NewSecret!123"}), ctx)
    assert resp["statusCode"] == 200


def test_admin_can_create_user_via_form(ctx):
    from app import dispatch
    resp = dispatch(_event("POST", "/users",
                           {"email": "form@company.com", "firstName": "Fo", "lastName": "Rm"},
                           claims={"sub": "admin-1", "role": "Administrator"}), ctx)
    assert resp["statusCode"] == 201
    assert json.loads(resp["body"])["email"] == "form@company.com"


def test_member_cannot_create_user_403(ctx):
    from app import dispatch
    resp = dispatch(_event("POST", "/users",
                           {"email": "x@company.com", "firstName": "X", "lastName": "Y"},
                           claims=_member_claims()), ctx)
    assert resp["statusCode"] == 403


def _approval_group_with_request(ctx, repo):
    """Create an approval-required group + a pending join request from a member."""
    repo.put_user({"id": "u-l", "email": "l@company.com", "firstName": "L", "lastName": "X",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    repo.put_user({"id": "u-req", "email": "req@company.com", "firstName": "Rita", "lastName": "Quest",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    g = ctx.group_service.create_group(
        {"name": "Gated", "leaderIds": ["u-l"], "approvalRequired": True}, actor="cl")
    out = ctx.group_service.join_group(g["id"], "u-req")
    return g["id"], out["requestId"]


def test_community_leader_can_list_join_requests(ctx, repo):
    """US-1.21 — CL reviews pending join requests for any group (global scope)."""
    from app import dispatch
    group_id, _ = _approval_group_with_request(ctx, repo)
    resp = dispatch(_event("GET", f"/groups/{group_id}/requests",
                           claims={"sub": "cl-1", "role": "CommunityLeader"}), ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 1
    assert body["items"][0]["memberName"] == "Rita Quest"
    assert body["items"][0]["memberEmail"] == "req@company.com"


def test_community_leader_can_approve_join_request(ctx, repo):
    """US-1.21 — CL approves via POST /groups/{id}/requests/{requestId}."""
    from app import dispatch
    group_id, req_id = _approval_group_with_request(ctx, repo)
    resp = dispatch(_event("POST", f"/groups/{group_id}/requests/{req_id}",
                           {"decision": "approve"},
                           claims={"sub": "cl-1", "role": "CommunityLeader"}), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "Approved"
    # Membership took effect at the moment of approval (BR-G5).
    assert "u-req" in ctx.repo.current_members_of_group(group_id)


def test_ugl_can_decide_own_group_request_only(ctx, repo):
    """US-1.21 — UGL decides for their led group; other groups are 403."""
    from app import dispatch
    group_id, req_id = _approval_group_with_request(ctx, repo)
    ugl_claims = {"sub": "u-l", "role": "UserGroupLeader", "led_group_id": group_id}
    other_claims = {"sub": "u-other", "role": "UserGroupLeader", "led_group_id": "g-other"}
    assert dispatch(_event("POST", f"/groups/{group_id}/requests/{req_id}",
                           {"decision": "reject"}, claims=other_claims), ctx)["statusCode"] == 403
    resp = dispatch(_event("POST", f"/groups/{group_id}/requests/{req_id}",
                           {"decision": "reject", "reason": "Not a fit"}, claims=ugl_claims), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "Rejected"


def test_reject_without_reason_400(ctx, repo):
    from app import dispatch
    group_id, req_id = _approval_group_with_request(ctx, repo)
    resp = dispatch(_event("POST", f"/groups/{group_id}/requests/{req_id}",
                           {"decision": "reject"},
                           claims={"sub": "cl-1", "role": "CommunityLeader"}), ctx)
    assert resp["statusCode"] == 400


def test_member_cannot_decide_join_request_403(ctx, repo):
    from app import dispatch
    group_id, req_id = _approval_group_with_request(ctx, repo)
    resp = dispatch(_event("POST", f"/groups/{group_id}/requests/{req_id}",
                           {"decision": "approve"}, claims=_member_claims()), ctx)
    assert resp["statusCode"] == 403


def test_cl_cross_group_join_request_queue(ctx, repo):
    """US-1.21 — CL sees pending requests across all groups with groupName; UGL/Member 403."""
    from app import dispatch
    group_id, _ = _approval_group_with_request(ctx, repo)
    resp = dispatch(_event("GET", "/join-requests",
                           claims={"sub": "cl-1", "role": "CommunityLeader"}), ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 1
    assert body["items"][0]["groupName"] == "Gated"
    assert body["items"][0]["memberName"] == "Rita Quest"
    assert dispatch(_event("GET", "/join-requests",
                           claims={"sub": "u-l", "role": "UserGroupLeader",
                                   "led_group_id": group_id}), ctx)["statusCode"] == 403
    assert dispatch(_event("GET", "/join-requests", claims=_member_claims()), ctx)["statusCode"] == 403


def test_cl_can_restore_soft_deleted_group(ctx, repo):
    """US-1.11 — Undo Delete within grace period; hidden from members meanwhile."""
    from app import dispatch
    repo.put_user({"id": "u-l", "email": "l@company.com", "firstName": "L", "lastName": "X",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    g = ctx.group_service.create_group({"name": "Doomed", "leaderIds": ["u-l"]}, actor="cl")
    cl = {"sub": "cl-1", "role": "CommunityLeader"}
    assert dispatch(_event("DELETE", f"/groups/{g['id']}", claims=cl), ctx)["statusCode"] == 204
    # Members don't see soft-deleted groups; CL sees them with includeDeleted=true.
    member_list = json.loads(dispatch(_event("GET", "/groups", claims=_member_claims()), ctx)["body"])
    assert all(x["id"] != g["id"] for x in member_list["items"])
    cl_list = json.loads(dispatch(_event("GET", "/groups", claims=cl,
                                         qs={"includeDeleted": "true"}), ctx)["body"])
    row = next(x for x in cl_list["items"] if x["id"] == g["id"])
    assert row["status"] == "SoftDeleted" and row.get("deletedAt")
    # includeDeleted is ignored for non-CL callers.
    member_list2 = json.loads(dispatch(_event("GET", "/groups", claims=_member_claims(),
                                              qs={"includeDeleted": "true"}), ctx)["body"])
    assert all(x["id"] != g["id"] for x in member_list2["items"])
    # Restore.
    resp = dispatch(_event("POST", f"/groups/{g['id']}/restore", claims=cl), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["status"] == "Active"
    # Restoring an active group is a 400; member restore is 403.
    assert dispatch(_event("POST", f"/groups/{g['id']}/restore", claims=cl), ctx)["statusCode"] == 400
    assert dispatch(_event("POST", f"/groups/{g['id']}/restore", claims=_member_claims()), ctx)["statusCode"] == 403


def test_delete_group_auto_rejects_pending_requests(ctx, repo):
    """US-1.21 lifecycle — pending requests are system-rejected on group delete."""
    from app import dispatch
    group_id, req_id = _approval_group_with_request(ctx, repo)
    cl = {"sub": "cl-1", "role": "CommunityLeader"}
    assert dispatch(_event("DELETE", f"/groups/{group_id}", claims=cl), ctx)["statusCode"] == 204
    jrs = ctx.repo.list_join_requests(group_id)
    assert jrs and all(j["status"] == "Rejected" for j in jrs)
    assert jrs[0]["decisionReason"] == "User group deleted"
    # Cross-group queue no longer shows it.
    body = json.loads(dispatch(_event("GET", "/join-requests", claims=cl), ctx)["body"])
    assert body["count"] == 0


def test_ugl_cannot_join_or_leave_group_403(ctx, repo):
    """Decided 2026-08-03 — UGLs lead their group and can neither join nor
    leave groups; membership/leadership changes are a CL function."""
    from app import dispatch
    repo.put_user({"id": "u-l", "email": "l@company.com", "firstName": "L", "lastName": "X",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    g = ctx.group_service.create_group({"name": "Open", "leaderIds": ["u-l"]}, actor="cl")
    ugl_claims = {"sub": "u-other-ugl", "role": "UserGroupLeader", "led_group_id": "g-led"}
    assert dispatch(_event("POST", f"/groups/{g['id']}/join", {}, claims=ugl_claims), ctx)["statusCode"] == 403
    assert dispatch(_event("POST", f"/groups/{g['id']}/leave", {}, claims=ugl_claims), ctx)["statusCode"] == 403


def test_membership_history_resolves_names(ctx, repo):
    """History rows carry memberName/groupName so the UI shows names, not ids."""
    from app import dispatch
    repo.put_user({"id": "u-l", "email": "l@company.com", "firstName": "Lea", "lastName": "Der",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    repo.put_user({"id": "u-m", "email": "m@company.com", "firstName": "Mia", "lastName": "Moon",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    g = ctx.group_service.create_group({"name": "Named Group", "leaderIds": ["u-l"]}, actor="cl")
    ctx.group_service.join_group(g["id"], "u-m")
    resp = dispatch(_event("GET", "/membership-history", claims=_member_claims(),
                           qs={"groupId": g["id"]}), ctx)
    assert resp["statusCode"] == 200
    rows = json.loads(resp["body"])["items"]
    assert rows and rows[0]["memberName"] == "Mia Moon"
    assert rows[0]["groupName"] == "Named Group"


# --- listUsers pagination params (D-U1/D-U5, 2026-08-03) ---

def _admin_claims():
    return {"sub": "admin-1", "role": "Administrator", "account_type": "cognito"}


def _seed_n(repo, n):
    for i in range(n):
        repo.put_user({"id": f"ru{i:03d}", "email": f"ru{i:03d}@company.com", "firstName": f"F{i:03d}",
                       "lastName": "L", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})


def test_list_users_paged(ctx, repo):
    from app import dispatch
    _seed_n(repo, 5)
    resp = dispatch(_event("GET", "/users", claims=_admin_claims(), qs={"limit": "2"}), ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 2
    assert body["cursor"]
    resp2 = dispatch(_event("GET", "/users", claims=_admin_claims(),
                            qs={"limit": "2", "cursor": body["cursor"]}), ctx)
    body2 = json.loads(resp2["body"])
    assert body2["count"] == 2
    assert {i["id"] for i in body2["items"]}.isdisjoint({i["id"] for i in body["items"]})


def test_list_users_filters_without_limit_use_paged_path(ctx, repo):
    from app import dispatch
    _seed_n(repo, 3)
    resp = dispatch(_event("GET", "/users", claims=_admin_claims(), qs={"role": "Member"}), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["count"] == 3  # default page size 25 covers all


def test_list_users_invalid_params_400(ctx, repo):
    from app import dispatch
    _seed_n(repo, 1)
    for qs in ({"limit": "abc"}, {"limit": "0"}, {"limit": "9999"},
               {"role": "SuperAdmin"}, {"status": "Banned"},
               {"limit": "2", "cursor": "garbage!!"}):
        resp = dispatch(_event("GET", "/users", claims=_admin_claims(), qs=qs), ctx)
        assert resp["statusCode"] == 400, qs
        assert json.loads(resp["body"])["code"] == "VALIDATION_ERROR"


def test_list_users_unpaged_when_no_params(ctx, repo):
    from app import dispatch
    _seed_n(repo, 3)
    resp = dispatch(_event("GET", "/users", claims=_admin_claims()), ctx)
    body = json.loads(resp["body"])
    assert body["count"] == 3
    assert "cursor" not in body


# ---- Group member list: paged vs unpaged dispatch (2026-08-05) ----

def _group_of(ctx, repo, n):
    repo.put_user({"id": "gl", "email": "gl@company.com", "firstName": "Lead", "lastName": "Er",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    g = ctx.group_service.create_group({"name": "Guild", "leaderIds": ["gl"]}, actor="cl")
    for i in range(n):
        uid = f"gm{i:03d}"
        repo.put_user({"id": uid, "email": f"gm{i:03d}@company.com", "firstName": f"M{i:03d}",
                       "lastName": "Ember", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
        ctx.group_service.join_group(g["id"], uid)
    return g


def test_group_members_paged_walks_with_cursor(ctx, repo):
    from app import dispatch
    g = _group_of(ctx, repo, 5)  # 5 members + 1 leader
    resp = dispatch(_event("GET", f"/groups/{g['id']}/members",
                           claims=_cl_claims(), qs={"limit": "2"}), ctx)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["count"] == 2
    assert body["cursor"]
    resp2 = dispatch(_event("GET", f"/groups/{g['id']}/members",
                            claims=_cl_claims(), qs={"limit": "2", "cursor": body["cursor"]}), ctx)
    body2 = json.loads(resp2["body"])
    assert {i["id"] for i in body2["items"]}.isdisjoint({i["id"] for i in body["items"]})


def test_group_members_unpaged_returns_everyone_for_export(ctx, repo):
    from app import dispatch
    g = _group_of(ctx, repo, 4)
    resp = dispatch(_event("GET", f"/groups/{g['id']}/members", claims=_cl_claims()), ctx)
    body = json.loads(resp["body"])
    assert body["count"] == 5  # 4 members + the leader
    assert "cursor" not in body


def test_group_members_search_and_role_in_group(ctx, repo):
    from app import dispatch
    g = _group_of(ctx, repo, 4)
    resp = dispatch(_event("GET", f"/groups/{g['id']}/members",
                           claims=_cl_claims(), qs={"q": "M002"}), ctx)
    body = json.loads(resp["body"])
    assert [i["id"] for i in body["items"]] == ["gm002"]
    assert body["items"][0]["roleInGroup"] == "Member"
    leader = dispatch(_event("GET", f"/groups/{g['id']}/members",
                             claims=_cl_claims(), qs={"q": "Lead"}), ctx)
    assert json.loads(leader["body"])["items"][0]["roleInGroup"] == "UserGroupLeader"


def test_group_members_invalid_paging_params_400(ctx, repo):
    from app import dispatch
    g = _group_of(ctx, repo, 1)
    for qs in ({"limit": "abc"}, {"limit": "0"}, {"limit": "500"}, {"limit": "2", "cursor": "garbage!!"}):
        resp = dispatch(_event("GET", f"/groups/{g['id']}/members", claims=_cl_claims(), qs=qs), ctx)
        assert resp["statusCode"] == 400, qs


# ---- My Group / 13k-scale routes (2026-08-05) ----

def _ugl_claims(sub, led_group_id):
    """UserGroupLeader claims. `led_group_id` is what makes group-scoped
    permissions resolve — token_claims_handler puts it on the JWT at sign-in."""
    return {"sub": sub, "role": "UserGroupLeader", "account_type": "cognito",
            "led_group_id": led_group_id}


def _seeded_group(ctx, repo, members=3, approval=False):
    repo.put_user({"id": "u-lead", "email": "lead@company.com", "firstName": "Priya",
                   "lastName": "Nair", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
    g = ctx.group_service.create_group(
        {"name": "Serverless Guild", "leaderIds": ["u-lead"], "approvalRequired": approval},
        actor="cl")
    for i in range(members):
        uid = f"u-mm{i}"
        repo.put_user({"id": uid, "email": f"mm{i}@company.com", "firstName": f"M{i}",
                       "lastName": "Ember", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
        ctx.group_service.join_group(g["id"], uid)
    return g


def test_login_returns_led_group_id_for_a_user_group_leader(ctx, aws, repo):
    """My Group needs to know WHICH group without a discovery round-trip."""
    from app import dispatch
    from models import now_iso
    sub = aws.create_user("ugl@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "ugl@company.com", "firstName": "U", "lastName": "G",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    g = ctx.group_service.create_group({"name": "Led", "leaderIds": [sub]}, actor="cl")
    # create_group promoted them to UserGroupLeader with ledGroupId set.
    user = repo.get_user(sub)
    repo.put_user({**user, "lastVerifiedAt": now_iso()})

    resp = dispatch(_event("POST", "/auth/login",
                           {"email": "ugl@company.com", "password": "Secret!123"}), ctx)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["role"] == "UserGroupLeader"
    assert body["ledGroupId"] == g["id"]


def test_login_omits_led_group_id_for_a_plain_member(ctx, aws, repo):
    from app import dispatch
    from models import now_iso
    sub = aws.create_user("plain@company.com", "Secret!123")
    repo.put_user({"id": sub, "email": "plain@company.com", "firstName": "P", "lastName": "M",
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE, "accountType": "cognito",
                   "lastVerifiedAt": now_iso()})
    resp = dispatch(_event("POST", "/auth/login",
                           {"email": "plain@company.com", "password": "Secret!123"}), ctx)
    assert "ledGroupId" not in json.loads(resp["body"])


def test_group_members_route_paged_with_joined_at(ctx, repo):
    from app import dispatch
    g = _seeded_group(ctx, repo, members=3)
    resp = dispatch(_event("GET", f"/groups/{g['id']}/members",
                           claims=_member_claims("u-lead", "UserGroupLeader"),
                           qs={"limit": "2"}), ctx)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["count"] == 2 and body["cursor"]
    # Leader first, then members by id; the member row carries its join date.
    assert body["items"][0]["id"] == "u-lead"
    assert body["items"][1]["joinedAt"]


def test_group_members_route_rejects_a_bad_limit(ctx, repo):
    from app import dispatch
    g = _seeded_group(ctx, repo, members=1)
    for bad in ("0", "999", "abc"):
        resp = dispatch(_event("GET", f"/groups/{g['id']}/members",
                               claims=_cl_claims(), qs={"limit": bad}), ctx)
        assert resp["statusCode"] == 400, bad


def test_group_members_route_rejects_a_bad_cursor(ctx, repo):
    from app import dispatch
    g = _seeded_group(ctx, repo, members=1)
    resp = dispatch(_event("GET", f"/groups/{g['id']}/members",
                           claims=_cl_claims(), qs={"cursor": "@@@"}), ctx)
    assert resp["statusCode"] == 400


def test_group_route_member_count_without_folding_history(ctx, repo):
    from app import dispatch
    g = _seeded_group(ctx, repo, members=4)
    resp = dispatch(_event("GET", f"/groups/{g['id']}",
                           claims=_member_claims("u-lead", "UserGroupLeader")), ctx)
    assert json.loads(resp["body"])["memberCount"] == 4


def test_join_requests_route_paged_with_total(ctx, repo):
    from app import dispatch
    g = _seeded_group(ctx, repo, members=0, approval=True)
    for i in range(3):
        uid = f"u-rr{i}"
        repo.put_user({"id": uid, "email": f"rr{i}@company.com", "firstName": f"R{i}",
                       "lastName": "Req", "role": ROLE_MEMBER, "status": STATUS_ACTIVE})
        ctx.group_service.join_group(g["id"], uid)
    # A UGL's join-request permission is group-scoped, so the JWT must carry
    # led_group_id (set by token_claims_handler) — this is the claim My Group
    # relies on for the Join Requests tab to work at all.
    resp = dispatch(_event("GET", f"/groups/{g['id']}/requests",
                           claims=_ugl_claims("u-lead", g["id"]), qs={"limit": "2"}), ctx)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["count"] == 2 and body["total"] == 3 and body["cursor"]


def test_ugl_cannot_read_join_requests_of_a_group_they_do_not_lead(ctx, repo):
    """US-1.12/US-1.21 — a UGL is scoped to their own group. My Group can only
    ever address one group, but the route must enforce it regardless."""
    from app import dispatch
    g = _seeded_group(ctx, repo, members=0, approval=True)
    resp = dispatch(_event("GET", f"/groups/{g['id']}/requests",
                           claims=_ugl_claims("u-other", "g-somewhere-else")), ctx)
    assert resp["statusCode"] == 403


def test_ugl_can_remove_a_member_of_their_own_group_only(ctx, repo):
    """US-1.17 — the Remove button on My Group."""
    from app import dispatch
    g = _seeded_group(ctx, repo, members=2)
    ok = dispatch(_event("DELETE", f"/groups/{g['id']}/members/u-mm0",
                         claims=_ugl_claims("u-lead", g["id"])), ctx)
    assert ok["statusCode"] == 204
    assert "u-mm0" not in ctx.repo.current_members_of_group(g["id"])
    denied = dispatch(_event("DELETE", f"/groups/{g['id']}/members/u-mm1",
                             claims=_ugl_claims("u-lead", "g-elsewhere")), ctx)
    assert denied["statusCode"] == 403


def test_ugl_cannot_edit_group_configuration(ctx, repo):
    """US-1.18 — group settings are a Community Leader function, which is why My
    Group shows no Edit/Delete controls."""
    from app import dispatch
    g = _seeded_group(ctx, repo, members=1)
    for evt in (_event("PUT", f"/groups/{g['id']}", {"name": "Renamed"},
                       claims=_ugl_claims("u-lead", g["id"])),
                _event("DELETE", f"/groups/{g['id']}", claims=_ugl_claims("u-lead", g["id"]))):
        assert dispatch(evt, ctx)["statusCode"] == 403


def test_membership_history_route_paged_newest_first(ctx, repo):
    from app import dispatch
    g = _seeded_group(ctx, repo, members=3)
    resp = dispatch(_event("GET", "/membership-history", claims=_member_claims(),
                           qs={"groupId": g["id"], "limit": "2"}), ctx)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["count"] == 2
    ats = [h["at"] for h in body["items"]]
    assert ats == sorted(ats, reverse=True)
    assert body["cursor"]


def test_membership_history_route_unpaged_still_works(ctx, repo):
    """The member-scoped view is small and deliberately stays unpaged."""
    from app import dispatch
    g = _seeded_group(ctx, repo, members=2)
    resp = dispatch(_event("GET", "/membership-history", claims=_member_claims(),
                           qs={"memberId": "u-mm0"}), ctx)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["count"] == 1 and body["items"][0]["groupId"] == g["id"]
