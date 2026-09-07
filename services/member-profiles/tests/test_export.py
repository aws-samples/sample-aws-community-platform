"""Async Member Directory CSV export: role gate, job lifecycle, CSV output, routes.

The OpenSearch-backed reads (count_members / search_members) are faked, since moto
provides no OpenSearch. Everything else runs for real against moto DynamoDB — so
the job record, the conditional-write lock and the route wiring are exercised as
deployed rather than mocked.

The distinguishing concern here versus identity-access's user export is WHO may
run it: `GET /members` is open to any authenticated principal, so without the gate
any of ~25k Members could download the whole directory as a file. Several tests
below exist only to pin that gate.
"""
import json

import pytest
from _conventions.authz import Principal
from _conventions.errors import ForbiddenError, NotFoundError, ValidationError
from export_service import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_READY,
    ExportService,
)


class FakeStorage:
    """Records what would be written to S3 and hands back a fixed URL."""

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


def _svc(repo, storage=None, lambda_client=None, fan_out=None):
    return ExportService(repo, storage or FakeStorage(), fan_out=fan_out,
                         lambda_client=lambda_client or FakeLambda(),
                         worker_function="test-member-export-worker")


def _principal(role="CommunityLeader", sub="u-cl"):
    return Principal.from_claims({"sub": sub, "role": role})


def _event(method, path, *, claims=None, body=None):
    return {
        "httpMethod": method,
        "path": path,
        "headers": {"Authorization": "Bearer test-token"},
        "requestContext": {"authorizer": {"claims": claims or {}}},
        "body": json.dumps(body) if body is not None else None,
        "queryStringParameters": None,
    }


# ------------------------------------------------------- who may export

@pytest.mark.parametrize("role", ["CommunityLeader", "UserGroupLeader"])
def test_leaders_may_start_an_export(repo, role):
    out = _svc(repo).start_export({}, principal=_principal(role, sub=f"u-{role}"))
    assert out["status"] == STATUS_QUEUED


@pytest.mark.parametrize("role", ["Member", "Administrator", "SpeakerBureau", None])
def test_export_is_refused_to_everyone_else(repo, role):
    """The gate, not presentation, is the control. Administrators are excluded on
    purpose — they have the richer Admin > Users export in identity-access."""
    with pytest.raises(ForbiddenError):
        _svc(repo).start_export({}, principal=_principal(role, sub="u-x"))


def test_status_polling_is_refused_to_a_member_too(repo):
    """Gating only the POST would leave a Member able to poll — and therefore to
    obtain the presigned download URL — for a job id they had guessed or seen."""
    job_id = _svc(repo).start_export({}, principal=_principal())["jobId"]
    with pytest.raises(ForbiddenError):
        _svc(repo).get_export(job_id, principal=_principal("Member", sub="u-m"))


# ------------------------------------------------------- start_export

def test_start_export_creates_the_job_before_invoking_the_worker(repo):
    lam = FakeLambda()
    out = _svc(repo, lambda_client=lam).start_export({}, principal=_principal())

    assert out["status"] == STATUS_QUEUED
    # Queued: nothing counted yet, so there is no denominator and the bar is
    # indeterminate rather than a misleading 0%.
    assert out["percent"] is None
    assert out["processed"] == 0
    # The record must exist BEFORE the invoke, or the SPA's first poll could 404
    # on a job the worker is already writing to.
    assert repo.get_export_job(out["jobId"]) is not None

    assert len(lam.calls) == 1
    call = lam.calls[0]
    assert call["InvocationType"] == "Event"   # async: must not block the request
    assert call["FunctionName"] == "test-member-export-worker"
    assert json.loads(call["Payload"])["jobId"] == out["jobId"]


def test_start_export_records_only_the_supported_filters(repo):
    """certId is dropped deliberately: resolving cert holders needs a fan-out with
    the caller's JWT, which the async worker does not have."""
    out = _svc(repo).start_export(
        {"q": "smith", "role": "Member", "groupId": "g-1",
         "certId": "c-1", "bogus": "x"},
        principal=_principal())
    stored = repo.get_export_job(out["jobId"])
    assert stored["filters"] == {"q": "smith", "role": "Member", "groupId": "g-1"}


