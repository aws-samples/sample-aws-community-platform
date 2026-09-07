// Pure helpers for the Scheduled Jobs page.
//
// Extracted from the component because this repo has no React Testing Library —
// only jsdom and pure-helper suites — so logic left inline in JSX is logic with no
// test. The state derivation below is exactly the part that silently regresses:
// getting it wrong makes the page misreport what the system is doing, which is the
// one thing this page exists to do correctly.

/** What a card shows. Five states, not three.
 *
 *  `queued` is the one the requirement did not name but the design needs: the
 *  batch runs jobs ONE AT A TIME, so while job 2 executes, jobs 3-6 are waiting.
 *  Without a distinct state they render identically to "never run", and an
 *  operator watching five untouched cards reasonably concludes they are broken.
 *
 *  `never` is distinct from `success` for the same reason — an absent run is not
 *  a passing run. */
export type JobState = "running" | "queued" | "success" | "failed" | "never";

export interface JobRun {
  runId?: string;
  status?: string;
  startedAt?: string | null;
  completedAt?: string | null;
  error?: string | null;
}

export interface JobBatch {
  batchId?: string;
  status?: string;
  order?: string[];
  currentIndex?: number;
  jobs?: Record<string, { status?: string; error?: string | null }>;
  failedJobs?: string[];
}

export interface Job {
  id: string;
  label: string;
  description: string;
  batchSchedule?: string;
  ownSchedule?: string | null;
  nextRunAt?: string | null;
  lastRun?: JobRun | null;
}

/** The state to render for one job.
 *
 *  An in-flight batch WINS over the last-run record, and that ordering matters:
 *  the batch is the live view, whereas `lastRun` may still describe the previous
 *  night until the runner writes the new outcome. Reading lastRun first would show
 *  yesterday's green tick beside a job that is currently running.
 */
export function jobState(job: Job, batch?: JobBatch | null): JobState {
  const inBatch = batch?.status === "running" ? batch?.jobs?.[job.id] : undefined;
  const status = inBatch?.status ?? job.lastRun?.status;

  switch (status) {
    case "running":   return "running";
    case "queued":    return "queued";
    case "completed": return "success";
    case "failed":    return "failed";
    default:          return "never";
  }
}

/** Colour class + label per state. Kept beside jobState so a new state cannot be
 *  added without deciding how it looks. */
export function stateBadge(state: JobState): { cls: string; label: string } {
  switch (state) {
    case "running": return { cls: "badge blue",  label: "Running" };
    case "queued":  return { cls: "badge gray",  label: "Queued" };
    case "success": return { cls: "badge green", label: "Success" };
    case "failed":  return { cls: "badge red",   label: "Failed" };
    default:        return { cls: "badge gray",  label: "Never run" };
  }
}

/** Is a batch in flight? Drives the spinner, the disabled button and the polling.
 *  Anything other than an explicit "running" is treated as finished, so an
 *  unexpected status can never leave the page polling forever. */
export function isBatchRunning(batch?: JobBatch | null): boolean {
  return batch?.status === "running";
}

/** "3 of 6 finished" for the batch progress line.
 *
 *  Falls back to counting terminal jobs when `currentIndex` is absent, so a batch
 *  written before that field existed still reports progress instead of 0. */
export function batchProgress(batch?: JobBatch | null): { done: number; total: number } {
  if (!batch) return { done: 0, total: 0 };
  const total = batch.order?.length ?? Object.keys(batch.jobs ?? {}).length;
  const counted = Object.values(batch.jobs ?? {}).filter(
    (j) => j.status === "completed" || j.status === "failed").length;
  return { done: batch.currentIndex ?? counted, total };
}

/** Local-time rendering for an ISO timestamp, or an em dash when absent.
 *
 *  Absent is common and legitimate — a job that never ran has no start time, and a
 *  running job has no end time — so this must read as "nothing to show" rather
 *  than as an error.
 *
 *  THE TIME ZONE IS PART OF THE VALUE, not decoration. `toLocaleString()` rendered
 *  "29/08/2026, 08:30:00" directly above the cadence line "Daily at 03:00 UTC" —
 *  two different clocks, neither labelled, five and a half hours apart, reading as
 *  a bug. The cadence has to stay in UTC because that is the zone the cron rules
 *  are authored in, so the fix is to name the zone on the timestamp.
 *
 *  The month is spelled to kill the DD/MM vs MM/DD ambiguity, and seconds are
 *  dropped: nothing here is decided on a one-second difference. */
export function formatTime(iso?: string | null): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString(undefined, {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
    hour12: false, timeZoneName: "short",
  });
}

/** Lowercase the FIRST LETTER ONLY, for dropping a server-cased phrase into the
 *  middle of a sentence.
 *
 *  `toLowerCase()` on the whole string turned "Daily at 03:00 UTC" into
 *  "daily at 03:00 utc" — a lowercased acronym, which is the kind of detail that
 *  makes a page look unfinished. */
export function leadLower(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

/** EXTRA cadence for a job that runs more often than the batch, or [] if it does
 *  not. Parts rather than one string so the separator can be styled instead of
 *  being a literal "·" in the text.
 *
 *  Batch-only jobs deliberately get NOTHING. The batch schedule is stated once in
 *  the page header, so repeating "Daily at 03:00 UTC" on every card printed the
 *  same line four times and drowned out the two jobs whose cadence is genuinely
 *  different. An empty line here is what makes those two stand out. */
export function cadenceParts(job: Job): string[] {
  return job.ownSchedule ? [job.ownSchedule, "plus the scheduled batch"] : [];
}

/** Coarse "in 6h" / "in 12m" wording for the next run.
 *
 *  Deliberately relative: an operator cares how long until the data refreshes, and
 *  an absolute UTC timestamp forces them to do the subtraction. The absolute time
 *  is still shown alongside via formatTime. */
export function relativeToNow(iso?: string | null, now: Date = new Date()): string | null {
  if (!iso) return null;
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return null;
  const minutes = Math.round((target.getTime() - now.getTime()) / 60000);
  if (minutes <= 0) return "due now";
  if (minutes < 60) return `in ${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h ${minutes % 60}m`;
  return `in ${Math.floor(hours / 24)}d ${hours % 24}h`;
}
