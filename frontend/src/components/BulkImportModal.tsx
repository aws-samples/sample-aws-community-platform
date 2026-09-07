import { useRef, useState } from "react";
import { apiFetch } from "../lib/apiClient";
import { download } from "../lib/exportCsv";
import { IMPORT_TEMPLATE_CSV, parseCsvText, toImportRows } from "../lib/parseCsv";

// Max users per import — mirrors the backend MAX_IMPORT_ROWS guard
// (services/identity-access/src/user_service.py). Keep the two in sync.
// Capped at 25 (not 100) because API Gateway's hard 29s integration timeout
// means a 100-row batch reliably 504s the client even though the rows still
// get created server-side.
const MAX_IMPORT_ROWS = 25;

interface ImportResult {
  created?: number;
  skipped?: number;
  rejected?: number;
  report?: { row: number; email?: string; outcome: string }[];
}

// Color-code each outcome row so the admin can scan the results instantly.
function outcomeStyle(outcome: string): React.CSSProperties {
  if (outcome === "Created") return { color: "var(--success)" };
  if (outcome.startsWith("Skipped")) return { color: "var(--warning)" };
  if (outcome.startsWith("Rejected")) return { color: "var(--danger)" };
  return {};
}

// Dedicated Bulk Import modal (US-1.31): real file upload + client-side CSV
// parsing (see lib/parseCsv.ts for why .xlsx isn't supported — the xlsx/SheetJS
// npm package has unpatched high-severity CVEs), a downloadable template, and
// a per-row result report. Replaces the generic FormModal's single "file name"
// text field, which never actually read or sent file contents.
export default function BulkImportModal(props: { onClose: () => void }) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string>("");
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const onFile = async (file: File) => {
    setParseError(null); setResult(null);
    if (!/\.csv$/i.test(file.name)) {
      setParseError("Only .csv files are supported. Use the template below.");
      setFileName(""); setRows([]);
      return;
    }
    setFileName(file.name);
    try {
      const text = await file.text();
      const parsed = parseCsvText(text);
      if (parsed.length === 0) {
        setParseError("No data rows found in the file.");
        setRows([]);
        return;
      }
      setRows(toImportRows(parsed));
    } catch (e) {
      setParseError((e as Error).message);
      setRows([]);
    }
  };

  const submit = async () => {
    // Front-end row-limit check — mirrors the backend MAX_IMPORT_ROWS=25 guard.
    // Gives instant feedback without a round-trip; the backend enforces it too.
    if (rows.length > MAX_IMPORT_ROWS) {
      setError(
        `Your file contains ${rows.length} users. The maximum is ${MAX_IMPORT_ROWS} per import. ` +
        `Please split your file into batches of up to ${MAX_IMPORT_ROWS} rows and import each separately.`
      );
      return;
    }
    setSubmitting(true); setError(null);
    try {
      const r = await apiFetch<ImportResult>("/users/import", {
        method: "POST",
        body: JSON.stringify({ fileName, rows }),
      });
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 560, maxWidth: "92vw", maxHeight: "88vh", overflowY: "auto" }} data-testid="bulk-import-modal">
        <div className="card-head"><h3>Bulk Import Users</h3><button className="icon-btn" onClick={props.onClose}>✕</button></div>

        <p className="small faint mb-8">
          Upload a .csv file with columns: email, first_name, last_name (required), city,
          country, professional_role, aws_project (optional). Imported users take the
          system-wide default time zone.
        </p>
        <button className="btn sm mb-8" data-testid="download-import-template"
                onClick={() => download("user-import-template.csv", IMPORT_TEMPLATE_CSV)}>
          ⬇ Download CSV template
        </button>

        <div className="field">
          <label>CSV file *</label>
          <input ref={fileInputRef} className="input" type="file" accept=".csv" data-testid="bulk-import-file"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
        </div>
        {fileName && !parseError && (
          <>
            <p className="small">
              Loaded <b>{fileName}</b> — {rows.length} row(s) ready to import.
            </p>
            {rows.length > MAX_IMPORT_ROWS && (
              <p className="small" style={{ color: "var(--danger)" }}>
                ⚠️ File exceeds the {MAX_IMPORT_ROWS}-row limit. Split into batches of up to {MAX_IMPORT_ROWS} rows before importing.
              </p>
            )}
          </>
        )}
        {parseError && <p className="small" style={{ color: "var(--danger)" }}>{parseError}</p>}
        {error && <p className="small" style={{ color: "var(--danger)" }}>{error}</p>}

        {result && (
          <div className="card mb-16" data-testid="bulk-import-result"
               style={{ background: (result.rejected ?? 0) > 0 ? "var(--warning-bg)" : "var(--success-bg)" }}>
            <p className="small mb-8">
              <b style={{ color: "var(--success)" }}>{result.created ?? 0} created</b>
              {(result.skipped ?? 0) > 0 && <>, <b style={{ color: "var(--warning)" }}>{result.skipped} skipped</b></>}
              {(result.rejected ?? 0) > 0 && <>, <b style={{ color: "var(--danger)" }}>{result.rejected} rejected</b></>}
              .
            </p>
            {result.report && result.report.length > 0 && (
              <div style={{ maxHeight: 260, overflowY: "auto" }}>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th style={{ width: 48 }}>Row</th>
                      <th>Email</th>
                      <th>Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.report.map((r) => (
                      <tr key={r.row}>
                        <td>{r.row}</td>
                        <td style={{ fontFamily: "monospace", fontSize: 12 }}>{r.email || "—"}</td>
                        <td style={outcomeStyle(r.outcome)}>{r.outcome}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        <div className="btn-row">
          {!result ? (
            <>
              <button className="btn primary" disabled={submitting || rows.length === 0} data-testid="bulk-import-submit" onClick={submit}>
                {submitting ? "Importing…" : `Import ${rows.length || ""} rows`}
              </button>
              <button className="btn" onClick={props.onClose}>Cancel</button>
            </>
          ) : (
            <button className="btn primary" onClick={props.onClose}>Done</button>
          )}
        </div>
      </div>
    </div>
  );
}