def test_start_export_ignores_blank_filters(repo):
    out = _svc(repo).start_export({"q": "  ", "role": "", "groupId": None},
                                  principal=_principal())
    assert repo.get_export_job(out["jobId"])["filters"] == {}


def test_second_export_for_the_same_leader_is_refused(repo):
    """One in-flight export per leader. The SPA also disables the button, but that
    is presentation only — a refresh re-enables it."""
    svc = _svc(repo)
    svc.start_export({}, principal=_principal())
    with pytest.raises(ValidationError):
        svc.start_export({}, principal=_principal())


def test_two_different_leaders_can_export_concurrently(repo):
    svc = _svc(repo)
    svc.start_export({}, principal=_principal(sub="u-cl-1"))
    svc.start_export({}, principal=_principal("UserGroupLeader", sub="u-ugl-1"))


def test_releasing_the_lock_allows_a_new_export(repo):
    svc = _svc(repo)
    svc.start_export({}, principal=_principal())
    repo.release_export_lock("u-cl")
    svc.start_export({}, principal=_principal())     # must not raise


def test_failed_worker_invoke_marks_the_job_failed_and_frees_the_lock(repo):
    """A job the worker never received must not sit at "queued" forever, and must
    not hold the leader's only slot."""
    svc = _svc(repo, lambda_client=FakeLambda(fail=True))
    with pytest.raises(ValidationError):
        svc.start_export({}, principal=_principal())

    jobs = [i for i in repo._t.scan().get("Items", []) if i["pk"].startswith("EXPORT#")]
    assert [j["status"] for j in jobs] == [STATUS_FAILED]
    _svc(repo).start_export({}, principal=_principal())   # lock freed


# ------------------------------------------------------- group-name resolution

def test_group_names_are_resolved_at_request_time_and_stored_on_the_job(repo, fan_out):
    """Resolved HERE, not in the worker: the fan-out forwards the caller's JWT and
    the worker has no caller."""
    fan_out.responses["groups"] = {"items": [
        {"id": "g-1", "name": "AWS Bangalore"},
        {"id": "g-2", "name": "Serverless Guild"},
    ]}
    out = _svc(repo, fan_out=fan_out).start_export(
        {}, principal=_principal(), bearer_token="tok-123")

    assert repo.get_export_job(out["jobId"])["groupNames"] == {
        "g-1": "AWS Bangalore", "g-2": "Serverless Guild"}
    # The caller's token must be forwarded, or Identity & Access refuses the read.
    assert fan_out.calls[0]["token"] == "tok-123"
    assert fan_out.calls[0]["calls"] == {"groups": "/groups"}


def test_export_still_starts_when_the_group_lookup_fails(repo, fan_out):
    """Degraded column (raw ids) beats a failed export."""
    fan_out.failing.add("groups")
    out = _svc(repo, fan_out=fan_out).start_export({}, principal=_principal())
    assert out["status"] == STATUS_QUEUED
    assert repo.get_export_job(out["jobId"])["groupNames"] == {}


def test_an_unreasonable_number_of_groups_is_not_stored(repo, fan_out):
    """DynamoDB items cap at 400 KB; past MAX_GROUP_NAMES the worker falls back to
    ids rather than the write failing."""
    fan_out.responses["groups"] = {
        "items": [{"id": f"g-{i}", "name": f"Group {i}"} for i in range(600)]}
    out = _svc(repo, fan_out=fan_out).start_export({}, principal=_principal())
    assert repo.get_export_job(out["jobId"])["groupNames"] == {}


# ------------------------------------------------------- get_export

def test_get_export_returns_progress_without_a_url_while_running(repo):
    svc = _svc(repo)
    job_id = svc.start_export({}, principal=_principal())["jobId"]
    repo.update_export_job(job_id, {"status": "running", "total": 200, "processed": 50})

    out = svc.get_export(job_id, principal=_principal())
    assert out["percent"] == 25
    assert "url" not in out          # no link until the file exists


def test_get_export_returns_a_fresh_download_url_when_ready(repo):
    svc = _svc(repo)
    job_id = svc.start_export({}, principal=_principal())["jobId"]
    repo.update_export_job(job_id, {"status": STATUS_READY, "total": 10, "processed": 10})

    out = svc.get_export(job_id, principal=_principal())
    assert out["percent"] == 100
    assert out["url"].startswith("https://example.test/members/")
    assert out["expiresInSeconds"] == 300


