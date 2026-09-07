import { useState } from "react";
import { apiFetch } from "../lib/apiClient";

export interface Field {
  name: string;
  label: string;
  type?: "text" | "textarea" | "select" | "date" | "datetime-local" | "checkbox" | "tags" | "image";
  /** Select options — a bare string is used as both value and label. */
  options?: (string | { value: string; label: string })[];
  required?: boolean;
  /** Image fields only: endpoint that mints the presigned upload grant. The
   *  file is uploaded straight to storage and the field value becomes its URL. */
  uploadPath?: string;
  /** Opt-in extras (default off, so the other FormModal uses are unchanged). */
  hint?: string;
  /** Character cap. With `counter`, shows "N of max remaining" and blocks Save
   *  while over. Does NOT hard-stop typing, so the user can see and trim excess. */
  maxLength?: number;
  counter?: boolean;
}

const opt = (o: string | { value: string; label: string }) =>
  (typeof o === "string" ? { value: o, label: o } : o);

// Generic create/edit modal that POSTs/PUTs to an endpoint via the API client.
// Values are strings for text/select/date inputs; checkbox fields are sent as
// the literal strings "true"/"" so plain-string state stays uniform, and the
// backend already coerces awsProject-style booleans loosely (see
// member-profiles ProfileService / EDITABLE_FIELDS).
export default function FormModal(props: {
  title: string;
  fields: Field[];
  path: string;
  method?: "POST" | "PUT";
  initial?: Record<string, string>;
  /** Optional informational note rendered between the title and the fields. */
  intro?: React.ReactNode;
  onClose: () => void;
  onSaved?: (result: unknown) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(props.initial ?? {});
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Image field: grant a presigned upload, send the file straight to storage,
  // then store the returned public URL as the field value (saved with the form).
  const uploadImage = async (field: Field, file: File) => {
    setUploading(true); setError(null);
    try {
      const grant = await apiFetch<{ url: string; fields: Record<string, string>; avatarUrl: string }>(
        field.uploadPath!,
        { method: "POST", body: JSON.stringify({ fileName: file.name, contentType: file.type, sizeBytes: file.size }) },
      );
      const form = new FormData();
      Object.entries(grant.fields).forEach(([k, v]) => form.append(k, v));
      form.append("file", file);           // the file part MUST be last for S3
      const res = await fetch(grant.url, { method: "POST", body: form });
      if (!res.ok) throw new Error("Upload failed. Please try a different image (PNG/JPEG/WebP, ≤5 MB).");
      setValues((v) => ({ ...v, [field.name]: grant.avatarUrl }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  };

  // A counter field that is over its cap blocks Save (FR-7). The server remains
  // the enforcement point; this only spares the user a round-trip.
  const overLimit = props.fields.some(
    (f) => f.counter && f.maxLength != null && (values[f.name] ?? "").length > f.maxLength,
  );

  const submit = async () => {
    setSaving(true); setError(null);
    try {
      const body: Record<string, unknown> = { ...values };
      for (const f of props.fields) {
        if (f.type === "checkbox") body[f.name] = values[f.name] === "true";
        if (f.type === "tags") {
          body[f.name] = (values[f.name] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
        }
      }
      const result = await apiFetch(props.path, { method: props.method ?? "POST", body: JSON.stringify(body) });
      props.onSaved?.(result);
      props.onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay">
      <div className="card modal-card" data-testid="form-modal">
        <div className="card-head" style={{ flexShrink: 0 }}><h3>{props.title}</h3><button className="icon-btn" onClick={props.onClose}>✕</button></div>
        <div style={{ overflowY: "auto", flex: "1 1 auto", minHeight: 0, paddingBottom: 8 }}>
        {props.intro && (
          <div className="card mb-12" style={{ background: "var(--info-bg)", borderColor: "var(--border)", padding: 10 }} data-testid="form-intro">
            <span className="small">{props.intro}</span>
          </div>
        )}
        {props.fields.map((f) => (
          <div className="field" key={f.name}>
            {f.type === "checkbox" ? (
              <label className="small" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input type="checkbox" data-testid={`field-${f.name}`} checked={values[f.name] === "true"}
                       onChange={(e) => setValues({ ...values, [f.name]: e.target.checked ? "true" : "" })} />
                {f.label}
              </label>
            ) : (
              <>
                <label>{f.label}{f.required ? " *" : ""}</label>
                {f.type === "textarea" ? (
                  <textarea className="textarea" data-testid={`field-${f.name}`} value={values[f.name] ?? ""}
                            aria-invalid={f.counter && f.maxLength != null && (values[f.name] ?? "").length > f.maxLength}
                            onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
                ) : f.type === "image" ? (
                  <div className="flex" style={{ gap: 12, alignItems: "center" }}>
                    {values[f.name]
                      ? <img src={values[f.name]} alt="Profile picture preview"
                             style={{ width: 56, height: 56, borderRadius: "50%", objectFit: "cover" }} />
                      : <div className="avatar" aria-hidden="true">?</div>}
                    <div>
                      <input type="file" accept="image/png,image/jpeg,image/webp"
                             data-testid={`field-${f.name}`} disabled={uploading}
                             onChange={(e) => { const file = e.target.files?.[0]; if (file) uploadImage(f, file); }} />
                      {uploading && <span className="small" data-testid={`uploading-${f.name}`} style={{ marginLeft: 8 }}>⏳ Uploading…</span>}
                    </div>
                  </div>
                ) : f.type === "tags" ? (
                  <input className="input" placeholder="Comma-separated" value={values[f.name] ?? ""}
                         data-testid={`field-${f.name}`} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
                ) : f.type === "select" ? (
                  <select className="select" data-testid={`field-${f.name}`} value={values[f.name] ?? ""}
                          onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                    <option value="">Select…</option>
                    {(f.options ?? []).map(opt).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                ) : (
                  <input className="input" type={f.type ?? "text"} value={values[f.name] ?? ""}
                         data-testid={`field-${f.name}`} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
                )}
                {(() => {
                  if (!f.counter || f.maxLength == null) {
                    return f.hint ? <div className="hint" data-testid={`hint-${f.name}`}>{f.hint}</div> : null;
                  }
                  const used = (values[f.name] ?? "").length;
                  const remaining = f.maxLength - used;
                  const over = remaining < 0;
                  const near = !over && remaining <= Math.max(20, Math.floor(f.maxLength * 0.1));
                  const color = over ? "var(--danger)" : near ? "#b45309" : undefined;
                  return (
                    <div className="flex between" style={{ gap: 8 }}>
                      {f.hint ? <span className="hint" data-testid={`hint-${f.name}`}>{f.hint}</span> : <span />}
                      <span className="small" data-testid={`counter-${f.name}`} style={{ color }}>
                        {over
                          ? `${-remaining} over the ${f.maxLength} limit`
                          : `${remaining} of ${f.maxLength} remaining`}
                      </span>
                    </div>
                  );
                })()}
              </>
            )}
          </div>
        ))}
        </div>
        {error && (
          <div className="card" role="alert" data-testid="form-error"
               style={{ flexShrink: 0, margin: "12px 0 0", padding: 10, background: "#fef2f2",
                        borderColor: "#fecaca", color: "var(--danger)" }}>
            <span className="small"><b>Could not save.</b> {error}</span>
          </div>
        )}
        <div className="btn-row" style={{ flexShrink: 0, marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border, #e2e8f0)", background: "var(--surface)" }}>
          <button className="btn primary" disabled={saving || overLimit || uploading} data-testid="form-submit" onClick={submit}>{saving ? "Saving…" : "Save"}</button>
          <button className="btn" onClick={props.onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
