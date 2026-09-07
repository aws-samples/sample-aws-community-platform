"""Nightly job registry (US-7.1 + the on-demand Nightly Jobs page).

The registry is the contract between three things that must agree or a job
silently never runs: the EventBridge rule's payload, the Lambda's `source`
dispatch branch, and this map. These tests pin the pairing, because a mismatch
fails as "the job appears in the UI and does nothing", not as an error.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from _conventions.errors import ValidationError  # noqa: E402
from nightly_jobs_service import JOB_REGISTRY, VALID_JOB_IDS  # noqa: E402


class _FakeLambda:
    def __init__(self):
        self.invocations = []

    def invoke(self, **kwargs):
        self.invocations.append(kwargs)
        return {"StatusCode": 202}


def test_group_member_stats_job_is_registered(ctx):
    """It must appear on the Nightly Jobs page, or a CL has no way to refresh the
    Members by User Group chart after a membership change."""
    assert "group-member-stats" in VALID_JOB_IDS

    job = JOB_REGISTRY["group-member-stats"]
    assert job["label"] == "Members by User Group"
    assert job["function"].startswith("identity-access-")
    # This exact source string is what identity-access's dispatch branches on.
    assert job["payload"] == {"source": "scheduled-group-member-stats"}


def test_group_member_stats_is_separate_from_community_counts():
    """Two jobs, two snapshot items, so one failing does not take the other's
    dashboard panel down. Sharing an entry would couple them."""
    assert JOB_REGISTRY["community-counts"]["payload"]["source"] == "scheduled-community-counts"
    assert (JOB_REGISTRY["group-member-stats"]["payload"]["source"]
            != JOB_REGISTRY["community-counts"]["payload"]["source"])


def test_every_job_is_listed_with_a_label_and_description(ctx):
    """`list_jobs` feeds the page directly, so a missing description renders as a
    blank row the operator cannot interpret."""
    from nightly_jobs_service import NightlyJobsService

    svc = NightlyJobsService(ctx.repo, lambda_client=_FakeLambda())
    items = svc.list_jobs()["items"]

    assert {j["id"] for j in items} == VALID_JOB_IDS
    for job in items:
        assert job["label"], job["id"]
        assert job["description"], job["id"]


def test_triggering_the_job_invokes_the_runner_with_its_payload(ctx):
    from nightly_jobs_service import NightlyJobsService

    fake = _FakeLambda()
    svc = NightlyJobsService(ctx.repo, lambda_client=fake)

    run = svc.trigger_job("group-member-stats")

    assert run["jobId"] == "group-member-stats"
    assert run["status"] == "running"
    assert len(fake.invocations) == 1
    # Async: the page polls the run record rather than blocking on a fold that
    # takes minutes at community scale.
    assert fake.invocations[0]["InvocationType"] == "Event"


def test_unknown_job_is_rejected(ctx):
    from _conventions.errors import ValidationError
    from nightly_jobs_service import NightlyJobsService

    svc = NightlyJobsService(ctx.repo, lambda_client=_FakeLambda())
    with pytest.raises(ValidationError):
        svc.trigger_job("no-such-job")


# ---- failure detection in the runner (2026-08-27) ---------------------------
#
# Before this, `FunctionError` was the runner's only check — and it is set only
# when a Lambda genuinely crashes. Every service handler is wrapped in
# `global_handler`, whose stated purpose is that no exception escapes, so an
# application failure came back as a 200-shaped envelope carrying a 5xx and the
# run was recorded `completed`. A job could fail every night showing green.

def _envelope(status, body):
    """A Lambda proxy response, the shape the service handlers return."""
    return {"statusCode": status, "body": json.dumps(body)}


class _FakeInvoker:
    """Stands in for the Lambda client, returning a scripted response per call."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        payload, function_error = self._responses.pop(0)
        body = json.dumps(payload).encode()

        class _Stream:
            def read(self_inner):
                return body

        out = {"Payload": _Stream()}
        if function_error:
            out["FunctionError"] = function_error
        return out


