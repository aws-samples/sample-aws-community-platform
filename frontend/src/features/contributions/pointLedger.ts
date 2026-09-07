// Pure helpers for the Point Ledger (US-7.9), kept React-free so they can be
// unit-tested without a DOM. See PointLedgerPanel.tsx for the UI.

/** Activity categories — MUST match the backend `CATEGORY_LABELS` (models.py).
 *  Forum/organize/other auto awards collapse into "other-auto" because the
 *  stored activity name is CL-editable and historical rows carry no category
 *  code, so only source + the stable prefixes are reliably classifiable. */
export const ACTIVITY_CATEGORY_OPTIONS: { value: string; label: string }[] = [
  { value: "event-attendance", label: "Event Attendance" },
  { value: "event-delivery", label: "Event Delivery" },
  { value: "certification", label: "Certification" },
  { value: "other-auto", label: "Other (auto-awarded)" },
  { value: "evidence", label: "Evidence Submission" },
  { value: "adjustment", label: "Manual Adjustment" },
];

export const SOURCE_OPTIONS: { value: string; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "evidence", label: "Evidence" },
  { value: "adjustment", label: "Adjustment" },
];

/** Build the group-ledger query string from the current filter state. Cursor is
 *  added by the caller/paged-export helper, not here. */
export interface LedgerFilterState {
  groupId: string;
  quarter: string;
  memberId?: string;
  sources: string[];
  categories: string[];
}

/** The filter set as a plain object, shared by the table query string and the
 *  async export's POST body so the CSV can never be filtered differently from
 *  the rows on screen. Only strict subsets are sent — sending every value is the
 *  same as no filter, and omitting it keeps the URL and cursor space clean. */
export function ledgerFilterFields(f: LedgerFilterState): Record<string, string> {
  const out: Record<string, string> = {};
  if (f.groupId) out.groupId = f.groupId;
  if (f.quarter) out.quarter = f.quarter;
  if (f.memberId) out.memberId = f.memberId;
  if (f.sources.length && f.sources.length < SOURCE_OPTIONS.length) {
    out.source = f.sources.join(",");
  }
  if (f.categories.length && f.categories.length < ACTIVITY_CATEGORY_OPTIONS.length) {
    out.activityType = f.categories.join(",");
  }
  return out;
}

export function buildLedgerQuery(f: LedgerFilterState): string {
  return new URLSearchParams(ledgerFilterFields(f)).toString();
}

// The CSV row mapping and filename used to live here, built in the browser by
// exportPagedCsv. The export is now an async server-side job
// (POST /contributions/group-ledger/export), so the column set and the download
// name are produced by services/contributions-scoring/src/export_worker.py —
// keeping a second copy here would be dead code that silently drifts from the
// file the user actually receives.
