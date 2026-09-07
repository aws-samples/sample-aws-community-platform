import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useInfinitePages } from "../lib/useInfinitePages";
import { apiFetch } from "../lib/apiClient";
import { bumpNavCounts } from "../lib/navCounts";
import { EvidenceCell } from "./contributions/EvidenceCell";
import DataTable from "../components/DataTable";
import FormModal from "../components/FormModal";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import Avatar from "../components/Avatar";
import type { Role } from "../roles";
import { tierClass as tierBadge, tierIcon } from "../lib/tiers";
import { PILLARS, PILLAR_OPTIONS, pillarLabel } from "../lib/pillars";
import { useGroupName } from "../lib/useGroupName";
import AdjustPointsModal from "./contributions/AdjustPointsModal";
import PointLedgerPanel from "./contributions/PointLedgerPanel";
import { activityFilterOptions, groupFilterOptions } from "./contributions/approvalFilters";
import TopicTagInput from "../components/TopicTagInput";

// Scoring rows carry ONE denormalised `memberName`, while <Avatar> takes
// firstName/lastName (it derives the initials fallback from the two parts).
// Split here so an avatar chip can be rendered from a leaderboard row.
function nameParts(name?: string | null): [string, string] {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return [parts[0] ?? "", parts[1] ?? ""];
}

// Unit 7 Contributions & Scoring (v2.0.0). Points/tiers per group per quarter,
// derived from an append-only ledger. DL21 scope: member My Contributions +
// Leaderboard, leader Framework/Approvals/Adjust. Tier-distribution +
// community top-contributors carry an "updated daily" disclaimer (DL14).
export type Tab = "mypoints" | "leaderboard" | "framework" | "approvals" | "ledger";

export default function ContributionsPage({ role, ledGroupId, initialTab, variant = "contributions" }: { role: Role; ledGroupId?: string; initialTab?: Tab; variant?: "contributions" | "framework" }) {
  const isLeader = role === "CommunityLeader" || role === "UserGroupLeader";
  // Only a Community Leader may CHANGE the framework (BR-F6); a UGL gets the
  // same tables read-only plus their own approvals queue.
  const isCL = role === "CommunityLeader";
  const isUgl = role === "UserGroupLeader";
  const [searchParams] = useSearchParams();

  // ALL hooks are called before any early return so the hook order is identical
  // for both variants — React reuses this component's instance when navigating
  // between /contributions and /scoring-framework (same type, same Routes slot),
  // and a conditional hook would then crash the render to a blank page.
  //
  // Deep-link support (e.g. the Home "Leaderboard" button -> ?tab=leaderboard).
  // Leaderboard is available for UGLs on this page; Members now have it on the
  // Home page. A CL has it on the Community Dashboard.
  // A ?tab=leaderboard deep link is only honoured for UGLs.
  const wantsLeaderboard = searchParams.get("tab") === "leaderboard" && isUgl;
  const initial: Tab = initialTab ?? (wantsLeaderboard
    ? "leaderboard" : isLeader ? "approvals" : "mypoints");
  const [tab, setTab] = useState<Tab>(initial);

  // The "framework" variant is the CL sidebar's dedicated "Scoring Framework"
  // page (/scoring-framework): the framework config ONLY, no Leaderboard or
  // Approvals, its own title. A UGL has no sidebar link here, but the route is
  // leaderOnly so if one reaches it they get the read-only tables (BR-F6).
  if (variant === "framework") {
    return (
      <>
        <div className="page-head"><h1>Scoring Framework</h1>
          <p>Activity types and point values for the community, by pillar.</p></div>
        <Framework canEdit={isCL} />
      </>
    );
  }

  return (
    <>
      <div className="page-head"><h1>Contributions & Scoring</h1>
        <p>Points and tiers are tracked per group, per quarter.</p></div>
      <div className="tabs" style={{ marginBottom: 16 }}>
        {!isLeader && <div className={"tab" + (tab === "mypoints" ? " active" : "")} data-testid="tab-mypoints" onClick={() => setTab("mypoints")}>My Contributions</div>}
        {/* Leaderboard: Members have it on Home, CL on Community Dashboard.
            Only UGLs keep it here since their Home is the group-specific dashboard. */}
        {isUgl && <div className={"tab" + (tab === "leaderboard" ? " active" : "")} data-testid="tab-leaderboard" onClick={() => setTab("leaderboard")}>Leaderboard</div>}
        {/* Scoring Framework tab kept on this page for a UGL ONLY — they have no
            dedicated sidebar entry, so this read-only tab is their access to the
            framework. A CL configures it on its own /scoring-framework page, so
            the tab is removed here to keep the two CL menu links distinct. */}
        {isUgl && <div className={"tab" + (tab === "framework" ? " active" : "")} data-testid="tab-framework" onClick={() => setTab("framework")}>Scoring Framework</div>}
        {/* Summary tab REMOVED (user request 2026-08-10). The community/group
            roll-up it showed is on the CL Dashboard, which reads the same
            /contributions/summary endpoint — so nothing was orphaned, and the
            endpoint is still live for both leader dashboards. */}
        {isLeader && <div className={"tab" + (tab === "approvals" ? " active" : "")} data-testid="tab-approvals" onClick={() => setTab("approvals")}>Approvals</div>}
        {/* Point Ledger (US-7.9) — CL and UGL. Individual point entries for a
            group + quarter, filterable and exportable. */}
        {isLeader && <div className={"tab" + (tab === "ledger" ? " active" : "")} data-testid="tab-ledger" onClick={() => setTab("ledger")}>Point Ledger</div>}
      </div>
      {/* Members' "My Contributions" tab bundles their points/pillars AND their
          submissions (US-6.7) on one screen — there is no separate tab. */}
      {tab === "mypoints" && !isLeader && <><MyPoints /><MySubmissions /></>}
      {tab === "leaderboard" && <Leaderboard role={role} ledGroupId={ledGroupId} />}
      {tab === "framework" && isUgl && <Framework canEdit={false} />}
      {tab === "approvals" && isLeader && <Approvals role={role} ledGroupId={ledGroupId} />}
      {tab === "ledger" && isLeader && <PointLedgerPanel role={role} ledGroupId={ledGroupId} />}
    </>
  );
}

