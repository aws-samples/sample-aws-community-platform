import { useMemo, useState } from "react";
import ColumnSettings from "./ColumnSettings";
import ScrollSentinel from "./ScrollSentinel";

// US-8.9 configurable data table: sortable columns, show/hide/reorder columns,
// rows-per-page, with per-user (per-table) preference persistence in localStorage.
export interface TableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  sortValue?: (row: T) => string | number;
  // Hidden on first render (and after Reset) unless the user turns it on via
  // Column Settings — for secondary columns a table offers but doesn't show by
  // default. Only applied when the table has no saved prefs yet.
  defaultHidden?: boolean;
}

interface Prefs {
  order: string[];
  hidden: string[];
  rows: number;
  sortKey: string | null;
  sortDir: "asc" | "desc";
}

function loadPrefs(id: string, cols: string[], defaultHidden: string[] = []): Prefs {
  try {
    const raw = localStorage.getItem(`tblprefs:${id}`);
    if (raw) return JSON.parse(raw) as Prefs;
  } catch { /* ignore */ }
  return { order: cols, hidden: defaultHidden, rows: 25, sortKey: null, sortDir: "asc" };
}

// The saved rows-per-page pref for a table — lets a page using server-side
// pagination initialize its `limit` param from the same pref the Rows dropdown
// saves (directory perf change 2026-08-03, D-P5).
export function loadRowsPref(id: string): number {
  return loadPrefs(id, []).rows || 25;
}

// Server-side (cursor) pagination controls. When provided, the table renders
// `rows` as-is: the server owns paging and ordering, so client-side sort and
// row truncation are disabled. Rows dropdown becomes the page size (D-P5).
export interface ServerPaging {
  fetching: boolean; // request in flight (skeleton on first load, "Refreshing…" after)
  hasMore: boolean; // a next page exists (API returned a cursor)
  canPrev: boolean;
  onNext: () => void;
  onPrev: () => void;
  onPageSizeChange: (n: number) => void;
  // Optional exact total + 1-based index of the first row on this page, so the
  // toolbar can read "Showing 1–25 of 412 members" as the mockups do. Cursor
  // paging cannot derive a total on its own; supply it only when the API
  // returns one cheaply (e.g. the group member counter). Omit and the toolbar
  // falls back to "Showing N — more available".
  total?: number;
  startIndex?: number;
  unit?: string; // noun for the total, e.g. "members"
}

// Infinite-scroll (append-on-scroll) controls — the Member Directory pattern.
// When provided, the table renders ALL accumulated `rows` (the caller owns the
// growing list), hides the Rows dropdown and Prev/Next, and shows a progress
// bar, skeleton (first load), a "Loading more…" row, an "All N loaded" footer,
// and a scroll sentinel that calls onLoadMore. Mutually exclusive with `server`.
export interface InfinitePaging {
  loadingInitial: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  onLoadMore: () => void;
  unit?: string; // noun for the footer, e.g. "entries" → "All 42 entries loaded"
}

// Action columns are declared with an empty header (`header: ""`) so the table
// head stays clean — the settings panel still needs a name for them. Applies to
// every table: `key: "act"` is the app-wide convention for the button column.
function panelLabel(c: { key: string; header: string }): string {
  if (c.header.trim()) return c.header;
  if (/^act(ion)?s?$/i.test(c.key)) return "Actions";
  return c.key.replace(/([A-Z])/g, " $1").replace(/^./, (s) => s.toUpperCase());
}

