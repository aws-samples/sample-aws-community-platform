import { useState } from "react";
import { apiFetch, uploadToPresignedPost, type UploadGrant } from "../../lib/apiClient";
import { useApi } from "../../lib/useApi";
import DataTable from "../../components/DataTable";
import { ComingSoon, EmptyState, ErrorState, Loading } from "../../components/States";
import { BadgeTile, type CertDefinition } from "./types";

// Definitions tab (US-5.1/5.2/5.3) — leader/certifications.html: full-field
// define/edit modal (incl. real badge-image upload with a scanning state) and
// Deactivate/Reactivate with confirmation. Revoke moved to its own tab
// (change request 2026-08-07).
export default function DefinitionsTable({ nonce, onChanged }: {
  nonce: number;
  onChanged: () => void;
}) {
  const { data, loading, error, comingSoon } =
    useApi<{ items: CertDefinition[] }>(`/certifications?includeInactive=true&_=${nonce}`);
  const [modal, setModal] = useState<{ mode: "create" } | { mode: "edit"; def: CertDefinition } | null>(null);
  const [confirmToggle, setConfirmToggle] = useState<CertDefinition | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const toggleActive = async () => {
    if (!confirmToggle) return;
    setBusy(true);
    try {
      await apiFetch(`/certifications/${confirmToggle.id}`, {
        method: "PUT", body: JSON.stringify({ active: !confirmToggle.active }),
      });
      setConfirmToggle(null);
      onChanged();
    } catch (e) {
      setMsg((e as Error).message);
      setConfirmToggle(null);
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <Loading />;
  if (comingSoon) return <ComingSoon feature="Certification definitions" />;
  if (error) return <ErrorState message={error} />;
  const items = data?.items ?? [];

  const expiryLabel = (d: CertDefinition) => !d.expiryPeriodMonths ? "None"
    : d.expiryPeriodMonths % 12 === 0 ? `${d.expiryPeriodMonths / 12} years`
    : `${d.expiryPeriodMonths} months`;

  return (
    <>
      <div className="flex between mb-12">
        <span className="faint small" style={{ alignSelf: "center" }}>
          {items.length} certification definition{items.length === 1 ? "" : "s"}</span>
        <button className="btn primary" data-testid="define-cert"
                onClick={() => setModal({ mode: "create" })}>＋ Define Certification</button>
      </div>
      {msg && (
        <p className="small flex between mb-8" style={{ color: "var(--danger)" }} role="alert">
          <span>{msg}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button>
        </p>
      )}
      {items.length === 0 ? (
        <EmptyState message="No certifications defined yet — create the first one." />
      ) : (
        <div className="card">
          <DataTable id="cert-definitions" rows={items} columns={[
            { key: "name", header: "Certification", render: (d: CertDefinition) => (
              <div className="name-cell"><BadgeTile def={d} size={30} /><b>{d.name}</b>
                {d.badgeImageStatus === "PendingScan" && (
                  <span className="badge gray" title="Badge image is being scanned.">scanning…</span>)}
              </div>) },
            { key: "category", header: "Category", render: (d: CertDefinition) => d.category },
            { key: "expiry", header: "Expiry", render: expiryLabel },
            { key: "points", header: "Points", sortValue: (d: CertDefinition) => d.points,
              render: (d: CertDefinition) => d.points },
            { key: "active", header: "Status", render: (d: CertDefinition) => (
              <span className={"badge " + (d.active ? "green" : "gray")}>
                {d.active ? "Active" : "Inactive"}</span>) },
            { key: "act", header: "", render: (d: CertDefinition) => (
              <span className="btn-row">
                <button className="btn sm" data-testid={`edit-cert-${d.id}`}
                        onClick={() => setModal({ mode: "edit", def: d })}>Edit</button>
                <button className="btn sm" data-testid={`toggle-cert-${d.id}`}
                        onClick={() => setConfirmToggle(d)}>
                  {d.active ? "Deactivate" : "Reactivate"}</button>
              </span>) },
          ]} />
        </div>
      )}

      {modal && (
        <DefinitionModal def={modal.mode === "edit" ? modal.def : null}
                         onClose={() => setModal(null)}
                         onSaved={() => { setModal(null); onChanged(); }} />
      )}

      {confirmToggle && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 140,
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 440, maxWidth: "92vw" }} role="alertdialog"
               aria-modal="true" data-testid="toggle-confirm">
            <div className="card-head"><h3>{confirmToggle.active ? "Deactivate" : "Reactivate"} certification?</h3>
              <button className="icon-btn" aria-label="Close" onClick={() => setConfirmToggle(null)}>✕</button></div>
            <p className="small">
              {confirmToggle.active
                ? <><b>{confirmToggle.name}</b> is hidden from the catalog and no new claims can be
                    submitted. Members who already hold it keep their badge, and claims already in the
                    verification queue can still be decided. You can reactivate any time.</>
                : <><b>{confirmToggle.name}</b> becomes available in the catalog for new claims again.</>}
            </p>
            <div className="btn-row mt-12">
              <button className="btn primary" disabled={busy} data-testid="toggle-confirm-button"
                      onClick={toggleActive}>
                {busy ? "Saving…" : confirmToggle.active ? "Deactivate" : "Reactivate"}</button>
              <button className="btn" onClick={() => setConfirmToggle(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

// Define / Edit Certification modal — full US-5.1 field set: name, description,
// category, expiry period, per-cert points (gap-analysis B1), badge image (D6).
function DefinitionModal({ def, onClose, onSaved }: {
  def: CertDefinition | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(def?.name ?? "");
  const [description, setDescription] = useState(def?.description ?? "");
  const [category, setCategory] = useState(def?.category ?? "AWS Certification");
  const [expiryYears, setExpiryYears] = useState(
    def?.expiryPeriodMonths ? String(def.expiryPeriodMonths / 12) : "");
  const [points, setPoints] = useState(def ? String(def.points) : "25");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    if (!name.trim()) { setError("Name is required."); return; }
    if (!description.trim()) { setError("Description is required."); return; }
    const pts = Number(points);
    if (!Number.isInteger(pts) || pts < 0) { setError("Points must be a whole number ≥ 0."); return; }
    const years = expiryYears.trim() === "" ? null : Number(expiryYears);
    if (years !== null && (!Number.isFinite(years) || years <= 0)) {
      setError("Expiry period must be a positive number of years (or empty for never)."); return;
    }
    try {
      let badge: Record<string, string> = {};
      if (file) {
        setBusy("Uploading badge image…");
        const grant = await apiFetch<UploadGrant>("/certifications/badge-uploads", {
          method: "POST",
          body: JSON.stringify({ fileName: file.name, contentType: file.type || undefined }),
        });
        await uploadToPresignedPost(grant, file);
        badge = { badgeImageKey: grant.fileKey, badgeImageFileName: file.name };
      }
      setBusy("Saving…");
      const body = {
        name: name.trim(), description: description.trim(), category, points: pts,
        expiryPeriodMonths: years === null ? null : Math.round(years * 12),
        ...badge,
      };
      if (def) {
        await apiFetch(`/certifications/${def.id}`, { method: "PUT", body: JSON.stringify(body) });
      } else {
        await apiFetch("/certifications", { method: "POST", body: JSON.stringify(body) });
      }
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                  display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 500, maxWidth: "92vw", maxHeight: "90vh", overflowY: "auto" }}
           data-testid="definition-modal">
        <div className="card-head">
          <h3>{def ? `Edit ${def.name}` : "Define Certification / Badge"}</h3>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="field"><label>Name</label>
          <input className="input" data-testid="def-name" placeholder="e.g. AWS Security Specialty"
                 value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="field"><label>Description</label>
          <textarea className="textarea" data-testid="def-description"
                    value={description} onChange={(e) => setDescription(e.target.value)} /></div>
        <div className="form-row">
          <div className="field"><label>Category</label>
            <select className="select" data-testid="def-category" value={category}
                    onChange={(e) => setCategory(e.target.value as CertDefinition["category"])}>
              <option>AWS Certification</option>
              <option>Community Badge</option>
            </select></div>
          <div className="field"><label>Expiry period (years, optional)</label>
            <input className="input" data-testid="def-expiry" placeholder="e.g. 3 — empty = never"
                   value={expiryYears} onChange={(e) => setExpiryYears(e.target.value)} />
          </div>
        </div>
        <div className="form-row">
          <div className="field"><label>Points awarded on approval</label>
            <input className="input" type="number" min={0} style={{ width: 120 }}
                   data-testid="def-points" value={points}
                   onChange={(e) => setPoints(e.target.value)} />
            <div className="hint">Per-certification value credited when a claim is approved
              (US-5.1/US-6.5). Different certifications can be worth different points. Changing it later
              never alters points already awarded.</div></div>
          <div className="field"><label>Badge image</label>
            <input className="input" type="file" data-testid="def-badge-image"
                   accept=".png,.jpg,.jpeg,image/png,image/jpeg"
                   onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <div className="hint">PNG/JPG up to 5 MB. Shown publicly after a malware scan.
              {def?.badgeImageStatus === "Clean" && " Uploading a new image replaces the current one."}</div></div>
        </div>
        {error && <p className="small" style={{ color: "var(--danger)" }} role="alert"
                     data-testid="def-error">{error}</p>}
        <div className="btn-row mt-12">
          <button className="btn primary" disabled={Boolean(busy)} data-testid="def-save"
                  onClick={save}>{busy ?? (def ? "Save" : "Publish")}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
