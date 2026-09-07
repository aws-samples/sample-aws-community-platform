import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { useGroupName } from "../lib/useGroupName";
import type { Role } from "../roles";

export function timeAgo(iso: string): string {
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

// Single shoutout card — shared between Home feed and full page
export function ShoutoutCard({ s, onReact, reacting }: {
  s: any;
  onReact?: (id: string) => void;
  reacting?: string | null;
}) {
  const groupName = useGroupName();

  // Fix: resolve group name from ID — recipientGroupName may be a raw group ID
  // if the backend couldn't resolve it at write time (old records).
  // Group IDs have the pattern: g-<uuid> or similar non-human-readable strings.
  const looksLikeId = !!(s.recipientGroupName && /^[a-z]-[0-9a-f-]{36}$/.test(s.recipientGroupName));
  const displayGroup = looksLikeId
    ? groupName(s.recipientGroupName)
    : (s.recipientGroupName || "");

  const isReacting = reacting === s.id;
  const anyReacting = reacting != null;

  const handleReact = async () => {
    if (!onReact || anyReacting) return;
    onReact(s.id);
  };

  return (
    <div style={{
      padding: "12px 16px",
      background: "var(--surface, #fff)",
      borderRadius: "var(--radius, 6px)",
      border: "1px solid var(--border, #e2e8f0)",
      display: "flex",
      justifyContent: "space-between",
      alignItems: "flex-start",
      gap: 16,
    }}>
      {/* Left: message + footer */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{ margin: "0 0 6px", fontSize: 13, lineHeight: 1.5, fontStyle: "italic" }}>
          "{s.message}"
        </p>
        <div style={{ fontSize: 12, color: "var(--muted, #64748b)" }}>
          <span>→ </span>
          <Link to={`/directory/${s.recipientId}`} style={{ fontWeight: 600, color: "var(--primary, #2563eb)" }}>
            {s.recipientName}
          </Link>
          {displayGroup && <span> · {displayGroup}</span>}
          {s.isLeaderPick && (
            <span style={{ marginLeft: 6, fontSize: 11, background: "#fef3c7", color: "#92400e", padding: "1px 6px", borderRadius: 3, fontWeight: 600 }}>
              ⭐ Leader Pick
            </span>
          )}
          <br />
          <span>by {s.senderName} · {timeAgo(s.createdAt)}</span>
        </div>
      </div>

      {/* Right: react button + count */}
      {onReact && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          <button
            className="btn sm"
            style={{
              fontSize: 16, padding: "4px 10px", lineHeight: 1,
              opacity: anyReacting && !isReacting ? 0.5 : 1,
              cursor: anyReacting ? "not-allowed" : "pointer",
              transition: "opacity .15s",
            }}
            onClick={handleReact}
            disabled={anyReacting}
            aria-label={isReacting ? "Reacting…" : "React"}
            data-testid="shoutout-react"
          >
            {isReacting ? "⏳" : "👏"}
          </button>
          {s.reactionCount > 0 && (
            <span style={{ fontSize: 13, color: "var(--muted, #64748b)", whiteSpace: "nowrap" }}>
              ({s.reactionCount} {s.reactionCount === 1 ? "reaction" : "reactions"})
            </span>
          )}
        </div>
      )}
      {/* Read-only count when no react handler (e.g. other contexts) */}
      {!onReact && s.reactionCount > 0 && (
        <span style={{ fontSize: 12, color: "var(--muted, #64748b)", flexShrink: 0 }}>
          👏 {s.reactionCount}
        </span>
      )}
    </div>
  );
}

// Home page shoutouts section — collapsible, last 7 days max 5, "View all" link
export default function ShoutoutsSection({ role: _role }: { role?: Role }) {
  const [nonce, setNonce] = useState(0);
  const [collapsed, setCollapsed] = useState(false);
  const [reacting, setReacting] = useState<string | null>(null);
  const { data, loading } = useApi<{ items: any[] }>(`/shoutouts/recent?_=${nonce}`);
  const items = data?.items ?? [];

  if (loading || items.length === 0) return null;

  const react = async (id: string) => {
    if (reacting) return;
    setReacting(id);
    try {
      await apiFetch(`/shoutouts/${id}/react`, { method: "POST" });
      setNonce((n) => n + 1);
    } catch { /* silent — reaction toggle */ }
    finally { setReacting(null); }
  };

  return (
    <div className="card mb-16" data-testid="shoutouts-section">
      {/* Collapsible header */}
      <div
        className="flex between"
        style={{ cursor: "pointer", userSelect: "none" }}
        onClick={() => setCollapsed((c) => !c)}
      >
        <h3 style={{ margin: 0, fontSize: 15 }}>
          {collapsed ? "▸" : "▾"} 👏 Shoutouts
          <span style={{ marginLeft: 6, fontSize: 12, fontWeight: 400, color: "var(--muted)" }}>
            {items.length}
          </span>
        </h3>
        <Link
          to="/shoutouts"
          style={{ fontSize: 12 }}
          onClick={(e) => e.stopPropagation()}
        >
          View all →
        </Link>
      </div>

      {!collapsed && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 12 }}>
          {items.map((s) => (
            <ShoutoutCard key={s.id} s={s} onReact={react} reacting={reacting} />
          ))}
        </div>
      )}
    </div>
  );
}

