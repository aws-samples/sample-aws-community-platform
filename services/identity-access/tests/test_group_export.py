"""Async group-roster CSV export (UGL > My Group > Export).

Third export on the same pattern, but the first whose rows come from the
AUTHORITATIVE DynamoDB roster rather than OpenSearch — `joinedAt` lives on the
membership projection and is not indexed at all, so an index-sourced export could
not reproduce this file. Everything here therefore runs for real against moto
DynamoDB: the group, the membership projection, the job record and the
conditional-write lock are all exercised as deployed.

Two concerns get the most attention because they are what a shared job record and
a shared worker can silently get wrong: that each status route only serves its own
KIND of export, and that a job is bound to the group in its URL.
"""
import json

import pytest
from _conventions.errors import NotFoundError, ValidationError
from export_service import (
    KIND_GROUP_MEMBERS,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_READY,
    ExportService,
)
from models import ROLE_MEMBER, STATUS_ACTIVE


class FakeStorage:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_csv(self, key, body):
        self.objects[key] = body

    def download_url(self, key):
        return {"url": f"https://example.test/{key}?sig=abc", "expiresInSeconds": 300}


class FakeLambda:
    def __init__(self, fail=False):
        self.calls = []
        self._fail = fail

    def invoke(self, **kwargs):
        if self._fail:
            raise RuntimeError("invoke boom")
        self.calls.append(kwargs)
        return {"StatusCode": 202}


def _svc(repo, storage=None, lambda_client=None):
    return ExportService(repo, storage or FakeStorage(),
                         lambda_client=lambda_client or FakeLambda(),
                         worker_function="test-export-worker")


def _member(repo, uid, email, first="A", last="B"):
    repo.put_user({"id": uid, "email": email, "firstName": first, "lastName": last,
                   "role": ROLE_MEMBER, "status": STATUS_ACTIVE})


def _group_with(ctx, repo, *, leaders=("u-l",), members=()):
    """A real group with real leaders and joined members."""
    for lid in leaders:
        _member(repo, lid, f"{lid}@company.com", first="Lead", last=lid)
    for mid in members:
        _member(repo, mid, f"{mid}@company.com", first="Mem", last=mid)
    group = ctx.group_service.create_group(
        {"name": "Cloud Guild", "leaderIds": list(leaders)}, actor="cl")
    for mid in members:
        ctx.group_service.join_group(group["id"], mid)
    return group


def _event(method, path, *, claims=None, body=None):
    return {
        "httpMethod": method, "path": path,
        "headers": {"Authorization": "Bearer test-token"},
        "requestContext": {"authorizer": {"claims": claims or {}},
                           "identity": {"sourceIp": "1.2.3.4"}},
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": None,
    }


# ------------------------------------------------------------------ start

def test_start_creates_a_group_scoped_job_and_invokes_the_worker(ctx, repo):
    group = _group_with(ctx, repo, members=("u-m",))
    lam = FakeLambda()
    out = _svc(repo, lambda_client=lam).start_group_member_export(
        group["id"], {}, actor="u-l")

    assert out["status"] == STATUS_QUEUED
    assert out["percent"] is None and out["processed"] == 0

    stored = repo.get_export_job(out["jobId"])
    # The record must exist BEFORE the invoke, or the SPA's first poll could 404
    # on a job the worker is already writing to.
    assert stored is not None
    assert stored["kind"] == KIND_GROUP_MEMBERS
    assert stored["groupId"] == group["id"]
    # Its own prefix: the IAM grant for this export must not reach the admin
    # roster exports under users/, nor member-profiles' under members/.
    assert stored["fileKey"].startswith("groups/")
    assert out["fileName"].startswith("group-members-")

    assert len(lam.calls) == 1
    assert lam.calls[0]["InvocationType"] == "Event"   # async: must not block
    assert json.loads(lam.calls[0]["Payload"])["jobId"] == out["jobId"]


def test_start_records_only_the_keyword_filter(ctx, repo):
    """The roster is already scoped to one group, so the keyword is the only
    filter the screen offers."""
    group = _group_with(ctx, repo)
    out = _svc(repo).start_group_member_export(
        group["id"], {"q": "ravi", "role": "Member", "status": "Active", "bogus": "x"},
        actor="u-l")
    assert repo.get_export_job(out["jobId"])["filters"] == {"q": "ravi"}


