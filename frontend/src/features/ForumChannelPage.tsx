import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { apiFetch } from "../lib/apiClient";
import FormModal from "../components/FormModal";
import { Loading } from "../components/States";
import Banner from "../components/Banner";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import type { Role } from "../roles";

export default function ForumChannelPage({ role }: { role: Role }) {
  const { id = "" } = useParams();
  const [nonce, setNonce] = useState(0);
  const [sort, setSort] = useState("newest");
  const [newPost, setNewPost] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [posts, setPosts] = useState<any[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  // Channel search. The input used to be a decorative placeholder with no state
  // and no request behind it, so typing filtered nothing and the unfiltered
  // listing stayed on screen — indistinguishable from "search returned
  // everything". It now queries the real endpoint, scoped to this channel.
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<any[] | null>(null);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const isLeader = role === "CommunityLeader" || role === "UserGroupLeader";
  const trimmedQ = searchQ.trim();
  const searchActive = trimmedQ.length >= 2;

  // Initial load + reload on sort/nonce change
  useEffect(() => {
    setLoading(true);
    setPosts([]);
    setCursor(null);
    apiFetch<any>(`/channels/${id}/posts?sort=${sort}&limit=20&_=${nonce}`)
      .then((data) => {
        setPosts(data.items ?? []);
        setCursor(data.cursor ?? null);
        setLoading(false);
      })
      .catch((e) => { setMsg((e as Error).message); setLoading(false); });
  }, [id, sort, nonce]);

  // Channel-scoped search, debounced so a query is not fired per keystroke.
  useEffect(() => {
    if (!searchActive) {
      setSearchResults(null);
      setSearchTotal(0);
      setSearching(false);
      setSearchError(null);
      return;
    }
    setSearching(true);
    setSearchError(null);
    let cancelled = false;
    const timer = setTimeout(() => {
      apiFetch<any>(`/forums/search?q=${encodeURIComponent(trimmedQ)}`
                    + `&channelId=${encodeURIComponent(id)}&limit=50`)
        .then((data) => {
          if (cancelled) return;
          setSearchResults(data.items ?? []);
          setSearchTotal(data.total ?? (data.items ?? []).length);
          setSearching(false);
        })
        .catch((e) => {
          if (cancelled) return;
          setSearchError((e as Error).message);
          setSearchResults([]);
          setSearching(false);
        });
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [id, trimmedQ, searchActive]);

  // Infinite scroll: load more when user scrolls near bottom.
  // Suspended while a search is showing — otherwise scrolling the (short)
  // result list would append unrelated posts underneath the matches.
  useEffect(() => {
    const handleScroll = () => {
      if (loadingMore || !cursor || searchActive) return;
      const nearBottom = window.innerHeight + window.scrollY >= document.body.offsetHeight - 300;
      if (nearBottom) {
        setLoadingMore(true);
        apiFetch<any>(`/channels/${id}/posts?sort=${sort}&limit=20&cursor=${cursor}`)
          .then((data) => {
            setPosts((prev) => [...prev, ...(data.items ?? [])]);
            setCursor(data.cursor ?? null);
            setLoadingMore(false);
          })
          .catch(() => setLoadingMore(false));
      }
    };
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, [id, sort, cursor, loadingMore, searchActive]);

  // While searching, the list IS the result set: pinning a post to the top of
  // search results would misrepresent relevance, so pinning only applies to the
  // normal listing.
  const shown = searchActive ? (searchResults ?? []) : posts;
  const pinned = searchActive ? [] : shown.filter((p: any) => p.pinned);
  const regular = searchActive ? shown : shown.filter((p: any) => !p.pinned);

  const togglePin = async (postId: string) => {
    try { await apiFetch(`/posts/${postId}/pin`, { method: "POST" }); setNonce((n) => n + 1); }
    catch (e) { setMsg((e as Error).message); }
  };
  const deletePost = (postId: string, _postTitle: string) => setConfirm({
    title: "Delete this post?",
    body: (
      <><p>⚠️ This permanently removes the post from the channel. All replies will also become inaccessible.</p>
      <p>The post author will not be notified. This cannot be undone.</p></>
    ),
    confirmLabel: "Delete Post",
    cancelLabel: "Keep Post",
    onConfirm: async () => {
      await apiFetch(`/posts/${postId}`, { method: "DELETE" });
      setMsg("Post deleted."); setNonce((n) => n + 1);
    },
  });
  const followChannel = async () => {
    try { await apiFetch(`/channels/${id}/follow`, { method: "POST" }); setMsg("Channel follow toggled."); }
    catch (e) { setMsg((e as Error).message); }
  };

  if (loading) return <Loading />;

  return (
    <>
      <div className="breadcrumb"><Link to="/forums">Forums</Link> › <b>Channel</b></div>
      <div className="page-head flex between">
        <div>
          <h1># Channel</h1>
          <p>{posts.length} post{posts.length !== 1 ? "s" : ""}</p>
        </div>
        <div className="btn-row">
          <button className="btn" data-testid="follow-channel" onClick={followChannel}>🔔 Follow channel</button>
          <button className="btn primary" data-testid="new-post" onClick={() => setNewPost(true)}>＋ New Post</button>
        </div>
      </div>
      <Banner message={msg} onDismiss={() => setMsg(null)} />

      {/* Search + Sort */}
      <div className="card mb-16">
        <div className="flex" style={{ gap: 10 }}>
          <input className="input" placeholder="🔍 Search this channel…" data-testid="channel-search"
            value={searchQ} onChange={(e) => setSearchQ(e.target.value)}
            aria-label="Search this channel" />
          {searchQ && (
            <button className="btn" data-testid="channel-search-clear"
              onClick={() => setSearchQ("")} aria-label="Clear search">Clear</button>
          )}
          {/* Sort applies to the channel listing, not to search results, which
              come back newest-first from the server. */}
          <select className="select" style={{ width: "auto" }} value={sort} disabled={searchActive}
            onChange={(e) => { setSort(e.target.value); setNonce((n) => n + 1); }} data-testid="channel-sort">
            <option value="newest">Sort: Newest</option>
            <option value="active">Sort: Most active</option>
            <option value="reactions">Sort: Most reactions</option>
            <option value="unanswered">Sort: Unanswered</option>
          </select>
        </div>
        {searchQ.trim().length === 1 && (
          <p className="faint small" style={{ marginTop: 8 }} data-testid="channel-search-hint">
            Type at least 2 characters to search.
          </p>
        )}
        {searchActive && (
          <p className="faint small" style={{ marginTop: 8 }} data-testid="channel-search-status">
            {searching ? "Searching…"
              : searchError ? `Search failed: ${searchError}`
              : searchTotal === 0 ? `No posts in this channel match “${trimmedQ}”.`
              : `${searchTotal} match${searchTotal === 1 ? "" : "es"} for “${trimmedQ}”`
                + (searchTotal > (searchResults?.length ?? 0)
                   ? ` — showing the ${searchResults?.length} most recent.` : "")}
          </p>
        )}
      </div>

      {/* Posts list */}
      <div className="card pad-0">
        <div style={{ padding: "0 18px" }}>
          {/* Pinned posts first */}
          {pinned.map((p: any) => (
            <PostRow key={p.id} post={p} isLeader={isLeader} onPin={() => togglePin(p.id)} onDelete={deletePost} isPinned />
          ))}
          {/* Regular posts */}
          {regular.map((p: any) => (
            <PostRow key={p.id} post={p} isLeader={isLeader} onPin={() => togglePin(p.id)} onDelete={deletePost} />
          ))}
          {searchActive && !searching && shown.length === 0 && (
            <div style={{ padding: "24px 0" }} className="faint" data-testid="channel-search-empty">
              No posts in this channel match “{trimmedQ}”. Try a different word, or clear the search.
            </div>
          )}
          {!searchActive && posts.length === 0 && <div style={{ padding: "24px 0" }} className="faint">No posts yet. Be the first to start a discussion!</div>}
        </div>
        {loadingMore && <div style={{ padding: "12px 18px", textAlign: "center" }} className="faint small">Loading more posts…</div>}
        {!searchActive && !cursor && posts.length > 0 && <div style={{ padding: "12px 18px", textAlign: "center" }} className="faint small">All posts loaded.</div>}
      </div>

      {newPost && (
        <FormModal title="New Post" path={`/channels/${id}/posts`}
          onClose={() => setNewPost(false)}
          onSaved={() => { setNewPost(false); setNonce((n) => n + 1); }}
          fields={[
            { name: "title", label: "Title", required: true },
            { name: "body", label: "Body", type: "textarea", required: true },
          ]} />
      )}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

function PostRow({ post, isLeader, onPin, onDelete, isPinned }: {
  post: any; isLeader: boolean; onPin: () => void; onDelete: (id: string, title: string) => void; isPinned?: boolean;
}) {
  const reactionTotal = Object.values(post.reactionCounts || {}).reduce((a: number, b: any) => a + (Number(b) || 0), 0);
  return (
    <div className="post-row" style={{
      display: "flex", gap: 12, padding: "14px 0", borderBottom: "1px solid var(--border)",
      ...(isPinned ? { background: "var(--warning-bg)", margin: "0 -18px", padding: "14px 18px" } : {}),
    }}>
      <div className="avatar sm">{(post.authorName || post.authorId || "?").slice(0, 2).toUpperCase()}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: "14.5px" }}>
          {isPinned && <span className="badge amber" style={{ marginRight: 6 }}>📌 Pinned</span>}
          <Link to={`/forums/post/${post.id}`} style={{ color: "var(--text)" }}>{post.title}</Link>
          {post.acceptedReplyId && <span className="badge green" style={{ marginLeft: 6 }}>✓ Answered</span>}
        </div>
        {post.body && <div style={{ color: "var(--text-muted)", fontSize: 13, marginTop: 3 }}>{post.body.slice(0, 120)}{post.body.length > 120 ? "…" : ""}</div>}
        <div style={{ color: "var(--text-faint)", fontSize: 12, marginTop: 5, display: "flex", gap: 12, flexWrap: "wrap" }}>
          <span>👤 {post.authorName || post.authorId}{post.authorRoleLabel && post.authorRoleLabel !== "Member" ? ` (${post.authorRoleLabel})` : ""}</span>
          <span>🕒 {timeAgo(post.createdAt)}</span>
          {post.edited && <span className="badge gray">edited</span>}
          {isLeader && <span><a href="#" onClick={(e) => { e.preventDefault(); onPin(); }}>{isPinned ? "unpin" : "pin"}</a> · <a href="#" onClick={(e) => { e.preventDefault(); onDelete(post.id, post.title); }}>delete</a></span>}
        </div>
      </div>
      <div style={{ textAlign: "center", minWidth: 54 }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{post.replyCount ?? 0}</div>
        <div style={{ fontSize: 11, color: "var(--text-faint)" }}>replies</div>
      </div>
      {reactionTotal > 0 && (
        <div style={{ textAlign: "center", minWidth: 54 }}>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{reactionTotal}</div>
          <div style={{ fontSize: 11, color: "var(--text-faint)" }}>👍</div>
        </div>
      )}
    </div>
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
