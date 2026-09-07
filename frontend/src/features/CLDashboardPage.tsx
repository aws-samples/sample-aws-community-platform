import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { exportEndpointCsv } from "../lib/exportCsv";
import { currentQuarter, trailingQuarters } from "../lib/quarters";
import AnnouncementPanel from "../components/AnnouncementPanel";
import { ErrorState, Loading } from "../components/States";
import type { RankedBar } from "../components/charts";
import { RankedBarChart, TierDonut, TrendChart } from "../components/charts";
import Avatar from "../components/Avatar";
import { tierClass } from "../lib/tiers";
import { Leaderboard } from "./ContributionsPage";
import CertificationGrowthChart from "./certifications/CertificationGrowthChart";
import CertificationSnapshotChart from "./certifications/CertificationSnapshotChart";

// Community Leader landing dashboard (US-7.1), laid out per the
// Community Leader dashboard mockup.
//
// Built on the REAL services (contributions, identity-access) — the portal has
// no separate analytics service; these panels compute from live domain data.
//
// FRESHNESS IS MIXED, so it is labelled per panel instead of once per page:
//   * live  — Points Distributed and Points by Pillar read current rollups
//   * nightly — Total Members / New (roster snapshot) and Active Members / Tier
//     Distribution / Top Contributors (contribution sweep, DL14)
// The two nightly sources have their own timestamps; where a single line is
// shown it uses the OLDER one so freshness is never overstated.

/** "as of <local time>" for a nightly figure; null when the job has never run. */
function asOf(computedAt?: string | null): string | null {
  if (!computedAt) return null;
  const d = new Date(computedAt);
  return isNaN(d.getTime()) ? null : d.toLocaleString();
}

// Freshness labels are colour-coded so the two data cadences are visually
// distinct at a glance: nightly figures (periodic) in amber, live figures
// (real-time, refreshed on load) in green.
function NightlyNote({ computedAt }: { computedAt?: string | null }) {
  const at = asOf(computedAt);
  return (
    <span className="small" data-testid="nightly-note"
          style={{ color: "var(--warning)", fontWeight: 500 }}>
      {at ? `Updated nightly · as of ${at}` : "Updated nightly · not yet computed"}
    </span>
  );
}

/** Live-figure freshness label — green, to contrast with the amber NightlyNote. */
function LiveNote({ label }: { label: string }) {
  return (
    <span className="small" data-testid="live-note"
          style={{ color: "var(--success)", fontWeight: 500 }}>
      {label}
    </span>
  );
}

/** The OLDER of two nightly timestamps — a panel fed by two jobs is only as
 *  fresh as its stalest input, and overstating freshness is the failure mode. */
function older(a?: string | null, b?: string | null): string | null {
  if (!a) return b ?? null;
  if (!b) return a;
  return a < b ? a : b;
}