def _run(ctx, monkeypatch, event, *responses):
    """Drive job_runner_handler with a scripted Lambda client, return the run record."""
    import app as settings_app
    import boto3

    fake = _FakeInvoker(*responses)
    real_resource = boto3.resource

    def _client(name, *a, **k):
        assert name == "lambda"
        return fake

    monkeypatch.setattr(boto3, "client", _client)
    monkeypatch.setattr(boto3, "resource", lambda *a, **k: real_resource(*a, **k))
    monkeypatch.setenv("TABLE_NAME", ctx.repo._t.name)

    settings_app.job_runner_handler(event, None)
    return ctx.repo.get_job_run(event["runId"]), fake


def test_a_4xx_envelope_fails_the_run(ctx, monkeypatch):
    """THE REGRESSION. events-reminders sent a payload matching no dispatch branch,
    fell through to the HTTP router and returned 404. The Lambda did not crash, so
    FunctionError was absent and the run was marked completed — while its own result
    field stored {"code": "NOT_FOUND"}."""
    ctx.repo.put_job_run({"runId": "r1", "jobId": "group-member-stats",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, _ = _run(ctx, monkeypatch,
                  {"runId": "r1", "jobId": "group-member-stats",
                   "function": "events-dev", "payload": {"source": "scheduled-sweep"}},
                  (_envelope(404, {"code": "NOT_FOUND", "message": "Resource not found."}), None))

    assert run["status"] == "failed"
    assert "404" in run["error"]


def test_a_500_envelope_fails_the_run(ctx, monkeypatch):
    """What global_handler produces when a job throws internally. This is the
    everyday case the old check could never see."""
    ctx.repo.put_job_run({"runId": "r2", "jobId": "community-counts",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, _ = _run(ctx, monkeypatch,
                  {"runId": "r2", "jobId": "community-counts",
                   "function": "identity-access-dev", "payload": {}},
                  (_envelope(500, {"code": "INTERNAL", "message": "boom"}), None))

    assert run["status"] == "failed"
    assert "500" in run["error"]


def test_a_missing_expected_key_fails_the_run(ctx, monkeypatch):
    """A 200 that did no work. The envelope check cannot catch this — a misrouted
    payload landing on a healthy no-op returns a perfectly good 200."""
    ctx.repo.put_job_run({"runId": "r3", "jobId": "group-member-stats",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, _ = _run(ctx, monkeypatch,
                  {"runId": "r3", "jobId": "group-member-stats",
                   "function": "identity-access-dev", "payload": {},
                   "expect": "computedAt"},
                  (_envelope(200, {"status": "ok"}), None))

    assert run["status"] == "failed"
    assert "computedAt" in run["error"]


def test_a_good_run_completes_and_stores_the_result(ctx, monkeypatch):
    ctx.repo.put_job_run({"runId": "r4", "jobId": "group-member-stats",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, _ = _run(ctx, monkeypatch,
                  {"runId": "r4", "jobId": "group-member-stats",
                   "function": "identity-access-dev", "payload": {},
                   "expect": "computedAt"},
                  (_envelope(200, {"quarter": "2026-Q3", "groups": 2,
                                   "computedAt": "2026-08-27T13:14:06Z"}), None))

    assert run["status"] == "completed"
    assert run["result"]["identity-access-dev"]["groups"] == 2


def test_a_bare_dict_result_is_accepted(ctx, monkeypatch):
    """contributions-sweep returns {"swept": n} with NO proxy envelope. A missing
    statusCode must read as fine — treating absence as failure would break the one
    job that does not wrap its response."""
    ctx.repo.put_job_run({"runId": "r5", "jobId": "contributions-sweep",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, _ = _run(ctx, monkeypatch,
                  {"runId": "r5", "jobId": "contributions-sweep",
                   "function": "contributions-sweep-dev", "payload": {},
                   "expect": "swept"},
                  ({"swept": 3}, None))

    assert run["status"] == "completed"


def test_zero_work_is_not_a_failure(ctx, monkeypatch):
    """A healthy night expires no certifications. The expected key is present with
    a zero value, which must pass — asserting on the count itself would report
    routine idleness as breakage."""
    ctx.repo.put_job_run({"runId": "r6", "jobId": "certifications-expiry",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, _ = _run(ctx, monkeypatch,
                  {"runId": "r6", "jobId": "certifications-expiry",
                   "function": "certifications-dev", "payload": {},
                   "expect": "due"},
                  (_envelope(200, {"due": 0, "expired": 0, "noticed": 0}), None))

    assert run["status"] == "completed"


def test_a_later_step_failing_stops_the_run(ctx, monkeypatch):
    """Steps WITHIN one job are sequential and dependent (the reindex pair writes
    the same OpenSearch documents), so a failure there must abort the rest."""
    ctx.repo.put_job_run({"runId": "r7", "jobId": "opensearch-reindex",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, fake = _run(ctx, monkeypatch,
                     {"runId": "r7", "jobId": "opensearch-reindex", "steps": [
                         {"function": "member-profiles-dev", "payload": {}, "expect": "indexed"},
                         {"function": "identity-access-dev", "payload": {}, "expect": "indexed"},
                     ]},
                     (_envelope(200, {"indexed": 10}), None),
                     (_envelope(500, {"message": "opensearch unreachable"}), None))

    assert run["status"] == "failed"
    assert len(fake.calls) == 2


def test_function_error_still_fails_the_run(ctx, monkeypatch):
    """The original check must keep working — it is the only one that catches a
    timeout or OOM, where there is no envelope to inspect."""
    ctx.repo.put_job_run({"runId": "r8", "jobId": "group-member-stats",
                          "status": "running", "startedAt": "2026-08-27T00:00:00",
                          "completedAt": None, "result": None, "error": None})

    run, _ = _run(ctx, monkeypatch,
                  {"runId": "r8", "jobId": "group-member-stats",
                   "function": "identity-access-dev", "payload": {}},
                  ({"errorMessage": "Task timed out after 300.00 seconds"}, "Unhandled"))

    assert run["status"] == "failed"
    assert "Unhandled" in run["error"]


# ---- registry integrity -----------------------------------------------------

def test_job_order_covers_the_registry_exactly():
    """A job missing from JOB_ORDER would never run in a "Run all", and one listed
    twice would run twice. Neither surfaces at runtime, so it is asserted here."""
    from nightly_jobs_service import JOB_ORDER

    assert set(JOB_ORDER) == VALID_JOB_IDS
    assert len(JOB_ORDER) == len(set(JOB_ORDER)), "a job is listed twice"


def test_events_reminders_is_no_longer_registered():
    """Removed 2026-08-27: its payload matched no dispatch branch in the events
    service, so it did nothing and reported success. Its own rate(5 minutes)
    schedule is unaffected and still sends the correct payload."""
    assert "events-reminders" not in VALID_JOB_IDS


def test_every_job_declares_an_expected_result_key():
    """`expect` is what separates "the invoke succeeded" from "the job did its
    work". Not every job has an `ownSchedule` — three run only in the nightly
    batch — so that is asserted separately."""
    for job_id, meta in JOB_REGISTRY.items():
        if "steps" in meta:
            for step in meta["steps"]:
                assert step.get("expect"), f"{job_id} step {step['function']}"
        else:
            assert meta.get("expect"), job_id


def test_reindex_runs_member_profiles_before_identity_access():
    """ORDER IS LOAD-BEARING HERE, unlike across jobs. member-profiles writes with
    OpenSearch `index` (whole-document replace) while identity-access uses `update`
    over an allowlist, so whoever runs last wins. Identity-access must be last or
    its authoritative role/status are discarded every night - which is exactly what
    happened to a stub profile on dev (the Administrator account), leaving a search
    document with no `role` and making it invisible to role-filtered queries."""
    steps = JOB_REGISTRY["opensearch-reindex"]["steps"]

    assert [s["function"].rsplit("-", 1)[0] for s in steps] == [
        "member-profiles", "identity-access"]


def test_trigger_all_follows_the_declared_order(ctx):
    """Not dict insertion order - that makes the sequence an accident of where a
    new entry was pasted."""
    from nightly_jobs_service import JOB_ORDER, NightlyJobsService

    svc = NightlyJobsService(ctx.repo, lambda_client=_FakeLambda())

    runs = svc.trigger_all()["runs"]

    assert [r["jobId"] for r in runs] == JOB_ORDER


def test_single_step_jobs_forward_expect_to_the_runner(ctx):
    """The runner normalises single-step jobs into a steps list. If `expect` is not
    forwarded, the result-shape check is silently skipped for most of the jobs."""
    from nightly_jobs_service import NightlyJobsService

    fake = _FakeLambda()
    svc = NightlyJobsService(ctx.repo, lambda_client=fake)

    svc.trigger_job("group-member-stats")

    sent = json.loads(fake.invocations[0]["Payload"].decode())
    assert sent["expect"] == "computedAt"


# ---- per-job last-run lookup + batch state (2026-08-27) ---------------------

def test_last_run_is_found_however_many_other_runs_followed(ctx):
    """THE BUG. get_last_job_run used to read the 50 most recent runs across ALL
    jobs and filter in Python. Six jobs per batch meant it covered ~8 batches, so a
    job that had not run inside that window reported "never run" while its history
    sat in the table — and it degraded silently as volume grew.

    60 later runs for other jobs is comfortably past the old window.
    """
    ctx.repo.put_job_run({"runId": "old", "jobId": "group-member-stats",
                          "status": "completed", "startedAt": "2026-08-01T00:00:00",
                          "completedAt": "2026-08-01T00:01:00", "result": {"ok": 1},
                          "error": None})
    for n in range(60):
        ctx.repo.put_job_run({"runId": f"noise-{n}", "jobId": "contributions-sweep",
                              "status": "completed", "startedAt": f"2026-08-02T00:{n:02d}:00",
                              "completedAt": None, "result": None, "error": None})

    found = ctx.repo.get_last_job_run("group-member-stats")

    assert found is not None, "the old Limit=50 filter returned None here"
    assert found["runId"] == "old"


def test_the_pointer_tracks_the_latest_run_per_job(ctx):
    for run_id, started in (("r1", "2026-08-01T00:00:00"), ("r2", "2026-08-02T00:00:00")):
        ctx.repo.put_job_run({"runId": run_id, "jobId": "community-counts",
                              "status": "completed", "startedAt": started,
                              "completedAt": None, "result": None, "error": None})

    assert ctx.repo.get_last_job_run("community-counts")["runId"] == "r2"


def test_a_status_transition_updates_the_pointer(ctx):
    """update_job_run routes through put_job_run, so the pointer must follow a run
    from running to completed without a separate call."""
    ctx.repo.put_job_run({"runId": "r1", "jobId": "community-counts",
                          "status": "running", "startedAt": "2026-08-01T00:00:00",
                          "completedAt": None, "result": None, "error": None})
    assert ctx.repo.get_last_job_run("community-counts")["status"] == "running"

    ctx.repo.update_job_run("r1", {"status": "completed",
                                   "completedAt": "2026-08-01T00:05:00"})

    pointer = ctx.repo.get_last_job_run("community-counts")
    assert pointer["status"] == "completed"
    assert pointer["completedAt"] == "2026-08-01T00:05:00"


def test_a_job_that_never_ran_has_no_last_run(ctx):
    assert ctx.repo.get_last_job_run("certifications-expiry") is None


def test_the_active_batch_survives_leaving_the_page(ctx):
    """The requirement: navigate away, come back, still see progress. State is
    server-side, so "coming back" is just this read."""
    ctx.repo.put_job_batch({"batchId": "b1", "status": "running",
                            "startedAt": "2026-08-27T00:00:00", "completedAt": None,
                            "order": ["community-counts", "group-member-stats"],
                            "currentIndex": 1,
                            "jobs": {"community-counts": {"status": "completed"},
                                     "group-member-stats": {"status": "running"}}})
    ctx.repo.set_active_batch("b1")

    active = ctx.repo.get_active_batch()

    assert active["batchId"] == "b1"
    assert int(active["currentIndex"]) == 1
    assert active["jobs"]["group-member-stats"]["status"] == "running"


def test_no_active_batch_when_none_is_running(ctx):
    assert ctx.repo.get_active_batch() is None


def test_clearing_the_pointer_leaves_the_batch_readable(ctx):
    """History must outlive the in-flight marker — the cards still show the last
    run after the batch finishes."""
    ctx.repo.put_job_batch({"batchId": "b1", "status": "completed",
                            "startedAt": "2026-08-27T00:00:00",
                            "completedAt": "2026-08-27T00:09:00",
                            "order": [], "currentIndex": 0, "jobs": {}})
    ctx.repo.set_active_batch("b1")

    ctx.repo.clear_active_batch()

    assert ctx.repo.get_active_batch() is None
    assert ctx.repo.get_job_batch("b1")["status"] == "completed"


# ---- schedule metadata + next-run computation (2026-08-27) ------------------

def test_next_run_rolls_to_tomorrow_once_todays_time_has_passed():
    from datetime import datetime, timezone

    from nightly_jobs_service import next_run_at

    now = datetime(2026, 8, 27, 5, 0, 0, tzinfo=timezone.utc)

    assert next_run_at("cron(0 3 * * ? *)", now=now).startswith("2026-08-28T03:00")
    # Still ahead of `now`, so today.
    assert next_run_at("cron(0 6 * * ? *)", now=now).startswith("2026-08-27T06:00")


def test_next_run_for_a_rate_schedule_is_now_plus_the_interval():
    from datetime import datetime, timezone

    from nightly_jobs_service import next_run_at

    now = datetime(2026, 8, 27, 5, 0, 0, tzinfo=timezone.utc)

    assert next_run_at("rate(15 minutes)", now=now).startswith("2026-08-27T05:15")


def test_an_unrecognised_expression_returns_none_rather_than_a_guess():
    """Only the two shapes this system actually uses are supported. Anything else
    must be reported as unknown — inventing a time is the same defect class as the
    dashboard badge that showed one job's timestamp beside another job's data."""
    from nightly_jobs_service import next_run_at

    for expression in ("cron(0 3 15 * ? *)",      # day-of-month restriction
                       "cron(0/5 * * * ? *)",     # step values
                       "rate(1 hour)",            # hours, not minutes
                       "", "nonsense"):
        assert next_run_at(expression) is None, expression


def test_describe_schedule_falls_back_to_the_raw_expression():
    """An operator can act on `cron(0 3 15 * ? *)`. A blank string tells them
    nothing and hides that it was not understood."""
    from nightly_jobs_service import describe_schedule

    assert describe_schedule("cron(45 3 * * ? *)") == "Daily at 03:45 UTC"
    assert describe_schedule("rate(15 minutes)") == "Every 15 minutes"
    assert describe_schedule("rate(1 minute)") == "Every 1 minute"
    assert describe_schedule("cron(0 3 15 * ? *)") == "cron(0 3 15 * ? *)"


def test_the_batch_schedule_matches_the_nightly_rule():
    """DRIFT GUARD 1. BATCH_SCHEDULE is what the page tells the operator; the
    EventBridge rule is what actually fires. Change one without the other and the
    page confidently shows the wrong next-run time — the same defect class as the
    dashboard badge that displayed one job's timestamp beside another job's data."""
    from nightly_jobs_service import BATCH_SCHEDULE

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    template = (repo_root / "infra/services/service-settings-app.yaml").read_text()

    assert "ScheduledJobsNightly:" in template, "the nightly rule is gone"
    assert BATCH_SCHEDULE in template, (
        f"BATCH_SCHEDULE is {BATCH_SCHEDULE!r} but that expression is not in the "
        f"settings template")


def test_the_watchdog_own_schedule_matches_its_template():
    """DRIFT GUARD 2. Exactly ONE job keeps a cadence of its own, so the batch is
    not its only trigger and the card has to say so."""
    from nightly_jobs_service import JOB_REGISTRY as REG

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    own = REG["certifications-scanwatch"]["ownSchedule"]
    template = (repo_root / "infra/services/service-certifications-app.yaml").read_text()

    assert own in template, f"ownSchedule {own!r} is not in the certifications template"
    assert "ScanWatchdogSchedule:" in template, "the watchdog rule is gone"


def test_only_the_watchdog_declares_an_own_schedule():
    """Every other job runs ONCE, in the batch. Their independent rules were removed
    (2026-08-27) so nothing runs twice a night; leaving an ownSchedule behind would
    make a card promise a run that nothing fires."""
    for job_id in JOB_REGISTRY:
        own = JOB_REGISTRY[job_id].get("ownSchedule")
        if job_id == "certifications-scanwatch":
            assert own == "rate(15 minutes)"
        else:
            assert own is None, f"{job_id} still claims its own schedule: {own!r}"


def test_the_removed_per_job_rules_are_gone_from_their_templates():
    """The registry saying "batch only" and the template still holding a cron would
    be a silent double-run — the job would fire twice a night while the page showed
    one schedule. Asserted against the templates, not just the registry."""
    repo_root = pathlib.Path(__file__).resolve().parents[3]

    contributions = (repo_root
                     / "infra/services/service-contributions-scoring-app.yaml").read_text()
    assert "cron(0 2 * * ? *)" not in contributions, (
        "contributions-sweep still has its own nightly schedule")

    certifications = (repo_root
                      / "infra/services/service-certifications-app.yaml").read_text()
    assert "cron(0 6 * * ? *)" not in certifications, (
        "certifications-expiry still has its own nightly schedule")
    # The watchdog must survive that cleanup.
    assert "rate(15 minutes)" in certifications


def test_list_jobs_returns_cards_in_execution_order(ctx):
    from nightly_jobs_service import JOB_ORDER, NightlyJobsService

    svc = NightlyJobsService(ctx.repo, lambda_client=_FakeLambda())

    out = svc.list_jobs()

    assert [j["id"] for j in out["items"]] == JOB_ORDER
    assert out["batchSchedule"] == "Daily at 03:00 UTC"
    assert out["batchNextRunAt"]


def test_next_run_is_the_earliest_of_the_batch_and_the_jobs_own_schedule(ctx):
    """scanwatch runs every 15 minutes, so its next run is minutes away even though
    the batch is hours away. Showing only the batch time would overstate how stale
    its data may get."""
    from nightly_jobs_service import NightlyJobsService

    svc = NightlyJobsService(ctx.repo, lambda_client=_FakeLambda())
    by_id = {j["id"]: j for j in svc.list_jobs()["items"]}

    assert by_id["certifications-scanwatch"]["nextRunAt"] < \
        by_id["opensearch-reindex"]["nextRunAt"]
    # A batch-only job reports the batch time and no own schedule.
    assert by_id["opensearch-reindex"]["ownSchedule"] is None
    assert by_id["certifications-scanwatch"]["ownSchedule"] == "Every 15 minutes"


# ---- batch orchestration via the state machine (2026-08-27) -----------------

class _FakeSfn:
    def __init__(self, fail=False):
        self.started = []
        self._fail = fail

    def start_execution(self, **kwargs):
        if self._fail:
            raise RuntimeError("ExecutionAlreadyExists")
        self.started.append(kwargs)
        return {"executionArn": "arn:aws:states:::execution/x"}


def _svc(ctx, sfn=None):
    from nightly_jobs_service import NightlyJobsService

    return NightlyJobsService(ctx.repo, lambda_client=_FakeLambda(),
                              sfn_client=sfn or _FakeSfn(),
                              state_machine_arn="arn:aws:states:::stateMachine/jobs")


def test_starting_a_batch_queues_every_job_in_order(ctx):
    """Every job gets a run record up front, in `queued`. That is what lets the
    page tell QUEUED from NEVER RUN for jobs further down the sequence — without
    it, five cards look untouched while one works and the operator reasonably
    concludes the rest are broken."""
    from nightly_jobs_service import JOB_ORDER

    sfn = _FakeSfn()
    batch = _svc(ctx, sfn).start_batch()

    assert batch["status"] == "running"
    assert batch["order"] == JOB_ORDER
    assert all(j["status"] == "queued" for j in batch["jobs"].values())
    for job_id in JOB_ORDER:
        assert ctx.repo.get_last_job_run(job_id)["status"] == "queued"


def test_the_execution_input_carries_the_jobs_in_order(ctx):
    """The state machine is generic — the sequence lives in the input, so the
    registry stays the single source of truth instead of being duplicated in ASL."""
    import json as _json

    from nightly_jobs_service import JOB_ORDER

    sfn = _FakeSfn()
    _svc(ctx, sfn).start_batch()

    sent = _json.loads(sfn.started[0]["input"])
    assert [j["jobId"] for j in sent["jobs"]] == JOB_ORDER
    # Multi-step jobs pass steps; single-step jobs pass function+payload.
    by_id = {j["jobId"]: j for j in sent["jobs"]}
    assert "steps" in by_id["opensearch-reindex"]
    assert "function" in by_id["community-counts"]
    # Every item carries the batch id, so the runner can record progress on it.
    assert all(j["batchId"] == sent["batchId"] for j in sent["jobs"])


def test_the_execution_name_is_derived_from_the_batch_id(ctx):
    """Idempotency lives in Step Functions: a duplicate name is rejected with
    ExecutionAlreadyExists, which replaces two hand-rolled stuck-run heuristics."""
    sfn = _FakeSfn()
    batch = _svc(ctx, sfn).start_batch()

    assert sfn.started[0]["name"] == f"batch-{batch['batchId']}"


def test_a_second_batch_is_refused_while_one_is_running(ctx):
    sfn = _FakeSfn()
    svc = _svc(ctx, sfn)
    svc.start_batch()

    with pytest.raises(ValidationError):
        svc.start_batch()

    assert len(sfn.started) == 1


def test_a_failed_start_does_not_strand_the_page_on_a_spinner(ctx):
    """If StartExecution fails, nothing will ever advance the batch. Leaving it
    `running` would spin forever AND block the next attempt behind the
    already-in-progress guard."""
    svc = _svc(ctx, _FakeSfn(fail=True))

    with pytest.raises(ValidationError):
        svc.start_batch()

    assert ctx.repo.get_active_batch() is None


def test_an_unconfigured_environment_is_reported_clearly(ctx):
    from nightly_jobs_service import NightlyJobsService

    svc = NightlyJobsService(ctx.repo, lambda_client=_FakeLambda(),
                             state_machine_arn="")

    with pytest.raises(ValidationError):
        svc.start_batch()


def test_active_batch_is_readable_after_navigating_away(ctx):
    svc = _svc(ctx)
    started = svc.start_batch()

    assert svc.active_batch()["batchId"] == started["batchId"]


def test_finalize_completes_the_batch_and_clears_the_pointer(ctx, monkeypatch):
    """Runs whether or not jobs failed — the batch finished either way, and a
    lingering pointer would keep the page spinning."""
    svc = _svc(ctx)
    batch = svc.start_batch()
    ctx.repo.put_job_batch({**batch, "jobs": {
        "community-counts": {"status": "completed"},
        "group-member-stats": {"status": "failed", "error": "boom"}}})

    run, _ = _run(ctx, monkeypatch, {"finalizeBatchId": batch["batchId"],
                                    "runId": "unused", "jobId": "unused"})

    final = ctx.repo.get_job_batch(batch["batchId"])
    assert final["status"] == "completed"
    assert final["completedAt"]
    assert final["failedJobs"] == ["group-member-stats"]
    assert ctx.repo.get_active_batch() is None


def test_a_job_outcome_is_recorded_on_its_batch(ctx, monkeypatch):
    svc = _svc(ctx)
    batch = svc.start_batch()
    run_id = batch["jobs"]["community-counts"]["runId"]

    _run(ctx, monkeypatch,
         {"batchId": batch["batchId"], "runId": run_id, "jobId": "community-counts",
          "function": "identity-access-dev", "payload": {}, "expect": "computedAt"},
         (_envelope(200, {"computedAt": "2026-08-27T03:00:00Z"}), None))

    updated = ctx.repo.get_job_batch(batch["batchId"])
    assert updated["jobs"]["community-counts"]["status"] == "completed"
    assert int(updated["currentIndex"]) == 1


def test_the_per_job_trigger_route_is_gone():
    """Removed rather than hidden: it fanned out its own async invocation, so any
    caller using it bypassed the sequencing the state machine guarantees."""
    from app import OPERATIONS

    paths = {path for _method, path in OPERATIONS}
    assert "/settings/nightly-jobs/{id}/trigger" not in paths
    assert "/settings/nightly-jobs/run" in paths


def test_community_leaders_may_start_a_batch():
    """A CL is a community-wide operator and the dashboard data comes from these
    jobs, so they must be able to refresh it — same remit as the CL dashboard."""
    from app import NIGHTLY_JOB_OPS

    assert "startJobBatch" in NIGHTLY_JOB_OPS
    assert "getJobBatch" in NIGHTLY_JOB_OPS
    # The internal write-back path stays Administrator-only.
    assert "completeRun" not in NIGHTLY_JOB_OPS


def test_the_listing_reports_an_in_flight_batch(ctx):
    """One request on mount. Fetching the listing and then discovering separately
    that a batch is running would render every card idle for a beat first."""
    svc = _svc(ctx)
    started = svc.start_batch()

    out = svc.list_jobs()

    assert out["activeBatch"]["batchId"] == started["batchId"]
    assert out["activeBatch"]["status"] == "running"


def test_the_listing_omits_activebatch_when_nothing_is_running(ctx):
    assert "activeBatch" not in _svc(ctx).list_jobs()
