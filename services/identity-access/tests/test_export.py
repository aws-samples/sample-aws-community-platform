"""Async CSV export: job lifecycle, per-admin guard, worker output, routes.

The OpenSearch-backed reads (count_users / search_users) are faked, since moto
provides no OpenSearch. Everything else runs for real against moto DynamoDB —
so the job record, the conditional-write lock and the route wiring are all
exercised as deployed, not mocked.
"""
import json

import pytest
from _conventions.errors import NotFoundError, ValidationError
from export_service import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_READY,
    ExportService,
)
from models import ROLE_MEMBER


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


def _svc(repo, storage=None, lambda_client=None):
    return ExportService(repo, storage or FakeStorage(),
                         lambda_client=lambda_client or FakeLambda(),
                         worker_function="test-export-worker")


def _admin_claims(sub="u-admin"):
    return {"sub": sub, "role": "Administrator", "account_type": "cognito"}


def _event(method, path, body=None, claims=None):
    evt = {"httpMethod": method, "path": path,
           "body": json.dumps(body) if body is not None else None,
           "queryStringParameters": None}
    if claims is not None:
        evt["requestContext"] = {"authorizer": {"claims": claims},
                                 "identity": {"sourceIp": "1.2.3.4"}}
    return evt


# ---------------------------------------------------------------- start_export

def test_start_export_creates_job_and_invokes_worker_async(repo):
    lam = FakeLambda()
    out = _svc(repo, lambda_client=lam).start_export({}, actor="u-admin")

    assert out["status"] == STATUS_QUEUED
    # Queued: the worker has not counted yet, so there is no denominator and the
    # bar is indeterminate rather than a misleading 0%.
    assert out["percent"] is None
    assert out["processed"] == 0
    # The record must exist BEFORE the worker is invoked, or the SPA's first
    # poll could 404 on a job the worker is already writing to.
    assert repo.get_export_job(out["jobId"]) is not None

    assert len(lam.calls) == 1
    call = lam.calls[0]
    assert call["InvocationType"] == "Event"   # async: must not block the request
    assert json.loads(call["Payload"])["jobId"] == out["jobId"]


def test_start_export_records_only_the_supported_filters(repo):
    """The CSV matches the filtered table (q/role/status). groupId is excluded:
    it resolves to a per-user id set that would become a terms clause of up to
    13k values."""
    out = _svc(repo).start_export(
        {"q": "smith", "role": "Member", "status": "Active",
         "groupId": "g-1", "bogus": "x"},
        actor="u-admin")
    stored = repo.get_export_job(out["jobId"])
    assert stored["filters"] == {"q": "smith", "role": "Member", "status": "Active"}


def test_start_export_ignores_blank_filters(repo):
    out = _svc(repo).start_export({"q": "  ", "role": "", "status": None}, actor="u-admin")
    assert repo.get_export_job(out["jobId"])["filters"] == {}


def test_second_export_for_the_same_admin_is_refused(repo):
    """One in-flight export per admin. The SPA also disables the button, but that
    is presentation only — a page refresh re-enables it, so this is the control."""
    svc = _svc(repo)
    svc.start_export({}, actor="u-admin")
    with pytest.raises(ValidationError):
        svc.start_export({}, actor="u-admin")


def test_a_different_admin_can_export_concurrently(repo):
    svc = _svc(repo)
    svc.start_export({}, actor="u-admin-1")
    svc.start_export({}, actor="u-admin-2")   # must not raise


def test_releasing_the_lock_allows_a_new_export(repo):
    svc = _svc(repo)
    svc.start_export({}, actor="u-admin")
    repo.release_export_lock("u-admin")
    svc.start_export({}, actor="u-admin")     # must not raise


def test_failed_worker_invoke_marks_the_job_failed_and_frees_the_lock(repo):
    """A job the worker never received must not sit at "queued" forever, and it
    must not hold the admin's slot."""
    svc = _svc(repo, lambda_client=FakeLambda(fail=True))
    with pytest.raises(ValidationError):
        svc.start_export({}, actor="u-admin")

    jobs = [i for i in repo._t.scan().get("Items", []) if i["pk"].startswith("EXPORT#")]
    assert [j["status"] for j in jobs] == [STATUS_FAILED]
    # Lock released, so the admin can retry immediately.
    _svc(repo).start_export({}, actor="u-admin")


# ---------------------------------------------------------------- get_export

def test_get_export_returns_progress_without_a_url_while_running(repo):
    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-admin")["jobId"]
    repo.update_export_job(job_id, {"status": "running", "total": 200, "processed": 50})

    out = svc.get_export(job_id, actor="u-admin")
    assert out["percent"] == 25
    assert "url" not in out          # no link until the file exists