export default function CLDashboardPage() {
  const [scope, setScope] = useState<"community" | "group">("community");
  const [groupId, setGroupId] = useState("");
  const [quarter, setQuarter] = useState(currentQuarter());
  const [msg, setMsg] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const quarters = trailingQuarters(8);
  const groupsApi = useApi<{ items: { id: string; name: string }[] }>("/groups");
  const groups = groupsApi.data?.items ?? [];
  // Community-wide until a group is chosen; the picker only appears on that tab.
  const byGroup = scope === "group" && Boolean(groupId);

  // Roster snapshot (nightly). Community-wide only — the by-group tab uses the
  // group's own member count instead.
  const rosterApi = useApi<{ totalMembers?: number; newByQuarter?: Record<string, number>;
                            totalByQuarter?: Record<string, number>;
                            computedAt?: string }>("/community-stats");

  // Contribution figures. Same endpoint shape for both scopes, so the panels
  // below do not care which is selected.
  const summaryPath = byGroup
    ? `/contributions/summary/group?groupId=${encodeURIComponent(groupId)}&quarter=${quarter}`
    : `/contributions/summary/community?quarter=${quarter}`;
  const summaryApi = useApi<any>(summaryPath);
  const groupDetail = useApi<{ memberCount?: number }>(
    `/groups/${groupId}`, byGroup);

  // ---- Membership growth (US-7.1/7.3) ------------------------------------
  // Fixed trailing 4 quarters, oldest first — the axis is stable regardless of
  // which quarter is selected above, because this panel is a trend, not a
  // snapshot.
  //
  // The ACTIVE line is only definable per quarter (a member who earned a point
  // in the quarter), so the whole chart is quarterly rather than the mockup's
  // monthly axis; a monthly axis would have to invent a monthly definition of
  // "active" that no other figure on this page uses.
  //
  // Community-wide the two lines come from the two nightly jobs; by group they
  // come from the same pair of endpoints the UGL dashboard uses, so a CL sees
  // exactly what that group's leader sees.
  const chartQuarters = useMemo(() => trailingQuarters(4).slice().reverse(), []);
  const communityTrendApi = useApi<{ items?: { quarter: string; activeMembers: number | null }[];
                                     computedAt?: string | null }>(
    "/contributions/community-trend?quarters=4", !byGroup);
  const groupTrendApi = useApi<{ items?: { quarter: string; activeMembers: number }[] }>(
    `/contributions/group-trend?quarters=4&groupId=${encodeURIComponent(groupId)}`, byGroup);
  const groupGrowthApi = useApi<{ items?: { quarter: string; members: number }[] }>(
    `/groups/${groupId}/growth?quarters=4`, byGroup);

  const growthSeries = useMemo(() => {
    // MEMBERS: community-wide this is the roster snapshot, deliberately the same
    // figure as the Total Members card so the card and the line cannot disagree.
    // A quarter recorded before the nightly job first ran is UNKNOWN (null) — a
    // zero here would read as "the community had no members".
    const totalBy = rosterApi.data?.totalByQuarter ?? {};
    const growthBy = new Map((groupGrowthApi.data?.items ?? []).map((g) => [g.quarter, g.members]));
    const activeBy = new Map(
      (byGroup ? groupTrendApi.data?.items : communityTrendApi.data?.items ?? [])
        ?.map((p) => [p.quarter, p.activeMembers]) ?? []);
    return [
      {
        label: "Members", color: "var(--primary)",
        values: chartQuarters.map((qq) => (byGroup
          ? growthBy.get(qq) ?? 0            // membership history covers every quarter
          : (Object.prototype.hasOwnProperty.call(totalBy, qq) ? totalBy[qq] : null))),
      },
      {
        label: "Active members", color: "var(--accent)",
        values: chartQuarters.map((qq) => (activeBy.has(qq) ? activeBy.get(qq) ?? null : null)),
      },
    ];
  }, [byGroup, chartQuarters, rosterApi.data, groupGrowthApi.data, groupTrendApi.data,
      communityTrendApi.data]);

  // ---- Per-group breakdowns for the selected quarter (US-7.1) --------------
  // Only meaningful community-wide: the By-group tab is already scoped to one
  // group, where a cross-group comparison has nothing to compare.
  const crossGroup = !byGroup;
  const membersByGroupApi = useApi<{
    items?: { groupId: string; groupName: string; members: number }[];
    noGroup?: number | null; totalMembers?: number | null; inAnyGroup?: number | null;
    overlap?: number | null; offRoster?: number | null; computedAt?: string | null;
  }>(`/groups/stats/members?quarter=${quarter}`, crossGroup);
  // The events service holds no group registry, so it is told which groups to
  // count; the ids come from the /groups call the picker already makes.
  const groupIdsParam = groups.map((g) => g.id).join(",");
  const eventsByGroupApi = useApi<{
    items?: { groupId: string; events: number }[];
    communityWide?: number; total?: number;
  }>(`/events/stats/by-group?quarter=${quarter}&groupIds=${encodeURIComponent(groupIdsParam)}`,
     crossGroup && groups.length > 0);

  const groupNameById = useMemo(
    () => new Map(groups.map((g) => [g.id, g.name])), [groups]);

  const memberBars = useMemo<RankedBar[]>(() => {
    const rows = membersByGroupApi.data?.items ?? [];
    const bars: RankedBar[] = rows.map((r) => ({
      label: r.groupName || r.groupId, value: r.members,
    }));
    const noGroup = membersByGroupApi.data?.noGroup;
    // Only when the server could establish it — for a past quarter the roster
    // basis does not exist and a bar here would be a guess.
    if (noGroup != null) {
      bars.push({ label: "In no group", value: noGroup, muted: true });
    }
    return bars;
  }, [membersByGroupApi.data]);

  const eventBars = useMemo<RankedBar[]>(() => {
    const rows = eventsByGroupApi.data?.items ?? [];
    const bars: RankedBar[] = rows.map((r) => ({
      label: groupNameById.get(r.groupId) ?? r.groupId, value: r.events,
    }));
    const community = eventsByGroupApi.data?.communityWide;
    // Community-wide events belong to no group (BR-S1) — shown as their own bar
    // so the rows account for every event in the quarter.
    if (community != null) {
      bars.push({ label: "Community-wide", value: community, muted: true });
    }
    return bars.sort((a, b) => b.value - a.value);
  }, [eventsByGroupApi.data, groupNameById]);

  /** No snapshot for this quarter yet — distinct from "there are no groups", and
   *  the two would otherwise render the same empty chart. Reachable for quarters
   *  older than the job's first run, which cannot be backfilled. */
  const membersNotComputed = Boolean(
    membersByGroupApi.data && (membersByGroupApi.data.items ?? []).length === 0
    && membersByGroupApi.data.totalMembers == null,
  );

  /** Plain-language reconciliation for the members panel. Silence would leave a
   *  CL comparing bars against the Total Members card and finding a gap. */
  const memberCaption = useMemo(() => {
    const d = membersByGroupApi.data;
    if (!d) return null;
    if ((d.items ?? []).length === 0 && d.totalMembers == null) {
      // Nothing recorded for this quarter — do not describe reconciliation of
      // figures that do not exist.
      return null;
    }
    if (d.totalMembers == null) {
      return `Group figures are as of the end of ${quarter}. "In no group" is only `
        + "available for the current quarter.";
    }
    const parts = [`${d.inAnyGroup} of ${d.totalMembers} members belong to a user group`,
                   `${d.noGroup} in none`];
    if (d.overlap) parts.push(`${d.overlap} counted in more than one group`);
    if (d.offRoster) parts.push(`${d.offRoster} group membership(s) held by leaders or `
      + "deactivated accounts, which the member total excludes");
    return parts.join(" · ");
  }, [membersByGroupApi.data, quarter]);

  const growthLoading = byGroup
    ? (groupTrendApi.loading || groupGrowthApi.loading)
    : (communityTrendApi.loading || rosterApi.loading);
  const growthError = byGroup
    ? (groupTrendApi.error || groupGrowthApi.error)
    : communityTrendApi.error;
  // Quarters where ANY line has a measurement. Below two, there is no trend to
  // read yet and the panel says so rather than showing a lone dot unexplained.
  const measuredQuarters = chartQuarters.filter((_, i) =>
    growthSeries.some((s) => s.values[i] != null));

  const s = summaryApi.data ?? {};
  const pillars = s.pillars ?? {};
  const tierCounts: Record<string, number> = s.tierDistribution ?? {};
  const unranked = Number(s.unranked ?? 0);
  const activeContributors = Number(s.activeContributors ?? 0);
  const topContributors: any[] = s.topContributors ?? [];

  const totalMembers = byGroup
    ? Number(groupDetail.data?.memberCount ?? 0)
    : Number(rosterApi.data?.totalMembers ?? 0);
  const newThisQuarter = (rosterApi.data?.newByQuarter ?? {})[quarter] ?? 0;
  const pctActive = totalMembers > 0
    ? Math.round((activeContributors / totalMembers) * 100) : null;

  const pillarBars = useMemo(() => ([
    { label: "Upskilling", key: "pillar1", alt: false },
    { label: "Peer Learn", key: "pillar2", alt: false },
    { label: "Assets", key: "pillar3", alt: true },
    { label: "Thought Ldr", key: "pillar4", alt: true },
  ].map((p) => ({ ...p, value: Number(pillars[p.key] ?? 0) }))), [pillars]);
  // "Other" reconciliation bar: points in the total but not attributed to any
  // pillar (manual adjustments, certification auto-awards before a pillar was
  // stamped). Shown only when > 0; makes pillar bars sum to the headline total.
  const pillarSum = pillarBars.reduce((n, p) => n + p.value, 0);
  const otherPoints = Math.max(0, Number(s.totalPoints ?? 0) - pillarSum);
  const pillarMax = Math.max(1, ...pillarBars.map((p) => p.value), otherPoints);

  const scopeLabel = byGroup
    ? (groups.find((g) => g.id === groupId)?.name ?? "selected group")
    : "Community-wide";

  const doExport = async () => {
    setExporting(true);
    try {
      const params = new URLSearchParams({ quarter });
      if (byGroup) { params.set("scope", "group"); params.set("groupId", groupId); }
      const n = await exportEndpointCsv(
        `/contributions/export?${params}`,
        `contributions_${byGroup ? scopeLabel.replace(/\s+/g, "-") : "community"}_${quarter}.csv`);
      setMsg(`Exported ${n} row${n === 1 ? "" : "s"} for ${scopeLabel} · ${quarter}.`);
    } catch (e) { setMsg((e as Error).message); }
    finally { setExporting(false); }
  };

  // The shell renders immediately; every panel resolves on its own so one slow
  // or failing call can neither block nor blank the page.
  return (
    <>
      <div className="page-head">
        <h1>Community Analytics</h1>
        <p>Community-wide health and engagement. Live figures refresh on page load;
          membership and tier figures are computed nightly.</p>
      </div>

      <AnnouncementPanel />

      <div className="card mb-16">
        <div className="flex between" style={{ flexWrap: "wrap", gap: 12 }}>
          <div className="tabs" style={{ border: "none", margin: 0 }}>
            <div className={"tab" + (scope === "community" ? " active" : "")}
                 data-testid="cl-scope-community" onClick={() => setScope("community")}>
              Community-wide</div>
            <div className={"tab" + (scope === "group" ? " active" : "")}
                 data-testid="cl-scope-group" onClick={() => setScope("group")}>
              By user group</div>
          </div>
          <div className="flex" style={{ gap: 10, flexWrap: "wrap" }}>
            {scope === "group" && (
              <select className="select" style={{ width: "auto" }} data-testid="cl-group-picker"
                      value={groupId} onChange={(e) => setGroupId(e.target.value)}>
                <option value="">Select a group…</option>
                {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
              </select>
            )}
            <select className="select" style={{ width: "auto" }} data-testid="cl-quarter"
                    value={quarter} onChange={(e) => setQuarter(e.target.value)}>
              {quarters.map((qq, i) => (
                <option key={qq} value={qq}>{qq}{i === 0 ? " (current)" : ""}</option>
              ))}
            </select>
            <button className="btn" data-testid="cl-export" disabled={exporting} onClick={doExport}>
              {exporting ? "Exporting…" : "⬇ Export Data"}
            </button>
          </div>
        </div>
        {scope === "group" && !groupId && (
          <div className="card mt-12 mb-0" style={{ background: "var(--primary-light)", borderColor: "#c7dbf5", padding: 12 }}>
            <span className="small"><b>Viewing user group:</b> select a group above. Every figure
              below is then scoped to that group.</span>
          </div>
        )}
      </div>

      {msg && <div className="banner info" data-testid="cl-dash-msg">{msg}</div>}

      {scope === "group" && !groupId ? null : (
        <>
          <div className="grid cols-4 mb-16">
            <div className="card stat"><div className="ic-bubble">👥</div>
              <div className="label">{byGroup ? "Group Members" : "Total Members"}</div>
              <div className="value" data-testid="cl-stat-members">
                {(byGroup ? groupDetail.loading : rosterApi.loading) ? "…" : totalMembers}</div>
              {byGroup
                ? <div className="trend">active memberships</div>
                : <NightlyNote computedAt={rosterApi.data?.computedAt} />}
            </div>
            <div className="card stat">
              <div className="ic-bubble" style={{ background: "var(--success-bg)", color: "var(--success)" }}>✅</div>
              <div className="label">Active Members</div>
              <div className="value" data-testid="cl-stat-active">
                {summaryApi.loading ? "…" : activeContributors}</div>
              <div className="trend up">
                {pctActive == null ? "earned ≥1 point" : `${pctActive}% active`}</div>
              <NightlyNote computedAt={s.computedAt} />
            </div>
            <div className="card stat">
              <div className="ic-bubble" style={{ background: "#f3e8ff", color: "var(--accent)" }}>🆕</div>
              <div className="label">New ({quarter})</div>
              <div className="value" data-testid="cl-stat-new">
                {byGroup ? "—" : rosterApi.loading ? "…" : newThisQuarter}</div>
              {byGroup
                ? <div className="trend">community-wide only</div>
                : <NightlyNote computedAt={rosterApi.data?.computedAt} />}
            </div>
            <div className="card stat">
              <div className="ic-bubble" style={{ background: "var(--warning-bg)", color: "var(--warning)" }}>📈</div>
              <div className="label">Points Distributed</div>
              <div className="value" data-testid="cl-stat-points">
                {summaryApi.loading ? "…" : Number(s.totalPoints ?? 0)}</div>
              <div className="trend">{quarter} · live</div>
            </div>
          </div>

          {summaryApi.error && <ErrorState message={summaryApi.error} />}

          <div className="grid cols-2 mb-16">
            <div className="card">
              <div className="card-head"><h3>Membership Growth — last 4 quarters</h3>
                {/* Fed by BOTH nightly jobs community-wide, so the label uses the
                    stalest of the two. */}
                {byGroup
                  ? <LiveNote label={`Live · ${scopeLabel}`} />
                  : <NightlyNote computedAt={older(rosterApi.data?.computedAt, s.computedAt)} />}
              </div>
              {growthLoading ? <Loading />
                : growthError ? <ErrorState message={growthError} />
                  : measuredQuarters.length === 0 ? (
                    <p className="faint small mb-0" data-testid="cl-growth-empty">
                      No membership history recorded yet. The trend starts from the first
                      nightly run.</p>
                  ) : (
                    <>
                      <TrendChart quarters={chartQuarters} series={growthSeries} />
                      <p className="faint small text-c mt-12 mb-0">
                        {measuredQuarters.length === 1
                          ? `Only ${measuredQuarters[0]} has data so far — the trend fills in from next quarter.`
                          : "Active = earned at least 1 point that quarter."}
                      </p>
                    </>
                  )}
            </div>

            <div className="card">
              <div className="card-head"><h3>Tier Distribution ({quarter})</h3>
                <NightlyNote computedAt={s.computedAt} /></div>
              {summaryApi.loading ? <Loading /> : (
                // Centre counts CONTRIBUTORS, which is exactly the population the
                // slices are drawn from (tiers + unranked), so the two reconcile —
                // members who earned nothing are not a tier and are not shown here.
                <TierDonut counts={tierCounts} unranked={unranked}
                           centreLabel="contributors"
                           emptyNote="No contributors recorded for this period yet." />
              )}
            </div>
          </div>

          {crossGroup && (
            <div className="grid cols-2 mb-16">
              <div className="card">
                {/* computedAt comes from THIS endpoint's own snapshot. It used to
                    read rosterApi's, so the badge reported when a DIFFERENT job
                    last ran — and claimed "nightly" while the figures were in
                    fact computed live on every load. */}
                <div className="card-head"><h3>Members by User Group ({quarter})</h3>
                  <NightlyNote computedAt={membersByGroupApi.data?.computedAt} /></div>
                {membersByGroupApi.loading ? <Loading />
                  : membersByGroupApi.error ? <ErrorState message={membersByGroupApi.error} />
                    : (
                      <>
                        <RankedBarChart bars={memberBars} testId="cl-members-by-group"
                                        emptyNote={membersNotComputed
                                          ? `Not computed for ${quarter} yet — the nightly job records each quarter as it runs.`
                                          : "No user groups yet."} />
                        {memberCaption && (
                          <p className="faint small mt-12 mb-0">{memberCaption}</p>
                        )}
                      </>
                    )}
              </div>

              <div className="card">
                <div className="card-head"><h3>Events by User Group ({quarter})</h3>
                  <LiveNote label="Live · excludes cancelled" /></div>
                {eventsByGroupApi.loading || groupsApi.loading ? <Loading />
                  : eventsByGroupApi.error ? <ErrorState message={eventsByGroupApi.error} />
                    : (
                      <>
                        <RankedBarChart bars={eventBars} testId="cl-events-by-group"
                                        emptyNote="No user groups yet." />
                        <p className="faint small mt-12 mb-0">
                          {Number(eventsByGroupApi.data?.total ?? 0)} event
                          {Number(eventsByGroupApi.data?.total ?? 0) === 1 ? "" : "s"} in {quarter}.
                          Community-wide events belong to no single group, so they are counted
                          on their own row.</p>
                      </>
                    )}
              </div>
            </div>
          )}

          {/* Certifications (Certification Ledger enh.): growth + snapshot, following
              the dashboard's scope — community-wide, or the selected group. */}
          <div className="grid cols-2 mb-16">
            <CertificationGrowthChart groupId={byGroup ? groupId : undefined} />
            <CertificationSnapshotChart groupId={byGroup ? groupId : undefined} quarter={quarter} />
          </div>

          {/* Row 3 per the mockup: pillar breakdown beside the leaderboard. */}
          <div className="grid cols-2 mb-16">
            <div className="card">
              <div className="card-head"><h3>Points by Pillar ({quarter})</h3>
                <LiveNote label="Live" /></div>
              {summaryApi.loading ? <Loading /> : (
                <>
                  <div className="barchart">
                    {pillarBars.map((p) => (
                      <div className="col" key={p.key}>
                        <div className="val">{p.value}</div>
                        <div className={"bar" + (p.alt ? " alt" : "")}
                             style={{ height: `${Math.max(3, Math.round((p.value / pillarMax) * 100))}%` }} />
                        <div className="lbl">{p.label}</div>
                      </div>
                    ))}
                    {otherPoints > 0 && (
                      <div className="col" key="other" data-testid="pillar-other">
                        <div className="val">{otherPoints}</div>
                        <div className="bar" style={{
                          height: `${Math.max(3, Math.round((otherPoints / pillarMax) * 100))}%`,
                          background: "var(--text-faint, #94a3b8)", opacity: 0.6 }} />
                        <div className="lbl">Other</div>
                      </div>
                    )}
                  </div>
                  <p className="faint small text-c mt-12 mb-0">
                    {scopeLabel} · {quarter} · {Number(s.totalPoints ?? 0)} points
                    {otherPoints > 0 ? " · Other = points not mapped to a pillar (e.g. manual adjustments)" : ""}</p>
                </>
              )}
            </div>

            <div className="card">
              <div className="card-head"><h3>Top Contributors ({quarter})</h3>
                <NightlyNote computedAt={s.computedAt} /></div>
              {summaryApi.loading ? <Loading /> : topContributors.length === 0 ? (
                <p className="faint small mb-0">No contributors recorded for this period yet.</p>
              ) : (
                <table className="tbl">
                  <tbody>
                    {topContributors.slice(0, 5).map((r: any) => {
                      const name = (r.memberName && String(r.memberName).trim()) || "Unknown member";
                      return (
                        <tr key={r.memberId}>
                          <td>
                            <Link to={`/directory/${r.memberId}`} className="name-cell">
                              {/* Photo if the sweep captured one, initials otherwise. */}
                              <Avatar size="sm" src={r.avatar}
                                      firstName={name.split(" ")[0]} lastName={name.split(" ")[1]} />
                              {name}
                            </Link>
                          </td>
                          <td className="text-r">
                            {r.tier && <span className={tierClass(r.tier)}>{r.tier}</span>}</td>
                          <td className="text-r"><b>{r.points}</b></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              {!byGroup && topContributors.length > 0 && (
                <p className="faint small mt-12 mb-0">
                  Community ranking uses each member's highest single-group total, so points are
                  comparable within a group rather than summed across groups.</p>
              )}
            </div>
          </div>

          {/* Leaderboard moved here from the Contributions page (2026-08-11).
              Live and per-group (its own group/quarter/pillar controls), it
              complements the nightly, community-ranked Top Contributors above. */}
          <div className="card mb-16" data-testid="cl-leaderboard">
            <div className="card-head"><h3>Leaderboard</h3>
              <LiveNote label="Live · per group" /></div>
            <Leaderboard role="CommunityLeader" lockedGroupId={byGroup ? groupId : undefined} />
          </div>
        </>
      )}
    </>
  );
}