def test_another_leaders_job_is_reported_as_missing_not_forbidden(repo):
    """404 rather than 403 so the response cannot confirm that another leader's
    job id exists."""
    job_id = _svc(repo).start_export({}, principal=_principal(sub="u-cl-1"))["jobId"]
    with pytest.raises(NotFoundError):
        _svc(repo).get_export(job_id, principal=_principal(sub="u-cl-2"))


def test_unknown_job_is_not_found(repo):
    with pytest.raises(NotFoundError):
        _svc(repo).get_export("mexp-nope", principal=_principal())


def test_percent_is_none_when_the_total_is_unknown(repo):
    """OpenSearch could not supply a count -> indeterminate bar, not a fabricated
    percentage."""
    svc = _svc(repo)
    job_id = svc.start_export({}, principal=_principal())["jobId"]
    repo.update_export_job(job_id, {"status": "running", "total": None, "processed": 40})
    out = svc.get_export(job_id, principal=_principal())
    assert out["percent"] is None
    assert out["processed"] == 40


def test_percent_is_clamped_when_members_are_added_mid_export(repo):
    """The count is taken once at the start, so members created during the run can
    push processed past it."""
    svc = _svc(repo)
    job_id = svc.start_export({}, principal=_principal())["jobId"]
    repo.update_export_job(job_id, {"status": "running", "total": 100, "processed": 130})
    assert svc.get_export(job_id, principal=_principal())["percent"] == 100


def test_failed_job_surfaces_its_error(repo):
    svc = _svc(repo)
    job_id = svc.start_export({}, principal=_principal())["jobId"]
    repo.update_export_job(job_id, {"status": STATUS_FAILED, "error": "boom"})
    assert svc.get_export(job_id, principal=_principal())["error"] == "boom"


# ------------------------------------------------------- worker / CSV

