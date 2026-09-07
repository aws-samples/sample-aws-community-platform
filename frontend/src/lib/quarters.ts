// Calendar-quarter helpers shared by the leader dashboards and the Events page.
//
// The key format ("YYYY-Qn") is the one every backend service uses (Identity &
// Access, Contributions & Scoring, Events), so a quarter picked here can be sent
// to any of them unchanged.

/** Quarter key for a date (defaults to now). */
export function currentQuarter(at: Date = new Date()): string {
  return `${at.getUTCFullYear()}-Q${Math.floor(at.getUTCMonth() / 3) + 1}`;
}

/** The `count` most recent quarters, NEWEST first (picker order). */
export function trailingQuarters(count = 8, at: Date = new Date()): string[] {
  let year = at.getUTCFullYear();
  let q = Math.floor(at.getUTCMonth() / 3) + 1;
  const out: string[] = [];
  for (let i = 0; i < Math.max(1, count); i += 1) {
    out.push(`${year}-Q${q}`);
    q -= 1;
    if (q === 0) { q = 4; year -= 1; }
  }
  return out;
}

/** Inclusive calendar date range (YYYY-MM-DD) for a quarter key, or null if the
 *  key is not a quarter. Used as `from`/`to` on date-filtered list endpoints. */
export function quarterRange(quarter: string): { from: string; to: string } | null {
  const m = /^(\d{4})-Q([1-4])$/.exec(quarter);
  if (!m) return null;
  const year = Number(m[1]);
  const startMonth = (Number(m[2]) - 1) * 3;
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return {
    from: iso(new Date(Date.UTC(year, startMonth, 1))),
    // Day 0 of the following month is the last day of this quarter.
    to: iso(new Date(Date.UTC(year, startMonth + 3, 0))),
  };
}