// Give Shoutout modal (US-13.1/13.2/13.11)
export function ShoutoutModal({ recipientId, recipientName, onClose }: {
  recipientId?: string;
  recipientName?: string;
  onClose: () => void;
  // Kept for backward compatibility with existing callers; the modal now shows
  // success/failure inline and stays open, so it is no longer invoked.
  onSent?: () => void;
}) {
  const [searchQ, setSearchQ] = useState("");
  const [selectedId, setSelectedId] = useState(recipientId || "");
  const [selectedName, setSelectedName] = useState(recipientName || "");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set on a successful send. The modal stays open and, per Option A, the form
  // is locked so the user just reads the confirmation and closes manually.
  const [done, setDone] = useState<string | null>(null);

  const search = useApi<{ items: any[] }>(
    searchQ.length >= 2 ? `/members?q=${encodeURIComponent(searchQ)}&limit=8` : "",
    searchQ.length >= 2);

  // Quota is enforced by the backend (single source of truth). We do not compute
  // it client-side — the only quota feedback is the backend error shown after a
  // submit that exceeds the limit (with the correct role-based number).
  const send = async () => {
    if (!selectedId || !message.trim()) return;
    setSending(true); setError(null);
    try {
      await apiFetch("/shoutouts", { method: "POST", body: JSON.stringify({ recipientId: selectedId, message: message.trim() }) });
      setDone(`Shoutout sent to ${selectedName || selectedId}!`);
    } catch (e) { setError((e as Error).message); }
    finally { setSending(false); }
  };

  return (
    <div className="modal-overlay">
      <div className="card modal-card" style={{ width: 480 }} data-testid="shoutout-modal">
        <div className="card-head">
          <h3>👏 Give a Shoutout</h3>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>

        <div className="field">
          <label>To</label>
          {selectedId ? (
            <div className="flex between" style={{ padding: "8px 12px", background: "var(--surface-2)", borderRadius: "var(--radius)", border: "1px solid var(--border)" }}>
              <b style={{ fontSize: 13 }}>{selectedName || selectedId}</b>
              {!recipientId && !done && <button className="icon-btn" style={{ fontSize: 12 }} onClick={() => { setSelectedId(""); setSelectedName(""); }}>✕</button>}
            </div>
          ) : (
            <>
              <input className="input" placeholder="Search members by name…" data-testid="shoutout-search"
                value={searchQ} onChange={(e) => setSearchQ(e.target.value)} autoFocus />
              {search.data && search.data.items.length > 0 && (
                <ul className="clean" style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", maxHeight: 160, overflowY: "auto", marginTop: 4 }}>
                  {search.data.items.filter((m) => m.role === "Member").map((m) => (
                    <li key={m.id}
                      style={{ padding: "6px 12px", cursor: "pointer", fontSize: 13 }}
                      onClick={() => { setSelectedId(m.id); setSelectedName(`${m.firstName ?? ""} ${m.lastName ?? ""}`.trim()); setSearchQ(""); }}>
                      <b>{m.firstName} {m.lastName}</b> <span className="faint">· {m.email}</span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>

        <div className="field">
          <label>Message</label>
          <textarea className="input" rows={3} maxLength={280} data-testid="shoutout-message"
            placeholder="What did they do? Be specific — it means more."
            value={message} onChange={(e) => setMessage(e.target.value)}
            disabled={!!done}
            style={{ resize: "vertical" }} />
          <div className="flex between">
            <span className="faint small">{message.length}/280</span>
          </div>
        </div>

        {done && (
          <div style={{
            background: "var(--success-bg, #dcfce7)", border: "1px solid var(--success, #16a34a)",
            borderRadius: "var(--radius, 6px)", padding: "10px 14px",
            display: "flex", alignItems: "center", gap: 8, fontSize: 13,
          }} role="status" data-testid="shoutout-success">
            <span style={{ fontSize: 16 }}>✅</span>
            <span>{done}</span>
          </div>
        )}

        {error && (
          <div style={{
            background: "var(--warning-bg, #fef3c7)", border: "1px solid #f59e0b",
            borderRadius: "var(--radius, 6px)", padding: "10px 14px",
            display: "flex", alignItems: "center", gap: 8, fontSize: 13,
          }} role="alert" data-testid="shoutout-error">
            <span style={{ fontSize: 16 }}>⚠️</span>
            <span>{error}</span>
          </div>
        )}

        <div className="btn-row mt-12">
          {done ? (
            <button className="btn primary" data-testid="shoutout-close" onClick={onClose}>Close</button>
          ) : (
            <>
              <button
                className="btn primary"
                disabled={sending || !selectedId || !message.trim()}
                data-testid="shoutout-send"
                onClick={send}
              >
                {sending ? "Sending…" : "Send Shoutout 👏"}
              </button>
              <button className="btn" onClick={onClose}>Cancel</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