def _fake_search(pages):
    """search_members stub: yields (docs, cursor) per call."""
    calls = {"n": 0, "kwargs": []}

    def search_members(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        calls["kwargs"].append(kwargs)
        return pages[i] if i < len(pages) else ([], None)
    return search_members, calls


def test_worker_writes_a_csv_and_marks_the_job_ready(repo, monkeypatch, fan_out):
    import export_worker

    fan_out.responses["groups"] = {"items": [
        {"id": "g-1", "name": "AWS Bangalore"}, {"id": "g-2", "name": "Serverless Guild"}]}
    svc = _svc(repo, fan_out=fan_out)
    job_id = svc.start_export({}, principal=_principal())["jobId"]
    job = repo.get_export_job(job_id)

    docs = [
        {"firstName": "Ann", "lastName": "Lee", "email": "a@x.com", "role": "Member",
         "status": "active", "groups": [{"groupId": "g-1"}, {"groupId": "g-2"}],
         "city": "Pune", "country": "India", "awsProject": True},
        {"firstName": "Bob", "lastName": "Roy", "email": "b@x.com", "role": "Member",
         "status": "inactive", "awsProject": False},
    ]
    search, _ = _fake_search([(docs, None)])
    monkeypatch.setattr(repo, "search_members", search)
    monkeypatch.setattr(repo, "count_members", lambda **kw: 2)

    storage = FakeStorage()
    rows = export_worker._run_export(repo, storage, job_id, job)

    assert rows == 2
    lines = storage.objects[job["fileKey"]].decode().split("\n")
    assert lines[0] == ",".join(export_worker.COLUMNS)
    # Real group NAMES, semicolon-joined so the cell needs no CSV quoting. The old
    # client-side export rendered an array of objects and produced the literal
    # text "[object Object],[object Object]" here.
    assert lines[1] == ("Ann,Lee,a@x.com,Member,active,AWS Bangalore; Serverless Guild,"
                        "Pune,India,true")
    # status stays lowercase (unlike identity-access, which title-cases it):
    # member-profiles stores and serves "active"/"inactive" natively.
    # Missing optional fields render as empty cells, not "None".
    assert lines[2] == "Bob,Roy,b@x.com,Member,inactive,,,,false"

    final = repo.get_export_job(job_id)
    assert final["status"] == STATUS_READY
    # total reconciled to rows written, so a finished bar always reads 100%.
    assert final["processed"] == 2 and final["total"] == 2


def test_unknown_group_ids_fall_back_to_the_raw_id(repo):
    """Happens if the name lookup failed at request time, or a group was created
    after the job started. Degraded but never wrong."""
    import export_worker

    cell = export_worker._group_cell(
        {"groups": [{"groupId": "g-1"}, {"groupId": "g-missing"}]},
        {"g-1": "AWS Bangalore"})
    assert cell == "AWS Bangalore; g-missing"


def test_group_cell_reads_the_flat_group_ids_array_too(repo):
    """Index docs carry a flat groupIds array alongside the nested objects."""
    import export_worker

    assert export_worker._group_cell({"groupIds": ["g-1"]}, {"g-1": "AWS Bangalore"}) \
        == "AWS Bangalore"
    assert export_worker._group_cell({}, {}) == ""


def test_worker_passes_the_stored_filters_to_the_search(repo, monkeypatch):
    """The CSV must match the filtered table the leader was looking at."""
    import export_worker

    job_id = _svc(repo).start_export(
        {"q": "smith", "role": "Member", "groupId": "g-1"},
        principal=_principal())["jobId"]
    job = repo.get_export_job(job_id)

    search, calls = _fake_search([([], None)])
    monkeypatch.setattr(repo, "search_members", search)
    counted = {}
    monkeypatch.setattr(repo, "count_members",
                        lambda **kw: counted.update(kw) or 0)

    export_worker._run_export(repo, FakeStorage(), job_id, job)

    assert calls["kwargs"][0]["q"] == "smith"
    assert calls["kwargs"][0]["role"] == "Member"
    assert calls["kwargs"][0]["group_id"] == "g-1"
    # The count must use the SAME query as the row walk or the percentage drifts.
    assert counted == {"q": "smith", "role": "Member", "group_id": "g-1"}


def test_worker_follows_the_cursor_across_pages(repo, monkeypatch):
    import export_worker

    job_id = _svc(repo).start_export({}, principal=_principal())["jobId"]
    job = repo.get_export_job(job_id)

    page1 = ([{"firstName": f"U{i}"} for i in range(3)], "cursor-1")
    page2 = ([{"firstName": "U3"}], None)
    search, calls = _fake_search([page1, page2])
    monkeypatch.setattr(repo, "search_members", search)
    monkeypatch.setattr(repo, "count_members", lambda **kw: 4)

    storage = FakeStorage()
    assert export_worker._run_export(repo, storage, job_id, job) == 4
    assert calls["n"] == 2                      # stopped when the cursor came back None
    assert calls["kwargs"][1]["cursor"] == "cursor-1"
    assert len(storage.objects[job["fileKey"]].decode().strip().split("\n")) == 5


def test_worker_leaves_total_unset_when_opensearch_cannot_count(repo, monkeypatch):
    import export_worker

    job_id = _svc(repo).start_export({}, principal=_principal())["jobId"]
    job = repo.get_export_job(job_id)
    search, _ = _fake_search([([{"firstName": "A"}], None)])
    monkeypatch.setattr(repo, "search_members", search)
    monkeypatch.setattr(repo, "count_members", lambda **kw: None)

    export_worker._run_export(repo, FakeStorage(), job_id, job)
    # Reconciled at the end, so a finished export still reports 100%.
    assert repo.get_export_job(job_id)["total"] == 1


def test_worker_marks_the_job_failed_and_frees_the_lock(repo, monkeypatch):
    """Deliberately swallows the error: the function runs with
    MaximumRetryAttempts=0, so a re-raise would let Lambda retry an export the
    leader has already been told failed."""
    import export_worker

    job_id = _svc(repo).start_export({}, principal=_principal())["jobId"]
    monkeypatch.setattr(repo, "count_members",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("os down")))
    monkeypatch.setattr(export_worker, "ProfileRepository", lambda table: repo)
    monkeypatch.setattr(export_worker, "ExportStorage", FakeStorage)

    out = export_worker.handler({"jobId": job_id}, None)

    assert out == {"ok": False}
    failed = repo.get_export_job(job_id)
    assert failed["status"] == STATUS_FAILED
    # Generic message: it is shown to the leader and exception text can carry
    # internals.
    assert "os down" not in failed["error"]
    # Lock freed, so the leader can retry rather than waiting out the 30-min TTL.
    _svc(repo).start_export({}, principal=_principal())


