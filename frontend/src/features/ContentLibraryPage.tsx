/**
 * ContentLibraryPage — standalone community knowledge hub (US-2.20 rework).
 *
 * Search-first: nothing fetched until user submits a keyword or filter.
 * Community-wide: all resources visible regardless of group membership.
 * Admins: excluded (route is not rendered for Administrator role in App.tsx).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "../lib/apiClient";
import { EmptyState, ErrorState, Loading, LoadingMoreRow } from "../components/States";
import ScrollSentinel from "../components/ScrollSentinel";
import LibraryAddResourceModal from "../components/LibraryAddResourceModal";
import EditResourceModal from "../components/EditResourceModal";

const PAGE_SIZE = 25;
const FORMAT_OPTIONS = ["Slides", "PDF", "Doc", "Recording", "Link"];
const SOURCE_LABELS: Record<string, string> = {
  "event-material": "Event Material",
  "member-contribution": "Member Contribution",
  "curator-direct": "Curator Direct",
};
const FORMAT_ICON: Record<string, string> = {
  Slides: "📊", PDF: "📄", Doc: "📝", Recording: "🎥", Link: "🔗",
};

interface LibraryResource {
  id: string;
  title: string;
  description: string;
  format: string;
  topics: string[];
  source: string;
  submittedBy: string;
  submittedByName?: string;
  addedAt: string;
  eventId?: string;
  eventTitle?: string;
  downloadUrl?: string;
  url?: string;
  scanState?: string;
}

interface ContentLibraryPageProps {
  role: string;
}

// Infinite-scroll data hook. `endpoint` is null until a search is submitted
// (search-first). It appends `pageSize` records per fetch, following the
// DynamoDB GSI1 cursor returned by /library. A change to `endpoint` (new
// keyword, filter, or reload nonce) resets to page 1.
function useInfiniteLibrary(endpoint: string | null, pageSize: number) {
  const [items, setItems] = useState<LibraryResource[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingInitial, setLoadingInitial] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Guards against out-of-order responses when the endpoint changes rapidly
  // (e.g. fast filter switches): only the latest request's result is applied.
  const reqIdRef = useRef(0);

  const fetchPage = useCallback(async (url: string, append: boolean) => {
    const reqId = ++reqIdRef.current;
    try {
      const res = await apiFetch<{ items: LibraryResource[]; count: number; cursor?: string }>(url);
      if (reqId !== reqIdRef.current) return; // superseded
      setItems((prev) => (append ? [...prev, ...res.items] : res.items));
      setCursor(res.cursor ?? null);
      setHasMore(Boolean(res.cursor));
      setError(null);
    } catch (e) {
      if (reqId !== reqIdRef.current) return;
      setError((e as Error).message);
    } finally {
      if (reqId === reqIdRef.current) {
        setLoadingInitial(false);
        setLoadingMore(false);
      }
    }
  }, []);

  // Reset + fetch page 1 whenever the endpoint changes; clear when null.
  useEffect(() => {
    if (endpoint === null) {
      reqIdRef.current++; // invalidate any in-flight request
      setItems([]); setCursor(null); setHasMore(false);
      setLoadingInitial(false); setLoadingMore(false); setError(null);
      return;
    }
    setLoadingInitial(true); setError(null); setCursor(null); setHasMore(false);
    const sep = endpoint.includes("?") ? "&" : "?";
    fetchPage(`${endpoint}${sep}limit=${pageSize}`, false);
  }, [endpoint, pageSize, fetchPage]);

  const loadMore = useCallback(() => {
    if (!hasMore || loadingMore || loadingInitial || endpoint === null) return;
    setLoadingMore(true);
    const sep = endpoint.includes("?") ? "&" : "?";
    const url = `${endpoint}${sep}limit=${pageSize}` + (cursor ? `&cursor=${encodeURIComponent(cursor)}` : "");
    fetchPage(url, true);
  }, [hasMore, loadingMore, loadingInitial, endpoint, pageSize, cursor, fetchPage]);

  return { items, hasMore, loadingInitial, loadingMore, error, loadMore };
}

export default function ContentLibraryPage({ role }: ContentLibraryPageProps) {
  const isCurator = role === "CommunityLeader" || role === "UserGroupLeader";

  // Search state
  const [term, setTerm] = useState("");
  const [format, setFormat] = useState("");
  const [source, setSource] = useState("");
  const [submitted, setSubmitted] = useState<{
    q: string; format: string; source: string;
  } | null>(null);
  // Change 1: inline prompt shown when Search is clicked with an empty keyword.
  const [keywordAlert, setKeywordAlert] = useState(false);
  // Bumped after a mutation (add/edit/delete) to force a page-1 reload.
  const [reloadNonce, setReloadNonce] = useState(0);

  // Modal state
  const [showAddModal, setShowAddModal] = useState(false);
  const [editResource, setEditResource] = useState<LibraryResource | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  // Endpoint is null until a search is submitted (search-first). The hook
  // appends limit + cursor; `_` forces a refetch after a mutation.
  const endpoint = submitted === null ? null : (() => {
    const params = new URLSearchParams();
    if (submitted.q) params.set("q", submitted.q);
    if (submitted.format) params.set("format", submitted.format);
    if (submitted.source) params.set("source", submitted.source);
    if (reloadNonce) params.set("_", String(reloadNonce));
    const qs = params.toString();
    return qs ? `/library?${qs}` : "/library";
  })();

  const {
    items, hasMore, loadingInitial, loadingMore, error, loadMore,
  } = useInfiniteLibrary(endpoint, PAGE_SIZE);

  const runSearch = () => {
    // Change 1: require a keyword; prompt instead of a silent empty result.
    if (!term.trim()) { setKeywordAlert(true); return; }
    setKeywordAlert(false);
    setSubmitted({ q: term.trim(), format, source });
  };

  const handleFormatChange = (v: string) => {
    setFormat(v);
    if (submitted !== null) setSubmitted((s) => s ? { ...s, format: v } : s);
  };

  const handleSourceChange = (v: string) => {
    setSource(v);
    if (submitted !== null) setSubmitted((s) => s ? { ...s, source: v } : s);
  };

  const handleDelete = async (id: string) => {
    try {
      await apiFetch(`/library/${id}`, { method: "DELETE" });
      setDeleteConfirmId(null);
      setReloadNonce((n) => n + 1);
    } catch {
      /* handled by error UI */
    }
  };

  const attribution = (r: LibraryResource) => {
    if (r.source === "event-material") {
      return `📅 ${r.eventTitle || "Event"} · ${r.addedAt ? new Date(r.addedAt).toLocaleDateString() : ""}`;
    }
    if (r.source === "member-contribution") {
      return `👤 ${r.submittedByName || r.submittedBy} · Community Contribution`;
    }
    return `🏷️ Curated by ${r.submittedByName || r.submittedBy}`;
  };

  return (
    <div style={{ maxWidth: 860, margin: "0 auto", padding: "16px 0" }}>
      <div className="flex between" style={{ alignItems: "center", marginBottom: 16 }}>
        <h1 style={{ margin: 0 }}>📚 Content Library</h1>
        {isCurator && (
          <button
            className="btn primary"
            data-testid="library-add-btn"
            onClick={() => setShowAddModal(true)}
          >
            + Add Resource
          </button>
        )}
      </div>

      {/* Search bar */}
      <div className="card mb-16">
        <div className="flex wrap" style={{ gap: 10, alignItems: "flex-end" }}>
          <input
            className="input"
            style={{ width: 240 }}
            placeholder="🔍 Search title or description…"
            data-testid="library-search-input"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") runSearch(); }}
          />
          <div style={{ flex: "0 0 140px" }}>
            <select
              className="select"
              style={{ width: "100%" }}
              data-testid="library-format-select"
              value={format}
              onChange={(e) => handleFormatChange(e.target.value)}
            >
              <option value="">All formats</option>
              {FORMAT_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div style={{ flex: "0 0 160px" }}>
            <select
              className="select"
              style={{ width: "100%" }}
              data-testid="library-source-select"
              value={source}
              onChange={(e) => handleSourceChange(e.target.value)}
            >
              <option value="">All sources</option>
              {Object.entries(SOURCE_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </div>
          <button
            className="btn primary"
            data-testid="library-search-btn"
            onClick={runSearch}
          >
            🔍 Search
          </button>
          {submitted !== null && !loadingInitial && (
            <span className="faint small" data-testid="library-count">
              {items.length} loaded{hasMore ? "+" : ""}
            </span>
          )}
        </div>
        <p className="faint small mb-0 mt-8">
          Search across title and description. Filter by format or source.
        </p>
        {keywordAlert && (
          <div className="card" role="alert" data-testid="library-keyword-alert"
               style={{ marginTop: 10, padding: 10, background: "#fef2f2",
                        borderColor: "#fecaca", color: "var(--danger)" }}>
            <span className="small"><b>Enter a keyword to search.</b> Type what you&apos;re
              looking for in the search box, then click Search.</span>
          </div>
        )}
      </div>

      {submitted === null && (
        <EmptyState message="Enter a keyword and/or pick a filter, then click Search to find community resources." />
      )}

      {submitted !== null && loadingInitial && <Loading label="Searching…" />}

      {submitted !== null && !loadingInitial && error && <ErrorState message={error} />}

      {submitted !== null && !loadingInitial && !error && (
        <>
          {items.map((r) => (
            <section
              className="card mb-16"
              key={r.id}
              data-testid={`resource-card-${r.id}`}
            >
              <div className="flex between" style={{ alignItems: "flex-start", gap: 12 }}>
                <div className="flex" style={{ gap: 10, alignItems: "flex-start", minWidth: 0 }}>
                  <span style={{ fontSize: 24, lineHeight: 1, flexShrink: 0 }} title={r.format}>
                    {FORMAT_ICON[r.format] ?? "📁"}
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <div><b>{r.title}</b></div>
                    <div style={{ marginTop: 4, display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <span className="badge gray">{r.format}</span>
                      <span className="badge" style={{ background: "var(--surface-alt)" }}>
                        {SOURCE_LABELS[r.source] ?? r.source}
                      </span>
                      {r.topics.map((t) => (
                        <span key={t} className="badge" style={{ background: "var(--surface-alt)", fontSize: 11 }}>
                          {t}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="btn-row" style={{ flexShrink: 0 }}>
                  {r.downloadUrl && (
                    <a
                      className="btn sm primary"
                      href={r.downloadUrl}
                      download
                      data-testid={`resource-download-${r.id}`}
                    >
                      ⬇ Download
                    </a>
                  )}
                  {!r.downloadUrl && r.url && (
                    <a
                      className="btn sm primary"
                      href={r.url}
                      target="_blank"
                      rel="noreferrer"
                      data-testid={`resource-open-${r.id}`}
                    >
                      🔗 Open
                    </a>
                  )}
                  {!r.downloadUrl && !r.url && r.scanState === "PendingScan" && (
                    <span className="faint small">⏳ Scanning…</span>
                  )}
                  {isCurator && (
                    <>
                      <button
                        className="btn sm"
                        data-testid={`resource-edit-${r.id}`}
                        onClick={() => setEditResource(r)}
                      >
                        ✏️ Edit
                      </button>
                      {deleteConfirmId === r.id ? (
                        <>
                          <button
                            className="btn sm danger"
                            data-testid={`resource-delete-confirm-${r.id}`}
                            onClick={() => handleDelete(r.id)}
                          >
                            Confirm delete
                          </button>
                          <button
                            className="btn sm"
                            onClick={() => setDeleteConfirmId(null)}
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <button
                          className="btn sm"
                          data-testid={`resource-delete-${r.id}`}
                          onClick={() => setDeleteConfirmId(r.id)}
                        >
                          🗑️
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
              <div className="divider" />
              <p style={{ margin: "8px 0 4px", fontSize: 14 }}>{r.description}</p>
              <div className="faint small">{attribution(r)}</div>
            </section>
          ))}

          {items.length === 0 && (
            <EmptyState message="No resources match your search." />
          )}

          {loadingMore && <LoadingMoreRow label="resources" />}

          {/* Sentinel: fetches the next 25 when scrolled near the bottom.
              Rendered only when another page exists and no fetch is in flight. */}
          {hasMore && !loadingMore && <ScrollSentinel onVisible={loadMore} />}

          {items.length > 0 && (
            <div className="flex between" style={{ alignItems: "center", marginTop: 8 }}>
              <span className="faint small" data-testid="library-showing">
                Showing {items.length}{hasMore ? "" : " · end of results"}
              </span>
            </div>
          )}
        </>
      )}

      {showAddModal && (
        <LibraryAddResourceModal
          onClose={() => setShowAddModal(false)}
          onAdded={() => { setShowAddModal(false); setReloadNonce((n) => n + 1); }}
        />
      )}

      {editResource && (
        <EditResourceModal
          resource={editResource}
          onClose={() => setEditResource(null)}
          onSaved={() => { setEditResource(null); setReloadNonce((n) => n + 1); }}
        />
      )}
    </div>
  );
}
