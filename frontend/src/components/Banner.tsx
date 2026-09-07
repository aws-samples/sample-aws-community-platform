// Dismissible feedback banner (success / error / info) — portal-wide UI
// standard: every success/failure/suggestion message panel must be user-
// dismissible (cross-cutting UI feedback standard). Renders nothing when message is empty.
export default function Banner({
  message, kind = "success", onDismiss, testId,
}: {
  message: string | null | undefined;
  kind?: "success" | "error" | "info";
  onDismiss: () => void;
  testId?: string;
}) {
  if (!message) return null;
  const bg = kind === "error" ? "var(--danger-bg)" : kind === "info" ? "var(--info-bg)" : "var(--success-bg)";
  return (
    <div className="card mb-16 flex between" role={kind === "error" ? "alert" : "status"}
         style={{ background: bg, padding: "10px 14px" }} data-testid={testId ?? `banner-${kind}`}>
      <span className="small">{message}</span>
      <button className="icon-btn" aria-label="Dismiss" title="Dismiss"
              style={{ flexShrink: 0 }} onClick={onDismiss}>✕</button>
    </div>
  );
}
