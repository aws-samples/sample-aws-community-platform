import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/apiClient";
import Banner from "../components/Banner";
import { ErrorState, Loading } from "../components/States";
import {
  batchProgress, cadenceParts, formatTime, isBatchRunning, jobState, leadLower,
  relativeToNow, stateBadge, type Job, type JobBatch,
} from "./scheduledJobs";

// Scheduled Jobs (Administrators and Community Leaders).
//
// ONE button. There is deliberately no per-job Run: the jobs are executed in a
// defined order by a Step Functions state machine, and a per-job trigger fanned
// out its own invocation, so any use of it bypassed that ordering. The endpoint was
// removed rather than merely hidden here.
//
// State lives entirely server-side (batch record + per-job run records), so
// navigating away and returning is just a re-read. Nothing about progress is held
// only in this component.

interface JobListResponse {
  items: Job[];
  batchSchedule?: string;
  batchNextRunAt?: string | null;
  activeBatch?: JobBatch;
}

/** Indeterminate spinner. Deliberately not a percentage bar: a job reports no
 *  progress fraction, so any bar would be animating a number we do not have. */
function Spinner() {
  return <span className="spinner-sm" aria-hidden="true" />;
}

function StateBadge({ job, batch }: { job: Job; batch?: JobBatch | null }) {
  const state = jobState(job, batch);
  const { cls, label } = stateBadge(state);
  return (
    <span className={cls} data-testid={`job-state-${job.id}`}
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      {state === "running" && <Spinner />}
      {label}
    </span>
  );
}

function JobCard({ job, batch }: { job: Job; batch?: JobBatch | null }) {
  const state = jobState(job, batch);
  const last = job.lastRun;
  // Prefer the batch's error for a job that just failed — it is the live one;
  // lastRun may still hold the previous run's message.
  const error = batch?.jobs?.[job.id]?.error ?? last?.error;
  const cadence = cadenceParts(job);

  // The finished cell has to say something different while a run is in flight:
  // showing the PREVIOUS finish time next to a live spinner reads as though the
  // current run already ended.
  const finished = state === "running" ? "Running now"
    : state === "queued" ? "Waiting its turn"
      : formatTime(last?.completedAt);
  const finishedIsPlaceholder = state === "running" || state === "queued" || !last?.completedAt;

  return (
    <div className={`card job-card is-${state}`} data-testid={`job-card-${job.id}`}>
      <div className="job-card-head">
        <div>
          <h3>{job.label}</h3>
          <p className="job-desc">{job.description}</p>
        </div>
        <StateBadge job={job} batch={batch} />
      </div>

      {/* Label/value PAIRS in DOM order, deliberately. .job-meta places them onto
          a label row and a value row on wide screens, which is what keeps the
          three values on a shared baseline; when it collapses to one column the
          pairs stay together. Emitting all three labels and then all three values
          looked identical when wide and fell apart completely when narrow. */}
      <div className="job-meta">
        <div className="label">Next run</div>
        <div className={`value${job.nextRunAt ? "" : " none"}`} data-testid={`job-next-${job.id}`}>
          {job.nextRunAt ? formatTime(job.nextRunAt) : "Schedule not recognised"}
        </div>
        <div className="label">Last started</div>
        <div className={`value${last?.startedAt ? "" : " none"}`} data-testid={`job-started-${job.id}`}>
          {formatTime(last?.startedAt)}
        </div>
        <div className="label">Last finished</div>
        <div className={`value${finishedIsPlaceholder ? " none" : ""}`}
             data-testid={`job-finished-${job.id}`}>
          {finished}
        </div>
      </div>

      {cadence.length > 0 && (
        <div className="job-cadence" data-testid={`job-cadence-${job.id}`}>
          {cadence.map((part, i) => (
            <span key={part}>
              {i > 0 && <span className="sep">·&nbsp;</span>}
              {part}
            </span>
          ))}
        </div>
      )}

      {state === "failed" && error && (
        <div className="job-error" data-testid={`job-error-${job.id}`}>{error}</div>
      )}
    </div>
  );
}