// Member "My Contributions" dashboard (US-6.10/6.11): per-group standing for a
// selected quarter — a group context switcher, quarter selector, the four
// headline stats, points-by-pillar, and the full points-history ledger below.
function MyPoints() {
  const groupName = useGroupName();
  // Base call (no group) is only used to learn the member's groups + the
  // trailing-quarter list; the per-group detail is a second, re-fetching call.
  const base = useApi<any>("/contributions/me");
  const groups: string[] = base.data?.groups ?? [];
  const quarters: string[] = base.data?.quarters ?? [];
  const [group, setGroup] = useState<string>("");
  const [quarter, setQuarter] = useState<string>(""); // "" = current quarter
  const selectedGroup = group || groups[0] || "";

  const params = new URLSearchParams();
  if (selectedGroup) params.set("groupId", selectedGroup);
  if (quarter) params.set("quarter", quarter);
  const detail = useApi<any>(`/contributions/me?${params}`, !!selectedGroup);

  if (base.loading) return <Loading />;
  if (base.comingSoon) return <ComingSoon feature="My Contributions" />;
  if (base.error) return <ErrorState message={base.error} />;
  if (groups.length === 0) {
    return (
      <div className="card text-c" style={{ padding: 32 }} data-testid="mypoints-empty">
        <div style={{ fontSize: 32 }}>📭</div>
        <h3 style={{ margin: "8px 0 4px" }}>No contributions yet</h3>
        <p className="faint mb-0">Join a user group to start earning points. Points and tiers are tracked per group, per quarter.</p>
      </div>
    );
  }

  const r = detail.data ?? {};
  const pillars = r.pillars ?? {};
  const isCurrent = !quarter || quarter === quarters[0];

  return (
    <>
      <div className="flex between mb-12" style={{ alignItems: "center", flexWrap: "wrap", gap: 12 }}>
        {/* One tab per group the member belongs to (BR-S1: per-group standing). */}
        <div className="tabs" style={{ margin: 0 }} data-testid="mypoints-groups">
          {groups.map((g) => (
            <div key={g} className={"tab" + (g === selectedGroup ? " active" : "")}
                 data-testid={`grp-tab-${g}`} onClick={() => setGroup(g)}>{groupName(g)}</div>
          ))}
        </div>
        <select className="select" style={{ width: "auto" }} data-testid="quarter-select"
                value={quarter} onChange={(e) => setQuarter(e.target.value)}>
          {quarters.map((qq, i) => <option key={qq} value={i === 0 ? "" : qq}>{qq}{i === 0 ? " (current)" : ""}</option>)}
        </select>
      </div>

      <div className="card mb-16" style={{ background: "var(--primary-light)", borderColor: "#c7dbf5" }}>
        <div className="flex between"><b>Viewing: {groupName(selectedGroup)}</b><span className="small muted">Your standing in this group</span></div>
      </div>

      {detail.fetching ? (
        <>
          {/* Skeleton stat cards — keep layout stable while fetching */}
          <div className="grid cols-4 mb-16">
            {[0,1,2,3].map((i) => (
              <div key={i} className="card stat" style={{ opacity: 0.4 }}>
                <div className="label">—</div>
                <div className="value" style={{ background: "var(--border)", borderRadius: 4, height: 36, width: "60%" }} />
              </div>
            ))}
          </div>
          <div className="card mb-16" style={{ opacity: 0.4, minHeight: 120 }}>
            <h3>Points by Pillar — {groupName(selectedGroup)}</h3>
            <Loading />
          </div>
        </>
      ) : detail.error ? <ErrorState message={detail.error} /> : (
        <>
          <div className="grid cols-4 mb-16">
            <div className="card stat"><div className="label">Lifetime (this group)</div><div className="value">{r.lifetime ?? 0}</div><div className="trend">all-time</div></div>
            <div className="card stat"><div className="label">Points ({r.quarter})</div><div className="value">{r.points ?? 0}</div></div>
            <div className="card stat"><div className="label">Tier ({r.quarter})</div><div className="value" style={{ fontSize: 20, paddingTop: 8 }}><span className={tierBadge(r.tier)}>{tierIcon(r.tier)} {r.tier ?? "—"}</span></div></div>
            {isCurrent ? (
              <div className="card stat"><div className="label">Quarter Ends</div><div className="value">{r.daysRemaining ?? "—"}</div><div className="trend">days remaining</div></div>
            ) : (
              <div className="card stat"><div className="label">Final Result</div><div className="value" style={{ fontSize: 20, paddingTop: 8 }}><span className={tierBadge(r.tier)}>{tierIcon(r.tier)} {r.tier ?? "—"}</span></div><div className="trend">quarter closed</div></div>
            )}
          </div>

          <div className="card mb-16"><h3>Points by Pillar — {groupName(selectedGroup)}</h3>
            <div className="barchart">
              {([["Upskilling", 1], ["Peer Learn", 2], ["Assets", 3], ["Thought Ldr", 4]] as [string, number][]).map(([lbl, p]) => {
                const v = pillars["pillar" + p] ?? 0;
                return (
                  <div className="col" key={p}><div className="val">{v}</div>
                    <div className={"bar" + (p >= 3 ? " alt" : "")} style={{ height: Math.min(100, v * 4) + "%" }}></div>
                    <div className="lbl">{lbl}</div></div>
                );
              })}
            </div>
            <p className="faint small text-c mt-12 mb-0">{r.quarter} · {r.points ?? 0} points in this group</p>
          </div>
        </>
      )}

      <PointsHistory quarter={quarter || quarters[0]} groupId={selectedGroup} groupName={groupName} />
    </>
  );
}

