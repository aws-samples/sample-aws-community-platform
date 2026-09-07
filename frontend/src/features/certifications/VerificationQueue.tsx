import { useState } from "react";
import { apiFetch } from "../../lib/apiClient";
import { useApi } from "../../lib/useApi";
import { useInfinitePages } from "../../lib/useInfinitePages";
import DataTable from "../../components/DataTable";
import Avatar from "../../components/Avatar";
import { ComingSoon, ErrorState } from "../../components/States";
import { openSafely, safeHostname } from "../../lib/safeUrl";
import { fmtDate, type Claim, type CertDefinition } from "./types";

// Pending Verifications (US-5.6/5.7) — leader/certifications.html pending tab /
// ugl/verifications.html. CL sees all groups (+group filter); UGL sees only
// claims credited to their led group (no group column — single-group scope).
// Oldest first (server order). Reject requires a reason (modal). Rows awaiting
// the malware scan are visible but not decidable (BR-V3).
//
// Thousands-pending at CL scale (2026-08-08): same approach as Admin > User
// Management — server-side cursor pagination + server filters, the page shell
// renders immediately with skeleton rows while a page loads. Filter dropdowns
// are sourced from dedicated endpoints (definitions catalog, groups directory)
// rather than derived from the visible page, so they stay complete under paging.
export default function VerificationQueue({ isCL, nonce, onChanged }: {
  isCL: boolean;
  nonce: number;
  onChanged: () => void;
}) {
  const [certFilter, setCertFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");

  // Filter option sources — complete lists, independent of the current page.
  const defs = useApi<{ items: CertDefinition[] }>("/certifications?includeInactive=true");
  const groups = useApi<{ items: { id: string; name: string }[] }>("/groups", isCL);

  // Endpoint carries the filters and the `_` nonce; the infinite hook appends
  // limit/cursor. onChanged() (a decision) bumps the nonce, so deciding a claim
  // resets the queue to page 1 and drops the row just handled.
  const params = new URLSearchParams();
  if (certFilter) params.set("certId", certFilter);
  if (isCL && groupFilter) params.set("groupId", groupFilter);
  params.set("_", String(nonce));
  const pages = useInfinitePages<Claim>(`/certifications/verifications?${params.toString()}`);
  const { rows, error, comingSoon } = pages;
  const [reject, setReject] = useState<Claim | null>(null);
  const [confirmApprove, setConfirmApprove] = useState<Claim | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const certOptions = (defs.data?.items ?? []).map((d) => [d.id, d.name] as const);
  const groupOptions = (groups.data?.items ?? []).map((g) => [g.id, g.name] as const);

  const decide = async (claim: Claim, decision: "approve" | "reject", reason?: string) => {
    setBusyId(claim.id);
    setMsg(null);
    try {
      await apiFetch(`/certifications/claims/${claim.id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, ...(reason ? { reason } : {}) }),
      });
      setReject(null);
      setConfirmApprove(null);
      onChanged();
    } catch (e) {
      setMsg((e as Error).message);
      setReject(null);
      setConfirmApprove(null);
    } finally {
      setBusyId(null);
    }
  };

  const openEvidence = async (claim: Claim) => {
    // openSafely, not window.open directly: window.open("javascript:...")
    // executes in the opener's origin, so this needs the same scheme
    // allow-list as an href would.
    if (claim.evidenceUrl) {
      if (!openSafely(claim.evidenceUrl)) setMsg("That evidence link is not a valid http(s) URL.");
      return;
    }
    try {
      const { url } = await apiFetch<{ url: string }>(
        `/certifications/claims/${claim.id}/evidence-url`);
      window.open(url, "_blank", "noopener");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  if (comingSoon) return <ComingSoon feature="Verifications" />;
  if (error) return <ErrorState message={error} />;

  return (
    <>
      <div className="card mb-16">
        <div className="flex" style={{ gap: 10 }}>
          <select className="select" style={{ width: "auto" }} data-testid="filter-cert"
                  value={certFilter} onChange={(e) => setCertFilter(e.target.value)}>
            <option value="">All certifications</option>
            {certOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
          {isCL && (
            <select className="select" style={{ width: "auto" }} data-testid="filter-group"
                    value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
              <option value="">All user groups</option>
              {groupOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          )}
        </div>
      </div>
      {msg && (
        <p className="small flex between mb-8" style={{ color: "var(--danger)" }} role="alert">
          <span>{msg}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button>
        </p>
      )}
      <div className="card">
        <DataTable id="cert-verifications" rows={rows}
                   infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                               hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "claims" }}
                   emptyLabel="No pending verifications match the current filters." columns={[
            { key: "member", header: "Member", render: (c: Claim) => (
              <div className="name-cell">
                <Avatar firstName={(c.memberName ?? "?").split(" ")[0]}
                        lastName={(c.memberName ?? "").split(" ").slice(1).join(" ")} size="sm" />
                {c.memberName ?? c.memberId}
              </div>) },
            ...(isCL ? [{ key: "group", header: "User Group",
              render: (c: Claim) => c.creditedGroupName ?? c.creditedGroupId }] : []),
            { key: "cert", header: "Certification", render: (c: Claim) => c.certName ?? c.certId },
            { key: "evidence", header: "Evidence", render: (c: Claim) => (
              c.scanStatus === "PendingScan"
                ? <span className="badge gray" title="The uploaded file has not finished its malware scan.">awaiting scan</span>
                : <a href="#" onClick={(e) => { e.preventDefault(); openEvidence(c); }}
                     data-testid={`evidence-${c.id}`}>
                    {c.evidenceUrl
                      ? `${safeHostname(c.evidenceUrl) ?? "link"} ↗`
                      : `${c.evidenceFileName ?? "file"} ↗`}
                  </a>) },
            { key: "submittedAt", header: "Submitted", sortValue: (c: Claim) => c.submittedAt,
              render: (c: Claim) => fmtDate(c.submittedAt) },
            // Always present under paging (a per-page derived column would
            // appear/disappear between pages); hide via the column settings gear.
            { key: "dateEarned", header: "Earned",
              render: (c: Claim) => c.dateEarned ? fmtDate(c.dateEarned) : "—" },
            { key: "act", header: "Action", render: (c: Claim) => {
              // A UGL's own claim is never in this queue (a Community Leader
              // verifies it), so every row here is one the caller may decide.
              const undecidable = c.scanStatus === "PendingScan";
              return (
                <span className="btn-row">
                  <button className="btn success sm" disabled={undecidable || busyId === c.id}
                          title={undecidable ? "Not decidable until the evidence scan completes." : undefined}
                          data-testid={`approve-${c.id}`}
                          onClick={() => setConfirmApprove(c)}>Approve</button>
                  <button className="btn danger sm" disabled={undecidable || busyId === c.id}
                          data-testid={`reject-${c.id}`}
                          onClick={() => setReject(c)}>Reject</button>
                </span>
              );
            } },
          ]} />
      </div>
      <p className="faint small mt-12">
        Sorted oldest first. {isCL
          ? <>Community Leaders can verify any claim; User Group Leaders verify claims <b>credited to the
              group they lead</b> — the group the member selected at submission, not necessarily a member
              of that group's roster.</>
          : <>On approval the badge is added to the member's profile and points are awarded. Rejection
              requires a reason; the member is notified either way. Your own claims are not shown here —
              a Community Leader verifies them.</>}
      </p>

      {confirmApprove && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 140,
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 440, maxWidth: "92vw" }} role="alertdialog"
               aria-modal="true" data-testid="approve-confirm">
            <div className="card-head"><h3>Approve claim?</h3>
              <button className="icon-btn" aria-label="Close" onClick={() => setConfirmApprove(null)}>✕</button></div>
            <p className="small"><b>{confirmApprove.memberName ?? confirmApprove.memberId}</b> earns the
              <b> {confirmApprove.certName ?? confirmApprove.certId}</b> badge, and points are credited
              to <b>{confirmApprove.creditedGroupName ?? confirmApprove.creditedGroupId}</b>.</p>
            <div className="btn-row mt-12">
              <button className="btn success" disabled={busyId === confirmApprove.id}
                      data-testid="approve-confirm-button"
                      onClick={() => decide(confirmApprove, "approve")}>
                {busyId === confirmApprove.id ? "Approving…" : "Approve"}</button>
              <button className="btn" onClick={() => setConfirmApprove(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {reject && (
        <RejectReasonModal claim={reject} busy={busyId === reject.id}
                           onCancel={() => setReject(null)}
                           onReject={(reason) => decide(reject, "reject", reason)} />
      )}
    </>
  );
}

function RejectReasonModal({ claim, busy, onCancel, onReject }: {
  claim: Claim;
  busy: boolean;
  onCancel: () => void;
  onReject: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    if (!reason.trim()) { setError("A reason is required — the member sees it."); return; }
    onReject(reason.trim());
  };
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 140,
                  display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 460, maxWidth: "92vw" }} role="alertdialog"
           aria-modal="true" data-testid="reject-modal">
        <div className="card-head"><h3>Reject claim</h3>
          <button className="icon-btn" aria-label="Close" onClick={onCancel}>✕</button></div>
        <p className="small">Rejecting <b>{claim.memberName ?? claim.memberId}</b>'s claim for
          <b> {claim.certName ?? claim.certId}</b>. The member is notified with your reason and may
          resubmit with updated evidence.</p>
        <div className="field"><label>Reason</label>
          <textarea className="textarea" data-testid="reject-reason" maxLength={500}
                    placeholder="e.g. evidence unreadable"
                    value={reason} onChange={(e) => { setReason(e.target.value); setError(null); }} />
        </div>
        {error && <p className="small" style={{ color: "var(--danger)" }} role="alert">{error}</p>}
        <div className="btn-row mt-12">
          <button className="btn danger" disabled={busy} data-testid="reject-confirm-button"
                  onClick={submit}>{busy ? "Rejecting…" : "Reject claim"}</button>
          <button className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
