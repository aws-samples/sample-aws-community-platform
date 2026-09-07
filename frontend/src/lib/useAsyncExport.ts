// Shared client for the platform's async CSV exports (Admin > Users,
// Member Directory).
//
// Both exports follow the same server contract: POST returns 202 with a job id,
// a worker Lambda builds the CSV into S3, and a status endpoint is polled until
// it reports `ready` with a short-lived presigned download URL. This hook owns
// that lifecycle so the two pages don't each re-implement the polling — and so
// the subtleties below are fixed in one place rather than half-remembered twice.
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "./apiClient";

/** Mirrors UserExportJob / DirectoryExportJob in the service contracts. */
export interface ExportJob {
  jobId: string;
  status: "queued" | "running" | "ready" | "failed";
  processed?: number;
  /** null when the search index cannot supply a count — bar goes indeterminate. */
  total?: number | null;
  percent?: number | null;
  fileName?: string;
  /** Presigned and short-lived. Present only once status is "ready". */
  url?: string;
  expiresInSeconds?: number;
  error?: string;
}

const POLL_INTERVAL_MS = 3000;

export function useAsyncExport(basePath: string) {
  const [job, setJob] = useState<ExportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stop = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Clear the interval on unmount so a poll cannot fire against a dead component.
  useEffect(() => stop, [stop]);

  const poll = useCallback((jobId: string) => {
    stop();
    pollRef.current = setInterval(async () => {
      try {
        const next = await apiFetch<ExportJob>(`${basePath}/${jobId}`);
        setJob(next);
        // Stop on EITHER terminal state. Without the "ready" case the interval
        // would keep running and re-sign a fresh presigned URL every few seconds.
        if (next.status === "ready" || next.status === "failed") stop();
      } catch {
        // Transient poll failures are ignored: the job is unaffected and the next
        // tick usually succeeds. A real failure arrives as job.status === "failed".
      }
    }, POLL_INTERVAL_MS);
  }, [basePath, stop]);

  /** Kick off an export. `filters` is sent as the POST body. */
  const start = useCallback(async (filters: Record<string, string> = {}) => {
    setError(null);
    try {
      const started = await apiFetch<ExportJob>(basePath, {
        method: "POST",
        body: JSON.stringify(filters),
      });
      setJob(started);
      poll(started.jobId);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [basePath, poll]);

  const reset = useCallback(() => {
    stop();
    setJob(null);
    setError(null);
  }, [stop]);

  const running = job?.status === "queued" || job?.status === "running";

  return { job, error, running, start, reset };
}
