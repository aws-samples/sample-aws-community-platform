import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../../lib/apiClient";
import { useApi } from "../../lib/useApi";
import PeoplePicker, { type PickedPerson } from "../../components/PeoplePicker";
import { trailingQuarters } from "../../lib/quarters";
import type { Role } from "../../roles";
import MemberLedgerPanel from "./MemberLedgerPanel";
import {
  groupOptionsFor,
  parseSignedDelta,
  quarterTotal,
  sanitizeDeltaInput,
  type GroupRef,
  type LedgerEntry,
} from "./adjustPoints";

// Manual point adjustment (US-6.15) for a Community Leader or User Group Leader.
//
// Replaces a generic six-free-text-box FormModal that required a leader to hand
// type internal m-… and g-… ids, and which never worked at all: FormModal submits
// every field as a string, and the server's require_int rejected `delta` with a
// 400 on every attempt. parseSignedDelta returning a number is the fix (FR-7).
//
// Authorization is NOT enforced here. The scoping below is usability — the server
// remains the control (CL any group, UGL their led group only, BR-A5).
export default function AdjustPointsModal(props: {
  role: Role;
  ledGroupId?: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const isUGL = props.role === "UserGroupLeader";

  const [person, setPerson] = useState<PickedPerson[]>([]);
  const member = person[0];

  const groupsApi = useApi<{ items: GroupRef[] }>("/groups");
  const [groupId, setGroupId] = useState("");

  const quarters = useMemo(() => trailingQuarters(8), []);
  const [quarter, setQuarter] = useState(quarters[0]); // FR-10: current, preselected
  const [deltaText, setDeltaText] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // One ledger read per member/group selection (NFR-1), feeding BOTH the impact
  // preview (FR-11) and the reverse list (FR-13) — DR-2.
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null);
  const [ledgerLoading, setLedgerLoading] = useState(false);
  const [ledgerError, setLedgerError] = useState<string | null>(null);
  const [ledgerNonce, setLedgerNonce] = useState(0);

  // FR-5: the group is never preselected, so a change of member clears it rather
  // than silently carrying the previous member's group forward.
  useEffect(() => { setGroupId(""); }, [member?.id]);

  useEffect(() => {
    if (!member?.id || !groupId) {
      setEntries(null);
      setLedgerError(null);
      return;
    }
    let cancelled = false;
    setLedgerLoading(true);
    setLedgerError(null);
    apiFetch<{ items: LedgerEntry[] }>(
      `/contributions/ledger?memberId=${encodeURIComponent(member.id)}&groupId=${encodeURIComponent(groupId)}`,
    )
      .then((res) => { if (!cancelled) setEntries(res.items ?? []); })
      .catch((e) => {
        // NFR-4: degrade, never block. The preview and reverse list switch off;
        // the adjustment itself stays available.
        if (cancelled) return;
        setEntries(null);
        setLedgerError((e as Error).message);
      })
      .finally(() => { if (!cancelled) setLedgerLoading(false); });
    return () => { cancelled = true; };
  }, [member?.id, groupId, ledgerNonce]);

  const groupOptions = useMemo(
    () => groupOptionsFor({
      memberGroupIds: member?.groupIds ?? [],
      allGroups: groupsApi.data?.items ?? [],
      role: props.role,
      ledGroupId: props.ledGroupId,
    }),
    [member?.groupIds, groupsApi.data, props.role, props.ledGroupId],
  );

  const parsed = parseSignedDelta(deltaText);
  const showDeltaError = deltaText.trim() !== "" && !parsed.ok;
  // FR-6: a member with no adjustable group blocks the save outright.
  const noGroups = !!member && !groupsApi.loading && groupOptions.length === 0;
  const canSave = !!member && !!groupId && parsed.ok && reason.trim().length > 0 && !saving;

  const currentTotal = quarterTotal(entries, groupId, quarter);
  const projectedTotal = currentTotal + (parsed.ok ? parsed.value : 0);
  const previewReady = !!member && !!groupId && !ledgerLoading && !ledgerError && entries !== null;

  const submit = async () => {
    if (!canSave || !parsed.ok || !member) return;
    setSaving(true);
    setError(null);
    try {
      await apiFetch("/contributions/adjustments", {
        method: "POST",
        body: JSON.stringify({
          memberId: member.id,
          memberName: member.name,
          groupId,
          quarter,
          delta: parsed.value, // a NUMBER — see FR-7
          reason: reason.trim(),
        }),
      });
      props.onSaved(`Adjustment recorded for ${member.name}.`);
      props.onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div className="card" style={{ width: 680, maxWidth: "94vw", maxHeight: "90vh", display: "flex", flexDirection: "column" }} data-testid="adjust-modal">
        <div className="card-head" style={{ flexShrink: 0 }}>
          <h3>Manual Point Adjustment</h3>
          <button className="icon-btn" aria-label="Close" onClick={props.onClose}>✕</button>
        </div>

        <div style={{ overflowY: "auto", flex: "1 1 auto", minHeight: 0 }}>
          {/* FR-16: say what an adjustment costs before it is made. */}
          <div className="card mb-12" style={{ background: "var(--info-bg)", borderColor: "var(--border)", padding: 10 }}
               data-testid="adjust-note">
            <span className="small">
              An adjustment is <b>permanent</b> — it is appended to the points ledger and cannot be
              edited or deleted, only offset by another entry. {member?.name ?? "The member"} is
              notified in the portal. A negative adjustment may take a total below zero.
            </span>
          </div>

          {/* FR-1/FR-2: searchable member; a UGL's search is scoped to their group. */}
          <PeoplePicker
            label="Member *"
            testId="adjust-member"
            selected={person}
            onChange={(next) => setPerson(next.slice(-1))} // single-select
            groupId={isUGL ? props.ledGroupId : undefined}
            hint={isUGL
              ? "Search members of the group you lead."
              : "Search any member of the community by name or email."}
          />

          {/* FR-4/FR-5 + DR-1 */}
          <div className="field">
            <label htmlFor="adjust-group">User group *</label>
            <select id="adjust-group" className="select" data-testid="adjust-group"
                    value={groupId} disabled={!member || noGroups}
                    onChange={(e) => setGroupId(e.target.value)}>
              <option value="">
                {!member ? "Select a member first…" : "Select the group to adjust…"}
              </option>
              {groupOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {member && !noGroups && (
              <div className="hint">
                Points, tiers and the leaderboard are tracked per group, so the group decides
                which totals this change moves.
              </div>
            )}
            {noGroups && (
              <div className="hint" data-testid="adjust-no-groups" style={{ color: "var(--danger)" }}>
                {isUGL
                  ? `${member?.name} is not a member of the group you lead, so there is no group whose points you can adjust.`
                  : `${member?.name} is not in any user group, so there is no group to adjust points for.`}
              </div>
            )}
          </div>

          {/* FR-10 */}
          <div className="field">
            <label htmlFor="adjust-quarter">Quarter *</label>
            <select id="adjust-quarter" className="select" data-testid="adjust-quarter"
                    value={quarter} onChange={(e) => setQuarter(e.target.value)}>
              {quarters.map((q, i) => (
                <option key={q} value={q}>{q}{i === 0 ? " (current)" : ""}</option>
              ))}
            </select>
          </div>

          {/* FR-8/FR-9 */}
          <div className="field">
            <label htmlFor="adjust-delta">Point change *</label>
            <input id="adjust-delta" className="input" data-testid="adjust-delta"
                   inputMode="text" autoComplete="off" placeholder="+10 or -5"
                   aria-invalid={showDeltaError} aria-describedby="adjust-delta-hint"
                   value={deltaText}
                   onChange={(e) => setDeltaText(sanitizeDeltaInput(e.target.value))} />
            <div id="adjust-delta-hint" className="hint"
                 style={showDeltaError ? { color: "var(--danger)" } : undefined}
                 data-testid="adjust-delta-hint">
              {showDeltaError && !parsed.ok
                ? parsed.reason
                : "Start with + to add points or - to subtract, e.g. +10 or -5."}
            </div>
          </div>

          <div className="field">
            <label htmlFor="adjust-reason">Reason *</label>
            <textarea id="adjust-reason" className="textarea" data-testid="adjust-reason"
                      maxLength={1000} value={reason}
                      onChange={(e) => setReason(e.target.value)} />
            <div className="hint">Recorded against the entry with your name and the time.</div>
          </div>

          {/* FR-11/FR-12 */}
          {member && groupId && (
            <div className="card mb-12" style={{ padding: 10 }} data-testid="adjust-preview">
              {ledgerLoading && <span className="small faint">Loading current total…</span>}
              {ledgerError && (
                <span className="small faint" data-testid="adjust-preview-unavailable">
                  Current total unavailable — the points history could not be read. You can still
                  record the adjustment.
                </span>
              )}
              {previewReady && (
                <div className="flex between" style={{ alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                  <span className="small">
                    Current total for {quarter}: <b data-testid="adjust-current-total">{currentTotal}</b>
                  </span>
                  {parsed.ok && (
                    <span className="small">
                      After this adjustment: <b data-testid="adjust-projected-total">{projectedTotal}</b>
                      {projectedTotal < 0 && <span className="faint"> · below zero, which is allowed</span>}
                    </span>
                  )}
                </div>
              )}
            </div>
          )}

          {/* FR-13/14/15 */}
          {member && groupId && (
            <div className="mt-12" style={{ borderTop: "1px solid var(--border, #e2e8f0)", paddingTop: 12 }}>
              <MemberLedgerPanel memberId={member.id} memberName={member.name}
                                 entries={entries} loading={ledgerLoading} error={ledgerError}
                                 onReversed={() => {
                                   setLedgerNonce((n) => n + 1);
                                   props.onSaved(`Point history updated for ${member.name}.`);
                                 }} />
            </div>
          )}
        </div>

        {error && <p className="small" style={{ color: "var(--danger)", flexShrink: 0 }} data-testid="adjust-error">{error}</p>}

        <div className="btn-row" style={{ flexShrink: 0, marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border, #e2e8f0)" }}>
          <button className="btn primary" data-testid="adjust-submit" disabled={!canSave} onClick={submit}>
            {saving ? "Saving…" : "Record adjustment"}
          </button>
          <button className="btn" onClick={props.onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