def test_start_ignores_a_blank_keyword(ctx, repo):
    group = _group_with(ctx, repo)
    out = _svc(repo).start_group_member_export(group["id"], {"q": "   "}, actor="u-l")
    assert repo.get_export_job(out["jobId"])["filters"] == {}


def test_one_export_per_person_across_both_kinds(ctx, repo):
    """The lock is keyed on the ACTOR alone, so a roster export and an admin
    export cannot run together. That is the intended reading of "one export at a
    time per person" and keeps the release path unambiguous."""
    group = _group_with(ctx, repo)
    svc = _svc(repo)
    svc.start_group_member_export(group["id"], {}, actor="u-l")
    with pytest.raises(ValidationError):
        svc.start_group_member_export(group["id"], {}, actor="u-l")
    with pytest.raises(ValidationError):
        svc.start_export({}, actor="u-l")          # the other kind, same person


def test_two_leaders_can_export_concurrently(ctx, repo):
    group = _group_with(ctx, repo, leaders=("u-l",))
    svc = _svc(repo)
    svc.start_group_member_export(group["id"], {}, actor="u-l")
    svc.start_group_member_export(group["id"], {}, actor="u-cl")   # must not raise


def test_failed_invoke_marks_the_job_failed_and_frees_the_lock(ctx, repo):
    group = _group_with(ctx, repo)
    with pytest.raises(ValidationError):
        _svc(repo, lambda_client=FakeLambda(fail=True)).start_group_member_export(
            group["id"], {}, actor="u-l")

    jobs = [i for i in repo._t.scan().get("Items", []) if i["pk"].startswith("EXPORT#")]
    assert [j["status"] for j in jobs] == [STATUS_FAILED]
    _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")   # lock freed


# ------------------------------------------------------------------ status

def test_status_returns_progress_then_a_download_url(ctx, repo):
    group = _group_with(ctx, repo)
    svc = _svc(repo)
    job_id = svc.start_group_member_export(group["id"], {}, actor="u-l")["jobId"]

    repo.update_export_job(job_id, {"status": "running", "total": 4, "processed": 1})
    running = svc.get_group_member_export(group["id"], job_id, actor="u-l")
    assert running["percent"] == 25
    assert "url" not in running            # no link until the file exists

    repo.update_export_job(job_id, {"status": STATUS_READY, "total": 4, "processed": 4})
    ready = svc.get_group_member_export(group["id"], job_id, actor="u-l")
    assert ready["percent"] == 100
    assert ready["url"].startswith("https://example.test/groups/")
    assert ready["expiresInSeconds"] == 300


def test_another_persons_job_is_reported_as_missing(ctx, repo):
    group = _group_with(ctx, repo)
    job_id = _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")["jobId"]
    with pytest.raises(NotFoundError):
        _svc(repo).get_group_member_export(group["id"], job_id, actor="u-other")


def test_a_job_cannot_be_read_through_another_groups_url(ctx, repo):
    """Not redundant with the actor check: without it a leader could read any of
    their own jobs through any group's URL, so the route would stop meaning what
    it says and an audit of "who exported group X" could not rely on it."""
    group = _group_with(ctx, repo, leaders=("u-l",), members=("u-m",))
    other = ctx.group_service.create_group(
        {"name": "Other", "leaderIds": ["u-l2"]}, actor="cl")
    job_id = _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")["jobId"]
    with pytest.raises(NotFoundError):
        _svc(repo).get_group_member_export(other["id"], job_id, actor="u-l")


def test_each_status_route_serves_only_its_own_kind(ctx, repo):
    """A shared job record means the two routes could otherwise cross over: the
    admin URL would hand back a group CSV, and vice versa."""
    group = _group_with(ctx, repo)
    svc = _svc(repo)
    group_job = svc.start_group_member_export(group["id"], {}, actor="u-l")["jobId"]
    # Roster job on the admin route -> absent.
    with pytest.raises(NotFoundError):
        svc.get_export(group_job, actor="u-l")

    repo.release_export_lock("u-l")
    user_job = svc.start_export({}, actor="u-l")["jobId"]
    # Admin job on the roster route -> absent.
    with pytest.raises(NotFoundError):
        svc.get_group_member_export(group["id"], user_job, actor="u-l")


