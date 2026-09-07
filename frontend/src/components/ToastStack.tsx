import { useCallback, useEffect, useRef, useState } from "react";

// Toast notification system — stacked, auto-dismiss, individually dismissible.
// Matches the AWS Console flash-bar pattern: messages stack top-down, each with
// its own dismiss button and a colored left border indicating severity.

export type ToastKind = "success" | "error" | "info";

export interface Toast {
  id: number;
  message: string;
  kind: ToastKind;
}

/** Hook to manage a stack of toast messages. */
export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const addToast = useCallback((message: string, kind: ToastKind = "success") => {
    const id = nextId.current++;
    setToasts((prev) => [...prev, { id, message, kind }]);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const success = useCallback((msg: string) => addToast(msg, "success"), [addToast]);
  const error = useCallback((msg: string) => addToast(msg, "error"), [addToast]);
  const info = useCallback((msg: string) => addToast(msg, "info"), [addToast]);

  return { toasts, addToast, dismissToast, success, error, info };
}

/** Auto-dismiss timer for a single toast. */
function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    if (toast.kind === "error") return; // errors stay until manually dismissed
    const timer = setTimeout(() => onDismiss(toast.id), 6000);
    return () => clearTimeout(timer);
  }, [toast.id, toast.kind, onDismiss]);

  const borderColor = toast.kind === "error"
    ? "var(--danger, #dc2626)"
    : toast.kind === "info"
      ? "var(--info, #0369a1)"
      : "var(--success, #16a34a)";

  const bgColor = toast.kind === "error"
    ? "var(--danger-bg, #fef2f2)"
    : toast.kind === "info"
      ? "var(--info-bg, #f0f9ff)"
      : "var(--success-bg, #f0fdf4)";

  const textColor = toast.kind === "error"
    ? "var(--danger, #dc2626)"
    : toast.kind === "info"
      ? "var(--info, #0369a1)"
      : "var(--success, #16a34a)";

  return (
    <div
      className="toast-item"
      role={toast.kind === "error" ? "alert" : "status"}
      data-testid={`toast-${toast.kind}`}
      style={{
        background: bgColor,
        borderLeft: `4px solid ${borderColor}`,
        color: textColor,
        padding: "10px 14px",
        borderRadius: "var(--radius, 6px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 10,
        boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
        animation: "toastSlideIn 0.2s ease-out",
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 500 }}>{toast.message}</span>
      <button
        className="icon-btn"
        aria-label="Dismiss"
        title="Dismiss"
        style={{ flexShrink: 0, color: textColor, background: "none", border: "none", cursor: "pointer", fontSize: 14 }}
        onClick={() => onDismiss(toast.id)}
      >
        ✕
      </button>
    </div>
  );
}

/** Renders a vertical stack of toast messages. Place once per page. */
export default function ToastStack({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div
      className="toast-stack"
      aria-live="polite"
      style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
