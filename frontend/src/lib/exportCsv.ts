// Client-side CSV export helper (US-6.x / US-7.x export actions).
// Fetches export rows from a mock endpoint and triggers a browser download.
import { apiFetch } from "./apiClient";

// Internal identifier columns are meaningless outside the system, so they are
// dropped from every CSV export. Matches `id`, camelCase `*Id`/`*Ids`
// (e.g. memberId, groupIds) and snake_case `*_id`/`*_ids` — but deliberately
// not plain words that merely end in "id" like "valid" or "grid".
export function isIdColumn(key: string): boolean {
  return /^id$/i.test(key) || /[a-z]Ids?$/.test(key) || /_ids?$/i.test(key);
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).filter(
    (c) => !isIdColumn(c),
  );
  if (!cols.length) return "";
  const esc = (v: unknown) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export function download(filename: string, content: string): void {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// Fetch { items } from an endpoint and download as CSV. Returns row count.
export async function exportEndpointCsv(path: string, filename: string): Promise<number> {
  const res = await apiFetch<{ items: Record<string, unknown>[] }>(path);
  const rows = res.items ?? [];
  download(filename, toCsv(rows));
  return rows.length;
}

// Cursor-following export for endpoints that page (US-3.4 large lists).
//
// The single-request version above cannot be used where a collection may hold
// 13,000+ rows: the unpaged branch of such an endpoint reads one record per row
// server-side and the response would exceed API Gateway's 6 MB limit. This walks
// the same paged contract the table uses (`limit` + opaque `cursor`) and
// concatenates the pages client-side, so peak memory is one page and no single
// response is large. `maxRows` is a safety stop so a bad cursor cannot loop
// forever.
/** Trim an ISO timestamp to its calendar date. Exports are read in spreadsheets
 *  where a time component is noise (and invites timezone confusion). */
export function dateOnly(value: unknown): string {
  const s = value == null ? "" : String(value);
  const m = /^(\d{4}-\d{2}-\d{2})/.exec(s);
  return m ? m[1] : s;
}

export async function exportPagedCsv(
  basePath: string, filename: string,
  opts: {
    pageSize?: number; maxRows?: number;
    /** Reshape each row before it becomes a CSV line (column formatting). */
    transform?: (row: Record<string, unknown>) => Record<string, unknown>;
  } = {},
): Promise<number> {
  const pageSize = opts.pageSize ?? 200;
  const maxRows = opts.maxRows ?? 100_000;
  const rows: Record<string, unknown>[] = [];
  let cursor: string | undefined;

  do {
    const sep = basePath.includes("?") ? "&" : "?";
    const params = new URLSearchParams({ limit: String(pageSize) });
    if (cursor) params.set("cursor", cursor);
    const res = await apiFetch<{ items: Record<string, unknown>[]; cursor?: string }>(
      `${basePath}${sep}${params.toString()}`);
    const page = res.items ?? [];
    rows.push(...(opts.transform ? page.map(opts.transform) : page));
    cursor = res.cursor;
  } while (cursor && rows.length < maxRows);

  download(filename, toCsv(rows));
  return rows.length;
}