def test_a_job_record_without_a_kind_still_resolves_as_an_admin_export(ctx, repo):
    """Records written before the group export existed carry no `kind`; they must
    keep working on the admin route rather than 404ing after deploy."""
    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-a")["jobId"]
    job = repo.get_export_job(job_id)
    repo._t.put_item(Item={**{k: v for k, v in job.items() if k != "kind"},
                           "pk": f"EXPORT#{job_id}", "sk": "JOB"})
    assert repo.get_export_job(job_id).get("kind") is None
    assert svc.get_export(job_id, actor="u-a")["jobId"] == job_id


# ------------------------------------------------------------------ denominator

def test_count_includes_leaders_who_are_not_members(ctx, repo):
    """The listing emits leaders as a first block, so they belong in the
    denominator — leadership is not membership and a leader may have no
    projection row."""
    group = _group_with(ctx, repo, leaders=("u-l",), members=("u-m1", "u-m2"))
    total = repo.count_group_members(group["id"], leader_ids=["u-l"])
    assert total == 3          # 2 members + 1 leader who never joined


def test_count_does_not_double_count_a_leader_who_also_joined(ctx, repo):
    """Counting them twice would leave the bar stalled short of 100%."""
    group = _group_with(ctx, repo, leaders=("u-l",), members=("u-m",))
    ctx.group_service.join_group(group["id"], "u-l")
    assert repo.count_group_members(group["id"], leader_ids=["u-l"]) == 2


def test_count_is_unknown_when_a_keyword_filter_applies(ctx, repo):
    """The projection keeps no counter for a filtered subset, and counting one
    would walk the very rows the export is about to walk. None renders an
    indeterminate bar rather than a fabricated number."""
    group = _group_with(ctx, repo, members=("u-m",))
    assert repo.count_group_members(group["id"], leader_ids=["u-l"], keyword="ravi") is None


# ------------------------------------------------------------------ worker

def _worker(monkeypatch, repo, storage):
    import export_worker
    monkeypatch.setattr(export_worker, "IdentityRepository", lambda table: repo)
    monkeypatch.setattr(export_worker, "ExportStorage", lambda: storage)
    monkeypatch.setenv("TABLE_NAME", "identity-access-test")
    return export_worker


def test_worker_writes_the_roster_csv_and_marks_it_ready(ctx, repo, monkeypatch):
    group = _group_with(ctx, repo, leaders=("u-l",), members=("u-m",))
    job_id = _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")["jobId"]

    storage = FakeStorage()
    worker = _worker(monkeypatch, repo, storage)
    out = worker.handler({"jobId": job_id}, None)
    assert out["ok"] is True

    job = repo.get_export_job(job_id)
    assert job["status"] == STATUS_READY
    text = storage.objects[job["fileKey"]].decode()
    lines = text.strip().split("\n")

    # Header keeps the shape the old client-side export produced, with the two
    # group-only columns last.
    assert lines[0] == ",".join(worker.GROUP_COLUMNS)
    assert lines[0].endswith(",roleInGroup,joinedAt")
    assert len(lines) == 3                      # header + leader + member

    cols = worker.GROUP_COLUMNS
    rows = [dict(zip(cols, line.split(","), strict=False)) for line in lines[1:]]
    by_email = {r["email"]: r for r in rows}

    # Leaders are emitted first and carry no join date — leadership is not
    # membership, so there is nothing to show.
    assert rows[0]["email"] == "u-l@company.com"
    assert by_email["u-l@company.com"]["roleInGroup"] == "UserGroupLeader"
    assert by_email["u-l@company.com"]["joinedAt"] == ""
    # A joined member carries a DATE, not a timestamp: the file is read in a
    # spreadsheet where a time component is noise.
    member = by_email["u-m@company.com"]
    assert member["roleInGroup"] == ROLE_MEMBER
    assert len(member["joinedAt"]) == 10 and member["joinedAt"][4] == "-"

    # Reconciled, so a finished bar always reads 100%.
    assert job["processed"] == 2 and job["total"] == 2


