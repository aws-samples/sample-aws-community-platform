// Pure rules behind the Adjust Points screen (US-6.15). Deliberately free of
// React so every rule is unit-testable without a component-testing library —
// the repo has none installed, and these rules are where the behaviour lives.
//
// Requirement refs: FR-4..FR-11, FR-14, DR-1, DR-2 in
// aidlc-docs/inception/business-requirements/adjust-points-rework-requirements.md

/** Server-side bound on a manual adjustment (AdjustmentService.adjust). */
export const DELTA_LIMIT = 100000;

export interface GroupRef {
  id: string;
  name?: string | null;
}

export interface LedgerEntry {
  id?: string;
  groupId?: string | null;
  quarter?: string | null;
  points?: number | string | null;
  /** Set on a REVERSING entry, pointing at the id of the entry it reversed. */
  reverses?: string | null;
}

export interface SelectOption {
  value: string;
  label: string;
}

export type ParsedDelta =
  | { ok: true; value: number }
  | { ok: false; reason: string };

/**
 * FR-8 (Q5=A): the sign is MANDATORY. "+10" and "-5" are valid; a bare "10" is
 * rejected on purpose, so a leader can never add points while believing they
 * were subtracting.
 *
 * Returns a NUMBER, not a string. This is the fix for the defect that made the
 * old screen fail every time: the shared FormModal submitted "10", and the
 * server's require_int asserts isinstance(value, int), so every adjustment was
 * rejected with a 400. Callers MUST send this `value` verbatim (FR-7).
 */
export function parseSignedDelta(raw: string | null | undefined): ParsedDelta {
  const text = (raw ?? "").trim();
  if (text === "") return { ok: false, reason: "Enter a point change, e.g. +10 or -5." };
  if (!/^[+-]/.test(text)) {
    return { ok: false, reason: "Start with + to add points or - to subtract, e.g. +10 or -5." };
  }
  if (!/^[+-]\d+$/.test(text)) {
    return { ok: false, reason: "Use a sign followed by whole digits only, e.g. +10 or -5." };
  }
  const value = Number(text);
  // Number("-0") is -0, which is === 0, so this covers "0", "+0" and "-0".
  if (value === 0) return { ok: false, reason: "A point change cannot be zero." };
  if (Math.abs(value) > DELTA_LIMIT) {
    return { ok: false, reason: `A point change cannot exceed ${DELTA_LIMIT}.` };
  }
  return { ok: true, value };
}

/**
 * FR-8: keep the field unable to hold anything but a signed integer, so invalid
 * characters never reach state. Magnitude is NOT clamped here — an over-limit
 * number is left intact so parseSignedDelta can explain the bound, rather than
 * silently rewriting what the leader typed.
 */
export function sanitizeDeltaInput(raw: string | null | undefined): string {
  let out = "";
  for (const ch of Array.from(raw ?? "")) {
    if (out === "" && (ch === "+" || ch === "-")) { out = ch; continue; }
    if (ch >= "0" && ch <= "9") out += ch;
  }
  return out;
}

/**
 * FR-4/FR-5 + DR-1: the group choices for the selected member, as NAMES — raw
 * `g-…` ids never render (NFR-6).
 *
 * For a UserGroupLeader the list is narrowed to the group they lead. Offering a
 * member's other groups would offer choices the server is guaranteed to reject
 * with 403 (BR-A5), which is the same principle that scopes their member search.
 * The caller still renders this without a preselection (FR-5).
 */
export function groupOptionsFor(args: {
  memberGroupIds: string[];
  allGroups: GroupRef[];
  role?: string;
  ledGroupId?: string;
}): SelectOption[] {
  const { memberGroupIds, allGroups, role, ledGroupId } = args;
  const own = (memberGroupIds ?? []).filter(Boolean);
  const scoped = role === "UserGroupLeader"
    ? own.filter((id) => !!ledGroupId && id === ledGroupId)
    : own;

  const seen = new Set<string>();
  const options: SelectOption[] = [];
  for (const id of scoped) {
    if (seen.has(id)) continue;
    seen.add(id);
    const name = (allGroups ?? []).find((g) => g.id === id)?.name;
    // A group that cannot be resolved (e.g. soft-deleted) is still a real
    // membership, so it stays selectable — but it is labelled, never id-leaked.
    options.push({ value: id, label: (name && String(name).trim()) || "Unnamed group" });
  }
  return options.sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * FR-11 + DR-2: the member's current total for one group and quarter, summed
 * from their ledger entries.
 *
 * The ledger is the source rather than `tiersEarned`, which emits a row only
 * when the points clear a tier threshold — a member below the lowest tier would
 * be indistinguishable from a member with no data, and the preview would show a
 * confident, wrong zero right before writing a permanent entry.
 */
export function quarterTotal(
  entries: LedgerEntry[] | null | undefined,
  groupId: string,
  quarter: string,
): number {
  if (!entries || !groupId || !quarter) return 0;
  return entries.reduce((sum, e) => {
    if (e.groupId !== groupId || e.quarter !== quarter) return sum;
    const points = Number(e.points ?? 0);
    return sum + (Number.isFinite(points) ? points : 0);
  }, 0);
}

/**
 * FR-14: ids of entries that have ALREADY been reversed, derived from the same
 * response — a reversing entry carries `reverses` = its target's id. Lets the UI
 * withhold a reverse action that the server would reject with 409 (BR-J2), which
 * remains the actual control.
 */
export function reversedIdsOf(entries: LedgerEntry[] | null | undefined): Set<string> {
  const out = new Set<string>();
  for (const e of entries ?? []) {
    const target = e.reverses;
    if (target) out.add(String(target));
  }
  return out;
}
