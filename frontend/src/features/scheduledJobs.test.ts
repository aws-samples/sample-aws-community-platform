import { describe, expect, it } from "vitest";
import {
  batchProgress, cadenceParts, formatTime, isBatchRunning, jobState, leadLower,
  relativeToNow, stateBadge, type Job, type JobBatch,
} from "./scheduledJobs";

const JOB: Job = { id: "community-counts", label: "Roster Counts", description: "x" };

describe("jobState", () => {
  it("reports never-run when there is no history at all", () => {
    // Distinct from success: an absent run is not a passing run.
    expect(jobState(JOB)).toBe("never");
    expect(jobState(JOB, null)).toBe("never");
  });

  it("maps the last run's outcome when no batch is in flight", () => {
    expect(jobState({ ...JOB, lastRun: { status: "completed" } })).toBe("success");
    expect(jobState({ ...JOB, lastRun: { status: "failed" } })).toBe("failed");
  });

  it("shows queued for jobs waiting behind the one executing", () => {
    // THE STATE THE REQUIREMENT DID NOT NAME. The batch runs one job at a time, so
    // without this the four jobs still waiting look identical to never-run and the
    // operator concludes they are broken.
    const batch: JobBatch = {
      status: "running",
      jobs: { "community-counts": { status: "queued" } },
    };
    expect(jobState(JOB, batch)).toBe("queued");
  });

  it("lets an in-flight batch override a stale last run", () => {
    // Ordering matters: lastRun may still describe the previous night until the
    // runner writes the new outcome. Reading it first would show yesterday's green
    // tick beside a job that is currently running.
    const job: Job = { ...JOB, lastRun: { status: "completed" } };
    const batch: JobBatch = {
      status: "running",
      jobs: { "community-counts": { status: "running" } },
    };
    expect(jobState(job, batch)).toBe("running");
  });

  it("falls back to the last run once the batch has finished", () => {
    const job: Job = { ...JOB, lastRun: { status: "completed" } };
    const finished: JobBatch = {
      status: "completed",
      jobs: { "community-counts": { status: "queued" } },  // stale batch entry
    };
    // The completed batch must not pin the card on "queued" forever.
    expect(jobState(job, finished)).toBe("success");
  });

  it("reports never-run for a job absent from a running batch", () => {
    const batch: JobBatch = { status: "running", jobs: { "other-job": { status: "running" } } };
    expect(jobState(JOB, batch)).toBe("never");
  });
});

describe("stateBadge", () => {
  it("gives each state a distinct colour", () => {
    const colours = (["running", "queued", "success", "failed", "never"] as const)
      .map((s) => stateBadge(s).cls);
    // Success and failure must never share a colour — that is the whole point.
    expect(stateBadge("success").cls).not.toBe(stateBadge("failed").cls);
    expect(colours).toHaveLength(5);
  });
});

describe("isBatchRunning", () => {
  it("treats anything other than an explicit running as finished", () => {
    // Fail-safe: an unexpected status must not leave the page polling forever.
    expect(isBatchRunning({ status: "running" })).toBe(true);
    expect(isBatchRunning({ status: "completed" })).toBe(false);
    expect(isBatchRunning({ status: "weird" })).toBe(false);
    expect(isBatchRunning(null)).toBe(false);
    expect(isBatchRunning(undefined)).toBe(false);
  });
});

describe("batchProgress", () => {
  it("uses the server's currentIndex when present", () => {
    expect(batchProgress({ order: ["a", "b", "c"], currentIndex: 2, jobs: {} }))
      .toEqual({ done: 2, total: 3 });
  });

  it("counts terminal jobs when currentIndex is absent", () => {
    // A batch written before currentIndex existed should still report progress
    // rather than sitting at 0.
    expect(batchProgress({
      order: ["a", "b", "c"],
      jobs: { a: { status: "completed" }, b: { status: "failed" }, c: { status: "running" } },
    })).toEqual({ done: 2, total: 3 });
  });

  it("is zero for no batch", () => {
    expect(batchProgress(null)).toEqual({ done: 0, total: 0 });
  });
});