// Points history ledger (US-6.11) — scoped to the selected User Group tab and
// quarter. The scope toggle switches between the selected quarter and all-time
// within that group. Showing cross-group history when a specific group is
// selected was confusing — the User Group column now only appears in all-time
// view when it might include entries from multiple groups.
function PointsHistory({ quarter, groupId, groupName }: {
  quarter?: string;
  groupId?: string;
  groupName: (id?: string | null) => string;
}) {
  const [scope, setScope] = useState<"quarter" | "all">("quarter");
  const params = new URLSearchParams();
  params.set("scope", scope);
  if (scope === "quarter" && quarter) params.set("quarter", quarter);
  if (groupId) params.set("groupId", groupId);
  const hist = useApi<{ items: any[] }>(`/contributions/history?${params}`);
  return (
    <div className="card mt-16">
      <div className="card-head"><h3>Points History{groupId ? ` — ${groupName(groupId)}` : ""}</h3>
        <select className="select" style={{ width: "auto", padding: "5px 8px" }} data-testid="hist-scope"
                value={scope} onChange={(e) => setScope(e.target.value as "quarter" | "all")}>
          <option value="quarter">Selected quarter{quarter ? ` (${quarter})` : ""}</option>
          <option value="all">All time{groupId ? ` (this group)` : ""}</option>
        </select>
      </div>
      {hist.fetching ? (
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <Loading />
        </div>
      ) : hist.comingSoon ? <ComingSoon feature="Points history" /> : hist.error ? <ErrorState message={hist.error} /> : (
        <DataTable id="points-history" rows={hist.data?.items ?? []} hideRowsControl columns={[
          { key: "activity", header: "Activity", render: (r) => r.activity || r.reason || "—" },
          // Only show User Group column in all-time view — in quarter+group view
          // every row belongs to the same group, so the column adds no information.
          ...(!groupId || scope === "all" ? [{
            key: "groupId", header: "User Group",
            render: (r: any) => groupName(r.groupId),
          }] : []),
          { key: "pillar", header: "Pillar", render: (r) => pillarLabel(r.pillar) },
          { key: "earnedDate", header: "Date", sortValue: (r: any) => r.earnedDate ?? "", render: (r: any) => r.earnedDate ?? "—" },
          { key: "points", header: "Points", sortValue: (r: any) => Number(r.points ?? 0), render: (r: any) => <b className={"trend " + (Number(r.points) >= 0 ? "up" : "down")}>{Number(r.points) >= 0 ? "+" : ""}{r.points}</b> },
        ]} />
      )}
    </div>
  );
}