export default function DataTable<T extends { id?: string }>(props: {
  id: string;
  columns: TableColumn<T>[];
  rows: T[];
  server?: ServerPaging;
  // Optional controls rendered in the toolbar, left of "Rows:" (e.g. a search
  // box that belongs to the table rather than to a page-level filter bar).
  toolbarExtra?: React.ReactNode;
  // Server-mode empty-state text (defaults to the member-directory wording).
  emptyLabel?: string;
  // Hide the Rows per page dropdown — use when the caller owns pagination
  // (e.g. infinite scroll) so the control is meaningless.
  hideRowsControl?: boolean;
  // Infinite-scroll mode (append-on-scroll). Mutually exclusive with `server`.
  infinite?: InfinitePaging;
}) {
  const colKeys = props.columns.map((c) => c.key);
  const defaultHidden = props.columns.filter((c) => c.defaultHidden).map((c) => c.key);
  const [prefs, setPrefs] = useState<Prefs>(() => loadPrefs(props.id, colKeys, defaultHidden));

  const save = (p: Prefs) => { setPrefs(p); try { localStorage.setItem(`tblprefs:${props.id}`, JSON.stringify(p)); } catch { /* ignore */ } };
  const colById = (k: string) => props.columns.find((c) => c.key === k)!;
  // Saved prefs can predate a column being added to the table, so anything the
  // stored order doesn't know about is appended rather than dropped.
  const order = useMemo(() => {
    const known = prefs.order.filter((k) => colKeys.includes(k));
    return [...known, ...colKeys.filter((k) => !known.includes(k))];
  }, [prefs.order, colKeys.join("|")]);
  const visible = order.filter((k) => !prefs.hidden.includes(k));

  const server = props.server;
  const infinite = props.infinite;
  // Server and infinite modes both let the source own ordering, so client sort
  // is disabled for them.
  const serverOwned = Boolean(server || infinite);
  const sorted = useMemo(() => {
    if (serverOwned || !prefs.sortKey) return props.rows;
    const col = colById(prefs.sortKey);
    const val = col.sortValue ?? ((r: T) => String(col.render(r)));
    const dir = prefs.sortDir === "asc" ? 1 : -1;
    return [...props.rows].sort((a, b) => (val(a) > val(b) ? dir : val(a) < val(b) ? -dir : 0));
  }, [props.rows, prefs.sortKey, prefs.sortDir, serverOwned]);

  // Server/infinite modes: rows ARE the page. Client mode: truncate to the pref.
  const page = serverOwned ? sorted : sorted.slice(0, prefs.rows);
  const showSkeleton = Boolean(
    (server?.fetching || infinite?.loadingInitial) && props.rows.length === 0);
  // Rows dropdown is meaningless when the caller owns pagination.
  const hideRows = props.hideRowsControl || Boolean(infinite);

  const toggleSort = (k: string) =>
    save({ ...prefs, sortKey: k, sortDir: prefs.sortKey === k && prefs.sortDir === "asc" ? "desc" : "asc" });
  const toggleHidden = (k: string) =>
    save({ ...prefs, hidden: prefs.hidden.includes(k) ? prefs.hidden.filter((x) => x !== k) : [...prefs.hidden, k] });

  return (
    <>
      <div className="tbl-toolbar" style={{ paddingLeft: 0, paddingRight: 0 }}>
        <div className="tt-left">
          {server ? (
            <>
              {server.total != null && props.rows.length > 0
                ? `Showing ${server.startIndex ?? 1}–${(server.startIndex ?? 1) + props.rows.length - 1} of ${server.total}${server.unit ? ` ${server.unit}` : ""}`
                : `Showing ${props.rows.length}${server.hasMore ? " — more available" : ""}`}
              {server.fetching && props.rows.length > 0 &&
                <span className="faint small" style={{ marginLeft: 8 }} data-testid={`${props.id}-refreshing`}>Refreshing…</span>}
            </>
          ) : infinite ? (
            <>
              {`Showing ${props.rows.length}${infinite.hasMore ? " — more available" : ""}`}
              {(infinite.loadingMore || (infinite.loadingInitial && props.rows.length > 0)) &&
                <span className="faint small" style={{ marginLeft: 8 }} data-testid={`${props.id}-refreshing`}>Loading…</span>}
            </>
          ) : (
            <>{page.length} of {props.rows.length}</>
          )}
        </div>
        <div className="tt-right" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {server && (
            <span style={{ display: "flex", gap: 6 }}>
              <button className="btn sm" data-testid={`${props.id}-prev`} disabled={!server.canPrev || server.fetching}
                      onClick={server.onPrev}>← Prev</button>
              <button className="btn sm" data-testid={`${props.id}-next`} disabled={!server.hasMore || server.fetching}
                      onClick={server.onNext}>Next →</button>
            </span>
          )}
          {props.toolbarExtra}
          {!hideRows && (
            <span className="rows-select">Rows:
              <select className="select" style={{ width: "auto", padding: "5px 8px" }} value={prefs.rows}
                      data-testid={`${props.id}-rows`}
                      onChange={(e) => { const n = Number(e.target.value); save({ ...prefs, rows: n }); server?.onPageSizeChange(n); }}>
                {[10, 25, 50, 100].map((n) => <option key={n}>{n}</option>)}
              </select>
            </span>
          )}
          <ColumnSettings
            tableId={props.id}
            items={order.map((k) => ({ key: k, label: panelLabel(colById(k)) }))}
            hidden={prefs.hidden}
            onReorder={(next) => save({ ...prefs, order: next })}
            onToggle={toggleHidden}
            onReset={() => save({ ...prefs, order: colKeys, hidden: defaultHidden })}
          />
        </div>
      </div>
      {infinite && (infinite.loadingInitial || infinite.loadingMore) && (
        <div style={{ height: 3, background: "var(--border)", borderRadius: 2, marginBottom: 8, overflow: "hidden" }}
             data-testid={`${props.id}-progress`}>
          <div style={{ height: "100%", background: "var(--primary)", borderRadius: 2, width: "60%",
                        animation: "dt-progress-indeterminate 1.4s ease-in-out infinite" }} />
        </div>
      )}
      <div style={{ overflowX: "auto" as const, WebkitOverflowScrolling: "touch" as const }}>
      <table className="tbl" data-testid={`table-${props.id}`}>
        <thead><tr>{visible.map((k) => (
          serverOwned ? (
            // Server/infinite owns ordering — header sort disabled (D-P5).
            <th key={k}>{colById(k).header}</th>
          ) : (
            <th key={k} className="sortable" style={{ cursor: "pointer" }} onClick={() => toggleSort(k)}>
              {colById(k).header} <span className="sort-ind">{prefs.sortKey === k ? (prefs.sortDir === "asc" ? "▲" : "▼") : "⇅"}</span>
            </th>
          )
        ))}</tr></thead>
        <tbody style={(server?.fetching || infinite?.loadingInitial) && page.length > 0 ? { opacity: 0.55 } : undefined}>
          {showSkeleton
            ? Array.from({ length: Math.min(prefs.rows, 10) }, (_, i) => (
                <tr key={`sk-${i}`} aria-hidden="true" data-testid={i === 0 ? `${props.id}-skeleton` : undefined}>
                  {visible.map((k) => (
                    <td key={k}>
                      <span style={{ display: "inline-block", width: "70%", height: 12, borderRadius: 4,
                                     background: "var(--border, #e2e5ea)" }} />
                    </td>
                  ))}
                </tr>
              ))
            : page.map((row, i) => (
                <tr key={row.id ?? i}>{visible.map((k) => <td key={k}>{colById(k).render(row)}</td>)}</tr>
              ))}
        </tbody>
      </table>
      </div>
      {server && !server.fetching && page.length === 0 && (
        <div className="faint small" style={{ padding: "14px 4px" }}>
          {props.emptyLabel ?? "No members match the current filters."}</div>
      )}

      {infinite && (
        <>
          {infinite.loadingMore && (
            <div className="faint small" style={{ padding: "12px 4px", textAlign: "center" }}
                 data-testid={`${props.id}-loading-more`}>Loading more…</div>
          )}
          {!infinite.loadingInitial && page.length === 0 && (
            <div className="faint small" style={{ padding: "14px 4px", textAlign: "center" }}>
              {props.emptyLabel ?? "Nothing to show."}</div>
          )}
          {!infinite.loadingInitial && !infinite.hasMore && page.length > 0 && (
            <div className="faint small" style={{ textAlign: "center", padding: "10px 0" }}>
              All {page.length} {infinite.unit ?? "rows"} loaded</div>
          )}
          {/* Trigger the next page only when idle and more remains. */}
          {infinite.hasMore && !infinite.loadingMore && !infinite.loadingInitial && (
            <ScrollSentinel onVisible={infinite.onLoadMore} />
          )}
          <style>{`
            @keyframes dt-progress-indeterminate {
              0%   { margin-left: 0;    width: 30%; }
              50%  { margin-left: 40%;  width: 40%; }
              100% { margin-left: 100%; width: 10%; }
            }
          `}</style>
        </>
      )}
    </>
  );
}