describe("formatTime", () => {
  it("renders an em dash for absent times", () => {
    // Absent is legitimate: a job that never ran has no start, a running job has
    // no end. It must not read as an error.
    expect(formatTime(null)).toBe("—");
    expect(formatTime(undefined)).toBe("—");
  });

  it("returns the raw value when it is not a parseable date", () => {
    expect(formatTime("not-a-date")).toBe("not-a-date");
  });

  it("names the time zone and spells the month", () => {
    // THE REGRESSION THIS GUARDS. toLocaleString() rendered "29/08/2026, 08:30:00"
    // immediately above the cadence line "Daily at 03:00 UTC" — two unlabelled
    // clocks 5.5h apart, which reads as a bug rather than as two zones. The zone
    // name is load-bearing, not decoration.
    //
    // Mid-month and midday so no real time zone can shift the date or the month,
    // and the assertions avoid pinning a locale-specific layout.
    const out = formatTime("2026-08-15T12:00:00Z");
    expect(out).toContain("2026");
    expect(out).toMatch(/Aug/i);
    expect(out).not.toMatch(/\d{4}-\d{2}-\d{2}T/);    // not the raw ISO string
    expect(out).not.toMatch(/^\d{2}\/\d{2}\/\d{4}/);  // not ambiguous DD/MM/YYYY
    // A zone marker of some form must be present — GMT+5:30, UTC, IST, CEST…
    expect(out).toMatch(/GMT|UTC|[A-Z]{2,5}$/);
  });
});

describe("cadenceParts", () => {
  const base: Job = { ...JOB, batchSchedule: "Daily at 03:00 UTC" };

  it("says nothing for a job that only runs in the batch", () => {
    // THE POINT OF THE HELPER. The batch schedule is already stated once in the
    // page header; repeating it per card printed "Daily at 03:00 UTC" four times
    // and drowned out the two jobs whose cadence genuinely differs.
    expect(cadenceParts(base)).toEqual([]);
    expect(cadenceParts({ ...base, ownSchedule: null })).toEqual([]);
  });

  it("reports the extra cadence for a job that runs more often than the batch", () => {
    expect(cadenceParts({ ...base, ownSchedule: "Every 15 minutes" }))
      .toEqual(["Every 15 minutes", "plus the scheduled batch"]);
  });

  it("is empty when the server sent no schedule at all", () => {
    // Renders nothing rather than an orphaned separator.
    expect(cadenceParts(JOB)).toEqual([]);
  });
});

describe("leadLower", () => {
  it("lowercases only the first letter, preserving acronyms", () => {
    // THE BUG THIS REPLACES. toLowerCase() on the whole phrase rendered
    // "daily at 03:00 utc" in the header — a lowercased acronym.
    expect(leadLower("Daily at 03:00 UTC")).toBe("daily at 03:00 UTC");
    expect(leadLower("Every 15 minutes")).toBe("every 15 minutes");
    expect(leadLower("")).toBe("");
  });
});

describe("relativeToNow", () => {
  const now = new Date("2026-08-27T05:00:00Z");

  it("describes minutes, hours and days ahead", () => {
    expect(relativeToNow("2026-08-27T05:12:00Z", now)).toBe("in 12m");
    expect(relativeToNow("2026-08-27T11:30:00Z", now)).toBe("in 6h 30m");
    expect(relativeToNow("2026-08-29T08:00:00Z", now)).toBe("in 2d 3h");
  });

  it("says due now for a time already passed", () => {
    // A schedule in the past means the run is imminent or the clock drifted;
    // either way "in -5m" would be nonsense.
    expect(relativeToNow("2026-08-27T04:55:00Z", now)).toBe("due now");
  });

  it("returns null when there is no usable time", () => {
    // The server returns null for a schedule expression it does not recognise
    // rather than guessing, so the card must be able to say nothing.
    expect(relativeToNow(null, now)).toBeNull();
    expect(relativeToNow("nonsense", now)).toBeNull();
  });
});
