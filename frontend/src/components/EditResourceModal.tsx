/**
 * EditResourceModal — curator edit of a Library resource (US-2.25 / BR-LIB-C1).
 * File replacement is not supported via edit — delete and re-add instead.
 */
import { useState } from "react";
import { apiFetch } from "../lib/apiClient";
import TopicTagInput from "./TopicTagInput";

const FORMAT_OPTIONS = ["Slides", "PDF", "Doc", "Recording", "Link"];

interface LibraryResource {
  id: string;
  title: string;
  description: string;
  format: string;
  topics: string[];
  source: string;
  url?: string;
}

interface Props {
  resource: LibraryResource;
  onClose: () => void;
  onSaved: () => void;
}

export default function EditResourceModal({ resource, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(resource.title);
  const [description, setDescription] = useState(resource.description);
  const [format, setFormat] = useState(resource.format);
  const [topics, setTopics] = useState<string[]>(resource.topics || []);
  const [url, setUrl] = useState(resource.url || "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const isLink = format === "Link";

  const validate = () => {
    if (!title.trim()) return "Title is required.";
    if (!description.trim()) return "Description is required.";
    if (!format) return "Format is required.";
    if (isLink && url && !url.startsWith("https://")) return "URL must start with https://";
    return "";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validate();
    if (err) { setError(err); return; }
    setError("");
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        title: title.trim(),
        description: description.trim(),
        format,
        topics,
      };
      if (isLink && url) body.url = url;

      await apiFetch(`/library/${resource.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      onSaved();
    } catch (ex: unknown) {
      setError(ex instanceof Error ? ex.message : "Failed to update resource.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" data-testid="edit-resource-modal">
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <h2>Edit Resource</h2>
          <button className="btn sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <div className="alert danger mb-12">{error}</div>}

            <label className="field-label">Title <span className="required">*</span></label>
            <input
              className="input mb-12"
              data-testid="edit-title"
              value={title}
              maxLength={200}
              onChange={(e) => setTitle(e.target.value)}
            />

            <label className="field-label">
              Description <span className="required">*</span>
            </label>
            <textarea
              className="input mb-12"
              data-testid="edit-description"
              value={description}
              maxLength={5000}
              rows={4}
              onChange={(e) => setDescription(e.target.value)}
              style={{ resize: "vertical" }}
            />

            <label className="field-label">Format <span className="required">*</span></label>
            <select
              className="select mb-12"
              data-testid="edit-format"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              {FORMAT_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>

            {isLink && (
              <>
                <label className="field-label">URL</label>
                <input
                  className="input mb-12"
                  data-testid="edit-url"
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://…"
                />
              </>
            )}

            {!isLink && (
              <p className="faint small mb-12">
                💡 To replace the file, delete this resource and re-add it.
              </p>
            )}

            <label className="field-label">Topics</label>
            <TopicTagInput
              value={topics}
              onChange={setTopics}
              mode="multi"
              placeholder="Add topic tags…"
            />
          </div>
          <div className="modal-footer">
            <button type="button" className="btn" data-testid="edit-cancel" onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn primary"
              data-testid="edit-submit"
              disabled={submitting}
            >
              {submitting ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