def test_worker_does_not_rebuild_an_already_finished_export(repo, monkeypatch):
    """Async invocations can be redelivered; a completed export must not be redone
    (it would re-sign a new object under a key the leader may already be
    downloading)."""
    import export_worker

    job_id = _svc(repo).start_export({}, principal=_principal())["jobId"]
    repo.update_export_job(job_id, {"status": STATUS_READY})
    monkeypatch.setattr(export_worker, "ProfileRepository", lambda table: repo)
    monkeypatch.setattr(export_worker, "ExportStorage", FakeStorage)

    called = {"n": 0}
    monkeypatch.setattr(repo, "count_members",
                        lambda **kw: called.__setitem__("n", called["n"] + 1))

    out = export_worker.handler({"jobId": job_id}, None)
    assert out["ok"] is True
    assert called["n"] == 0                     # never started the walk


def test_worker_without_a_job_id_is_a_no_op():
    import export_worker
    assert export_worker.handler({}, None)["ok"] is False


def test_worker_on_a_vanished_job_is_a_no_op(repo, monkeypatch):
    """The job record has the same 1-day TTL as the S3 object, so an invoke that
    arrives after expiry has nothing to write to."""
    import export_worker

    monkeypatch.setattr(export_worker, "ProfileRepository", lambda table: repo)
    monkeypatch.setattr(export_worker, "ExportStorage", FakeStorage)
    assert export_worker.handler({"jobId": "mexp-gone"}, None)["ok"] is False


# ------------------------------------------------------- routes

def _ctx(aws, fan_out, events):
    from app import Context
    return Context(table=aws.table, idempotency_table="member-profiles-idem-test",
                   fan_out=fan_out, events=events,
                   export_storage=FakeStorage(), lambda_client=FakeLambda())


def test_post_members_export_returns_202(aws, fan_out, events):
    from app import dispatch
    resp = dispatch(_event("POST", "/members/export", body={},
                           claims={"sub": "u-cl", "role": "CommunityLeader"}),
                    _ctx(aws, fan_out, events))
    assert resp["statusCode"] == 202
    assert json.loads(resp["body"])["status"] == STATUS_QUEUED


def test_export_routes_require_authentication(aws, fan_out, events):
    from app import dispatch
    ctx = _ctx(aws, fan_out, events)
    assert dispatch(_event("POST", "/members/export", body={}), ctx)["statusCode"] == 401
    assert dispatch(_event("GET", "/members/export/mexp-1"), ctx)["statusCode"] == 401


def test_export_route_is_denied_to_a_member(aws, fan_out, events):
    """The HTTP-level pin on the gate: GET /members stays open to any authenticated
    principal, but exporting the directory as a file does not."""
    from app import dispatch
    ctx = _ctx(aws, fan_out, events)
    claims = {"sub": "u-m", "role": "Member"}
    assert dispatch(_event("POST", "/members/export", body={}, claims=claims),
                    ctx)["statusCode"] == 403
    assert dispatch(_event("GET", "/members/export/mexp-1", claims=claims),
                    ctx)["statusCode"] == 403


def test_get_export_route_round_trips(aws, fan_out, events):
    from app import dispatch
    ctx = _ctx(aws, fan_out, events)
    claims = {"sub": "u-ugl", "role": "UserGroupLeader"}
    started = json.loads(
        dispatch(_event("POST", "/members/export", body={}, claims=claims), ctx)["body"])

    resp = dispatch(_event("GET", f"/members/export/{started['jobId']}", claims=claims), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["jobId"] == started["jobId"]


def test_export_path_does_not_shadow_the_member_routes(aws):
    """"export" must not bind as {id}: /members/export is its own route, and the
    existing /members/me relies on the same first-wins ordering."""
    from app import _match
    assert _match("POST", "/members/export")[0] == "startDirectoryExport"
    assert _match("GET", "/members/export/mexp-1")[0] == "getDirectoryExport"
    assert _match("GET", "/members/me")[0] == "getOwnProfile"
    assert _match("GET", "/members/u-1")[0] == "getMember"