// Leaderboard dashboard (US-6.16) — per-group rankings for a selected quarter,
// optionally filtered by pillar. Top three render as a podium, the rest as a
// ranked table; the caller's own row is flagged "(You)". Rankings are only
// comparable within a group, so the group switcher is central.
export function Leaderboard({ role, ledGroupId, lockedGroupId }: { role: Role; ledGroupId?: string; lockedGroupId?: string }) {
  const groupName = useGroupName();
  const base = useApi<any>("/contributions/me");
  const me = useApi<{ id: string }>("/members/me");
  const quarters: string[] = base.data?.quarters ?? [];
  const [group, setGroup] = useState("");
  const [quarter, setQuarter] = useState("");
  const [pillar, setPillar] = useState("");

  // Which groups' leaderboards this caller may browse.
  //
  // /contributions/me returns MEMBERSHIP groups, and a User Group Leader is not
  // a member of the group they lead (BR-G7) — so for a UGL that list is empty.
  // Deriving the scope from it showed a UGL an empty board plus the nonsensical
  // "Join a user group to see its leaderboard", which is the reported bug. A
  // UGL's scope is exactly their led group.
  // A Community Leader also belongs to no group (BR-R6), so /contributions/me
  // is empty for them too — same empty-board + "Join a user group" bug as the
  // UGL case. A CL owns activity across ALL groups (US-6.16), so their scope is
  // every group, chosen from a dropdown (there can be many).
  const isUgl = role === "UserGroupLeader";
  const isCl = role === "CommunityLeader";
  const allGroups = useApi<{ items: { id: string; name: string }[] }>("/groups", isCl);
  const groups: string[] = isUgl
    ? (ledGroupId ? [ledGroupId] : [])
    : isCl
      ? (allGroups.data?.items ?? []).map((g) => g.id)
      : base.data?.groups ?? [];
  const selectedGroup = lockedGroupId || group || groups[0] || "";
  const groupLocked = Boolean(lockedGroupId);

  const params = new URLSearchParams();
  params.set("limit", "3");
  if (selectedGroup) params.set("groupId", selectedGroup);
  if (quarter) params.set("quarter", quarter);
  if (pillar) params.set("pillar", pillar);
  const lb = useApi<{ items: any[] }>(`/contributions/leaderboard?${params}`);

  if (base.loading) return <Loading />;
  if (base.comingSoon) return <ComingSoon feature="Leaderboard" />;
  if (base.error) return <ErrorState message={base.error} />;

  const rows = lb.data?.items ?? [];
  const myId = me.data?.id;
  const top3 = rows.slice(0, 3);
  const medal = ["🥇", "🥈", "🥉"];
  const medalBorder = ["#f5e6b8", "#dde1e8", "#ecd6c4"];
  const avatarBg = ["var(--gold)", "var(--silver)", "var(--bronze)"];
  // Rollup rows denormalise memberName and some carry an EMPTY string, so `??`
  // let a blank name through. Never fall back to a raw member id.
  const label = (r: any) =>
    ((r.memberName && String(r.memberName).trim()) || "Unknown member")
    + (r.memberId === myId ? " (You)" : "");

  return (
    <>
      <div className="card mb-16"><div className="flex" style={{ gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <select className="select" style={{ width: "auto" }} data-testid="lb-quarter" value={quarter} onChange={(e) => setQuarter(e.target.value)}>
          {quarters.map((qq, i) => <option key={qq} value={i === 0 ? "" : qq}>{qq}{i === 0 ? " (current)" : ""}</option>)}
        </select>
        {/* A CL can browse any group and there may be many, so use a dropdown;
            Members have few groups, so keep the tab strip.
            When lockedGroupId is set (e.g. "By user group" tab on the dashboard),
            the group selector is hidden — the leaderboard is already scoped. */}
        {!groupLocked && (isCl ? (
          (allGroups.data?.items ?? []).length > 0 && (
            <select className="select" style={{ width: "auto" }} data-testid="lb-group-select"
                    value={selectedGroup} onChange={(e) => setGroup(e.target.value)}>
              {(allGroups.data?.items ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          )
        ) : groups.length > 0 && (
          <div className="tabs" style={{ border: "none", margin: 0 }} data-testid="lb-groups">
            {groups.map((g) => <div key={g} className={"tab" + (g === selectedGroup ? " active" : "")} data-testid={`lb-grp-${g}`} onClick={() => setGroup(g)}>{groupName(g)}</div>)}
          </div>
        ))}
        <span className="spacer" style={{ flex: 1 }} />
        <select className="select" style={{ width: "auto" }} data-testid="pillar-filter" value={pillar} onChange={(e) => setPillar(e.target.value)}>
          <option value="">All pillars</option><option value="1">Upskilling</option><option value="2">Peer Learning</option><option value="3">Assets</option><option value="4">Thought Leadership</option>
        </select>
      </div></div>

      {lb.fetching ? (
        <div className="grid cols-3 mb-16">
          {[0,1,2].map((i) => (
            <div key={i} className="card text-c" style={{ opacity: 0.4, minHeight: 120 }}>
              <div style={{ fontSize: 30 }}>{"🥇🥈🥉"[i]}</div>
              <Loading />
            </div>
          ))}
        </div>
      ) : lb.comingSoon ? <ComingSoon feature="Leaderboard" /> : lb.error ? <ErrorState message={lb.error} /> : rows.length === 0 ? (
        <div className="card text-c" style={{ padding: 32 }} data-testid="lb-empty">
          <div style={{ fontSize: 32 }}>🏆</div>
          <h3 style={{ margin: "8px 0 4px" }}>No ranked members yet</h3>
          <p className="faint mb-0">{
            selectedGroup
              ? `No points recorded for ${groupName(selectedGroup)} in this period.`
              : isUgl
                ? "Your led group could not be determined. Please sign out and back in."
                : isCl
                  ? "No user groups exist yet. Create a group to see its leaderboard."
                  : "Join a user group to see its leaderboard."
          }</p>
        </div>
      ) : (
        <>
          <div className="grid cols-3 mb-16">
            {top3.map((r, i) => (
              <div key={r.memberId} className="card text-c" style={{ borderColor: medalBorder[i] }} data-testid={`lb-podium-${i + 1}`}>
                <div style={{ fontSize: 30 }}>{medal[i]}</div>
                {/* Profile photo when the member has one, medal-coloured initials
                    otherwise. `avatar` rides on the leaderboard row itself, so
                    there is no per-row profile call from the browser. */}
                <Avatar size="lg" src={r.avatar}
                        firstName={nameParts(r.memberName)[0]} lastName={nameParts(r.memberName)[1]}
                        style={{ margin: "8px auto", background: avatarBg[i] }} />
                <b>{label(r)}</b>
                <div className="muted small">{r.points} pts · {groupName(selectedGroup)}</div>
                <span className={tierBadge(r.tier)}>{tierIcon(r.tier)} {r.tier}</span>
              </div>
            ))}
          </div>
          <p className="faint small mt-12">Showing the <b>{groupName(selectedGroup)}</b> leaderboard. Switch groups above. Deactivated members are excluded. Points are not comparable across different groups.</p>
        </>
      )}
    </>
  );
}

function MySubmissions() {
  const [nonce, setNonce] = useState(0);
  const [open, setOpen] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const { data, loading, error, comingSoon } = useApi<{ items: any[] }>(`/contributions/submissions?_=${nonce}`);
  const fw = useApi<{ activities: any[] }>("/contributions/framework");
  const activityOptions = (fw.data?.activities ?? [])
    .filter((a: any) => a.active && !a.auto)
    .map((a: any) => ({ value: a.id ?? a.name, label: a.name }));
  const groupsApi = useApi<{ items: { id: string; name: string; myState?: string }[] }>("/groups");
  const allGroups = groupsApi.data?.items ?? [];
  const myGroups = allGroups.filter((g) => g.myState === "member");
  const groupOptions = myGroups.map((g) => ({ value: g.id, label: g.name }));
  const groupName = (id?: string) => allGroups.find((g) => g.id === id)?.name ?? id ?? "—";
  const withdraw = (r: any) => setConfirm({
    title: `Withdraw "${r.activity}" submission?`,
    body: (
      <><p>Your submission will be removed from the review queue. No points will be awarded.</p>
      <p>You can resubmit this activity at any time.</p></>
    ),
    confirmLabel: "Withdraw Submission",
    cancelLabel: "Keep Submission",
    onConfirm: async () => {
      await apiFetch(`/contributions/submissions/${r.id}`, { method: "DELETE" });
      setMsg("Withdrawn."); setNonce((n) => n + 1);
    },
  });
  if (loading) return <Loading />; if (comingSoon) return <ComingSoon feature="Submissions" />; if (error) return <ErrorState message={error} />;
  return (
    <div className="card mt-16"><div className="card-head"><h3>My Submissions</h3>
      <span className="btn-row">{msg && <span className="small faint">{msg}</span>}
        <button className="btn primary sm" data-testid="submit-contribution" onClick={() => setOpen(true)}>＋ Submit Contribution</button></span></div>
      <DataTable id="my-subs" rows={data?.items ?? []} columns={[
        { key: "activity", header: "Activity", render: (r) => r.activity },
        { key: "groupId", header: "Group", render: (r) => groupName(r.groupId) },
        { key: "status", header: "Status", render: (r) => <span className={"badge " + (r.status === "Approved" ? "green" : r.status === "Rejected" ? "red" : r.status === "Withdrawn" ? "gray" : "amber")}>{r.status}</span> },
        { key: "act", header: "", render: (r) => r.status === "Pending" ? <button className="btn sm" data-testid={`withdraw-${r.id}`} onClick={() => withdraw(r)}>Withdraw</button> : r.status === "Rejected" ? <button className="btn sm" onClick={() => setOpen(true)}>Resubmit</button> : null },
      ]} />
      {open && <FormModal title="Submit a Contribution" path="/contributions/submissions" onClose={() => setOpen(false)} onSaved={() => setNonce((n) => n + 1)}
        fields={[
          { name: "groupId", label: "User group", type: "select", options: groupOptions, required: true },
          { name: "activity", label: "Activity", type: "select", options: activityOptions, required: true },
          { name: "description", label: "Description", type: "textarea" },
          { name: "evidence", label: "Evidence (URL)", required: true },
          { name: "activityDate", label: "Date of activity", type: "date" },
        ]} />}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

// Scoring framework. Both leader roles can READ it, but only a Community Leader
// may change it (the framework is a single community-wide configuration, BR-F6 —
// every mutation endpoint is CL-only). A UGL therefore gets the same tables with
// no edit affordances plus a disclaimer, rather than buttons that would 403.
function Framework({ canEdit }: { canEdit: boolean }) {
  const [nonce, setNonce] = useState(0);
  const [sub, setSub] = useState<"activities" | "eventpoints" | "tiers">("activities");
  const [create, setCreate] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [editEvt, setEditEvt] = useState<any | null>(null);
  const [tiersEdit, setTiersEdit] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const { data, loading, error, comingSoon } = useApi<any>(`/contributions/framework?_=${nonce}`);
  const remove = (activity: any) => setConfirm({
    title: `Delete "${activity.name}"?`,
    body: (
      <><p>⚠️ This permanently removes the activity type from the scoring framework and cannot be undone.</p>
      <p>All <b>pending submissions</b> for this activity will be automatically rejected.</p>
      <p>Members who have already earned points through this activity are not affected — their points and approvals are preserved.</p></>
    ),
    confirmLabel: "Delete Activity",
    cancelLabel: "Keep Activity",
    onConfirm: async () => {
      await apiFetch(`/contributions/framework/${activity.id}`, { method: "DELETE" });
      setMsg("Removed."); setNonce((n) => n + 1);
    },
  });
  if (loading) return <Loading />; if (comingSoon) return <ComingSoon feature="Scoring Framework" />; if (error) return <ErrorState message={error} />;
  const fw = data ?? {};
  return (
    <>
      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (sub === "activities" ? " active" : "")} data-testid="subtab-activities" onClick={() => setSub("activities")}>Activity Types</div>
        <div className={"tab" + (sub === "eventpoints" ? " active" : "")} data-testid="subtab-event-points" onClick={() => setSub("eventpoints")}>Event Points</div>
        <div className={"tab" + (sub === "tiers" ? " active" : "")} data-testid="subtab-tiers" onClick={() => setSub("tiers")}>Quarterly Reward Tiers</div>
      </div>
      {msg && <p className="small" data-testid="framework-msg" style={{ color: "var(--success)" }}>{msg}</p>}

      {!canEdit && (
        <div className="banner info" data-testid="framework-readonly-note" role="note">
          👁 Read-only — shown for information. Only a Community Leader can change the
          scoring framework. If a change is required, please reach out to the Community Leader.
        </div>
      )}

      {sub === "activities" && (
        <>
          <div className="flex between mb-12"><h3 className="mb-0">Activity Types by Pillar</h3>
            {canEdit && <button className="btn primary sm" data-testid="create-activity" onClick={() => setCreate(true)}>＋ Add Activity</button>}</div>
          {/* Grouped by pillar (US-6.x, mirrors scoring-framework.html). Every pillar
              is shown even when empty so leaders see the full framework structure. */}
          {PILLARS.map((p) => {
            const rows = ((fw.activities ?? []) as any[]).filter((a: any) => Number(a.pillar) === p.value);
            return (
              <div className="card pad-0 mb-16" key={p.value} data-testid={`pillar-group-${p.value}`}>
                <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}><b>{p.label}</b></div>
                {rows.length === 0 ? (
                  <div className="faint small" style={{ padding: "12px 16px" }}>No activities in this pillar.</div>
                ) : (
                  <table className="tbl">
                    <thead><tr><th>Activity</th><th>Points</th><th>Evidence</th><th>Status</th>{canEdit && <th></th>}</tr></thead>
                    <tbody>
                      {rows.map((r: any) => (
                        <tr key={r.id}>
                          <td>{r.name}</td>
                          <td><b>{r.points}</b></td>
                          <td>{r.auto ? "Auto (no)" : "Required (yes)"}</td>
                          <td><span className={"badge " + (r.active ? "green" : "gray")}>{r.active ? "Active" : "Inactive"}</span></td>
                          {canEdit && <td>{r.systemDefined ? <span className="faint small">system</span> : <span className="btn-row">
                            <button className="btn sm" data-testid="edit-activity" onClick={() => setEditing(r)}>Edit</button>
                            {r.evidenceRequired && <button className="btn sm danger" data-testid="delete-activity" onClick={() => remove(r)}>Delete</button>}</span>}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            );
          })}
        </>
      )}

      {sub === "eventpoints" && (
        <div className="card" data-testid="event-points-card"><div className="card-head"><h3>Event Points</h3></div>
          <p className="faint small mt-0">Points awarded per event type — attendance for each attendee,
            delivery for the organizer/speaker. Event types are a fixed set{canEdit ? "; edit the point values below." : "."}</p>
          <table className="tbl">
            <thead><tr><th>Event Type</th><th>Attendance</th><th>Delivery</th>{canEdit && <th></th>}</tr></thead>
            <tbody>
              {((fw.eventPoints ?? []) as any[]).map((r: any) => (
                <tr key={r.eventType}>
                  <td>{r.eventType}</td>
                  <td><b>{r.attendancePoints}</b></td>
                  <td><b>{r.deliveryPoints}</b></td>
                  {canEdit && <td><button className="btn sm" data-testid="edit-event-points" onClick={() => setEditEvt(r)}>Edit</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {sub === "tiers" && (
        <div className="card" data-testid="tiers-card"><div className="card-head"><h3>Quarterly Reward Tiers</h3>
          {canEdit && <button className="btn primary sm" data-testid="edit-tiers" onClick={() => setTiersEdit(true)}>Edit Tiers</button>}</div>
          <table className="tbl">
            <thead><tr><th>Tier</th><th>Min Points</th><th>Recognition</th></tr></thead>
            <tbody>
              {((fw.tiers ?? []) as any[]).map((r: any) => (
                <tr key={r.tier}>
                  <td><span className={tierBadge(r.tier)}>{r.tier}</span></td>
                  <td><b>{r.minPoints}</b></td>
                  <td>{r.recognitionLabel}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {create && <FormModal title="Add Activity Type" path="/contributions/framework" onClose={() => setCreate(false)} onSaved={() => { setMsg("Activity added."); setNonce((n) => n + 1); }}
        fields={[{ name: "activity", label: "Activity", required: true },
                 { name: "description", label: "Description", type: "textarea" },
                 { name: "pillar", label: "Pillar", type: "select", options: PILLAR_OPTIONS, required: true },
                 { name: "points", label: "Points", required: true }]} />}
      {editing && <FormModal title={`Edit ${editing.name}`} path={`/contributions/framework/${editing.id}`} method="PUT"
        initial={{ activity: editing.name, pillar: String(editing.pillar), points: String(editing.points) }}
        onClose={() => setEditing(null)} onSaved={() => { setMsg("Activity saved."); setNonce((n) => n + 1); }}
        fields={[{ name: "activity", label: "Activity", required: true },
                 { name: "pillar", label: "Pillar", type: "select", options: PILLAR_OPTIONS },
                 { name: "points", label: "Points" }]} />}
      {editEvt && <FormModal title={`Edit Event Points — ${editEvt.eventType}`}
        path={`/contributions/event-points/${encodeURIComponent(editEvt.eventType)}`} method="PUT"
        initial={{ attendancePoints: String(editEvt.attendancePoints ?? 0), deliveryPoints: String(editEvt.deliveryPoints ?? 0) }}
        onClose={() => setEditEvt(null)} onSaved={() => { setEditEvt(null); setMsg(`Event points saved for ${editEvt.eventType}.`); setNonce((n) => n + 1); }}
        fields={[{ name: "attendancePoints", label: "Attendance points", required: true },
                 { name: "deliveryPoints", label: "Delivery points", required: true }]} />}
      {tiersEdit && <TiersEditModal tiers={(fw.tiers ?? []) as any[]}
        onClose={() => setTiersEdit(false)}
        onSaved={() => { setTiersEdit(false); setMsg("Reward tiers saved."); setNonce((n) => n + 1); }} />}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

// Quarterly Reward Tiers edit (PUT /contributions/tiers replaces the whole set).
// Tier names are the stable keys (Gold/Silver/Bronze/Rising) so only the
// threshold and recognition label are editable here.
function TiersEditModal({ tiers, onClose, onSaved }: { tiers: any[]; onClose: () => void; onSaved: () => void }) {
  const [rows, setRows] = useState(() => tiers.map((t) => ({
    tier: t.tier, minPoints: String(t.minPoints ?? 0), recognitionLabel: t.recognitionLabel ?? "",
  })));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const setRow = (i: number, key: "minPoints" | "recognitionLabel", val: string) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, [key]: val } : r)));
  const submit = async () => {
    setSaving(true); setError(null);
    try {
      const payload = { tiers: rows.map((r) => ({ tier: r.tier, minPoints: Number(r.minPoints) || 0, recognitionLabel: r.recognitionLabel })) };
      await apiFetch("/contributions/tiers", { method: "PUT", body: JSON.stringify(payload) });
      onSaved();
    } catch (e) { setError((e as Error).message); } finally { setSaving(false); }
  };
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div className="card" style={{ width: 520, maxWidth: "92vw", maxHeight: "90vh", display: "flex", flexDirection: "column" }} data-testid="tiers-modal">
        <div className="card-head" style={{ flexShrink: 0 }}><h3>Edit Quarterly Reward Tiers</h3><button className="icon-btn" onClick={onClose}>✕</button></div>
        <div style={{ overflowY: "auto", flex: "1 1 auto", minHeight: 0 }}>
          <table className="tbl">
            <thead><tr><th>Tier</th><th>Min Points</th><th>Recognition</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.tier}>
                  <td><span className={tierBadge(r.tier)}>{r.tier}</span></td>
                  <td><input className="input" type="number" min={0} style={{ width: 100 }} data-testid={`tier-min-${r.tier}`}
                             value={r.minPoints} onChange={(e) => setRow(i, "minPoints", e.target.value)} /></td>
                  <td><input className="input" data-testid={`tier-label-${r.tier}`}
                             value={r.recognitionLabel} onChange={(e) => setRow(i, "recognitionLabel", e.target.value)} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {error && <p className="small" style={{ color: "var(--danger)", flexShrink: 0 }}>{error}</p>}
        <div className="btn-row" style={{ flexShrink: 0, marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border, #e2e8f0)" }}>
          <button className="btn primary" disabled={saving} data-testid="tiers-submit" onClick={submit}>{saving ? "Saving…" : "Save"}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

// The Summary component that used to live here was removed with its tab (user
// request 2026-08-10). Its two jobs both survive elsewhere: the roll-up stats on
// CLDashboardPage/UglDashboardPage, and the aggregated CSV (US-6.14) behind the
// "Export Data" button on both leader dashboards.

// role/ledGroupId are needed by the adjust modal: a UGL's member search and group
// choices are scoped to the group they lead (FR-2, DR-1). This component took no
// ---------------------------------------------------------------- approve modal

const FORMAT_OPTIONS = ["Slides", "PDF", "Doc", "Recording", "Link"];

interface ApproveModalProps {
  submission: { id: string; memberName?: string; activity?: string; description?: string; evidence?: string };
  onClose: () => void;
  onApproved: (msg: string) => void;
}

function ApproveContributionModal({ submission, onClose, onApproved }: ApproveModalProps) {
  const [addToLibrary, setAddToLibrary] = useState(false);
  const [libTitle, setLibTitle] = useState(submission.activity || "");
  const [libDesc, setLibDesc] = useState(submission.description || "");
  const [libFormat, setLibFormat] = useState("");
  const [libTopics, setLibTopics] = useState<string[]>([]);
  // Pre-fill URL from evidence when format switches to Link
  const [libUrl, setLibUrl] = useState(submission.evidence?.startsWith("https://") ? submission.evidence : "");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const validate = () => {
    if (!addToLibrary) return "";
    if (!libTitle.trim()) return "Title is required for Library.";
    if (!libDesc.trim()) return "Description is required for Library.";
    if (!libFormat) return "Format is required for Library.";
    if (libFormat === "Link" && !libUrl.startsWith("https://"))
      return "A Link resource requires an https:// URL.";
    return "";
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validate();
    if (err) { setError(err); return; }
    setError("");
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = { decision: "approve" };
      if (addToLibrary) {
        body.addToLibrary = true;
        body.libraryTitle = libTitle.trim();
        body.libraryDescription = libDesc.trim();
        body.libraryFormat = libFormat;
        body.libraryTopics = libTopics;
        if (libFormat === "Link") body.libraryUrl = libUrl;
      } else {
        body.addToLibrary = false;
      }
      await apiFetch(`/contributions/submissions/${submission.id}/decision`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      onApproved(addToLibrary ? "Approved & added to Content Library." : "Submission approved.");
    } catch (ex: unknown) {
      setError(ex instanceof Error ? ex.message : "Approval failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" data-testid="approve-modal">
      <div className="modal" style={{ maxWidth: 520 }}>
        <div className="modal-header">
          <h2>Approve Contribution</h2>
          <button className="btn sm" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            {error && <div className="alert danger mb-12">{error}</div>}

            <div className="mb-12">
              <b>{submission.memberName || "Member"}</b>
              {submission.activity && <span className="faint small"> · {submission.activity}</span>}
            </div>

            {/* Library opt-in section */}
            <div
              className="card"
              style={{ background: "var(--surface-alt)", marginBottom: 0, padding: "12px 14px" }}
            >
              <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontWeight: 600 }}>
                <input
                  type="checkbox"
                  data-testid="add-to-library-toggle"
                  checked={addToLibrary}
                  onChange={(e) => setAddToLibrary(e.target.checked)}
                />
                📚 Add to Content Library
              </label>
              <p className="faint small mt-4 mb-0">
                Optionally publish this contribution to the community Content Library.
              </p>

              {addToLibrary && (
                <div className="mt-12" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <div>
                    <label className="field-label">Title <span className="required">*</span></label>
                    <input
                      className="input"
                      data-testid="lib-title"
                      value={libTitle}
                      maxLength={200}
                      onChange={(e) => setLibTitle(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="field-label">
                      Description <span className="required">*</span>
                      <span className="faint small" style={{ fontWeight: 400 }}> — used in search</span>
                    </label>
                    <textarea
                      className="input"
                      data-testid="lib-description"
                      value={libDesc}
                      maxLength={5000}
                      rows={3}
                      onChange={(e) => setLibDesc(e.target.value)}
                      style={{ resize: "vertical" }}
                    />
                  </div>
                  <div>
                    <label className="field-label">Format <span className="required">*</span></label>
                    <select
                      className="select"
                      data-testid="lib-format"
                      value={libFormat}
                      onChange={(e) => {
                        setLibFormat(e.target.value);
                        // Auto-populate URL from evidence when curator picks Link
                        if (e.target.value === "Link" && !libUrl && submission.evidence?.startsWith("https://")) {
                          setLibUrl(submission.evidence);
                        }
                      }}
                    >
                      <option value="">Select format…</option>
                      {FORMAT_OPTIONS.map((f) => <option key={f} value={f}>{f}</option>)}
                    </select>
                  </div>
                  {libFormat === "Link" && (
                    <div>
                      <label className="field-label">URL <span className="required">*</span></label>
                      <input
                        className="input"
                        data-testid="lib-url"
                        type="url"
                        value={libUrl}
                        onChange={(e) => setLibUrl(e.target.value)}
                        placeholder="https://…"
                      />
                    </div>
                  )}
                  <div>
                    <label className="field-label">Topics</label>
                    <TopicTagInput
                      value={libTopics}
                      onChange={setLibTopics}
                      mode="multi"
                      placeholder="Add topic tags…"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn" onClick={onClose} disabled={submitting}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn success"
              data-testid="approve-submit"
              disabled={submitting}
            >
              {submitting ? "Approving…" : addToLibrary ? "Approve & Add to Library" : "Approve"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// props before the Adjust Points rework.
function Approvals({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  const groupName = useGroupName();
  const isCl = role === "CommunityLeader";
  const [nonce, setNonce] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const [adjust, setAdjust] = useState(false);
  const [approvingSubmission, setApprovingSubmission] = useState<any | null>(null);
  const [groupFilter, setGroupFilter] = useState("");
  const [activityFilter, setActivityFilter] = useState("");

  // Filter option sources — complete lists from dedicated endpoints, NOT derived
  // from the visible page. Under cursor paging a page-derived dropdown would only
  // offer the values that happen to sit on page 1. Same approach as the
  // certifications verification queue.
  const allGroups = useApi<{ items: { id: string; name: string }[] }>("/groups", isCl);
  // `id`, not `activityId` — /contributions/framework returns the activity's
  // identifier as `id` (see the Activity schema in the contract). Reading a field
  // that does not exist yields undefined, and React then falls back to using the
  // <option>'s text as its value, so the filter silently sent the activity NAME
  // ("Public speaking") where the server matches on the id ("public-speaking")
  // and every filtered query came back empty.
  const fw = useApi<{ activities: { id: string; name: string }[] }>(
    "/contributions/framework");

  // Server-side cursor pagination (the queue is oldest-first over one sparse
  // index). Filters live in the endpoint string so changing one resets to page 1;
  // useInfinitePages appends limit/cursor. The nonce reloads after a decision.
  //
  // This used to read the whole pending set in a single response, which the
  // server capped at 500 rows — and because the order is oldest-first, anything
  // behind a 500-deep backlog was unreachable, so newly submitted contributions
  // could not be approved at all. The filters exist so a leader can jump
  // straight to a member/group/activity rather than paging through thousands.
  const params = new URLSearchParams();
  if (isCl && groupFilter) params.set("groupId", groupFilter);
  if (activityFilter) params.set("activityId", activityFilter);
  params.set("_", String(nonce));
  const pages = useInfinitePages<any>(`/contributions/approvals?${params.toString()}`);
  const { rows, error, comingSoon } = pages;

  const groupOptions = groupFilterOptions(allGroups.data?.items);
  const activityOptions = activityFilterOptions(fw.data?.activities);

  const reject = async (id: string) => {
    const reason = window.prompt("Reason for rejection?") ?? "";
    if (!reason) return;
    try {
      await apiFetch(`/contributions/submissions/${id}/decision`, {
        method: "POST", body: JSON.stringify({ decision: "reject", reason }),
      });
      setMsg("Submission rejected."); setNonce((n) => n + 1); bumpNavCounts();
    } catch (e) { setMsg((e as Error).message); }
  };

  if (comingSoon) return <ComingSoon feature="Approvals" />; if (error) return <ErrorState message={error} />;
  return (
    <div className="card">
      <div className="card-head"><h3>Pending Approvals</h3>
        <span className="btn-row">{msg && <span className="small faint">{msg}</span>}
          <button className="btn sm" data-testid="adjust-points" onClick={() => setAdjust(true)}>± Adjust points</button></span></div>
      <div className="flex mb-12" style={{ gap: 10 }}>
        {isCl && (
          <select className="select" style={{ width: "auto" }} data-testid="approvals-filter-group"
                  value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
            <option value="">All user groups</option>
            {groupOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
        )}
        <select className="select" style={{ width: "auto" }} data-testid="approvals-filter-activity"
                value={activityFilter} onChange={(e) => setActivityFilter(e.target.value)}>
          <option value="">All activities</option>
          {activityOptions.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
      </div>
      {adjust && <AdjustPointsModal role={role} ledGroupId={ledGroupId}
        onClose={() => setAdjust(false)} onSaved={(m) => setMsg(m)} />}
      {approvingSubmission && (
        <ApproveContributionModal
          submission={approvingSubmission}
          onClose={() => setApprovingSubmission(null)}
          onApproved={(m) => { setMsg(m); setApprovingSubmission(null); setNonce((n) => n + 1); bumpNavCounts(); }}
        />
      )}
      <DataTable id="approvals" rows={rows}
        infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                    hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "submissions" }}
        emptyLabel="No pending approvals match the current filters." columns={[
        { key: "memberName", header: "Member", render: (r) => (r.memberName && String(r.memberName).trim()) || "Unknown member" },
        { key: "groupId", header: "Group", render: (r) => groupName(r.groupId) },
        { key: "activity", header: "Activity", render: (r) => r.activity },
        // EvidenceCell, never r.evidence directly: this is the leader approval
        // queue, and submissions stored before the server-side https check
        // shipped may still hold a `javascript:` URI. See EvidenceCell.tsx —
        // it is a named component so the behaviour is actually testable.
        { key: "evidence", header: "Evidence", render: (r) => <EvidenceCell value={r.evidence} /> },
        { key: "act", header: "Decision", render: (r) => <span className="btn-row">
          <button className="btn sm success" data-testid={`approve-${r.id}`} onClick={() => setApprovingSubmission(r)}>Approve</button>
          <button className="btn sm danger" data-testid={`reject-${r.id}`} onClick={() => reject(r.id)}>Reject</button></span> },
      ]} />
      <p className="faint small mt-12">Oldest first, loaded a page at a time as you scroll — use the
        filters above to narrow a large backlog. Approving awards points immediately; rejecting
        requires a reason.</p>
    </div>
  );
}
