import { useState, useEffect } from "react";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { Loading } from "../components/States";
import { ShoutoutCard } from "../components/ShoutoutsSection";

type Filter = "all" | "received" | "sent";

export default function ShoutoutsPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [pages, setPages] = useState<any[][]>([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [reacting, setReacting] = useState<string | null>(null);

  // Reset pages when filter changes
  useEffect(() => { setPages([]); }, [filter, nonce]);

  // Endpoint per filter
  const endpoint = filter === "received"
    ? `/shoutouts/my-received?limit=20&_=${nonce}`
    : filter === "sent"
      ? `/shoutouts/my-sent?limit=20&_=${nonce}`
      : `/shoutouts/all?limit=20&_=${nonce}`;

  const first = useApi<{ items: any[]; cursor?: string }>(endpoint);

  const allItems = [
    ...(first.data?.items ?? []),
    ...pages.flat(),
  ];

  const nextCursor = pages.length > 0
    ? (pages[pages.length - 1] as any).__cursor
    : first.data?.cursor;

  const loadMore = async () => {
    if (loadingMore || !nextCursor) return;
    setLoadingMore(true);
    const base = filter === "received" ? "/shoutouts/my-received"
      : filter === "sent" ? "/shoutouts/my-sent"
      : "/shoutouts/all";
    try {
      const data = await apiFetch<{ items: any[]; cursor?: string }>(
        `${base}?limit=20&cursor=${encodeURIComponent(nextCursor)}`);
      const page: any[] = data.items ?? [];
      (page as any).__cursor = data.cursor;
      setPages((prev) => [...prev, page]);
    } catch { /* ignore */ }
    finally { setLoadingMore(false); }
  };

  const react = async (id: string) => {
    if (reacting) return;
    setReacting(id);
    try {
      await apiFetch(`/shoutouts/${id}/react`, { method: "POST" });
      setNonce((n) => n + 1);
      setPages([]);
    } catch { /* silent */ }
    finally { setReacting(null); }
  };

  const emptyMessages: Record<Filter, string> = {
    all: "No shoutouts in the past 30 days.",
    received: "You haven't received any shoutouts yet.",
    sent: "You haven't sent any shoutouts yet.",
  };

  return (
    <>
      <div className="page-head">
        <h1>👏 Shoutouts</h1>
        <p>Community recognition from the past 30 days.</p>
      </div>

      {/* Filter tabs */}
      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (filter === "all" ? " active" : "")}
          onClick={() => setFilter("all")}>All</div>
        <div className={"tab" + (filter === "received" ? " active" : "")}
          onClick={() => setFilter("received")}>Shoutouts I Received</div>
        <div className={"tab" + (filter === "sent" ? " active" : "")}
          onClick={() => setFilter("sent")}>Shoutouts I Sent</div>
      </div>

      {first.loading && <Loading />}

      {!first.loading && allItems.length === 0 && (
        <div className="card"><p className="faint">{emptyMessages[filter]}</p></div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {allItems.map((s) => (
          <ShoutoutCard key={s.id} s={s} onReact={filter !== "sent" ? react : undefined} reacting={reacting} />
        ))}
      </div>

      {nextCursor && (
        <div style={{ textAlign: "center", marginTop: 16 }}>
          <button className="btn" onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        </div>
      )}

      {!first.loading && !nextCursor && allItems.length > 0 && (
        <p className="faint small text-c mt-16">All shoutouts from the past 30 days shown.</p>
      )}
    </>
  );
}
