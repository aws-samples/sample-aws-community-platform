import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import FormModal from "../components/FormModal";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import ToastStack, { useToasts } from "../components/ToastStack";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import type { Role } from "../roles";

// Forum thread (US-4.5..4.11) — post + threaded replies, reactions, accepted
// answer, pin/follow, report, and @mention suggestions on reply.
export default function ForumThreadPage({ role }: { role: Role }) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [nonce, setNonce] = useState(0);
  const [reply, setReply] = useState("");
  const { toasts, success, error: toastError, dismissToast } = useToasts();
  const [mentions, setMentions] = useState<any[]>([]);
  const [editPost, setEditPost] = useState(false);
  const [reacting, setReacting] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const isLeader = role === "CommunityLeader" || role === "UserGroupLeader";

  const thread = useApi<any>(`/posts/${id}?_=${nonce}`);
  const replies = thread.data?.replies?.items ?? [];

  const act = async (path: string, body?: unknown) => {
    try { await apiFetch(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }); success("Action completed successfully."); setNonce((n) => n + 1); }
    catch (e) { toastError((e as Error).message); }
  };
  const react = async () => {
    setReacting(true);
    try {
      await apiFetch(`/posts/${id}/reactions`, { method: "POST", body: JSON.stringify({ kind: "upvote" }) });
      success("Reaction added.");
      setNonce((n) => n + 1);
    } catch (e) { toastError((e as Error).message); }
    finally { setReacting(false); }
  };
  const sendReply = async () => {
    if (!reply.trim()) return;
    await act(`/posts/${id}/replies`, { body: reply }); setReply(""); setMentions([]);
  };
  const del = async (path: string) => {
    try { await apiFetch(path, { method: "DELETE" }); success("Content deleted."); setNonce((n) => n + 1); } catch (e) { toastError((e as Error).message); }
  };
  const confirmDelete = (path: string, isPost: boolean) => setConfirm({
    title: isPost ? "Delete this post?" : "Delete this reply?",
    body: isPost
      ? (<><p>⚠️ This permanently removes the post from the channel. All replies will also become inaccessible.</p><p>The post author will not be notified. This cannot be undone.</p></>)
      : (<><p>⚠️ This permanently removes the reply. This cannot be undone.</p></>),
    confirmLabel: isPost ? "Delete Post" : "Delete Reply",
    cancelLabel: isPost ? "Keep Post" : "Keep Reply",
    onConfirm: () => del(path),
  });
  const onReplyChange = async (v: string) => {
    setReply(v);
    const m = v.match(/@(\w+)$/);
    if (m) { try { const r = await apiFetch<{ items: any[] }>(`/forums/mention-suggest?q=${m[1]}`); setMentions(r.items ?? []); } catch { setMentions([]); } }
    else setMentions([]);
  };

  if (thread.loading) return <Loading />;
  if (thread.comingSoon) return <ComingSoon feature="Forum thread" />;
  if (thread.error) return <ErrorState message={thread.error} />;
  const p = thread.data?.post ?? {};

  return (
    <>
      <div className="page-head">
        <a className="small" href="#" onClick={(e) => { e.preventDefault(); navigate(-1); }}>← Back to forums</a>
        <h1>{p.pinned ? "📌 " : ""}{p.title}</h1>
        <p className="faint small">by {p.authorName || p.authorId}{p.acceptedReplyId ? " · ✅ answered" : ""}</p>
      </div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      <div className="card mb-16">
        {editPost ? (
          <FormModal title="Edit Post" path={`/posts/${id}`} method="PUT" initial={{ title: p.title, body: p.body }}
            onClose={() => setEditPost(false)} onSaved={() => { setEditPost(false); setNonce((n) => n + 1); }}
            fields={[{ name: "title", label: "Title", required: true }, { name: "body", label: "Body", type: "textarea", required: true }]} />
        ) : <p style={{ whiteSpace: "pre-wrap" }}>{p.body}</p>}
        {/* Reaction counts display */}
        {p.reactionCounts && Object.keys(p.reactionCounts).length > 0 && (
          <div className="flex" style={{ gap: 8, marginBottom: 12 }}>
            {Object.entries(p.reactionCounts).map(([kind, count]) => {
              const icons: Record<string, string> = { upvote: "👍", like: "❤️", heart: "💖", celebrate: "🎉", insightful: "💡" };
              return count ? <span key={kind} className="badge" style={{ fontSize: 13 }}>{icons[kind] || kind} {String(count)}</span> : null;
            })}
          </div>
        )}
        <div className="btn-row">
          {p.canReact !== false && (
            <button className="btn sm" data-testid="react" disabled={reacting} onClick={react}>
              {reacting ? "⏳ Reacting…" : "👍 React"}
            </button>
          )}
          {/* BR-5, decided server-side (authz.can_edit / can_delete) and read off
              the payload. These two used to render unconditionally, so every
              member saw Edit and Delete on everyone's posts and only found out
              on click, via a 403. Do NOT re-derive this from authorId here — one
              rule, evaluated in one place. */}
          {p.canEdit && (
            <button className="btn sm" data-testid="edit-post" onClick={() => setEditPost(true)}>✏️ Edit</button>
          )}
          {p.canDelete && (
            <button className="btn sm danger" data-testid="delete-post" onClick={() => confirmDelete(`/posts/${id}`, true)}>🗑 Delete</button>
          )}
          {isLeader && <button className="btn sm" data-testid="pin" onClick={() => act(`/posts/${id}/pin`)}>📌 Pin</button>}
        </div>
      </div>

      <h3>Replies {p.replyCount ? `(${p.replyCount})` : ""}</h3>
      <div className="mb-16">
        {replies.map((r: any) => (
          <div key={r.id} className="card mb-8" style={r.accepted ? { borderColor: "var(--success)" } : undefined}>
            <div className="flex between">
              <div><b>{r.authorName || r.authorId}</b> {r.accepted && <span className="badge green">Accepted answer</span>}</div>
              <span className="btn-row">
                {!r.accepted && p.canAccept && <button className="btn sm" data-testid="accept" onClick={() => act(`/posts/${id}/accept`, { replyId: r.id })}>Accept</button>}
                {r.accepted && p.canAccept && <button className="btn sm" data-testid="unaccept" onClick={() => act(`/posts/${id}/accept`, { replyId: null })}>Unaccept</button>}
                {/* The REPLY's own flag, not the post's. The post author gets
                    Accept on every reply but Delete only on their own. */}
                {r.canDelete && (
                  <button className="btn sm danger" data-testid="delete-reply"
                          onClick={() => confirmDelete(`/replies/${r.id}?postId=${id}`, false)}>Delete</button>
                )}
              </span>
            </div>
            <p className="mb-0">{r.body}</p>
          </div>
        ))}
        {replies.length === 0 && <p className="faint small">No replies yet.</p>}
      </div>

      <div className="card">
        <div className="card-head"><h3>Add a reply</h3></div>
        <textarea className="textarea" placeholder="Write a reply… use @name to mention" data-testid="reply-input"
                  value={reply} onChange={(e) => onReplyChange(e.target.value)} />
        {mentions.length > 0 && (
          <div className="card" style={{ padding: 8 }} data-testid="mention-suggest">
            {mentions.slice(0, 5).map((u) => (
              <button key={u.id} className="btn sm" style={{ margin: 2 }}
                onClick={() => { setReply(reply.replace(/@\w+$/, `@${u.firstName} `)); setMentions([]); }}>
                {u.firstName} {u.lastName}
              </button>
            ))}
          </div>
        )}
        <div className="btn-row mt-12"><button className="btn primary" data-testid="send-reply" onClick={sendReply}>Post reply</button></div>
      </div>
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}
