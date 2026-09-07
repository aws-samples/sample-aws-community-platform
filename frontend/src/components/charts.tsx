// Shared dashboard visualisations (US-7.1/7.2/7.3/7.4).
//
// Inline SVG/CSS with no charting dependency, and deliberately shared between the
// Community Leader and User Group Leader dashboards: the same figure must look and
// behave identically whichever screen it appears on.

export const TIER_ORDER = ["Gold", "Silver", "Bronze", "Rising"] as const;

export const TIER_COLOR: Record<string, string> = {
  Gold: "var(--gold)", Silver: "var(--silver)", Bronze: "var(--bronze)", Rising: "var(--rising)",
};

/** Neutral slice/fill for members carrying no tier. */
export const NO_TIER_COLOR = "#dde1e8";

/** Initials for an avatar chip, e.g. "Alex Morgan" -> "AM". */
export function initials(name?: string | null): string {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
}

/** CSS conic-gradient from ordered slices. */
export function conic(slices: { color: string; value: number }[], total: number): string {
  if (total <= 0) return `conic-gradient(${NO_TIER_COLOR} 0 100%)`;
  let acc = 0;
  const parts = slices.filter((s) => s.value > 0).map((s) => {
    const start = (acc / total) * 100;
    acc += s.value;
    return `${s.color} ${start}% ${(acc / total) * 100}%`;
  });
  return `conic-gradient(${parts.join(", ")})`;
}

/** A period with no measurement is `null`, NOT 0 — a zero on a membership line
 *  reads as "nobody was a member", which is a different claim from "we did not
 *  measure this quarter". Gaps are drawn as breaks in the line. */
export interface Series { label: string; color: string; values: (number | null)[] }

/** Contiguous runs of measured points, so a gap breaks the line instead of
 *  drawing a straight segment across data that does not exist. */
function segments(values: (number | null)[]): { i: number; v: number }[][] {
  const out: { i: number; v: number }[][] = [];
  let run: { i: number; v: number }[] = [];
  values.forEach((v, i) => {
    if (v == null) { if (run.length) { out.push(run); run = []; } return; }
    run.push({ i, v });
  });
  if (run.length) out.push(run);
  return out;
}

/** Multi-series line chart over labelled periods. */
export function TrendChart({ quarters, series, height = 190 }: {
  quarters: string[]; series: Series[]; height?: number;
}) {
  const W = 480, H = height;
  const padL = 34, padR = 10, padT = 12, padB = 26;
  const measured = series.flatMap((s) => s.values.filter((v): v is number => v != null));
  const max = Math.max(1, ...measured);
  const x = (i: number) => (quarters.length <= 1
    ? padL
    : padL + (i * (W - padL - padR)) / (quarters.length - 1));
  const y = (v: number) => padT + (1 - v / max) * (H - padT - padB);
  const ticks = [0, Math.round(max / 2), max].filter((t, i, a) => a.indexOf(t) === i);

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
           aria-label={series.map((s) => s.label).join(" and ") + " per period"}
           data-testid="trend-chart">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth="1" />
            <text x={padL - 6} y={y(t) + 4} textAnchor="end" fontSize="10"
                  fill="var(--text-faint)">{t}</text>
          </g>
        ))}
        {quarters.map((qq, i) => (
          <text key={qq} x={x(i)} y={H - 8} textAnchor="middle" fontSize="10"
                fill="var(--text-muted)">{qq}</text>
        ))}
        {series.map((s) => (
          <g key={s.label}>
            {segments(s.values).map((seg, si) => (
              // A single measured point has no line to draw; the marker below
              // carries it, so the series is still visible on a one-point series.
              <polyline key={si} fill="none" stroke={s.color} strokeWidth="2.5"
                        strokeLinejoin="round" strokeLinecap="round"
                        points={seg.map((p) => `${x(p.i)},${y(p.v)}`).join(" ")} />
            ))}
            {s.values.map((v, i) => (v == null ? null : (
              <circle key={i} cx={x(i)} cy={y(v)} r="3.5" fill={s.color}>
                <title>{`${s.label} · ${quarters[i]}: ${v}`}</title>
              </circle>
            )))}
          </g>
        ))}
      </svg>
      <div className="flex" style={{ gap: 16, justifyContent: "center" }}>
        {series.map((s) => (
          <span key={s.label} className="small faint"
                style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 18, height: 3, background: s.color, borderRadius: 2 }} />
            {s.label}
          </span>
        ))}
      </div>
    </>
  );
}

