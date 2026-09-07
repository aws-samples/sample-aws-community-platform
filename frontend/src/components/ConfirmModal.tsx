// ConfirmModal — reusable destructive-action confirmation dialog.
//
// Replaces ad-hoc window.confirm() calls and inline confirm patterns with a
// consistent, branded modal. All delete/cancel/withdraw operations in the app
// route through this component.
//
// Usage:
//   const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
//   ...
//   <button onClick={() => setConfirm({ title: "Delete X?", body: "...",
//     confirmLabel: "Delete X", onConfirm: () => doDelete(id) })}>Delete</button>
//   {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}

import { useState } from "react";

export interface ConfirmOptions {
  title: string;
  /** Body text — accepts a JSX node for rich content (bullets, bold, etc.) */
  body: React.ReactNode;
  /** Label on the danger confirm button, e.g. "Delete Group" */
  confirmLabel: string;
  /** Label on the cancel button. Defaults to "Cancel". */
  cancelLabel?: string;
  /** Async action to run when the user confirms */
  onConfirm: () => Promise<void> | void;
}

interface Props extends ConfirmOptions {
  onClose: () => void;
}

export default function ConfirmModal({
  title,
  body,
  confirmLabel,
  cancelLabel = "Cancel",
  onConfirm,
  onClose,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      style={{
        position: "fixed", inset: 0,
        background: "rgba(15,23,42,.4)",
        zIndex: 140,
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="card"
        data-testid="confirm-modal"
        style={{ width: 460, maxWidth: "92vw" }}
      >
        {/* Header */}
        <div className="card-head">
          <h3 id="confirm-modal-title" style={{ margin: 0 }}>{title}</h3>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>

        {/* Body */}
        <div
          data-testid="confirm-modal-body"
          style={{ fontSize: 13.5, color: "var(--text-muted)", lineHeight: 1.6 }}
        >
          {body}
        </div>

        {/* Error feedback */}
        {error && (
          <div
            className="banner error"
            role="alert"
            data-testid="confirm-modal-error"
            style={{ marginTop: 12 }}
          >
            {error}
          </div>
        )}

        {/* Actions */}
        <div className="btn-row" style={{ marginTop: 16 }}>
          <button
            className="btn danger"
            disabled={busy}
            data-testid="confirm-modal-confirm"
            onClick={handleConfirm}
          >
            {busy ? "Please wait…" : confirmLabel}
          </button>
          <button
            className="btn"
            disabled={busy}
            data-testid="confirm-modal-cancel"
            onClick={onClose}
          >
            {cancelLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
