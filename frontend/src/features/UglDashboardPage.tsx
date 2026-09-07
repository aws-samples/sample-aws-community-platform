import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { exportEndpointCsv } from "../lib/exportCsv";
import AnnouncementPanel from "../components/AnnouncementPanel";
import { ErrorState, Loading } from "../components/States";
import { tierClass, tierIcon } from "../lib/tiers";
import { quarterRange } from "../lib/quarters";
import {
  ColumnChart, NO_TIER_COLOR, TIER_COLOR, TIER_ORDER, TrendChart, conic,
} from "../components/charts";
import Avatar from "../components/Avatar";
import CertificationGrowthChart from "./certifications/CertificationGrowthChart";
import CertificationSnapshotChart from "./certifications/CertificationSnapshotChart";

// User Group Leader landing dashboard (US-7.2), laid out per the
// UGL dashboard mockup.
//
// EVERY figure on this screen is scoped to the single group the leader leads
// (BR-G7): the group id comes from their own session/token, never from a
// picker, so there is no way to read another group's numbers here.
//
// Quarter-scoped metrics (events, points, tier distribution, top contributors)
// re-fetch when the quarter selector changes.
//
// Tier distribution and top contributors are computed from the LIVE per-member
// rollups behind /contributions/leaderboard rather than from the nightly sweep
// on /contributions/summary. US-7.1/7.2 require the dashboard to show "the most
// recent data ... refreshed on page load", and the sweep is up to a day stale —
// in this environment it reported one Silver member at 50 points while the live
// rollups held Gold 85 + Silver 55 for the same quarter.

// Chart primitives and the tier donut are SHARED with the Community Leader
// dashboard (components/charts.tsx) so the same figure cannot render two
// different ways depending on which screen you are on.
const TYPE_COLORS = [
  "var(--primary)", "var(--accent)", "var(--success)", "var(--warning)",
  "var(--info)", "var(--bronze)", "var(--silver)", "#8b5cf6",
];