def test_worker_pages_through_a_roster_larger_than_one_page(ctx, repo, monkeypatch):
    import export_worker
    monkeypatch.setattr(export_worker, "GROUP_PAGE_SIZE", 2)

    group = _group_with(ctx, repo, leaders=("u-l",),
                        members=tuple(f"u-m{i}" for i in range(5)))
    job_id = _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")["jobId"]

    storage = FakeStorage()
    worker = _worker(monkeypatch, repo, storage)
    worker.handler({"jobId": job_id}, None)

    job = repo.get_export_job(job_id)
    body = storage.objects[job["fileKey"]].decode().strip().split("\n")
    assert len(body) == 7                       # header + 1 leader + 5 members
    assert job["processed"] == 6
    # No duplicates across pages — the leaders-then-members cursor must not
    # re-emit a row when the leader block ends mid-page.
    emails = [line.split(",")[0] for line in body[1:]]
    assert len(set(emails)) == 6


def test_worker_honours_the_keyword_filter(ctx, repo, monkeypatch):
    group = _group_with(ctx, repo, leaders=("u-l",), members=("u-m1", "u-m2"))
    repo.put_user({**repo.get_user("u-m1"), "firstName": "Zoya"})
    ctx.group_service.join_group(group["id"], "u-m1")   # refresh the search key
    job_id = _svc(repo).start_group_member_export(
        group["id"], {"q": "zoya"}, actor="u-l")["jobId"]

    storage = FakeStorage()
    worker = _worker(monkeypatch, repo, storage)
    worker.handler({"jobId": job_id}, None)

    job = repo.get_export_job(job_id)
    assert job["status"] == STATUS_READY
    # Filtered, so the denominator was unknown while running and only reconciled
    # at the end.
    assert job["total"] == job["processed"]


def test_worker_marks_a_job_with_no_group_failed(ctx, repo, monkeypatch):
    """Rather than writing an empty CSV that looks like a group with no members."""
    group = _group_with(ctx, repo)
    job_id = _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")["jobId"]
    repo.update_export_job(job_id, {"groupId": ""})

    worker = _worker(monkeypatch, repo, FakeStorage())
    assert worker.handler({"jobId": job_id}, None) == {"ok": False}
    assert repo.get_export_job(job_id)["status"] == STATUS_FAILED
    _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")   # lock freed


def test_worker_failure_is_swallowed_and_reported_generically(ctx, repo, monkeypatch):
    """The function runs with MaximumRetryAttempts=0: re-raising would let Lambda
    retry an export the leader has already been told failed."""
    group = _group_with(ctx, repo)
    job_id = _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")["jobId"]
    monkeypatch.setattr(repo, "count_group_members",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ddb down")))

    worker = _worker(monkeypatch, repo, FakeStorage())
    assert worker.handler({"jobId": job_id}, None) == {"ok": False}
    failed = repo.get_export_job(job_id)
    assert failed["status"] == STATUS_FAILED
    assert "ddb down" not in failed["error"]     # internals never surface
    _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")   # lock freed


def test_worker_does_not_rebuild_a_finished_roster_export(ctx, repo, monkeypatch):
    group = _group_with(ctx, repo)
    job_id = _svc(repo).start_group_member_export(group["id"], {}, actor="u-l")["jobId"]
    repo.update_export_job(job_id, {"status": STATUS_READY})

    called = {"n": 0}
    monkeypatch.setattr(repo, "count_group_members",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1))
    worker = _worker(monkeypatch, repo, FakeStorage())
    assert worker.handler({"jobId": job_id}, None)["ok"] is True
    assert called["n"] == 0                     # never started the walk


