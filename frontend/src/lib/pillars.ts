// Canonical contribution pillars (Unit 7 Contributions & Scoring).
//
// The WIRE value is the pillar NUMBER (1–4) — that's what the framework API,
// fixtures, and the scoring seed all store (see platform seed_handler
// _FRAMEWORK_ACTIVITIES). The human name lives HERE and only here so the
// Activity Types table, the Add/Edit Activity dropdown, and any future pillar
// UI can't drift apart. Names mirror the approved scoring-framework design.
export interface Pillar {
  value: number;
  label: string;
}

export const PILLARS: Pillar[] = [
  { value: 1, label: "1 · Upskilling & Deployment" },
  { value: 2, label: "2 · Peer Learning & Knowledge Sharing" },
  { value: 3, label: "3 · Assets, Demos & Open Source" },
  { value: 4, label: "4 · Thought Leadership & External Visibility" },
];

/** Human pillar name for a stored pillar number. Falls back to the raw value. */
export function pillarLabel(pillar: number | string | null | undefined): string {
  const n = Number(pillar);
  return PILLARS.find((p) => p.value === n)?.label ?? (pillar != null && pillar !== "" ? String(pillar) : "—");
}

/** Options for a Pillar <select>; value is the wire number as a string. */
export const PILLAR_OPTIONS = PILLARS.map((p) => ({ value: String(p.value), label: p.label }));

/** Points in the quarter total that carry NO pillar (manual adjustments and any
 *  source without a pillar mapping). The "Points by Pillar" chart only sums
 *  pillar-tagged points, so without this bucket the bars silently under-total
 *  the "Points Distributed" headline. Clamped at 0 — the pillar sum should never
 *  exceed the total, but a transient rollup skew must not render a negative bar. */
export function unattributedPoints(total: number, pillarValues: number[]): number {
  const summed = pillarValues.reduce((n, v) => n + (Number(v) || 0), 0);
  return Math.max(0, (Number(total) || 0) - summed);
}