export default function AdminNightlyJobsPage() {
  const [data, setData] = useState<JobListResponse | null>(null);
  const [batch, setBatch] = useState<JobBatch | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [msgKind, setMsgKind] = useState<"success" | "error">("success");
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  /** Re-read the listing. Also the "resume" path: `activeBatch` comes back on the
   *  same response, so returning to the page after navigating away needs no extra
   *  request and never flashes every card as idle first. */
  const load = useCallback(async () => {
    try {
      const res = await apiFetch<JobListResponse>("/settings/nightly-jobs");
      setData(res);
      setBatch(res.activeBatch ?? null);
      setError(null);
      return res.activeBatch ?? null;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const startPolling = useCallback((batchId: string) => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const fresh = await apiFetch<JobBatch>(`/settings/nightly-jobs/batch/${batchId}`);
        setBatch(fresh);
        if (!isBatchRunning(fresh)) {
          // Finished: stop, then reload so each card picks up its final last-run
          // times from the run records rather than the batch's summary.
          stopPolling();
          const failed = fresh.failedJobs ?? [];
          setMsgKind(failed.length ? "error" : "success");
          setMsg(failed.length
            ? `Run finished with ${failed.length} failed job${failed.length === 1 ? "" : "s"}.`
            : "All jobs completed.");
          load();
        }
      } catch {
        // A transient poll failure is not worth surfacing — the next tick retries,
        // and the batch is still recorded server-side regardless.
      }
    }, 3000);
  }, [load, stopPolling]);

  useEffect(() => {
    load().then((active) => {
      if (active?.batchId && isBatchRunning(active)) startPolling(active.batchId);
    });
    return stopPolling;
  }, [load, startPolling, stopPolling]);

  const runAll = async () => {
    setStarting(true);
    setMsg(null);
    try {
      const started = await apiFetch<JobBatch>("/settings/nightly-jobs/run",
                                               { method: "POST" });
      setBatch(started);
      setMsgKind("success");
      setMsg("Run started. You can leave this page — progress is kept and will be here when you return.");
      if (started.batchId) startPolling(started.batchId);
    } catch (e) {
      setMsgKind("error");
      setMsg((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error} />;

  const jobs = data?.items ?? [];
  const running = isBatchRunning(batch);
  const { done, total } = batchProgress(batch);

  return (
    <>
      <div className="page-head flex between">
        <div>
          {/* "Scheduled", not "Nightly": two of these run every 15 minutes and
              every 5 minutes, so a nightly label would contradict their own cards. */}
          <h1>Scheduled Jobs</h1>
          <p>
            Recomputes the aggregates behind the dashboards. Run them now if a
            dashboard looks out of date.
          </p>
          {/* The countdown lives HERE and nowhere else. Every job shares the batch
              schedule, so repeating it per card printed the same "in 19h 8m" six
              times and buried the fields that do differ. */}
          {data?.batchSchedule && (
            <div className="jobs-schedule" data-testid="batch-schedule">
              <span>Runs automatically <strong>{leadLower(data.batchSchedule)}</strong></span>
              {data.batchNextRunAt && relativeToNow(data.batchNextRunAt) && (
                <>
                  <span className="sep">·</span>
                  <span>next <strong>{relativeToNow(data.batchNextRunAt)}</strong></span>
                </>
              )}
            </div>
          )}
        </div>
        <button className="btn primary" data-testid="run-all-jobs"
                disabled={starting || running} onClick={runAll}>
          {running ? <><Spinner /> Running {done} of {total}…</>
            : starting ? <><Spinner /> Starting…</>
              : "Run all jobs"}
        </button>
      </div>

      <Banner message={msg} kind={msgKind} onDismiss={() => setMsg(null)} />

      {running && (
        <div className="jobs-progress mb-16" role="status" data-testid="batch-progress">
          <Spinner />
          <span>
            Running one job at a time, in order — <strong>{done} of {total}</strong> finished.
            Safe to navigate away.
          </span>
        </div>
      )}

      {/* Cards follow EXECUTION order, which is the order the server returns them
          in. Sorting them any other way would imply a sequence that is not real. */}
      <div className="grid cols-1" style={{ gap: 16 }}>
        {jobs.map((job) => <JobCard key={job.id} job={job} batch={batch} />)}
      </div>
    </>
  );
}