def test_group_cell_does_not_re_translate_api_shaped_values(ctx):
    """These rows come from the API serializer, not an OpenSearch document, so
    `_cell`'s status/awsProject translations must NOT be applied again."""
    import export_worker
    row = {"status": "Active", "awsProject": True, "joinedAt": "2026-08-26T10:11:12Z"}
    assert export_worker._group_cell(row, "status") == "Active"     # not re-capitalised
    assert export_worker._group_cell(row, "awsProject") == "true"
    assert export_worker._group_cell(row, "joinedAt") == "2026-08-26"
    assert export_worker._group_cell({"awsProject": False}, "awsProject") == "false"
    assert export_worker._group_cell({}, "joinedAt") == ""
    assert export_worker._group_cell({"joinedAt": "not-a-date"}, "joinedAt") == "not-a-date"


# ------------------------------------------------------------------ routes

def _ctx_with_export(aws):
    from app import Context

    class FakeSes:
        def send(self, to, subject, body): pass

    class FakeEvents:
        def publish(self, event_type, data, correlation_id=None): pass

    return Context(table=aws.table, events=FakeEvents(), ses=FakeSes(),
                   export_storage=FakeStorage(), lambda_client=FakeLambda(),
                   settings={"allowedEmailDomains": ["company.com"], "auditEnabled": True,
                             "otpIntervalDays": 30, "selfRegistrationEnabled": True})


def _claims(role, sub="u-l"):
    return {"sub": sub, "role": role, "account_type": "cognito", "led_group_id": "g-1"}


@pytest.mark.parametrize("role", ["CommunityLeader", "UserGroupLeader"])
def test_route_allows_group_directory_viewers(aws, ctx, repo, role):
    from app import dispatch
    group = _group_with(ctx, repo)
    resp = dispatch(_event("POST", f"/groups/{group['id']}/members/export", body={},
                           claims=_claims(role)), _ctx_with_export(aws))
    assert resp["statusCode"] == 202
    assert json.loads(resp["body"])["status"] == STATUS_QUEUED


@pytest.mark.parametrize("role", ["Member", "Administrator"])
def test_route_refuses_everyone_else(aws, ctx, repo, role):
    """Exporting shares listGroupMembers' capability exactly, so nobody gains a
    power they did not already have. Administrators hold no user-group-directory
    permission and are refused here just as they are on the listing."""
    from app import dispatch
    group = _group_with(ctx, repo)
    resp = dispatch(_event("POST", f"/groups/{group['id']}/members/export", body={},
                           claims=_claims(role, sub="u-x")), _ctx_with_export(aws))
    assert resp["statusCode"] == 403


def test_routes_require_authentication(aws):
    from app import dispatch
    ctx_ = _ctx_with_export(aws)
    assert dispatch(_event("POST", "/groups/g-1/members/export", body={}),
                    ctx_)["statusCode"] == 401
    assert dispatch(_event("GET", "/groups/g-1/members/export/gexp-1"),
                    ctx_)["statusCode"] == 401


def test_route_round_trips(aws, ctx, repo):
    from app import dispatch
    group = _group_with(ctx, repo)
    ctx_ = _ctx_with_export(aws)
    started = json.loads(dispatch(
        _event("POST", f"/groups/{group['id']}/members/export", body={},
               claims=_claims("UserGroupLeader")), ctx_)["body"])

    resp = dispatch(_event("GET", f"/groups/{group['id']}/members/export/{started['jobId']}",
                           claims=_claims("UserGroupLeader")), ctx_)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["jobId"] == started["jobId"]


def test_export_paths_do_not_shadow_the_group_routes(aws):
    from app import _match
    assert _match("POST", "/groups/g-1/members/export")[0] == "startGroupMemberExport"
    assert _match("GET", "/groups/g-1/members/export/gexp-1")[0] == "getGroupMemberExport"
    # The listing anchors at the end of "members" and must still win for itself.
    assert _match("GET", "/groups/g-1/members")[0] == "listGroupMembers"
    assert _match("DELETE", "/groups/g-1/members/u-1")[0] == "removeMember"
    assert _match("GET", "/groups/stats/members")[0] == "membersByGroup"
    # The job id is named jobId, never id, so it cannot be authorized as a group.
    assert _match("GET", "/groups/g-1/members/export/gexp-1")[1] == {
        "id": "g-1", "jobId": "gexp-1"}
