"""On-demand nightly job triggering (Administrator only).

Allows an admin to invoke the scheduled nightly jobs on-demand and track their
progress. Each trigger creates a "run" record keyed by a run ID; the invoked
Lambda writes back a completion marker when done (or the trigger polls
CloudWatch for errors).

JOB_REGISTRY below is the source of truth for what can be triggered. JOB_ORDER is
the sequence a "Run all" executes in. Both are asserted against each other by a
test, so a job cannot be registered without an order position and silently drop
out of every run.

Ordering is for LOAD SPREADING, not correctness. Every job reads and writes only
its own service's table (verified job by job, 2026-08-27): none reads anything
another writes, and no two write the same item. That is why a failure does not
abort the batch — later jobs are unaffected by an earlier one failing, so stopping
would just withhold work for no reason.

`events-reminders` was REMOVED (2026-08-27). Its registered payload
`{"source": "scheduled-sweep"}` matched no dispatch branch in the events service,
so triggering it here did nothing and reported success. It is also not a nightly
job — its own `rate(5 minutes)` EventBridge Scheduler rule
(service-events-app.yaml) sends the correct `{"source":"aws.scheduler",
"sweep":true}` payload and is untouched by this removal.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from _conventions.errors import NotFoundError, ValidationError
from _conventions.logger import get_logger

_logger = get_logger("nightly-jobs")

STAGE = os.environ.get("STAGE", "dev")

# Map of job keys to their Lambda function names and invocation payloads.
JOB_REGISTRY: dict[str, dict] = {
    "contributions-sweep": {
        "label": "Contribution Rollups and Tiers",
        "description": "Recalculates tier distributions, active-contributor counts, and top contributors for all groups.",
        "function": f"contributions-sweep-{STAGE}",
        "payload": {},
        # Returns a BARE dict with no proxy envelope, so the runner's statusCode
        # check is skipped for this one and `expect` is the only signal.
        "expect": "swept",
    },
    "certifications-expiry": {
        "label": "Certification Expiry",
        "description": "Marks expired certifications and emits domain events for downstream processing.",
        "function": f"certifications-{STAGE}",
        "payload": {"source": "aws.scheduler", "job": "expiry"},
        # `due` not `expired`: a healthy night expires nothing, and asserting on a
        # count that is legitimately 0 would report success as failure.
        "expect": "due",
    },
    "certifications-scanwatch": {
        "label": "Certification Scan Watchdog",
        "description": "Re-checks uploads still awaiting a malware-scan verdict (claim evidence and badge images) and converges any the fast paths missed. A non-zero pending count is normal — it means the scanner has not answered yet, not that the job failed.",
        "function": f"certifications-{STAGE}",
        "payload": {"source": "aws.scheduler", "job": "scanwatch"},
        # The only job with a cadence of its own. A 15-minute watchdog reduced to
        # one nightly pass would leave a stuck scan unresolved for up to a day,
        # which is the condition it exists to prevent.
        "ownSchedule": "rate(15 minutes)",
        "expect": "pendingScans",
    },
    "opensearch-reindex": {
        "label": "OpenSearch Reindex",
        "description": "Re-indexes the Member Directory (full profiles) then Admin Users (identity fields) sequentially into the shared 'members' index. Run this after a bulk import or if search results appear incomplete.",
                # STEP ORDER REVERSED (2026-08-27) — member-profiles now runs FIRST.
        #
        # The two writers are not symmetric. member-profiles uses OpenSearch
        # `index`, a WHOLE-DOCUMENT REPLACE; identity-access uses `update` with
        # doc_as_upsert over an allowlist of identity fields. So whichever runs
        # last wins, and with identity-access first its work was being discarded
        # every single night.
        #
        # Usually invisible, because a member-profiles PROFILE item duplicates
        # firstName/lastName/email/role/status. It bites when that item is a STUB:
        # `event_consumer._get_or_stub` creates `{id, groups, createdAt}` with no
        # role and no status, and three handlers persist it without filling them
        # (_on_joined_group, _on_left_group, _set_status). If the matching
        # UserProvisioned event never lands, the stub is permanent — nothing
        # reconciles member-profiles' identity fields back against identity-access.
        # The reindex then replaced the correct document with one carrying no
        # `role` at all, and `_member_to_doc` defaulted roleSortOrder to Member.
        # That member disappears from every role-filtered directory and admin
        # query, silently, and re-breaks the next night after any manual repair.
        #
        # Confirmed live on dev, not hypothetical: one such stub existed — the
        # Administrator account. Putting the authoritative writer LAST fixes it
        # for every field identity-access owns.
        #
        # The deeper fix is for member-profiles to use `update` too, so no writer
        # can clobber another. Not done here because `index` is what lets a DELETED
        # attribute (a removed skill) actually disappear from the index; switching
        # would leave stale values behind. Recorded as the follow-up.
        "steps": [
            {"function": f"member-profiles-{STAGE}", "payload": {"source": "scheduled-reindex"},
             "expect": "indexed"},
            {"function": f"identity-access-{STAGE}", "payload": {"source": "scheduled-reindex"},
             "expect": "indexed"},
        ],
    },
    "community-counts": {
        "label": "Community Roster Counts",
        "description": "Recounts the member roster (Total Members, New Members by quarter, membership growth trend) that feeds the Community Leader dashboard's 'Total Members' card. This is a DynamoDB roster recount, independent of OpenSearch.",
        "function": f"identity-access-{STAGE}",
        "payload": {"source": "scheduled-community-counts"},
                "expect": "computedAt",
    },
    # Separate from community-counts even though both feed the same dashboard and
    # both are roster work: they write separate snapshot items, so one failing
    # leaves the other's panel current instead of taking both down. Splitting them
    # also lets a CL re-run just the chart that looks wrong.
    "group-member-stats": {
        "label": "Members by User Group",
        "description": "Recomputes the per-group member breakdown (and the in-no-group total) behind the Community Leader dashboard's 'Members by User Group' chart. Folds each group's membership history for the current quarter — too expensive to run on a page load, which is why the chart reads a nightly snapshot.",
        "function": f"identity-access-{STAGE}",
        "payload": {"source": "scheduled-group-member-stats"},
                "expect": "computedAt",
    },
}

# Execution order for "Run all". Heaviest write load first, while the nightly
# window is quietest; the two cheap certifications jobs last.
#
# Order is for LOAD SPREADING ONLY — no job reads what another writes (verified
# per job, 2026-08-27), so this list can be reordered freely without affecting
# correctness. A test asserts it covers JOB_REGISTRY exactly, so a newly
# registered job cannot silently drop out of every run.
JOB_ORDER = [
    "opensearch-reindex",
    "community-counts",
    "group-member-stats",
    "contributions-sweep",
    "certifications-expiry",
    "certifications-scanwatch",
]

# When the whole batch runs unattended. ONE rule (ScheduledJobsNightly in
# service-settings-app.yaml) starts the state machine, which walks JOB_ORDER one
# job at a time — replacing three staggered per-job rules that spread load by
# clock offset instead.
#
# Kept in step with that rule by test_the_batch_schedule_matches_the_nightly_rule.
BATCH_SCHEDULE = "cron(0 3 * * ? *)"

VALID_JOB_IDS = set(JOB_REGISTRY.keys())


def next_run_at(schedule: str, *, now: datetime | None = None) -> str | None:
    """When `schedule` next fires, as an ISO-8601 UTC string, or None if unparseable.

    Deliberately NOT a cron library. Every expression this system uses is one of
    two trivial shapes — `cron(M H * * ? *)` (daily at a fixed UTC time) and
    `rate(N minutes)` — so a dependency parsing the full cron grammar would be
    vendored into the Lambda zip to evaluate six constant strings.

    Returns None rather than guessing on anything outside those two shapes. The
    caller renders an absent value as "schedule not recognised", which is honest;
    inventing a time would be the same class of defect as the dashboard badge that
    showed one job's timestamp beside another job's data.

    Times are UTC because that is what EventBridge cron expressions mean. The SPA
    formats to the viewer's locale.
    """
    now = now or datetime.now(timezone.utc)
    expression = (schedule or "").strip()

    rate = re.fullmatch(r"rate\((\d+)\s+minutes?\)", expression)
    if rate:
        return (now + timedelta(minutes=int(rate.group(1)))).isoformat(timespec="seconds")

    # cron(minute hour day-of-month month day-of-week year) — EventBridge's
    # six-field form. Only the fixed-daily shape is supported; anything with a
    # real day/month restriction returns None rather than being approximated.
    cron = re.fullmatch(r"cron\((\d+)\s+(\d+)\s+\*\s+\*\s+\?\s+\*\)", expression)
    if cron:
        minute, hour = int(cron.group(1)), int(cron.group(2))
        if not (0 <= minute <= 59 and 0 <= hour <= 23):
            return None
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.isoformat(timespec="seconds")

    return None


def describe_schedule(schedule: str) -> str:
    """Human wording for the card, e.g. "Daily at 03:45 UTC", "Every 15 minutes".

    Falls back to the raw expression rather than an empty string: an operator
    seeing `cron(45 3 * * ? *)` can still act on it, whereas a blank tells them
    nothing and hides that the expression was not understood.
    """
    expression = (schedule or "").strip()
    rate = re.fullmatch(r"rate\((\d+)\s+minutes?\)", expression)
    if rate:
        minutes = int(rate.group(1))
        return f"Every {minutes} minute{'s' if minutes != 1 else ''}"
    cron = re.fullmatch(r"cron\((\d+)\s+(\d+)\s+\*\s+\*\s+\?\s+\*\)", expression)
    if cron:
        return f"Daily at {int(cron.group(2)):02d}:{int(cron.group(1)):02d} UTC"
    return expression


class NightlyJobsService:
    """Trigger and track on-demand nightly job runs."""

    def __init__(self, repo, lambda_client=None, sfn_client=None,
                 state_machine_arn: str | None = None):
        self._repo = repo
        self._lambda = lambda_client or boto3.client("lambda")
        # Injected in tests; resolved from the environment in the Lambda. Empty in
        # a local/dev environment without the state machine, which start_batch
        # reports as unconfigured rather than failing obscurely at call time.
        self._state_machine_arn = (
            state_machine_arn if state_machine_arn is not None
            else os.environ.get("JOBS_STATE_MACHINE_ARN", ""))
        self._sfn = sfn_client or (boto3.client("stepfunctions")
                                   if self._state_machine_arn else None)

    def list_jobs(self) -> dict:
        """Everything the Scheduled Jobs page renders, in execution order.

        Iterates JOB_ORDER so the cards appear in the sequence a run will actually
        follow — a page that lists them in a different order than they execute
        invites the reader to assume a dependency that is not there.

        `nextRunAt` is the EARLIEST of the nightly batch and the job's own extra
        schedule, because that is the next time the job genuinely runs. Three jobs
        keep independent rules in their own service templates (contributions-sweep,
        and both certifications jobs), so for them the batch is not the whole story;
        the other three run only as part of the batch. Reporting only one of the two
        would understate freshness for half the list.
        """
        batch_next = next_run_at(BATCH_SCHEDULE)
        jobs = []
        for job_id in JOB_ORDER:
            meta = JOB_REGISTRY[job_id]
            own = meta.get("ownSchedule")
            own_next = next_run_at(own) if own else None
            # min() over the ones that resolved. An unparseable expression yields
            # None and is skipped rather than poisoning the result.
            candidates = [t for t in (batch_next, own_next) if t]
            jobs.append({
                "id": job_id,
                "label": meta["label"],
                "description": meta["description"],
                "batchSchedule": describe_schedule(BATCH_SCHEDULE),
                "ownSchedule": describe_schedule(own) if own else None,
                "nextRunAt": min(candidates) if candidates else None,
                "lastRun": self._repo.get_last_job_run(job_id),
            })
        out = {"items": jobs, "batchSchedule": describe_schedule(BATCH_SCHEDULE),
               "batchNextRunAt": batch_next}
        # Included so the page resumes in ONE request on mount. Fetching the
        # listing and then discovering separately that a batch is in flight would
        # render every card idle for a beat before snapping to running.
        active = self._repo.get_active_batch()
        if active:
            out["activeBatch"] = active
        return out

    def start_batch(self) -> dict:
        """Start ONE sequential run of every job. Returns the batch immediately.

        Async by necessity, not preference: a full pass is minutes of work, well
        past API Gateway's 29s ceiling, so the response can only ever be a receipt.
        The page polls `get_batch` and survives being navigated away from because
        all the state lives in DynamoDB.

        IDEMPOTENT VIA THE EXECUTION NAME. Step Functions rejects a duplicate name
        with ExecutionAlreadyExists, so two rapid clicks cannot start two batches —
        and that check lives in the service that owns the truth rather than in a
        read-then-write guard here. It replaces two hand-rolled 1800s "stuck run"
        heuristics that previously had to agree with each other.
        """
        if not self._state_machine_arn:
            raise ValidationError(
                "Job orchestration is not configured in this environment.")

        active = self._repo.get_active_batch()
        if active and active.get("status") == "running":
            raise ValidationError(
                "A run is already in progress. Wait for it to finish before "
                "starting another.")

        batch_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        # Every job gets its run record up front, in "queued". That is what lets
        # the page distinguish QUEUED from NEVER RUN for jobs further down the
        # sequence — without it, five cards look untouched while one works and the
        # operator reasonably concludes the rest are broken.
        jobs_payload = []
        job_states: dict = {}
        for job_id in JOB_ORDER:
            meta = JOB_REGISTRY[job_id]
            run_id = str(uuid.uuid4())
            self._repo.put_job_run({
                "runId": run_id, "jobId": job_id, "status": "queued",
                "startedAt": now, "completedAt": None, "result": None,
                "error": None, "batchId": batch_id,
            })
            job_states[job_id] = {"status": "queued", "runId": run_id}
            item = {"batchId": batch_id, "runId": run_id, "jobId": job_id,
                    "expect": meta.get("expect")}
            if "steps" in meta:
                item["steps"] = meta["steps"]
            else:
                item["function"] = meta["function"]
                item["payload"] = meta["payload"]
            jobs_payload.append(item)

        batch = {"batchId": batch_id, "status": "running", "startedAt": now,
                 "completedAt": None, "order": list(JOB_ORDER),
                 "currentIndex": 0, "jobs": job_states}
        self._repo.put_job_batch(batch)
        self._repo.set_active_batch(batch_id)

        try:
            self._sfn.start_execution(
                stateMachineArn=self._state_machine_arn,
                name=f"batch-{batch_id}",
                input=json.dumps({"batchId": batch_id, "jobs": jobs_payload}),
            )
        except Exception as exc:  # noqa: BLE001
            # The batch record exists but nothing will ever advance it, so fail it
            # now. Leaving it "running" would strand the page on a spinner and block
            # the next attempt behind the already-in-progress guard above.
            _logger.exception("Failed to start the jobs state machine")
            batch["status"] = "failed"
            batch["completedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            batch["error"] = str(exc)
            self._repo.put_job_batch(batch)
            self._repo.clear_active_batch()
            raise ValidationError("Could not start the run. Please try again.") from exc

        return batch

    def get_batch(self, batch_id: str) -> dict:
        batch = self._repo.get_job_batch(batch_id)
        if not batch:
            raise NotFoundError(f"Batch {batch_id} not found.")
        return batch

    def active_batch(self) -> dict | None:
        """The in-flight batch, or None — what the page reads on mount to resume."""
        return self._repo.get_active_batch()

    def trigger_job(self, job_id: str) -> dict:
        """Trigger a single job. Returns the run record immediately.

        Guards against concurrent runs: if the same job is already running,
        raises ValidationError instead of creating a duplicate invocation.
        """
        if job_id not in VALID_JOB_IDS:
            raise ValidationError(f"Unknown job: {job_id}")

        # Running guard — prevent double-trigger of the same job.
        # A run is considered stuck if it has been "running" for more than
        # 1800s (30 min) — twice the JobRunnerFn max timeout (900s). This
        # covers the edge case where the JobRunner Lambda itself times out
        # and never writes the completed/failed status back to DynamoDB.
        now_ts = datetime.now(timezone.utc)
        active = self._repo.list_active_runs()
        for r in (active or []):
            if r.get("jobId") != job_id:
                continue
            started = r.get("startedAt", "")
            try:
                from datetime import datetime as _dt  # noqa: PLC0415
                started_dt = _dt.fromisoformat(started.replace("Z", "+00:00"))
                age_seconds = (now_ts - started_dt).total_seconds()
            except (ValueError, TypeError):
                age_seconds = 0
            if age_seconds < 1800:
                raise ValidationError(
                    f"Job '{job_id}' is already running (started {int(age_seconds)}s ago). "
                    f"Wait for it to finish before triggering again."
                )
            # Stuck run (> 30 min) — mark it failed and allow re-trigger.
            _logger.warning("Clearing stuck run %s for job %s (age %ss)",
                            r.get("runId"), job_id, int(age_seconds))
            self._repo.update_job_run(r["runId"], {
                "status": "failed",
                "completedAt": now_ts.isoformat(timespec="seconds"),
                "error": "Job runner timed out — cleared automatically.",
            })

        meta = JOB_REGISTRY[job_id]
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        run = {
            "runId": run_id,
            "jobId": job_id,
            "status": "running",
            "startedAt": now,
            "completedAt": None,
            "result": None,
            "error": None,
        }
        self._repo.put_job_run(run)

        # Build the JobRunner payload. Multi-step jobs (e.g. opensearch-reindex)
        # pass a "steps" list so the runner calls each Lambda sequentially.
        # Single-step jobs pass the legacy "function"+"payload" shape.
        runner_function = f"settings-job-runner-{STAGE}"
        if "steps" in meta:
            runner_payload = {
                "runId": run_id,
                "jobId": job_id,
                "steps": meta["steps"],
            }
        else:
            runner_payload = {
                "runId": run_id,
                "jobId": job_id,
                "function": meta["function"],
                "payload": meta["payload"],
                # The key the result must carry for this job to count as done.
                # Without forwarding it the runner cannot tell "ran" from "worked".
                "expect": meta.get("expect"),
            }

        try:
            self._lambda.invoke(
                FunctionName=runner_function,
                InvocationType="Event",  # async — returns 202 immediately
                Payload=json.dumps(runner_payload).encode(),
            )
        except Exception as exc:
            _logger.exception("Failed to invoke job runner for job %s", job_id)
            run["status"] = "failed"
            run["error"] = str(exc)
            run["completedAt"] = now
            self._repo.put_job_run(run)

        return run

    def trigger_all(self) -> dict:
        """Trigger every registered job, in JOB_ORDER.

        Iterates JOB_ORDER rather than JOB_REGISTRY: dict order happens to be
        insertion order, but relying on that makes the execution sequence an
        accident of where someone pasted a new entry.

        NOTE this still fans out - each `trigger_job` fires its own async runner
        invocation, so the jobs overlap rather than running in sequence. Genuine
        sequencing arrives with the Step Functions state machine; this method
        remains for the interim and for tests.
        """
        runs = []
        for job_id in JOB_ORDER:
            runs.append(self.trigger_job(job_id))
        return {"runs": runs}

    def get_run_status(self, run_id: str) -> dict:
        """Get the current status of a run."""
        run = self._repo.get_job_run(run_id)
        if not run:
            raise NotFoundError(f"Run {run_id} not found.")
        return run

    def get_active_runs(self) -> dict:
        """Get all currently running jobs."""
        runs = self._repo.list_active_runs()
        return {"runs": runs}

    def complete_run(self, run_id: str, result: dict | None = None, error: str | None = None) -> None:
        """Mark a run as complete (called by the invoked Lambda or a callback)."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._repo.update_job_run(run_id, {
            "status": "failed" if error else "completed",
            "completedAt": now,
            "result": result,
            "error": error,
        })
