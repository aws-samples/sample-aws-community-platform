import { useState } from "react";
import { apiFetch } from "../lib/apiClient";
import { useApi } from "../lib/useApi";
import { timezoneOptions } from "../lib/timezones";

const ROLES = ["Administrator", "CommunityLeader", "UserGroupLeader", "Member"];

// Dedicated Edit User modal (US-1.5/1.26): role change, role-dependent group
// membership (multi-select for Member, single-select led-group for
// UserGroupLeader, none for Administrator/CommunityLeader per BR-R6), and
// profile fields. Replaces the generic FormModal, which only exposed a raw
// comma-separated Group IDs text field.
export default function EditUserModal(props: {
  user: any;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { user } = props;
  const groupsApi = useApi<{ items: any[] }>("/groups");
  const groups = groupsApi.data?.items ?? [];

  const [role, setRole] = useState<string>(user.role ?? "Member");
  const [groupIds, setGroupIds] = useState<string[]>(user.groupIds ?? []);
  const [city, setCity] = useState<string>(user.city ?? "");
  const [country, setCountry] = useState<string>(user.country ?? "");
  const [professionalRole, setProfessionalRole] = useState<string>(user.professionalRole ?? "");
  const [awsProject, setAwsProject] = useState<boolean>(!!user.awsProject);
  const [timeZone, setTimeZone] = useState<string>(user.timeZone ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const toggleGroup = (id: string) => {
    setGroupIds((cur) => (cur.includes(id) ? cur.filter((g) => g !== id) : [...cur, id]));
  };

  const submit = async () => {
    setSaving(true); setError(null);
    try {
      const body: Record<string, unknown> = {
        role, city, country, professionalRole, awsProject, timeZone,
      };
      // BR-R6: Administrator/CommunityLeader cannot belong to groups; only send
      // groupIds when it's meaningful for the target role.
      if (role === "Member") body.groupIds = groupIds;
      else if (role === "UserGroupLeader") body.groupIds = groupIds.slice(0, 1);
      await apiFetch(`/users/${user.id}`, { method: "PUT", body: JSON.stringify(body) });
      props.onSaved();
      props.onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 560, maxWidth: "92vw", maxHeight: "88vh", overflowY: "auto" }} data-testid="edit-user-modal">
        <div className="card-head"><h3>Edit {user.email}</h3><button className="icon-btn" onClick={props.onClose}>✕</button></div>

        <div className="field">
          <label>Role *</label>
          <select className="select" data-testid="edit-user-role" value={role}
                  onChange={(e) => { setRole(e.target.value); setGroupIds([]); }}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>

        {role === "Member" && (
          <div className="field">
            <label>User groups (select any to join)</label>
            {groupsApi.loading ? <p className="small">Loading groups…</p> : (
              <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 10, maxHeight: 160, overflowY: "auto" }}>
                {groups.length === 0 && <p className="small faint">No groups exist yet.</p>}
                {groups.map((g) => (
                  <label key={g.id} className="small" style={{ display: "block", padding: "3px 0" }}>
                    <input type="checkbox" data-testid={`edit-user-group-${g.id}`}
                           checked={groupIds.includes(g.id)} onChange={() => toggleGroup(g.id)} /> {g.name}
                  </label>
                ))}
              </div>
            )}
          </div>
        )}

        {role === "UserGroupLeader" && (
          <div className="field">
            <label>Group to lead (optional)</label>
            {groupsApi.loading ? <p className="small">Loading groups…</p> : (
              <select className="select" data-testid="edit-user-led-group"
                      value={groupIds[0] ?? ""} onChange={(e) => setGroupIds(e.target.value ? [e.target.value] : [])}>
                <option value="">Not assigned yet — can be picked at group creation</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            )}
            <div className="hint">A User Group Leader may exist without a group; the Community Leader assigns them when creating a group. Leaving this empty never unassigns a currently led group.</div>
          </div>
        )}

        {(role === "Administrator" || role === "CommunityLeader") && (
          <p className="small faint mb-8">{role} cannot belong to user groups (BR-R6).</p>
        )}

        <div className="divider" />
        <p className="small faint mb-8">Profile</p>
        <div className="form-row">
          <div className="field"><label>City</label><input className="input" data-testid="edit-user-city" value={city} onChange={(e) => setCity(e.target.value)} /></div>
          <div className="field"><label>Country</label><input className="input" data-testid="edit-user-country" value={country} onChange={(e) => setCountry(e.target.value)} /></div>
        </div>
        <div className="field"><label>Professional role</label><input className="input" data-testid="edit-user-prof-role" value={professionalRole} onChange={(e) => setProfessionalRole(e.target.value)} /></div>
        <div className="field"><label>Time zone</label>
          <select className="select" data-testid="edit-user-timezone" value={timeZone} onChange={(e) => setTimeZone(e.target.value)}>
            <option value="">Select…</option>
            {timezoneOptions(timeZone).map((tz) => <option key={tz.value} value={tz.value}>{tz.label}</option>)}
          </select>
        </div>
        <label className="small" style={{ display: "block", marginBottom: 8 }}>
          <input type="checkbox" data-testid="edit-user-aws-project" checked={awsProject} onChange={(e) => setAwsProject(e.target.checked)} /> Working on an AWS project
        </label>

        {error && <p className="small" style={{ color: "var(--danger)" }}>{error}</p>}
        <div className="btn-row">
          <button className="btn primary" disabled={saving} data-testid="edit-user-submit" onClick={submit}>{saving ? "Saving…" : "Save"}</button>
          <button className="btn" onClick={props.onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
