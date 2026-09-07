import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, uploadToPresignedPost, type UploadGrant } from "../../lib/apiClient";
import { useApi } from "../../lib/useApi";
import type { Role } from "../../roles";
import type { CertDefinition, Claim } from "./types";

// Submit Certification Claim (US-5.4) — member/certifications.html modal.
// Real cert + group selects (the shipped stub hardcoded both), dateEarned
// required when the chosen cert expires, evidence = URL XOR file (direct-to-S3
// presigned POST — S3 itself enforces the 5 MB cap), optional notes.
// The "join a group first" gate renders in place of the form (US-5.4/422).
//
// UGL claiming (change request 2026-08-07, Q1=A): a UserGroupLeader credits the
// group they LEAD, not a group they belong to — so the group field is fixed to
// the led group (read-only) and the "join a group first" gate never applies.
export default function ClaimModal({ preselect, resubmitFrom, role, ledGroupId,
                                     onClose, onSubmitted }: {
  preselect?: CertDefinition | null;
  resubmitFrom?: Claim | null;
  role?: Role;
  ledGroupId?: string;
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const isUGL = role === "UserGroupLeader";
  const catalog = useApi<{ items: CertDefinition[] }>("/certifications");
  const groupsApi = useApi<{ items: { id: string; name: string; myState?: string }[] }>("/groups");

  const [certId, setCertId] = useState(preselect?.id ?? resubmitFrom?.certId ?? "");
  const [groupId, setGroupId] = useState(
    resubmitFrom?.creditedGroupId ?? (isUGL ? (ledGroupId ?? "") : ""));
  const [dateEarned, setDateEarned] = useState(resubmitFrom?.dateEarned ?? "");
  const [evidenceMode, setEvidenceMode] = useState<"url" | "file">(
    resubmitFrom?.hasEvidenceFile ? "file" : "url");
  const [evidenceUrl, setEvidenceUrl] = useState(resubmitFrom?.evidenceUrl ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [notes, setNotes] = useState(resubmitFrom?.notes ?? "");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Claimable = active, not held, not pending — the catalog already encodes it.
  const claimable = useMemo(
    () => (catalog.data?.items ?? []).filter((d) => !d.held && !d.pendingClaim),
    [catalog.data]);
  const allGroups = groupsApi.data?.items ?? [];
  const myGroups = useMemo(
    () => allGroups.filter((g) => g.myState === "member"),
    [allGroups]);
  // UGL: the credited group is the group they lead, resolved for its name.
  const ledGroup = useMemo(
    () => allGroups.find((g) => g.id === ledGroupId),
    [allGroups, ledGroupId]);
  const chosen = claimable.find((d) => d.id === certId)
    ?? (catalog.data?.items ?? []).find((d) => d.id === certId);
  const needsDate = Boolean(chosen?.expiryPeriodMonths);

  const submit = async () => {
    setError(null);
    if (!certId) { setError("Choose a certification."); return; }
    if (!groupId) { setError("Choose the user group to credit."); return; }
    // BR-C5′ (Certification Ledger enh.): earned date is required for EVERY claim.
    if (!dateEarned) {
      setError("Date earned is required — it's the date on your certificate."); return;
    }
    if (evidenceMode === "url" && !evidenceUrl.trim()) { setError("Paste an evidence link."); return; }
    if (evidenceMode === "file" && !file) { setError("Choose an evidence file (PDF or image)."); return; }
    try {
      let evidence: Record<string, string> = {};
      if (evidenceMode === "url") {
        evidence = { evidenceUrl: evidenceUrl.trim() };
      } else if (file) {
        setBusy("Uploading evidence…");
        const grant = await apiFetch<UploadGrant>("/certifications/evidence-uploads", {
          method: "POST",
          body: JSON.stringify({ fileName: file.name, contentType: file.type || undefined }),
        });
        await uploadToPresignedPost(grant, file);
        evidence = { evidenceFileKey: grant.fileKey, evidenceFileName: file.name };
      }
      setBusy("Submitting claim…");
      const groupName = isUGL
        ? ledGroup?.name
        : (myGroups.find((g) => g.id === groupId) ?? allGroups.find((g) => g.id === groupId))?.name;
      await apiFetch("/certifications/claims", {
        method: "POST",
        body: JSON.stringify({
          certId, creditedGroupId: groupId,
          ...(groupName ? { creditedGroupName: groupName } : {}),
          ...(dateEarned ? { dateEarned } : {}),
          ...(notes.trim() ? { notes: notes.trim() } : {}),
          ...evidence,
        }),
      });
      onSubmitted();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  // The "join a group first" gate is a Member concern only — a UGL always
  // credits the group they lead.
  const noGroups = !isUGL && !groupsApi.loading && myGroups.length === 0;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                  display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 500, maxWidth: "92vw", maxHeight: "90vh", overflowY: "auto" }}
           data-testid="claim-modal">
        <div className="card-head">
          <h3>{resubmitFrom ? "Resubmit Certification Claim" : "Submit Certification Claim"}</h3>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>

        {noGroups ? (
          // US-5.4: no group membership -> prompted to join first, not a form.
          <div data-testid="join-group-first">
            <p className="small">You must belong to at least one user group before you can submit a
              certification claim — approved points are credited to a group of yours, and that group's
              leader verifies the claim.</p>
            <div className="btn-row mt-12">
              <Link className="btn primary" to="/groups">Browse User Groups</Link>
              <button className="btn" onClick={onClose}>Close</button>
            </div>
          </div>
        ) : (
          <>
            <div className="field"><label>Certification</label>
              <select className="select" data-testid="claim-cert" value={certId}
                      disabled={Boolean(preselect) || Boolean(resubmitFrom)}
                      onChange={(e) => setCertId(e.target.value)}>
                <option value="">Choose…</option>
                {(preselect && !claimable.some((d) => d.id === preselect.id)
                  ? [...claimable, preselect] : claimable).map((d) => (
                  <option key={d.id} value={d.id}>{d.name}</option>
                ))}
                {resubmitFrom && !claimable.some((d) => d.id === resubmitFrom.certId) && (
                  <option value={resubmitFrom.certId}>{resubmitFrom.certName ?? resubmitFrom.certId}</option>
                )}
              </select>
            </div>

            <div className="field"><label>User group to credit</label>
              {isUGL ? (
                <>
                  <input className="input" data-testid="claim-group" readOnly
                         value={ledGroup?.name ?? "Your group"} />
                  <div className="hint">Your claim is credited to the group you lead and is verified by
                    a Community Leader. As a leader, your claim earns no points.</div>
                </>
              ) : (
                <>
                  <select className="select" data-testid="claim-group" value={groupId}
                          onChange={(e) => setGroupId(e.target.value)}>
                    <option value="">Choose…</option>
                    {myGroups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                  </select>
                  <div className="hint">Approved points are credited to this group, and the claim is
                    routed to that group's leader for verification.</div>
                </>
              )}
            </div>

            <div className="field">
              <label>Date earned</label>
              <input className="input" type="date" data-testid="claim-date-earned"
                     value={dateEarned} max={new Date().toISOString().slice(0, 10)}
                     onChange={(e) => setDateEarned(e.target.value)} />
              <div className="hint">Required — the date on your certificate (when you earned it).
                {needsDate && chosen?.expiryPeriodMonths
                  ? ` This certification expires ${Math.round(chosen.expiryPeriodMonths / 12)} year(s) after that date.`
                  : ""}</div>
            </div>

            <div className="field"><label>Evidence</label>
              <div className="flex" style={{ gap: 12, marginBottom: 6 }}>
                <label className="small"><input type="radio" name="ev" checked={evidenceMode === "url"}
                  onChange={() => setEvidenceMode("url")} /> Link</label>
                <label className="small"><input type="radio" name="ev" checked={evidenceMode === "file"}
                  data-testid="evidence-mode-file" onChange={() => setEvidenceMode("file")} /> File upload</label>
              </div>
              {evidenceMode === "url" ? (
                <input className="input" data-testid="claim-evidence-url"
                       placeholder="Paste a Credly/certificate URL"
                       value={evidenceUrl} onChange={(e) => setEvidenceUrl(e.target.value)} />
              ) : (
                <>
                  <input className="input" type="file" data-testid="claim-evidence-file"
                         accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
                         onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                  <div className="hint">PDF or image, up to 5 MB. The file is scanned before a reviewer
                    can open it.</div>
                </>
              )}
            </div>

            <div className="field"><label>Notes (optional)</label>
              <textarea className="textarea" data-testid="claim-notes"
                        placeholder="e.g. context for the reviewer"
                        value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>

            {error && <p className="small" style={{ color: "var(--danger)" }} role="alert"
                         data-testid="claim-error">{error}</p>}
            <div className="btn-row mt-12">
              <button className="btn primary" disabled={Boolean(busy)} data-testid="claim-submit"
                      onClick={submit}>{busy ?? "Submit"}</button>
              <button className="btn" onClick={onClose}>Cancel</button>
            </div>
            <p className="faint small mt-12 mb-0">You can't submit a duplicate for a certification you
              already hold or have pending.</p>
          </>
        )}
      </div>
    </div>
  );
}
