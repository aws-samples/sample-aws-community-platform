import { useMemo, useState } from "react";
import Toggle from "../components/Toggle";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import type { Role } from "../roles";

// Create/edit an announcement (US-10.1/10.2). CL chooses community-wide or one+
// selected groups; a UGL's audience is a read-only "your group" (the server
// forces the target to their led group, BR-2). Expiry is REQUIRED (default +2
// days, max +90 days — the mandatory-expiry deviation). Body is authored as
// Markdown in a plain textarea and stored verbatim: the server does NOT sanitize
// it (it length-bounds only). Safe rendering happens at the render boundary in
// components/AnnouncementBody.tsx, which renders the Markdown to React elements
// under an explicit allow-list — no HTML string, no innerHTML (NFR-AN-SEC-1/2).
interface Group { id: string; name: string; }

interface Props {
  mode: "create" | "edit";
  role: Role;
  ledGroupId?: string;
  initial?: any;
  onClose: () => void;
  onSaved: () => void;
}

function isoDate(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

export default function AnnouncementModal({ mode, role, initial, onClose, onSaved }: Props) {
  // ledGroupId is accepted (callers pass it) but not needed here — a UGL's target
  // is forced server-side from their led group (BR-2), so the modal omits target.
  const isCL = role === "CommunityLeader";
  const groupsApi = useApi<{ items: Group[] }>("/groups", isCL);

  const [title, setTitle] = useState<string>(initial?.title ?? "");
  const [body, setBody] = useState<string>(initial?.body ?? "");
  const initialScope = initial?.target?.scope ?? "community";
  const [scope, setScope] = useState<"community" | "groups">(isCL ? initialScope : "groups");
  const [groupIds, setGroupIds] = useState<string[]>(initial?.target?.groupIds ?? []);
  const [expiresAt, setExpiresAt] = useState<string>(
    initial?.expiresAt ? String(initial.expiresAt).slice(0, 10) : isoDate(2));
  const [emailOptIn, setEmailOptIn] = useState<boolean>(Boolean(initial?.emailOptIn));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const maxDate = useMemo(() => isoDate(90), []);
  const toggleGroup = (id: string) =>
    setGroupIds((ids) => ids.includes(id) ? ids.filter((g) => g !== id) : [...ids, id]);

  const submit = async () => {
    setBusy(true); setErr(null);
    try {
      const payload: any = { title, body, expiresAt, emailOptIn };
      if (isCL) {
        payload.target = scope === "groups" ? { scope: "groups", groupIds } : { scope: "community" };
      }
      // UGL: omit target — the server forces it to their led group (BR-2).
      const path = mode === "create" ? "/announcements" : `/announcements/${initial.id}`;
      await apiFetch(path, { method: mode === "create" ? "POST" : "PUT", body: JSON.stringify(payload) });
      onSaved();
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)",
      zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center", overflow: "auto", padding: "30px 0" }}>
      <div className="card" style={{ width: 560, maxWidth: "94vw" }}>
        <div className="card-head"><h3>{mode === "create" ? "New" : "Edit"} Announcement</h3>
          <button className="icon-btn" onClick={onClose} data-testid="announcement-modal-close">✕</button></div>

        <div className="field"><label>Title</label>
          <input className="input" data-testid="announcement-title" value={title}
                 onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Q3 planning survey is open" /></div>

        <div className="field"><label>Message (Markdown)</label>
          <textarea className="textarea" data-testid="announcement-body" value={body}
                    onChange={(e) => setBody(e.target.value)}
                    placeholder="Write your announcement… **bold**, _italic_, [links](https://…), - lists" />
          <div className="hint">Supports Markdown: **bold**, _italic_, [links](url), and - lists.</div></div>

        <div className="field"><label>Audience</label>
          {isCL ? (
            <select className="select" data-testid="announcement-audience" value={scope}
                    onChange={(e) => setScope(e.target.value as "community" | "groups")}>
              <option value="community">Community-wide (all members)</option>
              <option value="groups">Selected user group(s)</option>
            </select>
          ) : (
            <input className="input" readOnly value="Your group" data-testid="announcement-audience-readonly" />
          )}
          {!isCL && <div className="hint">User Group Leaders can post only to the group they lead.</div>}
        </div>

        {isCL && scope === "groups" && (
          <div className="field" data-testid="announcement-group-picker">
            <label>Select user groups</label>
            <ul className="clean" style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "0 12px" }}>
              {(groupsApi.data?.items ?? []).map((g) => (
                <li key={g.id} className="flex between" style={{ padding: "6px 0" }}>
                  <span>{g.name}</span>
                  <Toggle checked={groupIds.includes(g.id)} onChange={() => toggleGroup(g.id)}
                          label={g.name} labelHidden testId={`announcement-group-${g.id}`} />
                </li>
              ))}
            </ul>
            <div className="hint">All members of selected groups (including their User Group Leaders) will see it.</div>
          </div>
        )}

        <div className="form-row">
          <div className="field"><label>Expiry date</label>
            <input className="input" type="date" data-testid="announcement-expiry" value={expiresAt}
                   max={maxDate} onChange={(e) => setExpiresAt(e.target.value)} />
            <div className="hint">Required. Auto-removed after this date. Defaults to 2 days; up to 90 days maximum.</div></div>
          <div className="field"><label>Also send as email</label>
            <div className="flex" style={{ gap: 8, alignItems: "center" }}>
              <Toggle checked={emailOptIn} onChange={setEmailOptIn} label="Also send as email"
                      labelHidden testId="announcement-email" />
              <span className="muted small">Off = in-portal panel only</span></div></div>
        </div>

        {err && <div className="banner error" data-testid="announcement-error">{err}</div>}
        <div className="btn-row">
          <button className="btn primary" data-testid="announcement-submit" disabled={busy || !title || !expiresAt}
                  onClick={submit}>{mode === "create" ? "Post Announcement" : "Save Changes"}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