export default function UglDashboardPage({ ledGroupId }: { ledGroupId?: string }) {
  const enabled = Boolean(ledGroupId);
  // Trailing-quarter list comes from the API so the dashboard and the
  // Contributions screens always offer the same periods.
  const meApi = useApi<{ quarters?: string[] }>("/contributions/me");
  const quarters = meApi.data?.quarters ?? [];
  const [quarter, setQuarter] = useState("");           // "" = current quarter
  const q = quarter || quarters[0] || "";
  const range = q ? quarterRange(q) : null;

  const groupApi = useApi<{ id: string; name: string; memberCount?: number }>(
    `/groups/${ledGroupId}`, enabled);
  // Names for the top-contributor rows: the contributions rollups denormalise
  // memberName and some rows carry an empty one, so resolve against the group's
  // member list and never fall back to a raw id.
  const membersApi = useApi<{ items: any[] }>(`/groups/${ledGroupId}/members?limit=200`, enabled);
  const summaryApi = useApi<any>(`/contributions/summary/group${q ? `?quarter=${q}` : ""}`);
  // Top contributors only — a SMALL limit on purpose. The leaderboard issues one
  // profile read per returned row for the deactivated-member filter, so asking
  // it for every member turned the tier donut into hundreds of extra reads.
  // The donut now comes from group-trend, which buckets tiers in one query.
  const boardApi = useApi<{ items: any[] }>(
    `/contributions/leaderboard?groupId=${ledGroupId}&limit=5${q ? `&quarter=${q}` : ""}`,
    enabled);
  // One call powers the tier donut (selected quarter) AND the active-members
  // line (trailing 4 quarters, oldest first).
  const trendApi = useApi<{ tierCounts?: Record<string, number>; items?: any[] }>(
    `/contributions/group-trend?quarters=4${q ? `&quarter=${q}` : ""}`);
  // Membership per quarter from the append-only membership history: 8 quarters so
  // any selection in the picker is covered; the chart plots the last 4.
  const growthApi = useApi<{ items?: { quarter: string; members: number }[] }>(
    `/groups/${ledGroupId}/growth?quarters=8`, enabled);
  const eventsApi = useApi<{ items: any[] }>(
    `/events?groupId=${ledGroupId}&limit=200${range ? `&from=${range.from}&to=${range.to}` : ""}`,
    enabled);
  // Completed events per quarter by type — aggregated server-side, so the
  // response is a small matrix rather than a page of event records.
  const typeStatsApi = useApi<{
    quarters?: string[]; types?: string[];
    items?: { quarter: string; total: number; counts: Record<string, number> }[];
  }>("/events/stats/by-type?quarters=4");
  const approvalsApi = useApi<{ count: number }>("/contributions/approvals?countOnly=true");
  const verifyApi = useApi<{ count: number }>("/certifications/verifications?countOnly=true");
  // Forum moderation is live (same endpoint the /forum-moderation page and the
  // Forums view already read), so "Needs Your Attention" reports it as real work
  // instead of the placeholder line that used to sit under this card claiming the
  // Forums module was not available yet.
  const moderationApi = useApi<{ items?: any[] }>("/forums/moderation");
  const joinApi = useApi<{ count: number; total?: number }>(
    `/groups/${ledGroupId}/requests`, enabled);

  const [msg, setMsg] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const groupName = groupApi.data?.name ?? "Your group";
  const growth = growthApi.data?.items ?? [];
  // Membership AS OF the selected quarter (US-7.2) when history covers it,
  // otherwise the live count.
  const liveMemberCount = groupApi.data?.memberCount ?? 0;
  const memberCount = growth.find((g) => g.quarter === q)?.members ?? liveMemberCount;

  const nameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of membersApi.data?.items ?? []) {
      const full = [m.firstName, m.lastName].filter(Boolean).join(" ").trim();
      if (m.id && full) map.set(m.id, full);
    }
    return map;
  }, [membersApi.data]);
  // The group member list is the LIVE profile, so prefer its avatar over the
  // copy denormalised onto the scoring rollup (that one is only as fresh as the
  // member's last point event, so a photo uploaded since would not show).
  const avatarById = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of membersApi.data?.items ?? []) {
      if (m.id && m.avatar) map.set(m.id, m.avatar);
    }
    return map;
  }, [membersApi.data]);
  const displayName = (row: any) =>
    (row.memberName && String(row.memberName).trim())
    || nameById.get(row.memberId)
    || "Unknown member";
  const displayAvatar = (row: any) =>
    avatarById.get(row.memberId) || row.avatar || undefined;

  // Events held in the quarter. Series PARENT rows are containers whose
  // occurrences are separate rows, so counting them would double count;
  // cancelled events did not happen at all.
  const groupEvents = (eventsApi.data?.items ?? [])
    .filter((e) => !e.isSeries && e.status !== "Cancelled");

  const ranked = boardApi.data?.items ?? [];
  // Tier counts are computed server-side over the whole group for the selected
  // quarter, so the donut is not limited to the top-N rows fetched above.
  const serverTiers = trendApi.data?.tierCounts ?? {};
  const tierCounts = TIER_ORDER.map((t) => ({ tier: t, count: serverTiers[t] ?? 0 }));
  const withPoints = tierCounts.reduce((n, t) => n + t.count, 0);
  // Members with no ledger entry this quarter have no rollup row at all. They
  // are shown as an explicit "no points yet" slice rather than folded into the
  // lowest tier, because tier thresholds are configurable (BR-F6).
  const noPoints = Math.max(0, memberCount - withPoints);
  const donutTotal = withPoints + noPoints;

  // Trend series: membership (identity-access history) + active members
  // (contributions rollups). Both keyed by quarter so they share one axis.
  const trendPoints = trendApi.data?.items ?? [];
  const chartQuarters = trendPoints.map((p) => p.quarter);
  const growthByQuarter = new Map(growth.map((g) => [g.quarter, g.members]));
  const series = [
    {
      label: "Members", color: "var(--primary)",
      values: chartQuarters.map((qq) => growthByQuarter.get(qq) ?? 0),
    },
    {
      label: "Active members", color: "var(--accent)",
      values: trendPoints.map((p) => Number(p.activeMembers ?? 0)),
    },
  ];
  const trendLoading = trendApi.loading || growthApi.loading;

  // Events-by-type series, keyed quarter -> type -> count for the chart.
  const typeQuarters = typeStatsApi.data?.quarters ?? [];
  const eventTypes = typeStatsApi.data?.types ?? [];
  const typeCounts = Object.fromEntries(
    (typeStatsApi.data?.items ?? []).map((i) => [i.quarter, i.counts ?? {}]));
  const eventsInWindow = (typeStatsApi.data?.items ?? [])
    .reduce((n, i) => n + Number(i.total ?? 0), 0);
  const donut = conic(
    [...tierCounts.map((t) => ({ color: TIER_COLOR[t.tier], value: t.count })),
     { color: NO_TIER_COLOR, value: noPoints }],
    donutTotal);

  // Both counts are now TRUE totals. `pendingApprovals` used to be the length of
  // a read the server capped at 500, so this tile and the "Needs Your Attention"
  // line reported exactly 500 for any larger backlog.
  const pendingApprovals = approvalsApi.data?.count ?? 0;
  const pendingVerifications = verifyApi.data?.count ?? 0;
  const pendingJoins = joinApi.data?.total ?? joinApi.data?.count ?? 0;
  const pendingModeration = moderationApi.data?.items?.length ?? 0;
  const pendingReviews = pendingApprovals + pendingVerifications;

  const doExport = async () => {
    setExporting(true);
    try {
      const n = await exportEndpointCsv(
        `/contributions/export${q ? `?quarter=${q}` : ""}`,
        `contributions-${groupName.replace(/\s+/g, "-").toLowerCase()}-${q || "current"}.csv`);
      setMsg(`Exported ${n} contribution row${n === 1 ? "" : "s"} for ${groupName}.`);
    } catch (e) {
      setMsg((e as Error).message);
    } finally { setExporting(false); }
  };

  if (!enabled) {
    return (
      <ErrorState message="Your led group could not be determined. Please sign out and back in." />
    );
  }

  // The page shell renders IMMEDIATELY and every widget resolves on its own.
  // Gating the whole screen on the group read meant the slowest single call
  // decided when anything at all appeared; now the heading, layout and each
  // card arrive as their data does, and one failing panel cannot blank the page.
  return (
    <>
      <div className="page-head flex between">
        <div>
          <h1 data-testid="ugl-dash-title">
            {groupApi.loading ? "Group Dashboard" : `${groupName} — Dashboard`}</h1>
          <p>Your group's engagement at a glance.
            {groupApi.loading ? "" : ` You lead: ${groupName}.`}</p>
          {groupApi.error && <span className="small" style={{ color: "var(--danger)" }}>
            Group details unavailable: {groupApi.error}</span>}
        </div>
        <div className="flex" style={{ gap: 10 }}>
          <button className="btn" data-testid="ugl-export" disabled={exporting} onClick={doExport}>
            {exporting ? "Exporting…" : "⬇ Export Data"}
          </button>
          <select className="select" style={{ width: "auto" }} data-testid="ugl-quarter"
                  value={quarter} onChange={(e) => setQuarter(e.target.value)}>
            {quarters.map((qq, i) => (
              <option key={qq} value={i === 0 ? "" : qq}>{qq}{i === 0 ? " (current)" : ""}</option>
            ))}
          </select>
        </div>
      </div>

      {msg && <div className="banner info" data-testid="ugl-dash-msg">{msg}</div>}

      {/* Community-wide announcements + any targeting this group (US-10.4). */}
      <AnnouncementPanel />

      <div className="grid cols-4 mb-16">
        <div className="card stat"><div className="ic-bubble">👥</div>
          <div className="label">Group Members</div>
          {/* "…" rather than 0 while in flight — a flash of zero reads as real data. */}
          <div className="value" data-testid="stat-members">
            <Link className="stat-link" to="/my-group">
              {groupApi.loading && growthApi.loading ? "…" : memberCount}</Link></div>
          <div className="trend">active memberships</div></div>
        <div className="card stat">
          <div className="ic-bubble" style={{ background: "var(--success-bg)", color: "var(--success)" }}>📅</div>
          <div className="label">Group Events ({q || "current"})</div>
          {/* The quarter travels with the link, so the Events page opens on the
              same period the number was counted for. */}
          <div className="value" data-testid="stat-events">
            <Link className="stat-link" to={`/events${q ? `?quarter=${q}` : ""}`}>
              {eventsApi.loading ? "…" : groupEvents.length}</Link></div></div>
        <div className="card stat">
          <div className="ic-bubble" style={{ background: "#f3e8ff", color: "var(--accent)" }}>📈</div>
          <div className="label">Group Points ({q || "current"})</div>
          <div className="value" data-testid="stat-points">
            <Link className="stat-link" to={`/my-group?tab=points${q ? `&quarter=${q}` : ""}`}>
              {summaryApi.loading ? "…" : summaryApi.data?.totalPoints ?? 0}</Link></div></div>
        <div className="card stat">
          <div className="ic-bubble" style={{ background: "var(--warning-bg)", color: "var(--warning)" }}>📝</div>
          <div className="label">Pending Reviews</div>
          <div className="value" data-testid="stat-pending">
            {approvalsApi.loading || verifyApi.loading ? "…" : pendingReviews}</div>
          <div className="trend">contributions + verifications</div></div>
      </div>

      <div className="card mb-16">
        <div className="card-head"><h3>Membership &amp; Active Members — last 4 quarters</h3>
          <span className="faint small">Active = earned at least 1 point that quarter</span></div>
        {trendLoading ? <Loading />
          : trendApi.error ? <ErrorState message={trendApi.error} />
            : chartQuarters.length === 0 ? <p className="faint small mb-0">No trend data yet.</p>
              : <TrendChart quarters={chartQuarters} series={series} />}
      </div>

      <div className="card mb-16">
        <div className="card-head"><h3>Events by Type — last 4 quarters</h3>
          {/* Same counting rule as the Group Events card above: the group's own
              events, any status except Cancelled. */}
          <span className="faint small">Your group · excludes cancelled</span></div>
        {typeStatsApi.loading ? <Loading />
          : typeStatsApi.error ? <ErrorState message={typeStatsApi.error} />
            : eventsInWindow === 0 ? (
              <p className="faint small mb-0" data-testid="events-type-empty">
                No events for your group in the last 4 quarters yet.</p>
            ) : (
              <ColumnChart quarters={typeQuarters} types={eventTypes} counts={typeCounts}
                           colors={TYPE_COLORS} />
            )}
      </div>

      <div className="grid cols-2 mb-16">
        <div className="card">
          <h3>Group Tier Distribution ({q || "current"})</h3>
          {trendApi.loading ? <Loading /> : trendApi.error ? <ErrorState message={trendApi.error} /> : (
            <>
              <div className="flex" style={{ gap: 24 }}>
                <div className="donut" style={{ background: donut }} data-testid="tier-donut">
                  <div className="hole"><div>
                    <b style={{ fontSize: 18 }}>{donutTotal}</b>
                    <div className="faint small">members</div>
                  </div></div>
                </div>
                <ul className="clean" style={{ flex: 1 }}>
                  {tierCounts.map((t) => (
                    <li key={t.tier} className="flex between">
                      <span className={tierClass(t.tier)}>{tierIcon(t.tier)} {t.tier}</span>
                      <b>{t.count}</b>
                    </li>
                  ))}
                  {noPoints > 0 && (
                    <li className="flex between">
                      <span className="badge gray">No points yet</span><b>{noPoints}</b>
                    </li>
                  )}
                </ul>
              </div>
              {donutTotal === 0 && (
                <p className="faint small mt-12 mb-0">
                  No members with recorded points for this quarter yet.</p>
              )}
            </>
          )}
        </div>

        <div className="card">
          <div className="card-head"><h3>Top Contributors — {groupName}</h3>
            <Link className="small" to="/contributions?tab=leaderboard">Full leaderboard →</Link></div>
          {boardApi.loading ? <Loading /> : ranked.length === 0 ? (
            <p className="faint small mb-0">No points recorded for this quarter yet.</p>
          ) : (
            <table className="tbl">
              <tbody>
                {ranked.slice(0, 5).map((r) => (
                  <tr key={r.memberId}>
                    <td>
                      <Link to={`/directory/${r.memberId}`} className="name-cell">
                        <Avatar size="sm" src={displayAvatar(r)}
                                firstName={displayName(r).split(" ")[0]}
                                lastName={displayName(r).split(" ")[1]} />
                        {displayName(r)}
                      </Link>
                    </td>
                    <td className="text-r"><span className={tierClass(r.tier)}>{r.tier}</span></td>
                    <td className="text-r"><b>{r.points}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Certifications (Certification Ledger enh.): scoped to the led group. */}
      <div className="grid cols-2 mb-16">
        <CertificationGrowthChart groupId={ledGroupId} />
        <CertificationSnapshotChart groupId={ledGroupId} quarter={q || undefined} />
      </div>

      <div className="card">
        <div className="card-head"><h3>Needs Your Attention</h3></div>
        <ul className="clean" data-testid="needs-attention">
          {pendingJoins > 0 && (
            <li className="flex between">
              <span>👥 {pendingJoins} group join request{pendingJoins === 1 ? "" : "s"} pending approval</span>
              <Link className="btn sm primary" to="/my-group">Review Requests</Link></li>
          )}
          {pendingApprovals > 0 && (
            <li className="flex between">
              <span>📝 {pendingApprovals} contribution submission{pendingApprovals === 1 ? "" : "s"} awaiting approval</span>
              <Link className="btn sm primary" to="/contributions">Review</Link></li>
          )}
          {pendingVerifications > 0 && (
            <li className="flex between">
              <span>🎓 {pendingVerifications} certification claim{pendingVerifications === 1 ? "" : "s"} to verify</span>
              <Link className="btn sm primary" to="/certifications">Verify</Link></li>
          )}
          {pendingModeration > 0 && (
            <li className="flex between">
              <span>🛡️ {pendingModeration} reported forum item{pendingModeration === 1 ? "" : "s"} to moderate</span>
              <Link className="btn sm primary" to="/forum-moderation">Moderate</Link></li>
          )}
          {pendingJoins + pendingApprovals + pendingVerifications + pendingModeration === 0 && (
            <li className="faint small">✅ You're all caught up — nothing is waiting on you.</li>
          )}
        </ul>
      </div>
    </>
  );
}