def test_get_export_returns_a_fresh_download_url_when_ready(repo):
    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-admin")["jobId"]
    repo.update_export_job(job_id, {"status": STATUS_READY, "total": 10, "processed": 10})

    out = svc.get_export(job_id, actor="u-admin")
    assert out["percent"] == 100
    assert out["url"].startswith("https://example.test/")
    assert out["expiresInSeconds"] == 300


def test_another_admins_job_is_reported_as_missing_not_forbidden(repo):
    """404 rather than 403 so the response cannot confirm that someone else's
    job id exists."""
    job_id = _svc(repo).start_export({}, actor="u-admin-1")["jobId"]
    with pytest.raises(NotFoundError):
        _svc(repo).get_export(job_id, actor="u-admin-2")


def test_unknown_job_is_not_found(repo):
    with pytest.raises(NotFoundError):
        _svc(repo).get_export("exp-nope", actor="u-admin")


def test_percent_is_none_when_the_total_is_unknown(repo):
    """OpenSearch could not supply a count -> the UI shows an indeterminate bar
    rather than a fabricated percentage."""
    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-admin")["jobId"]
    repo.update_export_job(job_id, {"status": "running", "total": None, "processed": 40})
    out = svc.get_export(job_id, actor="u-admin")
    assert out["percent"] is None
    assert out["processed"] == 40


def test_percent_is_clamped_when_more_users_appear_mid_export(repo):
    """The count is taken once at the start, so users created during the run can
    push processed past it."""
    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-admin")["jobId"]
    repo.update_export_job(job_id, {"status": "running", "total": 100, "processed": 130})
    assert svc.get_export(job_id, actor="u-admin")["percent"] == 100


def test_failed_job_surfaces_a_generic_error(repo):
    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-admin")["jobId"]
    repo.update_export_job(job_id, {"status": STATUS_FAILED, "error": "boom"})
    assert svc.get_export(job_id, actor="u-admin")["error"] == "boom"


# ---------------------------------------------------------------- worker

def _fake_search(pages):
    """search_users stub: yields (docs, cursor) per call."""
    calls = {"n": 0}

    def search_users(**kwargs):
        i = calls["n"]
        calls["n"] += 1
        return pages[i] if i < len(pages) else ([], None)
    return search_users, calls


def test_worker_writes_a_csv_and_marks_the_job_ready(repo, monkeypatch):
    import export_worker

    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-admin")["jobId"]
    job = repo.get_export_job(job_id)

    docs = [
        {"email": "a@x.com", "firstName": "Ann", "lastName": "Lee", "role": ROLE_MEMBER,
         "status": "active", "city": "Pune", "country": "India",
         "professionalRole": "SA, Cloud", "awsProject": True, "timeZone": "Asia/Kolkata"},
        {"email": "b@x.com", "firstName": "Bob", "lastName": "Roy", "role": ROLE_MEMBER,
         "status": "inactive", "awsProject": False},
    ]
    search, _ = _fake_search([(docs, None)])
    monkeypatch.setattr(repo, "search_users", search)
    monkeypatch.setattr(repo, "count_users", lambda **kw: 2)

    storage = FakeStorage()
    rows = export_worker._run_export(repo, storage, job_id, job, {})

    assert rows == 2
    csv_text = storage.objects[job["fileKey"]].decode()
    lines = csv_text.split("\n")
    assert lines[0] == ",".join(export_worker.COLUMNS)
    # status restored to title case; awsProject lowercase; comma value quoted
    assert lines[1] == 'a@x.com,Ann,Lee,Member,Active,Pune,India,"SA, Cloud",true,Asia/Kolkata'
    # missing optional fields render as empty cells, not "None"
    assert lines[2] == "b@x.com,Bob,Roy,Member,Inactive,,,,false,"

    final = repo.get_export_job(job_id)
    assert final["status"] == STATUS_READY
    # total reconciled to rows written, so a finished bar always reads 100%
    assert final["processed"] == 2 and final["total"] == 2


def test_worker_follows_the_cursor_across_pages(repo, monkeypatch):
    import export_worker

    svc = _svc(repo)
    job_id = svc.start_export({}, actor="u-admin")["jobId"]
    job = repo.get_export_job(job_id)

    page1 = ([{"email": f"u{i}@x.com"} for i in range(3)], "cursor-1")
    page2 = ([{"email": "u3@x.com"}], None)
    search, calls = _fake_search([page1, page2])
    monkeypatch.setattr(repo, "search_users", search)
    monkeypatch.setattr(repo, "count_users", lambda **kw: 4)

    storage = FakeStorage()
    assert export_worker._run_export(repo, storage, job_id, job, {}) == 4
    assert calls["n"] == 2   # stopped when the cursor came back None
    assert len(storage.objects[job["fileKey"]].decode().strip().split("\n")) == 5  # header + 4


