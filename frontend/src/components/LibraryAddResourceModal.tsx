/**
 * LibraryAddResourceModal — Path 3 curator direct add (US-2.23).
 * Uploads files directly to S3 via presigned PUT (same pattern as event materials).
 * Shows upload progress bar and post-upload scan-queue confirmation message.
 */
import { useRef, useState } from "react";
import { apiFetch } from "../lib/apiClient";
import TopicTagInput from "./TopicTagInput";

const FORMAT_OPTIONS = ["Slides", "PDF", "Doc", "Recording", "Link"];

interface Props {
  onClose: () => void;
  onAdded: () => void;
}

export default function LibraryAddResourceModal({ onClose, onAdded }: Props) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [format, setFormat] = useState("");
  const [topics, setTopics] = useState<string[]>([]);
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null); // 0-100
  const [uploaded, setUploaded] = useState(false); // scan-queue confirmation shown
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const isLink = format === "Link";

  const validate = () => {
    if (!title.trim()) return "Title is required.";
    if (!description.trim()) return "Description is required.";
    if (!format) return "Format is required.";
    if (isLink && !url.startsWith("https://")) return "A Link resource requires an https:// URL.";
    if (!isLink && !file) return "Please select a file to upload.";
    return "";
  };

  /** Upload file to S3 via XHR so we get progress events. */
  const uploadToS3 = (presignedUrl: string, fileObj: File): Promise<void> =>
    new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", presignedUrl);
      xhr.setRequestHeader("Content-Type", fileObj.type || "application/octet-stream");
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable) {
          setUploadProgress(Math.round((ev.loaded / ev.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else reject(new Error(`S3 upload failed (${xhr.status})`));
      };
      xhr.onerror = () => reject(new Error("S3 upload failed (network error)"));
      xhr.send(fileObj);
    });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validate();
    if (err) { setError(err); return; }
    setError("");
    setSubmitting(true);
    setUploadProgress(isLink ? null : 0);

    try {
      const body: Record<string, unknown> = {
        title: title.trim(),
        description: description.trim(),
        format,
        topics,
      };
      if (isLink) {
        body.url = url;
      } else if (file) {
        body.fileName = file.name;
        body.sizeBytes = file.size;
      }

      const res = await apiFetch<{ presignedUploadUrl?: string }>("/library", {
        method: "POST",
        body: JSON.stringify(body),
      });

      // Upload file to S3 with progress tracking
      if (res.presignedUploadUrl && file) {
        await uploadToS3(res.presignedUploadUrl, file);
        setUploadProgress(100);
        // Show scan-queue confirmation — don't auto-close
        setUploaded(true);
        setSubmitting(false);
        return;
      }

      // Link resources are immediately available — close and refresh
      onAdded();
    } catch (ex: unknown) {
      setError(ex instanceof Error ? ex.message : "Failed to add resource.");
      setUploadProgress(null);
    } finally {
      if (!uploaded) setSubmitting(false);
    }
  };

  // ── Scan-queue confirmation screen ───────────────────────────────────────
  if (uploaded) {
    return (
      <div className="modal-overlay" role="dialog" aria-modal="true" data-testid="library-add-modal">
        <div className="modal" style={{ maxWidth: 520, textAlign: "center" }}>
          <div className="modal-body" style={{ padding: "32px 24px" }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>✅</div>
            <h2 style={{ marginBottom: 8 }}>File uploaded successfully</h2>
            <p style={{ marginBottom: 8 }}>
              <b>{title}</b> has been added to the Content Library and queued for GuardDuty malware scan.
            </p>
            <p className="faint small" style={{ marginBottom: 24 }}>
              Once the scan completes and the file is confirmed clean, it will appear in search results.
              Scanning may take several minutes depending on the number of files queued.
            </p>
            <div
              style={{
                background: "var(--surface-alt)",
                borderRadius: 8,
                padding: "12px 16px",
                marginBottom: 24,
                textAlign: "left",
                fontSize: 13,
              }}
            >
              <span style={{ marginRight: 8 }}>🔍</span>
              <b>Tip:</b> You can search for this resource by title or description once the scan clears.
              If the file is flagged, it will be quarantined and not shown to members.
            </div>
            <button
              className="btn primary"
              data-testid="upload-confirm-done"
              onClick={onAdded}
              style={{ minWidth: 120 }}
            >
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Main add form ─────────────────────────────────────────────────────────
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" data-testid="library-add-modal">
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <h2>Add to Content Library</h2>
          <button className="btn sm" onClick={onClose} aria-label="Close" disabled={submitting}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <div className="alert danger mb-12">{error}</div>}

            <label className="field-label">Title <span className="required">*</span></label>
            <input
              className="input mb-12"
              data-testid="add-title"
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Resource title"
              disabled={submitting}
            />

            <label className="field-label">
              Description <span className="required">*</span>
              <span className="faint small" style={{ fontWeight: 400 }}> — used in search</span>
            </label>
            <textarea
              className="input mb-12"
              data-testid="add-description"
              value={description}
              maxLength={5000}
              rows={4}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe this resource…"
              style={{ resize: "vertical" }}
              disabled={submitting}
            />

            <label className="field-label">Format <span className="required">*</span></label>
            <select
              className="select mb-12"
              data-testid="add-format"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              disabled={submitting}
            >
              <option value="">Select format…</option>
              {FORMAT_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>

            {isLink && (
              <>
                <label className="field-label">URL <span className="required">*</span></label>
                <input
                  className="input mb-12"
                  data-testid="add-url"
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://…"
                  disabled={submitting}
                />
              </>
            )}

            {!isLink && format && (
              <>
                <label className="field-label">File <span className="required">*</span></label>
                <input
                  ref={fileRef}
                  type="file"
                  data-testid="add-file"
                  className="mb-12"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  disabled={submitting}
                />
              </>
            )}

            {/* Upload progress bar */}
            {uploadProgress !== null && (
              <div style={{ marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span className="small">Uploading…</span>
                  <span className="small faint">{uploadProgress}%</span>
                </div>
                <div
                  style={{
                    height: 6,
                    borderRadius: 3,
                    background: "var(--border)",
                    overflow: "hidden",
                  }}
                >
                  <div
                    data-testid="upload-progress-bar"
                    style={{
                      height: "100%",
                      borderRadius: 3,
                      background: "var(--primary)",
                      width: `${uploadProgress}%`,
                      transition: "width 0.2s ease",
                    }}
                  />
                </div>
              </div>
            )}

            <label className="field-label">Topics</label>
            <TopicTagInput
              value={topics}
              onChange={setTopics}
              mode="multi"
              placeholder="Add topic tags…"
              disabled={submitting}
            />
            <p className="faint small mt-4 mb-0">Optional. Tags help members filter resources.</p>
          </div>
          <div className="modal-footer">
            <button
              type="button"
              className="btn"
              data-testid="add-cancel"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn primary"
              data-testid="add-submit"
              disabled={submitting}
            >
              {submitting ? (uploadProgress !== null ? `Uploading ${uploadProgress}%…` : "Adding…") : "Add to Library"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
