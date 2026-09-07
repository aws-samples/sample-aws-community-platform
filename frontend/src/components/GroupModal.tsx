import { useEffect, useState } from "react";
import { apiFetch } from "../lib/apiClient";
import { useApi } from "../lib/useApi";
import { useDebounced } from "../lib/useDebounced";
import {
  CANDIDATE_LIMIT,
  type LeaderCandidate,
  assembleCandidates,
  buildLeaderQuery,
} from "./leaderPicker";

// Create/Edit User Group modal (US-1.9 create, US-1.18 edit — field parity
// requested 2026-08-03: the Edit window must offer everything Create does,
// including changing/adding User Group Leaders).
//
// Create mode (no `group` prop): POST /groups. The create API promotes the
// selected members to UserGroupLeader atomically, so no pre-existing UGL is
// needed (resolves the group↔leader chicken-and-egg).
// Edit mode (`group` prop): PUT /groups/{id} with the same GroupInput shape;
// current leaders are pre-checked and can be swapped, added, or removed —
// the group must retain at least one leader (server re-validates, US-1.18).
//
// Mirrors the leader user-groups mockup: name, description,
// leader picker (search members), approval-required toggle.
export default function GroupModal(props: {
  onClose: () => void;
  onSaved: () => void;
  group?: {
    id: string; name: string; description?: string; approvalRequired?: boolean;
    leaderIds?: string[];
    // Resolved display list from GET /groups and GET /groups/{id} ({id, firstName,
    // lastName}). Used to keep this group's current leaders visible and checked
    // even when the server-side search does not return them — see `pinned` below.
    leaders?: { id: string; firstName?: string; lastName?: string; email?: string }[];
  };
}) {
  const editing = props.group ?? null;
  // Only the groups list is fetched up front, and only to work out which UGLs
  // already lead something (see `assignedElsewhere`). Candidates themselves are
  // searched server-side; see the effect below.
  const groupsApi = useApi<{ items: any[] }>("/groups");
  const [name, setName] = useState(editing?.name ?? "");
  const [description, setDescription] = useState(editing?.description ?? "");
  const [approvalRequired, setApprovalRequired] = useState(editing?.approvalRequired ?? false);
  const [leaderIds, setLeaderIds] = useState<string[]>(editing?.leaderIds ?? []);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // ---- Candidate search: server-side, role-filtered, OpenSearch-backed ----
  //
  // Previously this fetched GET /members with NO parameters and filtered by role
  // in the browser. That request takes the unpaged branch of DirectoryService.browse,
  // which full-scans every profile in the table; at 25k members it returned
  // HTTP 502 after ~28 s (measured 2026-08-26), so the picker sat on
  // "Loading members…" forever and a Community Leader could never assign a leader.
  //
  // Passing `limit` switches that endpoint to its OpenSearch path, where `role`
  // and `q` are applied by the index instead of the client. So we now ask for
  // exactly what the control needs — User Group Leaders — rather than the whole
  // directory. GET /members is also the right endpoint for this caller: it is open
  // to any authenticated principal, whereas GET /users?role=… is Administrator-only
  // (`list`/`admin-member-list`), so a CL is refused there.
  const [hits, setHits] = useState<LeaderCandidate[]>([]);
  const [searching, setSearching] = useState(true);
  const [searchError, setSearchError] = useState<string | null>(null);
  const debouncedSearch = useDebounced(search, 300);

  useEffect(() => {
    let cancelled = false;
    setSearching(true);
    apiFetch<{ items: LeaderCandidate[] }>(buildLeaderQuery(debouncedSearch))
      .then((res) => {
        if (cancelled) return;
        setHits(res.items ?? []);
        setSearchError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setHits([]);
        // Surfaced rather than swallowed: the old code had no error path at all,
        // which is why a failing request was indistinguishable from "still loading".
        setSearchError((e as Error).message);
      })
      .finally(() => { if (!cancelled) setSearching(false); });

    // Guards against out-of-order responses: a slow early query must not
    // overwrite the results of a later, narrower one.
    return () => { cancelled = true; };
  }, [debouncedSearch]);

  // Eligible leaders (requirement change 2026-08-03): UNASSIGNED UserGroupLeaders
  // — the Admin promotes users to UGL first (no group needed), then the group is
  // assigned here. A person can lead only one group (BR-G7), so UGLs already
  // leading (present in any OTHER group's leaderIds) are excluded. In edit mode
  // this group's own current leaders are always listed (pre-checked) so they can
  // be kept or removed. Server re-validates regardless.
  // Eligibility rules live in assembleCandidates (see that module): UGLs leading
  // another group are excluded, and this group's own leaders are pinned first so a
  // search can never hide a leader the form is about to save.
  const currentLeaders = new Set(editing?.leaderIds ?? []);
  const shown = assembleCandidates({
    hits,
    groupLeaders: editing?.leaders,
    currentLeaderIds: editing?.leaderIds,
    allGroups: groupsApi.data?.items ?? [],
    editingGroupId: editing?.id,
  });

  const toggleLeader = (id: string) =>
    setLeaderIds((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));

  const submit = async () => {
    setSaving(true); setError(null);
    try {
      await apiFetch(editing ? `/groups/${editing.id}` : "/groups", {
        method: editing ? "PUT" : "POST",
        body: JSON.stringify({ name, description, approvalRequired, leaderIds }),
      });
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
      <div className="card" style={{ width: 560, maxWidth: "92vw", maxHeight: "88vh", overflowY: "auto" }} data-testid={editing ? "edit-group-modal" : "create-group-modal"}>
        <div className="card-head"><h3>{editing ? "Edit User Group" : "Create User Group"}</h3><button className="icon-btn" onClick={props.onClose}>✕</button></div>

        <div className="field"><label>Group name *</label>
          <input className="input" placeholder="e.g. Security Guild" data-testid="group-name"
                 value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field"><label>Description</label>
          <textarea className="textarea" data-testid="group-description"
                    value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>

        <div className="field">
          <label>{editing ? "User Group Leader(s) — at least one *" : "Assign at least one User Group Leader *"}</label>
          <input className="input" placeholder="Search User Group Leaders by name or email…"
                 data-testid="leader-search"
                 value={search} onChange={(e) => setSearch(e.target.value)} />
          <div className="hint">
            {editing
              ? "Current leaders are pre-selected — uncheck to remove, check to add or replace. A group must keep at least one leader; a person can lead only one group. Showing this group's leaders plus User Group Leaders not leading a group yet."
              : "A group can't be created without a leader. The creator is not auto-assigned. A person can lead only one group. Showing User Group Leaders who don't lead a group yet — promote users to that role first via Admin → Users."}
          </div>
          {searchError && (
            <p className="small" style={{ color: "var(--danger)" }} data-testid="leader-search-error">
              Could not load User Group Leaders: {searchError}
            </p>
          )}
          {/* The list stays mounted while a new search is in flight — replacing it
              with a spinner on every keystroke makes the control flicker and loses
              the user's place. Only the very first load has nothing to show. */}
          {searching && shown.length === 0 && !searchError
            ? <p className="small" data-testid="leader-loading">Searching User Group Leaders…</p> : (
            <div style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 10, maxHeight: 160, overflowY: "auto", marginTop: 8, opacity: searching ? 0.6 : 1 }}>
              {shown.length === 0 && <p className="small faint">No eligible users{search ? " match your search" : ""}. Only User Group Leaders not already leading a group can be assigned — ask an Administrator to promote a user to User Group Leader first.</p>}
              {shown.length === CANDIDATE_LIMIT && (
                <p className="small faint">Showing the first {CANDIDATE_LIMIT} — type to narrow the search.</p>
              )}
              {shown.map((m) => (
                <label key={m.id} className="small" style={{ display: "block", padding: "3px 0" }}>
                  <input type="checkbox" data-testid={`group-leader-${m.id}`}
                         checked={leaderIds.includes(m.id)} onChange={() => toggleLeader(m.id)} /> {m.firstName} {m.lastName} <span className="faint">({m.email})</span>
                  {currentLeaders.has(m.id) && <span className="badge blue" style={{ marginLeft: 6 }}>current leader</span>}
                </label>
              ))}
            </div>
          )}
        </div>

        <label className="small" style={{ display: "block", marginBottom: 12 }}>
          <input type="checkbox" data-testid="group-approval-required"
                 checked={approvalRequired} onChange={(e) => setApprovalRequired(e.target.checked)} /> Approval required to join
          <span className="faint"> — off: members join instantly; on: join requests need leader approval{editing ? ". Changing this is not retroactive — existing members stay" : ""}.</span>
        </label>

        {error && <p className="small" style={{ color: "var(--danger)" }}>{error}</p>}
        <div className="btn-row">
          <button className="btn primary" data-testid="group-submit"
                  disabled={saving || !name.trim() || leaderIds.length === 0} onClick={submit}>
            {saving ? (editing ? "Saving…" : "Creating…") : (editing ? "Save changes" : "Create group")}
          </button>
          <button className="btn" onClick={props.onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
