// Progress / result panel for the async CSV exports (Admin > Users, Member
// Directory). Pairs with lib/useAsyncExport.
//
// The bar is PERCENTAGE-driven, unlike the status-driven one in
// AdminNightlyJobsPage (which can only say "running"): an export reports exact
// processed/total counts, and for a job users are told may take several minutes a
// real percentage is far more useful than an animation. It falls back to the
// indeterminate animation only when `percent` is null — which happens if the
// search index cannot supply a count — rather than displaying a fabricated number.
import type { ExportJob } from "../lib/useAsyncExport";

function ProgressBar({ percent }: { percent: number | null }) {
  const indeterminate = percent === null;
  return (
    <>
      <div className="progress-track"
           style={{ height: 8, background: "#e5e7eb", borderRadius: 4, overflow: "hidden" }}>
        <div
          className={indeterminate ? "export-progress-animated" : ""}
          style={{
            height: "100%",
            width: indeterminate ? "20%" : `${Math.max(2, Math.min(100, percent))}%`,
            background: "var(--primary-color, #2563eb)",
            borderRadius: 4,
            transition: indeterminate ? undefined : "width 0.4s ease",
          }}
          role="progressbar"
          aria-valuenow={indeterminate ? undefined : Math.min(100, percent)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={indeterminate ? "Export in progress" : `Export ${Math.min(100, percent)}% complete`}
        />
      </div>
      <style>{`
        @keyframes export-progress-indeterminate {
          0%   { width: 20%; margin-left: 0; }
          50%  { width: 60%; margin-left: 20%; }
          100% { width: 20%; margin-left: 80%; }
        }
        .export-progress-animated {
          animation: export-progress-indeterminate 2s ease-in-out infinite;
        }
      `}</style>
    </>
  );
}

export default function AsyncExportPanel({
  job, error, noun, onRetry, onDismiss,
}: {
  job: ExportJob | null;
  error: string | null;
  /** Plural noun for the row counts, e.g. "users" or "members". */
  noun: string;
  onRetry: () => void;
  onDismiss: () => void;
}) {
  if (!job && !error) return null;
  const running = job?.status === "queued" || job?.status === "running";

  return (
    <div className="card mb-16" data-testid="export-progress">
      {error && <p className="small" style={{ color: "var(--danger)" }}>{error}</p>}

      {running && (
        <>
          <p className="small mb-8">
            <b>Preparing your CSV…</b>{" "}
            {job?.total
              ? <>{(job.processed ?? 0).toLocaleString()} of {job.total.toLocaleString()} {noun}</>
              : <>{(job?.processed ?? 0).toLocaleString()} {noun} so far</>}
          </p>
          <ProgressBar percent={job?.percent ?? null} />
          <p className="small faint" style={{ marginTop: 8 }}>
            Please stay on this page — large exports can take several minutes.
            Leaving loses the download link.
          </p>
        </>
      )}

      {job?.status === "ready" && (
        <>
          <p className="small mb-8">
            <b style={{ color: "var(--success)" }}>Export ready</b>
            {" — "}{(job.processed ?? 0).toLocaleString()} {noun}.
          </p>
          <ProgressBar percent={100} />
          <div className="btn-row" style={{ marginTop: 10 }}>
            {/* A plain anchor, not fetch: the presigned URL is a direct
                browser-to-S3 GET and must not be proxied through the SPA. */}
            <a className="btn primary" data-testid="export-download"
               href={job.url} download={job.fileName}>
              ⬇ Download {job.fileName}
            </a>
            <button className="btn" onClick={onDismiss}>Dismiss</button>
          </div>
          <p className="small faint" style={{ marginTop: 8 }}>
            This link is valid for about{" "}
            {Math.round((job.expiresInSeconds ?? 300) / 60)} minute(s).
          </p>
        </>
      )}

      {job?.status === "failed" && (
        <>
          <p className="small" style={{ color: "var(--danger)" }}>
            <b>Export failed.</b> {job.error}
          </p>
          <div className="btn-row" style={{ marginTop: 10 }}>
            <button className="btn" data-testid="export-retry" onClick={onRetry}>Try again</button>
            <button className="btn" onClick={onDismiss}>Dismiss</button>
          </div>
        </>
      )}
    </div>
  );
}
