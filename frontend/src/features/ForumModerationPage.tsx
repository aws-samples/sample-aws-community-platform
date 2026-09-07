import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import DataTable from "../components/DataTable";
import { Loading, ErrorState } from "../components/States";
import Banner from "../components/Banner";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import type { Role } from "../roles";

export default function ForumModerationPage({ role }: { role: Role }) {
  const [nonce, setNonce] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const { data, loading, error } = useApi<{ items: any[] }>(`/forums/moderation?_=${nonce}`);

  const dismiss = async (reportId: string) => {
    try { await apiFetch(`/forums/moderation/${reportId}/dismiss`, { method: "POST" }); setMsg("Report dismissed."); setNonce((n) => n + 1); }
    catch (e) { setMsg((e as Error).message); }
  };
  const action = (r: any) => setConfirm({
    title: "Delete reported content?",
    body: (
      <><p>⚠️ This permanently deletes the {r.targetType === "post" ? "post and all its replies" : "reply"} and cannot be undone.</p>
      <p>The report will be closed as <b>Actioned</b>.</p></>
    ),
    confirmLabel: "Delete Content",
    cancelLabel: "Cancel",
    onConfirm: async () => {
      await apiFetch(`/forums/moderation/${r.id}/action`, { method: "POST" });
      setMsg("Content deleted."); setNonce((n) => n + 1);
    },
  });

  if (loading) return <Loading />;
  if (error) return <ErrorState message={error} />;

  const reports = data?.items ?? [];

  return (
    <>
      <div className="page-head">
        <h1>Forum Moderation</h1>
        <p>{role === "CommunityLeader" ? "Reported content across all groups." : "Reported content in your group."}</p>
      </div>
      <Banner message={msg} onDismiss={() => setMsg(null)} />

      {reports.length === 0 ? (
        <div className="card"><p className="faint">No reported content. The moderation queue is clear. 🎉</p></div>
      ) : (
        <div className="card pad-0">
          <DataTable id="moderation" rows={reports} columns={[
            { key: "targetId", header: "Reported Content", render: (r) => (
              <Link to={`/forums/post/${r.targetId}`}>{r.targetType === "post" ? "Post" : "Reply"}: {r.targetId.slice(0, 8)}…</Link>
            )},
            { key: "reason", header: "Reason", render: (r) => <span className="badge amber">{r.reason || "No reason given"}</span> },
            { key: "createdAt", header: "Reported", render: (r) => r.createdAt ? timeAgo(r.createdAt) : "—" },
            { key: "status", header: "Status", render: (r) => <span className="badge blue">{r.status}</span> },
            { key: "actions", header: "Action", render: (r) => (
              <span className="btn-row">
                <button className="btn danger sm" data-testid="action-report" onClick={() => action(r)}>Delete Content</button>
                <button className="btn sm" data-testid="dismiss-report" onClick={() => dismiss(r.id)}>Dismiss</button>
              </span>
            )},
          ]} />
        </div>
      )}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