/** Clustered column chart: one group of columns per period, one column per series. */
export function ColumnChart({ quarters, types, counts, colors }: {
  quarters: string[]; types: string[];
  counts: Record<string, Record<string, number>>;
  colors: string[];
}) {
  const W = 480, H = 200;
  const padL = 30, padR = 8, padT = 14, padB = 30;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const max = Math.max(1, ...quarters.flatMap((q) => types.map((t) => counts[q]?.[t] ?? 0)));
  const groupW = plotW / Math.max(1, quarters.length);
  const barW = Math.max(3, Math.min(22, (groupW * 0.8) / Math.max(1, types.length)));
  const y = (v: number) => padT + (1 - v / max) * plotH;
  const ticks = [0, Math.round(max / 2), max].filter((t, i, a) => a.indexOf(t) === i);

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img"
           aria-label="Events per period by type" data-testid="events-type-chart">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth="1" />
            <text x={padL - 6} y={y(t) + 4} textAnchor="end" fontSize="10"
                  fill="var(--text-faint)">{t}</text>
          </g>
        ))}
        {quarters.map((q, gi) => {
          const clusterW = barW * types.length;
          const left = padL + gi * groupW + (groupW - clusterW) / 2;
          return (
            <g key={q}>
              {types.map((t, ti) => {
                const v = counts[q]?.[t] ?? 0;
                const h = v === 0 ? 0 : Math.max(2, plotH - (y(v) - padT));
                return (
                  <rect key={t} x={left + ti * barW + 1} y={y(v)}
                        width={Math.max(1, barW - 2)} height={h}
                        fill={colors[ti % colors.length]} rx="2">
                    <title>{`${t} · ${q}: ${v} event${v === 1 ? "" : "s"}`}</title>
                  </rect>
                );
              })}
              <text x={padL + gi * groupW + groupW / 2} y={H - 10} textAnchor="middle"
                    fontSize="10" fill="var(--text-muted)">{q}</text>
            </g>
          );
        })}
      </svg>
      <div className="flex wrap" style={{ gap: 14, justifyContent: "center" }}>
        {types.map((t, ti) => (
          <span key={t} className="small faint"
                style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2,
                           background: colors[ti % colors.length] }} />
            {t}
          </span>
        ))}
      </div>
    </>
  );
}

export interface RankedBar { label: string; value: number; color?: string; muted?: boolean }

/** Horizontal ranked bar chart — one row per category, widest first.
 *
 *  Horizontal rather than columns because the categories here are user group
 *  NAMES: they are long, of varying length, and the list grows over time, all of
 *  which is where rotated column labels stop being readable.
 */
export function RankedBarChart({ bars, emptyNote, testId }: {
  bars: RankedBar[]; emptyNote?: string; testId?: string;
}) {
  const max = Math.max(1, ...bars.map((b) => b.value));
  if (bars.length === 0) {
    return <p className="faint small mb-0">{emptyNote ?? "Nothing to show yet."}</p>;
  }
  return (
    <ul className="clean" data-testid={testId ?? "ranked-bars"}>
      {bars.map((b) => (
        <li key={b.label} style={{ display: "grid", gridTemplateColumns: "40% 1fr auto",
                                   alignItems: "center", gap: 10, padding: "5px 0" }}>
          <span className={"small" + (b.muted ? " faint" : "")}
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={b.label}>{b.label}</span>
          <span style={{ background: "var(--bg-alt, #f1f3f6)", borderRadius: 3, height: 14 }}>
            {/* A zero keeps a 2px stub so the row still reads as a bar at zero
                rather than looking like a rendering failure. */}
            <span style={{ display: "block", height: "100%", borderRadius: 3,
                           width: `${Math.max(b.value === 0 ? 0.5 : 2,
                                              (b.value / max) * 100)}%`,
                           background: b.color ?? (b.muted ? NO_TIER_COLOR : "var(--primary)") }} />
          </span>
          <b style={{ minWidth: 28, textAlign: "right" }}>{b.value}</b>
        </li>
      ))}
    </ul>
  );
}

/** Tier distribution donut + legend.
 *
 *  The centre shows the SAME population the slices are drawn from, so the two
 *  always reconcile. `unranked` (contributors whose net total reaches no tier)
 *  and `noPoints` (members who earned nothing) are rendered as explicit neutral
 *  slices rather than being dropped — a slice total that silently disagrees with
 *  the centre is exactly the discrepancy this component exists to avoid.
 */
export function TierDonut({ counts, unranked = 0, noPoints = 0, centreLabel, emptyNote }: {
  counts: Record<string, number>;
  unranked?: number;
  noPoints?: number;
  centreLabel: string;
  emptyNote?: string;
}) {
  const tiers = TIER_ORDER.map((t) => ({ tier: t, count: counts[t] ?? 0 }));
  const total = tiers.reduce((n, t) => n + t.count, 0) + unranked + noPoints;
  const gradient = conic(
    [...tiers.map((t) => ({ color: TIER_COLOR[t.tier], value: t.count })),
     { color: NO_TIER_COLOR, value: unranked + noPoints }],
    total);

  return (
    <>
      <div className="flex" style={{ gap: 24 }}>
        <div className="donut" style={{ background: gradient }} data-testid="tier-donut">
          <div className="hole"><div>
            <b style={{ fontSize: 18 }}>{total}</b>
            <div className="faint small">{centreLabel}</div>
          </div></div>
        </div>
        <ul className="clean" style={{ flex: 1 }}>
          {tiers.map((t) => (
            <li key={t.tier} className="flex between">
              <span className={"tier " + t.tier.toLowerCase()}>{t.tier}</span>
              <b>{t.count}</b>
            </li>
          ))}
          {unranked > 0 && (
            <li className="flex between">
              <span className="badge gray" title="Net total reaches no tier (e.g. a negative adjustment)">
                Unranked</span><b>{unranked}</b>
            </li>
          )}
          {noPoints > 0 && (
            <li className="flex between">
              <span className="badge gray">No points yet</span><b>{noPoints}</b>
            </li>
          )}
        </ul>
      </div>
      {total === 0 && emptyNote && <p className="faint small mt-12 mb-0">{emptyNote}</p>}
    </>
  );
}
