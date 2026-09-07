// Pure (React-free) helpers for the Certification Ledger tab — query building,
// status options, on-screen status label, and CSV export mapping. Extracted so
// they can be unit-tested without a DOM (the repo has no component-test library).

import { dateOnly } from "../../lib/exportCsv";

// Ledger status filter values (BR-L2). "Active" = a currently-held (Approved)
// badge; Expired/Revoked are terminal history. Wire status "Approved" is shown
// as "Active" here to match the filter label.
export const STATUS_OPTIONS = [
  { value: "Active", label: "Active" },
  { value: "Expired", label: "Expired" },
  { value: "Revoked", label: "Revoked" },
] as const;

export const ALL_STATUS_VALUES = STATUS_OPTIONS.map((o) => o.value);

export interface LedgerFilters {
  quarter: string;
  groupId?: string;   // undefined/"" = all groups (CL)
  certId?: string;    // undefined/"" = all certificates
  memberId?: string;
  // Free-text member name. Replaces the directory typeahead that required
  // picking an exact member before the filter did anything.
  memberName?: string;
  statuses: string[]; // subset of ALL_STATUS_VALUES
}

/** Build the querystring for /certifications/ledger (without limit/cursor).
 *  Only sends `status` when the selection is a strict subset (all-selected =
 *  the server default, so we omit it). */
export function buildLedgerQuery(f: LedgerFilters): string {
  const p = new URLSearchParams();
  p.set("quarter", f.quarter);
  if (f.groupId) p.set("groupId", f.groupId);
  if (f.certId) p.set("certId", f.certId);
  if (f.memberId) p.set("memberId", f.memberId);
  if (f.memberName?.trim()) p.set("memberName", f.memberName.trim());
  if (f.statuses.length && f.statuses.length < ALL_STATUS_VALUES.length) {
    p.set("status", f.statuses.join(","));
  }
  return p.toString();
}

/** On-screen / export status label: Approved renders as "Active". */
export function certLedgerStatusLabel(status?: string): string {
  return status === "Approved" ? "Active" : (status ?? "");
}

/** CSV filename encoding scope + quarter (+ member when filtered). */
export function exportFilename(scopeLabel: string, quarter: string, memberName?: string): string {
  const scope = (scopeLabel || "all").replace(/\s+/g, "-").toLowerCase();
  const who = memberName ? `_${memberName.replace(/\s+/g, "-").toLowerCase()}` : "";
  return `certifications_${scope}_${quarter}${who}.csv`;
}

/** Map a ledger row to its CSV shape. `groupName` resolves the credited group id
 *  to a display name (no raw ids in exports). Email is intentionally omitted —
 *  it is not denormalized on the claim and resolving it per row would be a
 *  cross-service lookup the ledger deliberately avoids. */
export function toExportRow(
  row: Record<string, any>,
  groupName: (id?: string | null) => string,
): Record<string, unknown> {
  return {
    member: row.memberName || "Unknown member",
    certification: row.certName || row.certId,
    category: row.certCategory || "",
    certification_date: dateOnly(row.certificationDate),
    earned_date: dateOnly(row.dateEarned),
    approved_date: dateOnly(row.decidedAt),
    user_group: groupName(row.creditedGroupId),
    status: certLedgerStatusLabel(row.status),
    expires_on: dateOnly(row.expiresAt),
  };
}
