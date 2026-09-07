import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, FeatureNotAvailableError } from "./apiClient";

// Cursor-paginated infinite-scroll data source shared by the tables that follow
// the Member Directory pattern (append-on-scroll, no Prev/Next, no Rows control).
// Generalised from the Event Ideas feed hook.
//
// `endpoint` is the base path INCLUDING any filter query string but WITHOUT
// `limit`/`cursor` — the hook appends those. Pass `null` to disable fetching
// entirely (e.g. a Search gate that hasn't fired, or a missing group id): rows
// stay empty and no request is made. Changing `endpoint` (a filter/tab/nonce
// change) resets to page 1. Endpoints that return no `cursor` simply yield a
// single page with `hasMore === false` — the whole (bounded) set at once.
export interface InfinitePages<T> {
  rows: T[];
  loadingInitial: boolean; // first page in flight (show skeleton)
  loadingMore: boolean; // a subsequent page in flight (show "Loading more…")
  hasMore: boolean; // the API returned a cursor
  stale: boolean; // a refresh() reload is dimming the current rows
  error: string | null;
  comingSoon: boolean; // endpoint returned 501
  loadMore: () => void;
  refresh: () => void; // reload page 1, keeping current rows visible (dimmed) until it lands
}

function withPaging(endpoint: string, limit: number, cursor: string | null): string {
  const [base, qs = ""] = endpoint.split("?");
  const params = new URLSearchParams(qs);
  params.set("limit", String(limit));
  if (cursor) params.set("cursor", cursor);
  return `${base}?${params.toString()}`;
}

export function useInfinitePages<T = any>(
  endpoint: string | null,
  pageSize = 25,
): InfinitePages<T> {
  const [rows, setRows] = useState<T[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingInitial, setLoadingInitial] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [stale, setStale] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comingSoon, setComingSoon] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const fetchPage = useCallback(async (url: string, append: boolean) => {
    if (abortRef.current) abortRef.current.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      const res = await apiFetch<{ items: T[]; cursor?: string }>(url);
      if (ac.signal.aborted) return;
      setRows((prev) => append ? [...prev, ...(res.items ?? [])] : (res.items ?? []));
      setCursor(res.cursor ?? null);
      setHasMore(Boolean(res.cursor));
      setError(null);
      setComingSoon(false);
    } catch (e) {
      if (ac.signal.aborted) return;
      if (e instanceof FeatureNotAvailableError) { setComingSoon(true); setHasMore(false); }
      else if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      if (!ac.signal.aborted) {
        setLoadingInitial(false);
        setLoadingMore(false);
        setStale(false);
      }
    }
  }, []);

  // Reset + fetch page 1 whenever the endpoint changes (filter/tab/nonce), or
  // clear entirely when disabled.
  useEffect(() => {
    if (!endpoint) {
      if (abortRef.current) abortRef.current.abort();
      setRows([]); setCursor(null); setHasMore(false);
      setLoadingInitial(false); setLoadingMore(false); setStale(false);
      setError(null); setComingSoon(false);
      return;
    }
    setLoadingInitial(true); setStale(false); setCursor(null); setHasMore(false); setError(null);
    fetchPage(withPaging(endpoint, pageSize, null), false);
  }, [endpoint, pageSize, fetchPage]);

  const loadMore = useCallback(() => {
    if (!endpoint || !hasMore || loadingMore || loadingInitial) return;
    setLoadingMore(true);
    fetchPage(withPaging(endpoint, pageSize, cursor), true);
  }, [endpoint, hasMore, loadingMore, loadingInitial, cursor, pageSize, fetchPage]);

  // Soft reload of page 1 after a mutation — keeps rows visible (dimmed) so the
  // list doesn't blank out. loadingInitial gates the sentinel during the fetch.
  const refresh = useCallback(() => {
    if (!endpoint) return;
    setStale(true); setLoadingInitial(true); setCursor(null); setHasMore(false);
    fetchPage(withPaging(endpoint, pageSize, null), false);
  }, [endpoint, pageSize, fetchPage]);

  return { rows, loadingInitial, loadingMore, hasMore, stale, error, comingSoon, loadMore, refresh };
}
