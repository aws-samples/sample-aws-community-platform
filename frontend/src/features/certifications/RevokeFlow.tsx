import { useState } from "react";
import { apiFetch } from "../../lib/apiClient";
import PeoplePicker, { type PickedPerson } from "../../components/PeoplePicker";
import type { Role } from "../../roles";
import { certStatusLabel } from "../../lib/certStatus";
import { BadgeTile, fmtDate, type Claim } from "./types";

// Revoke a Certification (US-5.8, D9 claim-addressed) — member-search + pick
// which of their earned certifications to revoke + reason. Points already
// awarded are retained.
//
// CL: revokes any member's certification (global member search).
// UGL (change request 2026-08-07): revokes only certifications credited to the
// group they lead — the member search is scoped to that group's roster
// (GET /members?groupId=) and holdings are filtered to the led group. The
// backend is the real guarantee (404 outside the led group, 403 on self).
export default function RevokeFlow({ role, ledGroupId, onRevoked }: {
  role?: Role;
  ledGroupId?: string;
  onRevoked: () => void;
}) {
  const isUGL = role === "UserGroupLeader";
  const [person, setPerson] = useState<PickedPerson[]>([]);
  const [holdings, setHoldings] = useState<Claim[] | null>(null);
  const [loadingHoldings, setLoadingHoldings] = useState(false);
  const [target, setTarget] = useState<Claim | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const pick = async (next: PickedPerson[]) => {
    const chosen = next.slice(-1); // single-select behavior on a multi picker
    setPerson(chosen);
    setHoldings(null);
    setTarget(null);
    setMsg(null);
    if (chosen.length === 0) return;
    setLoadingHoldings(true);
    try {
      const res = await apiFetch<{ items: Claim[] }>(
        `/certifications/claims?memberId=${encodeURIComponent(chosen[0].id)}&status=Approved`);
      // A UGL revokes only certs credited to the group they lead — filter the
      // holdings to that group (the backend also 404s a cross-group revoke).
      const items = res.items ?? [];
      setHoldings(isUGL && ledGroupId
        ? items.filter((c) => c.creditedGroupId === ledGroupId)
        : items);
    } catch (e) {
      setMsg({ kind: "err", text: (e as Error).message });
    } finally {
      setLoadingHoldings(false);
    }
  };

  const revoke = async () => {
    if (!target) return;
    if (!reason.trim()) { setMsg({ kind: "err", text: "A reason for revocation is required." }); return; }
    setBusy(true);
    setMsg(null);
    try {
      await apiFetch(`/certifications/claims/${target.id}/revoke`, {
        method: "POST", body: JSON.stringify({ reason: reason.trim() }),
      });
      setMsg({ kind: "ok", text: `Revoked ${target.certName ?? target.certId} from ${person[0]?.name}. The member has been notified; points are retained.` });
      setTarget(null);
      setReason("");
      setHoldings((h) => (h ?? []).filter((c) => c.id !== target.id));
      onRevoked();
    } catch (e) {
      setMsg({ kind: "err", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" data-testid="revoke-flow">
      <h3>Revoke a Certification</h3>
      <p className="muted small">Removing an invalid certification requires a reason. Points already
        awarded are retained; the member is notified with your reason and may resubmit later.
        {isUGL && " You can revoke certifications credited to the group you lead."}</p>

      <PeoplePicker label="Member" testId="revoke-member" selected={person} onChange={pick}
                    groupId={isUGL ? ledGroupId : undefined}
                    hint={isUGL
                      ? "Search members of the group you lead."
                      : "Search the member whose certification should be revoked."} />

      {loadingHoldings && <p className="faint small">Loading earned certifications…</p>}
      {holdings !== null && !loadingHoldings && (
        holdings.length === 0
          ? <p className="faint small" data-testid="revoke-no-holdings">
              {person[0]?.name} holds no verified certifications{isUGL ? " credited to your group" : ""}.</p>
          : (
            <div className="field"><label>Certification to revoke</label>
              <div className="flex" style={{ gap: 8, flexWrap: "wrap" }}>
                {holdings.map((c) => (
                  <button key={c.id} type="button"
                          className={"btn sm" + (target?.id === c.id ? " primary" : "")}
                          data-testid={`revoke-pick-${c.id}`}
                          onClick={() => setTarget(c)}>
                    <span className="flex" style={{ gap: 6, alignItems: "center" }}>
                      <BadgeTile def={{ category: c.certCategory as never,
                                        badgeImageUrl: c.badgeImageUrl, name: c.certName }} size={20} />
                      {c.certName ?? c.certId}
                      <span className="faint small">· {certStatusLabel(c.status)} {fmtDate(c.dateEarned ?? c.decidedAt)}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )
      )}

      {target && (
        <div className="flex" style={{ gap: 10 }}>
          <input className="input" data-testid="revoke-reason" placeholder="Reason for revocation"
                 maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className="btn danger" disabled={busy} data-testid="revoke-confirm"
                  onClick={revoke}>{busy ? "Revoking…" : "Revoke"}</button>
        </div>
      )}

      {msg && (
        <p className="small flex between mt-8 mb-0" role={msg.kind === "err" ? "alert" : undefined}
           style={{ color: msg.kind === "err" ? "var(--danger)" : "var(--success)" }}>
          <span>{msg.text}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button>
        </p>
      )}
    </div>
  );
}
