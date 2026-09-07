import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import DataTable from "../components/DataTable";
import FormModal from "../components/FormModal";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import Banner from "../components/Banner";
import ToastStack, { useToasts } from "../components/ToastStack";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import type { Role } from "../roles";

// Forums (US-4.x) — role-aware landing pages per mockup:
// - UGL: single group forum, channels table, "+ Create Channel", moderation link
// - Member: card grid of forums from all their groups
// - CL: card grid of all forums, "+ Create Forum" (community-wide), tabs (All/Reported)
export default function ForumsPage({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  if (role === "UserGroupLeader") return <UglForumsView ledGroupId={ledGroupId} />;
  if (role === "CommunityLeader") return <ClForumsView />;
  return <MemberForumsView />;
}

// ─── UGL View ───────────────────────────────────────────────────────────────
// Shows: their group forum + community-wide forums in a card grid,
// with channel management for their own forum. Matches the CL mockup style.
function UglForumsView({ ledGroupId: _ledGroupId }: { ledGroupId?: string }) {
  const [nonce, setNonce] = useState(0);
  const [newChannelForumId, setNewChannelForumId] = useState<string | null>(null);
  const { toasts, success, dismissToast } = useToasts();
  const forums = useApi<{ items: any[] }>(`/forums?_=${nonce}`);
  const moderation = useApi<{ items: any[] }>("/forums/moderation");

  const forumList = forums.data?.items ?? [];
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);

  const removeChannel = (channelId: string, channelName: string) => setConfirm({
    title: `Delete "#${channelName}"?`,
    body: (
      <><p>⚠️ This permanently deletes the channel and cannot be undone.</p>
      <p>All <b>posts and replies</b> in this channel will become permanently inaccessible. There is no way to recover them.</p></>
    ),
    confirmLabel: "Delete Channel",
    cancelLabel: "Keep Channel",
    onConfirm: async () => {
      await apiFetch(`/channels/${channelId}`, { method: "DELETE" });
      success("Channel deleted."); setNonce((n) => n + 1);
    },
  });

  if (forums.loading) return <Loading />;
  if (forums.comingSoon) return <ComingSoon feature="Forums" />;
  if (forums.error) return <ErrorState message={forums.error} />;

  return (
    <>
      <div className="page-head flex between">
        <div><h1>Forums</h1><p>Manage channels and moderate discussions for your group.</p></div>
        <button className="btn primary" data-testid="create-channel" onClick={() => {
          const myForum = forumList.find((f) => f.groupId !== "COMMUNITY");
          if (myForum) setNewChannelForumId(myForum.id);
        }}>＋ Create Channel</button>
      </div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      {forumList.length === 0 ? (
        <div className="card"><p className="faint">No forums yet. A forum is created automatically when your group is set up.</p></div>
      ) : (
        <div className="grid cols-2">
          {forumList.map((forum) => {
            const isMyGroup = forum.groupId !== "COMMUNITY";
            return (
              <div key={forum.id} className="card pad-0">
                <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }} className="flex between">
                  <b>👥 {forum.name}</b>
                  {isMyGroup && (
                    <button className="btn sm" onClick={() => setNewChannelForumId(forum.id)}>＋ Channel</button>
                  )}
                </div>
                <ul className="clean" style={{ padding: "0 18px" }}>
                  {(forum.channels ?? []).map((c: any) => (
                    <li key={c.id} className="flex between" style={{ padding: "6px 0" }}>
                      <Link to={`/forums/channel/${c.id}`}># {c.name}</Link>
                      <span className="faint small">
                        {c.postCount ?? 0} posts · {c.lastActivityAt ? timeAgo(c.lastActivityAt) : "—"}
                        {isMyGroup && <>{" · "}<a href="#" onClick={(e) => { e.preventDefault(); removeChannel(c.id, c.name); }}>delete</a></>}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}

      {/* Moderation summary */}
      {(moderation.data?.items?.length ?? 0) > 0 && (
        <div className="card mt-16">
          <div className="card-head"><h3>Needs Moderation</h3><Link className="small" to="/forum-moderation">Open moderation →</Link></div>
          <p className="faint small">⚠️ {moderation.data!.items.length} item(s) awaiting review.</p>
        </div>
      )}

      {newChannelForumId && (
        <FormModal title="Create Channel" path={`/forums/${newChannelForumId}/channels`}
          onClose={() => setNewChannelForumId(null)}
          onSaved={() => { setNewChannelForumId(null); setNonce((n) => n + 1); }}
          fields={[
            { name: "name", label: "Channel name", required: true },
            { name: "description", label: "Description" },
          ]} />
      )}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

// ─── Member View ────────────────────────────────────────────────────────────
// Shows: card grid of all accessible forums (their groups + community-wide),
// each card lists channels with post count + last activity.
function MemberForumsView() {
  const forums = useApi<{ items: any[] }>("/forums");
  const [searchQ, setSearchQ] = useState("");
  const searchResults = useApi<{ items: any[] }>(`/forums/search?q=${encodeURIComponent(searchQ)}`, searchQ.length >= 2);

  if (forums.loading) return <Loading />;
  if (forums.comingSoon) return <ComingSoon feature="Forums" />;
  if (forums.error) return <ErrorState message={forums.error} />;

  const forumList = forums.data?.items ?? [];

  return (
    <>
      <div className="page-head"><h1>Forums</h1><p>Discussions from your user groups.</p></div>

      {/* Search bar */}
      <div className="card mb-16">
        <div className="flex" style={{ gap: 10 }}>
          <input className="input" placeholder="🔍 Search posts…" data-testid="forum-search-input"
            value={searchQ} onChange={(e) => setSearchQ(e.target.value)} />
          <button className="btn primary">Search</button>
        </div>
      </div>

      {/* Search results */}
      {searchQ.length >= 2 && searchResults.data && (
        <div className="card mb-16">
          <div className="card-head"><h3>Search Results</h3></div>
          {(searchResults.data.items ?? []).length === 0 ? <p className="faint small">No matches.</p> : (
            <ul className="clean">
              {(searchResults.data.items ?? []).map((p) => (
                <li key={p.id} className="flex between" style={{ padding: "8px 0" }}>
                  <div><Link to={`/forums/post/${p.id}`}><b>{p.title}</b></Link><div className="faint small">{p.authorName || p.authorId} · {p.groupId}</div></div>
                  <span className="faint small">💬 {p.replyCount ?? 0}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Forum cards grid */}
      {forumList.length === 0 ? (
        <div className="card"><p className="faint">No forums available. Join a user group to access discussions.</p></div>
      ) : (
        <div className="grid cols-2">
          {forumList.map((forum) => (
            <div key={forum.id} className="card pad-0">
              <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }} className="flex between">
                <b>👥 {forum.name}</b>
                <span className="badge blue">{(forum.channels ?? []).length} channel{(forum.channels ?? []).length !== 1 ? "s" : ""}</span>
              </div>
              <ul className="clean" style={{ padding: "0 18px" }}>
                {(forum.channels ?? []).map((c: any) => (
                  <li key={c.id} className="flex between" style={{ padding: "6px 0" }}>
                    <Link to={`/forums/channel/${c.id}`}># {c.name}</Link>
                    <span className="faint small">{c.postCount ?? 0} posts · {c.lastActivityAt ? timeAgo(c.lastActivityAt) : "—"}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ─── CL View ────────────────────────────────────────────────────────────────
// Shows: all forums across all groups in card grid, "+ Create Forum" (community-wide),
// tabs for All Forums / Reported.
function ClForumsView() {
  const [tab, setTab] = useState<"browse" | "reported">("browse");
  const [nonce, setNonce] = useState(0);
  const [creating, setCreating] = useState(false);
  const [newChannelForumId, setNewChannelForumId] = useState<string | null>(null);
  const { toasts, success, error: toastError, dismissToast } = useToasts();
  const forums = useApi<{ items: any[] }>(`/forums?_=${nonce}`);
  const moderation = useApi<{ items: any[] }>(`/forums/moderation?_=${nonce}`);
  const [searchQ, setSearchQ] = useState("");
  const searchResults = useApi<{ items: any[] }>(`/forums/search?q=${encodeURIComponent(searchQ)}`, searchQ.length >= 2);

  const forumList = forums.data?.items ?? [];
  const reportCount = moderation.data?.items?.length ?? 0;
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);

  const removeChannel = (channelId: string, channelName: string) => setConfirm({
    title: `Delete "#${channelName}"?`,
    body: (
      <><p>⚠️ This permanently deletes the channel and cannot be undone.</p>
      <p>All <b>posts and replies</b> in this channel will become permanently inaccessible. There is no way to recover them.</p></>
    ),
    confirmLabel: "Delete Channel",
    cancelLabel: "Keep Channel",
    onConfirm: async () => {
      await apiFetch(`/channels/${channelId}`, { method: "DELETE" });
      success("Channel deleted."); setNonce((n) => n + 1);
    },
  });

  const dismiss = async (reportId: string) => {
    try { await apiFetch(`/forums/moderation/${reportId}/dismiss`, { method: "POST" }); success("Report dismissed."); setNonce((n) => n + 1); }
    catch (e) { toastError((e as Error).message); }
  };
  const action = (reportId: string, targetType?: string) => setConfirm({
    title: "Delete reported content?",
    body: (
      <><p>⚠️ This permanently deletes the {targetType === "post" ? "post and all its replies" : "reply"} and cannot be undone.</p>
      <p>The report will be closed as <b>Actioned</b>.</p></>
    ),
    confirmLabel: "Delete Content",
    cancelLabel: "Cancel",
    onConfirm: async () => {
      await apiFetch(`/forums/moderation/${reportId}/action`, { method: "POST" });
      success("Content deleted."); setNonce((n) => n + 1);
    },
  });

  if (forums.loading) return <Loading />;
  if (forums.comingSoon) return <ComingSoon feature="Forums" />;
  if (forums.error) return <ErrorState message={forums.error} />;

  return (
    <>
      <div className="page-head flex between">
        <div><h1>Forums</h1><p>Browse and manage forums across all user groups.</p></div>
        <button className="btn primary" data-testid="create-forum" onClick={() => setCreating(true)}>＋ Create Forum</button>
      </div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (tab === "browse" ? " active" : "")} onClick={() => setTab("browse")}>All Forums</div>
        <div className={"tab" + (tab === "reported" ? " active" : "")} onClick={() => setTab("reported")}>
          Reported {reportCount > 0 && <span className="badge red" style={{ marginLeft: 4 }}>{reportCount}</span>}
        </div>
      </div>

      {tab === "browse" && (
        <>
          {/* Search */}
          <div className="card mb-16">
            <div className="flex" style={{ gap: 10 }}>
              <input className="input" placeholder="🔍 Search posts across all groups…" data-testid="forum-search-input"
                value={searchQ} onChange={(e) => setSearchQ(e.target.value)} />
              <button className="btn primary">Search</button>
            </div>
          </div>

          {searchQ.length >= 2 && searchResults.data && (
            <div className="card mb-16">
              <div className="card-head"><h3>Search Results</h3></div>
              {(searchResults.data.items ?? []).length === 0 ? <p className="faint small">No matches.</p> : (
                <ul className="clean">
                  {(searchResults.data.items ?? []).map((p) => (
                    <li key={p.id} style={{ padding: "6px 0" }}>
                      <Link to={`/forums/post/${p.id}`}><b>{p.title}</b></Link>
                      <span className="faint small"> · {p.authorName || p.authorId}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Forum cards */}
          <div className="grid cols-2">
            {forumList.map((forum) => (
              <div key={forum.id} className="card pad-0">
                <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }} className="flex between">
                  <b>👥 {forum.name}</b>
                  <div className="btn-row">
                    <button className="btn sm" onClick={() => setNewChannelForumId(forum.id)}>＋ Channel</button>
                  </div>
                </div>
                <ul className="clean" style={{ padding: "0 18px" }}>
                  {(forum.channels ?? []).map((c: any) => (
                    <li key={c.id} className="flex between" style={{ padding: "6px 0" }}>
                      <Link to={`/forums/channel/${c.id}`}># {c.name}</Link>
                      <span className="faint small">{c.postCount ?? 0} posts · {c.lastActivityAt ? timeAgo(c.lastActivityAt) : "—"}
                        {" · "}<a href="#" onClick={(e) => { e.preventDefault(); removeChannel(c.id, c.name); }}>delete</a>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </>
      )}

      {tab === "reported" && (
        <div className="card pad-0">
          <DataTable id="reports" rows={moderation.data?.items ?? []} columns={[
            { key: "targetId", header: "Reported Content", render: (r) => <Link to={`/forums/post/${r.targetId}`}>{r.targetType}: {r.targetId.slice(0, 12)}…</Link> },
            { key: "groupId", header: "Group", render: (r) => r.groupId },
            { key: "reporterId", header: "Reporter", render: (r) => r.reporterId },
            { key: "reason", header: "Reason", render: (r) => <span className="badge amber">{r.reason || "—"}</span> },
            { key: "act", header: "Action", render: (r) => (
              <span className="btn-row">
                <button className="btn danger sm" data-testid="action-report" onClick={() => action(r.id, r.targetType)}>Delete</button>
                <button className="btn sm" data-testid="dismiss-report" onClick={() => dismiss(r.id)}>Dismiss</button>
              </span>
            )},
          ]} />
        </div>
      )}

      {creating && <ClCreateForumModal onClose={() => setCreating(false)} onCreated={() => { setCreating(false); setNonce((n) => n + 1); }} />}
      {newChannelForumId && (
        <FormModal title="Create Channel" path={`/forums/${newChannelForumId}/channels`}
          onClose={() => setNewChannelForumId(null)}
          onSaved={() => { setNewChannelForumId(null); setNonce((n) => n + 1); }}
          fields={[
            { name: "name", label: "Channel name", required: true },
            { name: "description", label: "Description" },
          ]} />
      )}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

// CL Create Forum modal — community-wide forum (not specific to any UG)
function ClCreateForumModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  // Fetch groups for the dropdown
  const groups = useApi<{ items: any[] }>("/groups");

  const [groupId, setGroupId] = useState("community");

  const handleSave = async () => {
    if (!name.trim()) return;
    try {
      await apiFetch("/forums", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), groupId: groupId === "community" ? "COMMUNITY" : groupId, description }),
      });
      onCreated();
    } catch (e) { setMsg((e as Error).message); }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head"><h2>Create Forum</h2><button className="close" onClick={onClose}>×</button></div>
        <div className="modal-body">
          {msg && <Banner message={msg} onDismiss={() => setMsg(null)} />}
          <div className="field">
            <label>Forum name *</label>
            <input className="input" data-testid="forum-name-input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="field">
            <label>Description</label>
            <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="field">
            <label>Target user group</label>
            <select className="select" data-testid="forum-group-select" value={groupId} onChange={(e) => setGroupId(e.target.value)}>
              <option value="community">Community-wide (all members)</option>
              {(groups.data?.items ?? []).map((g: any) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </div>
          <p className="faint small">A default "General" channel is created automatically.</p>
        </div>
        <div className="modal-foot">
          <button className="btn primary" data-testid="forum-save" onClick={handleSave} disabled={!name.trim()}>Create Forum</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
