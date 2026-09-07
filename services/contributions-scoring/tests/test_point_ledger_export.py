"""Async Point Ledger CSV export (US-7.9).

Mirrors services/identity-access/tests/test_export.py, which covers the same job
lifecycle for Admin > Users: create + lock + async invoke, per-actor isolation,
progress reporting, presigned download on completion, and the worker's CSV.

The scope tests matter most here. The export reproduces `group_ledger`'s
fail-closed rule from a stored job rather than a live request, so a mistake would
hand a leader another group's ledger — the one thing the read path is careful to
prevent.
"""
from __future__ import annotations

import csv
import io
import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ForbiddenError, NotFoundError, ValidationError  # noqa: E402
from export_service import KIND_POINT_LEDGER, ExportService  # noqa: E402
from models import current_quarter  # noqa: E402


class FakeStorage:
    """Records the object written and hands back a stub download link."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.presigned = 0

    def put_csv(self, key: str, body: bytes) -> None:
        self.objects[key] = body

    def download_url(self, key: str) -> dict:
        self.presigned += 1
        return {"url": f"https://example.test/{key}", "expiresInSeconds": 300}


class FakeLambda:
    """Captures the async invoke instead of calling AWS."""

    def __init__(self, fail=False):
        self.calls: list[dict] = []
        self.fail = fail

    def invoke(self, **kwargs):
        if self.fail:
            raise RuntimeError("invoke blew up")
        self.calls.append(kwargs)
        return {"StatusCode": 202}


@pytest.fixture()
def storage():
    return FakeStorage()


@pytest.fixture()
def lam():
    return FakeLambda()


@pytest.fixture()
def exports(repo, storage, lam):
    return ExportService(repo, storage, lambda_client=lam, worker_function="wf-test")


def _entry(repo, member_id, group_id, quarter, points, *, date, activity="Attended an event",
           name="", ledger_id=None, source="auto", pillar=1, reason=None):
    repo.append_ledger({
        "ledgerId": ledger_id or f"led-{member_id}-{date}-{points}",
        "memberId": member_id, "memberName": name, "groupId": group_id,
        "quarter": quarter, "points": points, "pillar": pillar, "source": source,
        "activity": activity, "earnedDate": date, "reason": reason,
    })


# ------------------------------------------------------------------ start

class TestStartExport:
    def test_creates_a_job_and_invokes_the_worker_async(self, exports, repo, cl, lam):
        q = current_quarter()
        out = exports.start_export({"groupId": "g-serverless", "quarter": q}, principal=cl)

        assert out["status"] == "queued"
        assert out["processed"] == 0
        # Row count is deliberately unknown up front, so the UI shows an
        # indeterminate bar rather than a fabricated percentage.
        assert out["total"] is None
        assert out["percent"] is None
        assert out["fileName"].startswith("point-ledger-")

        job = repo.get_export_job(out["jobId"])
        assert job["kind"] == KIND_POINT_LEDGER
        assert job["groupId"] == "g-serverless"
        assert job["quarter"] == q
        assert job["actor"] == cl.user_id
        assert job["fileKey"] == f"contributions/{out['jobId']}.csv"

        assert len(lam.calls) == 1
        assert lam.calls[0]["InvocationType"] == "Event"
        assert lam.calls[0]["FunctionName"] == "wf-test"

    def test_records_only_the_supported_filters(self, exports, repo, cl):
        out = exports.start_export({
            "groupId": "g-serverless", "quarter": current_quarter(),
            "memberId": "m-a", "source": "adjustment", "activityType": "certification",
            "nonsense": "ignored", "limit": "9999",
        }, principal=cl)
        job = repo.get_export_job(out["jobId"])
        assert job["filters"] == {"memberId": "m-a", "source": "adjustment",
                                 "activityType": "certification"}

    def test_blank_filters_are_dropped(self, exports, repo, cl):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter(),
                                    "memberId": "   "}, principal=cl)
        assert repo.get_export_job(out["jobId"])["filters"] == {}

    def test_ugl_gets_their_led_group_whatever_the_body_says(self, exports, repo, ugl):
        out = exports.start_export({"groupId": "g-ml", "quarter": current_quarter()},
                                   principal=ugl)
        assert repo.get_export_job(out["jobId"])["groupId"] == "g-serverless"

    def test_cl_must_name_a_group(self, exports, cl):
        with pytest.raises(ValidationError):
            exports.start_export({"quarter": current_quarter()}, principal=cl)

    def test_quarter_is_required(self, exports, cl):
        with pytest.raises(ValidationError):
            exports.start_export({"groupId": "g-serverless"}, principal=cl)

    def test_member_cannot_export(self, exports, member):
        with pytest.raises(ForbiddenError):
            exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                 principal=member)

    def test_second_export_for_the_same_actor_is_refused(self, exports, cl):
        body = {"groupId": "g-serverless", "quarter": current_quarter()}
        exports.start_export(body, principal=cl)
        with pytest.raises(ValidationError):
            exports.start_export(body, principal=cl)

    def test_a_different_actor_can_export_concurrently(self, exports, cl, ugl):
        exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                             principal=cl)
        # Not refused — the lock is per actor, not global.
        exports.start_export({"quarter": current_quarter()}, principal=ugl)

    def test_releasing_the_lock_allows_a_new_export(self, exports, repo, cl):
        body = {"groupId": "g-serverless", "quarter": current_quarter()}
        exports.start_export(body, principal=cl)
        repo.release_export_lock(cl.user_id)
        exports.start_export(body, principal=cl)   # must not raise

    def test_failed_worker_invoke_marks_the_job_failed_and_frees_the_lock(
            self, repo, storage, cl):
        svc = ExportService(repo, storage, lambda_client=FakeLambda(fail=True),
                            worker_function="wf-test")
        body = {"groupId": "g-serverless", "quarter": current_quarter()}
        with pytest.raises(ValidationError):
            svc.start_export(body, principal=cl)

        jobs = [i for i in repo._t.scan()["Items"] if i.get("kind") == KIND_POINT_LEDGER]
        assert len(jobs) == 1
        assert jobs[0]["status"] == "failed"
        # The lock must be released, or the leader could never retry.
        svc2 = ExportService(repo, storage, lambda_client=FakeLambda(),
                             worker_function="wf-test")
        svc2.start_export(body, principal=cl)   # must not raise


# ------------------------------------------------------------------ status

class TestGetExport:
    def test_reports_progress_without_a_url_while_running(self, exports, repo, cl, storage):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        repo.update_export_job(out["jobId"], {"status": "running", "processed": 40,
                                              "totalRows": 100})
        status = exports.get_export(out["jobId"], principal=cl)
        assert status["status"] == "running"
        assert status["percent"] == 40
        assert "url" not in status
        assert storage.presigned == 0

    def test_mints_a_fresh_download_url_when_ready(self, exports, repo, cl, storage):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        repo.update_export_job(out["jobId"], {"status": "ready", "processed": 7, "totalRows": 7})
        status = exports.get_export(out["jobId"], principal=cl)
        assert status["status"] == "ready"
        assert status["percent"] == 100
        assert status["url"].endswith(f"contributions/{out['jobId']}.csv")
        # Minted per request, never stored.
        exports.get_export(out["jobId"], principal=cl)
        assert storage.presigned == 2

    def test_another_actors_job_is_reported_as_missing_not_forbidden(self, exports, cl, ugl):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        with pytest.raises(NotFoundError):
            exports.get_export(out["jobId"], principal=ugl)

    def test_a_ugls_job_for_a_group_they_no_longer_lead_is_missing(self, exports, repo, ugl):
        out = exports.start_export({"quarter": current_quarter()}, principal=ugl)
        ugl.led_group_id = "g-somewhere-else"   # reassigned since starting the job
        with pytest.raises(NotFoundError):
            exports.get_export(out["jobId"], principal=ugl)

    def test_unknown_job_is_not_found(self, exports, cl):
        with pytest.raises(NotFoundError):
            exports.get_export("plexp-nope", principal=cl)

    def test_member_cannot_read_a_job(self, exports, repo, cl, member):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        # Reported as missing first (not their job) — never leaks existence.
        with pytest.raises(NotFoundError):
            exports.get_export(out["jobId"], principal=member)

    def test_percent_is_clamped_when_more_rows_appear_mid_export(self, exports, repo, cl):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        repo.update_export_job(out["jobId"], {"status": "running", "processed": 150,
                                              "totalRows": 100})
        assert exports.get_export(out["jobId"], principal=cl)["percent"] == 100

    def test_failed_job_surfaces_a_generic_error(self, exports, repo, cl):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        repo.update_export_job(out["jobId"], {"status": "failed", "error": None})
        assert exports.get_export(out["jobId"], principal=cl)["error"] == "The export failed."


# ------------------------------------------------------------------ worker

def _rows(storage, key):
    return list(csv.reader(io.StringIO(storage.objects[key].decode("utf-8"))))


class TestWorker:
    def _run(self, repo, storage, job_id, monkeypatch):
        import export_worker
        monkeypatch.setattr(export_worker, "ContributionsRepository", lambda _t: repo)
        monkeypatch.setattr(export_worker, "ExportStorage", lambda: storage)

        class _Res:
            def Table(self, _name):  # noqa: N802, ANN001
                return None

        monkeypatch.setitem(__import__("os").environ, "TABLE_NAME", "contributions-scoring-test")
        monkeypatch.setattr("boto3.resource", lambda *_a, **_k: _Res())
        return export_worker.handler({"jobId": job_id}, None)

    def test_writes_a_csv_and_marks_the_job_ready(self, exports, repo, storage, cl,
                                                 framework, monkeypatch):
        q = current_quarter()
        _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Alpha",
               activity="Attend: Workshop")
        _entry(repo, "m-b", "g-serverless", q, 20, date="2026-08-15", name="Bravo",
               activity="Blog / article", source="evidence", pillar=4)

        out = exports.start_export({"groupId": "g-serverless", "quarter": q,
                                    "groupName": "Serverless Guild"}, principal=cl)
        result = self._run(repo, storage, out["jobId"], monkeypatch)

        assert result == {"ok": True, "rows": 2}
        job = repo.get_export_job(out["jobId"])
        assert job["status"] == "ready"
        assert int(job["processed"]) == 2
        # Denominator reconciled with what was written so the bar reads 100%.
        assert int(job["totalRows"]) == 2

        rows = _rows(storage, job["fileKey"])
        assert rows[0] == ["member_name", "member_email", "user_group", "activity_type",
                           "activity", "pillar", "points", "source", "earned_date", "quarter"]
        assert len(rows) == 3               # header + 2 entries
        # Newest first, matching the on-screen table.
        assert rows[1][0] == "Bravo"
        assert rows[1][2] == "Serverless Guild"   # resolved from the job, not the id
        assert rows[1][5] == "4 · Thought Leadership & External Visibility"
        assert rows[1][8] == "2026-08-15"
        assert rows[2][0] == "Alpha"
        assert rows[2][5] == "1 · Upskilling & Deployment"

    def test_group_name_falls_back_to_the_id(self, exports, repo, storage, cl, framework,
                                            monkeypatch):
        q = current_quarter()
        _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Alpha")
        out = exports.start_export({"groupId": "g-serverless", "quarter": q}, principal=cl)
        self._run(repo, storage, out["jobId"], monkeypatch)
        rows = _rows(storage, repo.get_export_job(out["jobId"])["fileKey"])
        assert rows[1][2] == "g-serverless"

    def test_follows_the_cursor_across_pages(self, exports, repo, storage, cl, framework,
                                            monkeypatch):
        q = current_quarter()
        for n in range(7):
            _entry(repo, f"m-{n}", "g-serverless", q, 5, date=f"2026-07-0{n + 1}",
                   name=f"M{n}", ledger_id=f"led-{n}")
        out = exports.start_export({"groupId": "g-serverless", "quarter": q}, principal=cl)

        import export_worker
        monkeypatch.setattr(export_worker, "PAGE_SIZE", 2)
        result = self._run(repo, storage, out["jobId"], monkeypatch)

        assert result["rows"] == 7
        assert len(_rows(storage, repo.get_export_job(out["jobId"])["fileKey"])) == 8

    def test_honours_the_stored_filters(self, exports, repo, storage, cl, framework,
                                       monkeypatch):
        q = current_quarter()
        _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Alpha")
        _entry(repo, "m-b", "g-serverless", q, 20, date="2026-07-02", name="Bravo")
        out = exports.start_export({"groupId": "g-serverless", "quarter": q,
                                    "memberId": "m-b"}, principal=cl)
        self._run(repo, storage, out["jobId"], monkeypatch)
        rows = _rows(storage, repo.get_export_job(out["jobId"])["fileKey"])
        assert len(rows) == 2 and rows[1][0] == "Bravo"

    def test_only_the_jobs_own_group_is_exported(self, exports, repo, storage, cl,
                                                framework, monkeypatch):
        q = current_quarter()
        _entry(repo, "m-a", "g-serverless", q, 10, date="2026-07-01", name="Mine")
        _entry(repo, "m-z", "g-ml", q, 99, date="2026-07-02", name="Theirs")
        out = exports.start_export({"groupId": "g-serverless", "quarter": q}, principal=cl)
        self._run(repo, storage, out["jobId"], monkeypatch)
        rows = _rows(storage, repo.get_export_job(out["jobId"])["fileKey"])
        assert [r[0] for r in rows[1:]] == ["Mine"]

    def test_failure_marks_the_job_failed_and_frees_the_lock(self, exports, repo, storage,
                                                            cl, monkeypatch):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        # A job with no group cannot be completed; the handler must record that
        # rather than writing an empty CSV that looks like a group with no entries.
        repo.update_export_job(out["jobId"], {"groupId": ""})
        result = self._run(repo, storage, out["jobId"], monkeypatch)

        assert result == {"ok": False}
        job = repo.get_export_job(out["jobId"])
        assert job["status"] == "failed"
        assert job["error"] == "The export could not be completed. Please try again."
        assert storage.objects == {}
        # Lock released so a retry is possible.
        exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                             principal=cl)

    def test_does_not_rebuild_an_already_finished_export(self, exports, repo, storage, cl,
                                                        monkeypatch):
        out = exports.start_export({"groupId": "g-serverless", "quarter": current_quarter()},
                                   principal=cl)
        repo.update_export_job(out["jobId"], {"status": "ready"})
        assert self._run(repo, storage, out["jobId"], monkeypatch) == {
            "ok": True, "reason": "already complete"}
        assert storage.objects == {}

    def test_without_a_job_id_is_a_no_op(self, repo, storage, monkeypatch):
        import export_worker
        assert export_worker.handler({}, None) == {"ok": False, "reason": "missing jobId"}

    def test_unknown_job_is_a_no_op(self, repo, storage, monkeypatch):
        assert self._run(repo, storage, "plexp-missing", monkeypatch) == {
            "ok": False, "reason": "job not found"}


# ------------------------------------------------------------------ routes

class TestRoutes:
    def _event(self, method, path, *, role, sub, led=None, body=None):
        import json
        claims = {"sub": sub, "role": role}
        if led:
            claims["led_group_id"] = led
        return {
            "httpMethod": method, "path": path,
            "headers": {"Authorization": "Bearer t"},
            "requestContext": {"authorizer": {"claims": claims}},
            "queryStringParameters": None,
            "body": json.dumps(body) if body is not None else None,
        }

    def _ctx(self, table, storage, lam):
        from app import Context
        return Context(table=table, idempotency_table=None, export_storage=storage,
                       lambda_client=lam)

    def test_post_returns_202_and_get_round_trips(self, table, storage, lam, framework):
        import json

        from app import dispatch_http
        ctx = self._ctx(table, storage, lam)
        resp = dispatch_http(self._event(
            "POST", "/contributions/group-ledger/export", role="CommunityLeader",
            sub="cl-dana", body={"groupId": "g-serverless", "quarter": current_quarter()}), ctx)
        assert resp["statusCode"] == 202
        job_id = json.loads(resp["body"])["jobId"]

        resp = dispatch_http(self._event(
            "GET", f"/contributions/group-ledger/export/{job_id}",
            role="CommunityLeader", sub="cl-dana"), ctx)
        assert resp["statusCode"] == 200
        assert json.loads(resp["body"])["jobId"] == job_id

    def test_export_path_does_not_shadow_the_group_ledger_route(self, table, storage, lam,
                                                               framework):
        """"export" must not bind as a path parameter on the ledger route."""
        from app import _match
        op, params = _match("GET", "/contributions/group-ledger")
        assert op == "groupLedger"
        op, params = _match("POST", "/contributions/group-ledger/export")
        assert op == "startPointLedgerExport"
        op, params = _match("GET", "/contributions/group-ledger/export/plexp-1")
        assert op == "getPointLedgerExport" and params == {"jobId": "plexp-1"}

    def test_member_is_refused(self, table, storage, lam, framework):
        from app import dispatch_http
        ctx = self._ctx(table, storage, lam)
        resp = dispatch_http(self._event(
            "POST", "/contributions/group-ledger/export", role="Member", sub="m-alex",
            body={"groupId": "g-serverless", "quarter": current_quarter()}), ctx)
        assert resp["statusCode"] == 403