def test_worker_marks_the_job_failed_and_frees_the_lock(repo, monkeypatch):
    """Deliberately swallows the error: the function runs with
    MaximumRetryAttempts=0, so a re-raise would let Lambda retry an export the
    admin has already been told failed."""
    import export_worker

    job_id = _svc(repo).start_export({}, actor="u-admin")["jobId"]
    monkeypatch.setattr(repo, "count_users", lambda **kw: (_ for _ in ()).throw(RuntimeError("os down")))
    monkeypatch.setattr(export_worker, "IdentityRepository", lambda table: repo)
    monkeypatch.setattr(export_worker, "ExportStorage", FakeStorage)
    monkeypatch.setenv("TABLE_NAME", "identity-access-test")

    out = export_worker.handler({"jobId": job_id}, None)

    assert out == {"ok": False}
    assert repo.get_export_job(job_id)["status"] == STATUS_FAILED
    # Lock freed, so the admin can retry rather than waiting out the 30-min TTL.
    _svc(repo).start_export({}, actor="u-admin")


def test_worker_does_not_rebuild_an_already_finished_export(repo, monkeypatch):
    """Async invocations can be redelivered; a completed export must not be redone."""
    import export_worker

    job_id = _svc(repo).start_export({}, actor="u-admin")["jobId"]
    repo.update_export_job(job_id, {"status": STATUS_READY})
    monkeypatch.setattr(export_worker, "IdentityRepository", lambda table: repo)
    monkeypatch.setattr(export_worker, "ExportStorage", FakeStorage)
    monkeypatch.setenv("TABLE_NAME", "identity-access-test")

    called = {"n": 0}
    monkeypatch.setattr(repo, "count_users", lambda **kw: called.__setitem__("n", called["n"] + 1))

    out = export_worker.handler({"jobId": job_id}, None)
    assert out["ok"] is True
    assert called["n"] == 0   # never started the walk


def test_worker_without_a_job_id_is_a_no_op(monkeypatch):
    import export_worker
    assert export_worker.handler({}, None)["ok"] is False


# ---------------------------------------------------------------- routes

def _ctx_with_export(aws):
    from app import Context

    class FakeSes:
        def __init__(self): self.sent = []
        def send(self, to, subject, body): self.sent.append((to, subject))

    class FakeEvents:
        def __init__(self): self.published = []
        def publish(self, event_type, data, correlation_id=None): pass

    return Context(table=aws.table, events=FakeEvents(), ses=FakeSes(),
                   export_storage=FakeStorage(), lambda_client=FakeLambda(),
                   settings={"allowedEmailDomains": ["company.com"], "auditEnabled": True,
                             "otpIntervalDays": 30, "selfRegistrationEnabled": True})


def test_post_users_export_returns_202(aws):
    from app import dispatch
    ctx = _ctx_with_export(aws)
    resp = dispatch(_event("POST", "/users/export", {}, claims=_admin_claims()), ctx)
    assert resp["statusCode"] == 202
    assert json.loads(resp["body"])["status"] == STATUS_QUEUED


def test_export_routes_require_authentication(aws):
    from app import dispatch
    ctx = _ctx_with_export(aws)
    assert dispatch(_event("POST", "/users/export", {}), ctx)["statusCode"] == 401
    assert dispatch(_event("GET", "/users/export/exp-1"), ctx)["statusCode"] == 401


def test_export_is_denied_to_a_member(aws):
    from app import dispatch
    ctx = _ctx_with_export(aws)
    claims = {"sub": "u-m", "role": ROLE_MEMBER, "account_type": "cognito"}
    assert dispatch(_event("POST", "/users/export", {}, claims=claims), ctx)["statusCode"] == 403


def test_get_export_route_round_trips(aws):
    from app import dispatch
    ctx = _ctx_with_export(aws)
    started = json.loads(
        dispatch(_event("POST", "/users/export", {}, claims=_admin_claims()), ctx)["body"])

    resp = dispatch(_event("GET", f"/users/export/{started['jobId']}", claims=_admin_claims()), ctx)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["jobId"] == started["jobId"]


def test_export_path_does_not_shadow_the_user_routes(aws):
    """"export" must not bind as {id}: /users/export is its own route."""
    from app import _match
    assert _match("POST", "/users/export")[0] == "startUserExport"
    assert _match("GET", "/users/export/exp-1")[0] == "getUserExport"
    assert _match("PUT", "/users/u-1")[0] == "editUser"
    assert _match("POST", "/users/import")[0] == "bulkImport"
