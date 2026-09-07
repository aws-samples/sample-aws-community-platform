import { useMemo, useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useInfinitePages } from "../lib/useInfinitePages";
import { useMemberRollups } from "../lib/useMemberRollups";
import { apiFetch } from "../lib/apiClient";
import { bumpNavCounts } from "../lib/navCounts";
import { refreshMembershipClaims } from "../lib/refreshMembership";
import DataTable from "../components/DataTable";
import GroupModal from "../components/GroupModal";
import Avatar from "../components/Avatar";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import ToastStack, { useToasts } from "../components/ToastStack";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import { tierClass, tierIcon } from "../lib/tiers";
import { exportPagedCsv } from "../lib/exportCsv";
import type { Role } from "../roles";

// Group detail (US-1.13..1.19/1.22..1.25) — overview + members, join requests,
// leader assignment, membership history; join/leave; leader edit/delete.
export default function GroupDetailPage({ role }: { role: Role }) {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [nonce, setNonce] = useState(0);
  const [tab, setTab] = useState<"members" | "requests" | "history">("members");
  const [edit, setEdit] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const [joining, setJoining] = useState(false);
  const { toasts, success, error: toastError, dismissToast } = useToasts();

  // Bridge for child components that use the legacy onMsg(string) callback
  const onMsg = (m: string) => {
    const isError = /^(The |An |Cannot |Failed|Unable|Invalid|Forbidden|Not found|Unauthorized)/i.test(m)
      || m.includes("error") || m.includes("Error");
    if (isError) toastError(m); else success(m);
  };
  // Role gating mirrors the permission matrix (SECURITY-08):
  // - join/leave: Member only (CLs hold no memberships US-1.8/1.9; UGLs lead
  //   their group and cannot join or leave — decided 2026-08-03; leadership
  //   changes are a Community Leader function)
  // - edit/delete/assign-leader: CommunityLeader only (group config is a CL function, BR-G2)
  // - join-request decisions: UserGroupLeader, own group (BR-G8)
  const canJoin = role === "Member";
  const canLeave = role === "Member";
  const isCL = role === "CommunityLeader";
  const isUGL = role === "UserGroupLeader";
  const g = useApi<any>(`/groups/${id}?_=${nonce}`);
  // Group switcher (US-1.16 — a Community Leader may view the member list of
  // ANY group, per the leader group-members mockup).
  const groups = useApi<{ items: any[] }>("/groups", isCL);

  const act = async (path: string, method: "POST" | "DELETE" = "POST", body?: unknown, done?: string) => {
    try {
      await apiFetch(path, { method, body: body ? JSON.stringify(body) : undefined });
      success(done || "Action completed successfully.");
      setNonce((n) => n + 1);
      // Same reason as MyGroupPage: AppLayout's pending pills share no cache
      // with this page. Removing a member, or soft-deleting the group, rejects
      // their pending submissions and claims, which empties queues the sidebar
      // is counting.
      bumpNavCounts();
    } catch (e) { toastError((e as Error).message); }
  };

  if (g.loading) return <Loading />;
  if (g.comingSoon) return <ComingSoon feature="Group detail" />;
  if (g.error) return <ErrorState message={g.error} />;
  const grp = g.data ?? {};
  // Only the Member role is group-scoped on the directory; a CL sees any group's
  // roster and a UGL keeps the directory-wide view they already had.
  const canViewMembers = role !== "Member" || grp.myState === "member";

  return (
    <>
      <div className="page-head flex between">
        <div>
          <div className="breadcrumb"><Link to="/groups">User Groups</Link> › {grp.name} › {
            tab === "members" ? "Members" : tab === "requests" ? "Join Requests" : "Membership History"}</div>
          <h1>{grp.name}</h1>
          <p>{grp.description} · {grp.memberCount ?? 0} members · <span className="badge blue">{grp.approvalRequired ? "Approval required" : "Open"}</span>
            {grp.myState === "member" && <span className="badge green" style={{ marginLeft: 6 }}>Joined</span>}
            {grp.myState === "requested" && <span className="badge amber" style={{ marginLeft: 6 }}>Requested</span>}</p>
          {(grp.leaders ?? []).length > 0 && (
            <p data-testid="group-leaders">Led by: {(grp.leaders ?? []).map((l: any, i: number) => (
              <span key={l.id}>{i > 0 && ", "}
                <Link to={`/directory/${l.id}`}><b>{`${l.firstName} ${l.lastName}`.trim() || l.id}</b></Link>
                {" "}<span className="badge blue">User Group Leader</span>
              </span>
            ))}</p>
          )}
        </div>
        <span className="btn-row">
          {/* CL-only group switcher — stay on the current tab, swap the group. */}
          {isCL && (groups.data?.items ?? []).length > 0 && (
            <select className="select" style={{ width: "auto" }} data-testid="group-switcher"
                    value={id} onChange={(e) => navigate(`/groups/${e.target.value}`)}>
              {(groups.data?.items ?? []).map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          )}
          {/* State-aware (myState from getGroup, 2026-08-04): exactly one of
              Join / Withdraw / Leave — mirrors the User Groups list. */}
          {/* Re-mint the ID token after a real membership change so the new
              group claim applies at once — the directory and event ideas are
              scoped by it. Skipped for approval-required groups: the request is
              only pending, so membership has not changed yet. */}
          {canJoin && !grp.myState && <button className="btn sm primary" disabled={joining}
            onClick={async () => { setJoining(true); try { await act(`/groups/${id}/join`, "POST", undefined, grp.approvalRequired ? "Join request sent — a leader needs to approve it." : "You have joined the group."); if (!grp.approvalRequired) await refreshMembershipClaims(); } finally { setJoining(false); } }}>
            {joining ? <><span className="spinner-sm" /> {grp.approvalRequired ? "Requesting…" : "Joining…"}</> : grp.approvalRequired ? "Request to Join" : "Join"}</button>}
          {canJoin && grp.myState === "requested" && <button className="btn sm" onClick={() => act(`/groups/${id}/join/withdraw`, "POST", undefined, "Join request withdrawn.")}>Withdraw</button>}
          {canLeave && grp.myState === "member" && <button className="btn sm" onClick={async () => { await act(`/groups/${id}/leave`, "POST", undefined, "You left the group."); await refreshMembershipClaims(); }}>Leave</button>}
          {isCL && <button className="btn sm" data-testid="edit-group" onClick={() => setEdit(true)}>Edit</button>}
          {isCL && <button className="btn sm danger" data-testid="delete-group" onClick={() => setConfirm({
            title: `Delete "${grp.name}"?`,
            body: (
              <><p>⚠️ This will immediately remove all <b>{grp.memberCount ?? 0} members</b>, cancel upcoming events, hide forums, and reject all pending submissions and join requests.</p>
              <p>Earned points, tiers, and approved certifications are not affected.</p>
              <p>You have <b>14 days to undo this</b> from the User Groups page. After that, all data is permanently deleted and members must rejoin manually.</p></>
            ),
            confirmLabel: "Delete Group",
            cancelLabel: "Keep Group",
            onConfirm: () => act(`/groups/${id}`, "DELETE", undefined, "Group deleted (recoverable for 2 weeks)."),
          })}>Delete</button>}
        </span>
      </div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (tab === "members" ? " active" : "")} data-testid="tab-members" onClick={() => setTab("members")}>Members</div>
        {(isUGL || isCL) && <div className={"tab" + (tab === "requests" ? " active" : "")} data-testid="tab-requests" onClick={() => setTab("requests")}>Join Requests</div>}
        <div className={"tab" + (tab === "history" ? " active" : "")} onClick={() => setTab("history")}>Membership History</div>
      </div>

      {/* The member list is GET /members?groupId=…, which is group-scoped for the
          Member role — a Member who has not joined THIS group gets a 403. The tab
          stays visible (the group's name, description and leaders are public, which
          is what lets people decide whether to join) but the roster is replaced with
          the reason, rather than letting the fetch fail into a red error box. */}
      {tab === "members" && (canViewMembers
        ? <Members id={id} group={grp} nonce={nonce}
                   canAssign={isCL} canRemove={isCL || isUGL} onAct={act} onMsg={onMsg}
                   onConfirm={setConfirm} />
        : <div className="card"><p className="faint">
            Join this group to see who else is in it.
          </p></div>)}
      {tab === "requests" && (isUGL || isCL) && <Requests id={id} nonce={nonce} onAct={act} />}
      {tab === "history" && <History id={id} />}

      {/* US-1.18 — full create-field parity incl. leader add/change/remove. */}
      {edit && <GroupModal group={grp}
        onClose={() => setEdit(false)} onSaved={() => setNonce((n) => n + 1)} />}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

// Group members (US-1.16/1.17), built to the leader group-members mockup:
// stat strip, in-toolbar search, Member / Role in group / Points (Q2) / Tier columns,
// CSV export. Server-side cursor pagination + debounced search mirror the Member
// Directory and Admin Users tables — a group can hold 13k+ members, so the old
// "fetch every member, page in the browser" approach does not hold (D-P5/D-P6).
function Members({ id, group, nonce, canAssign, canRemove, onAct, onMsg, onConfirm }: {
  id: string; group: any; nonce: number; canAssign: boolean; canRemove: boolean;
  onAct: any; onMsg: (m: string) => void; onConfirm: (opts: ConfirmOptions) => void;
}) {
  // Members are searched through the OpenSearch directory (GET /members) scoped
  // to this group — full-text over name/email/skills/bio, cursor pagination,
  // infinite scroll — so a 28k-member group is served like the Member Directory.
  // Nothing loads until Search is clicked (empty query lists the whole group).
  const [q, setQ] = useState("");
  const [activeSearch, setActiveSearch] = useState<string | null>(null);
  const doSearch = () => setActiveSearch(q.trim());
  const endpoint = activeSearch === null ? null
    : `/members?groupId=${encodeURIComponent(id)}`
      + (activeSearch ? `&q=${encodeURIComponent(activeSearch)}` : "")
      + `&sort=firstName&sortDir=asc&_=${nonce}`;
  const pages = useInfinitePages<any>(endpoint);

  // Bounded per-group leaderboard roll-up drives the points/tier columns AND the
  // stat cards below (independent of the member search).
  const board = useApi<{ items: { memberId: string; points?: number; tier?: string }[] }>(
    `/contributions/leaderboard?groupId=${id}&limit=500`, Boolean(id));
  const rollups = board.data?.items ?? [];
  const scoringLive = !board.comingSoon && !board.error && rollups.length > 0;

  // Row-level points/tier come from a per-page hydration (BatchGetItem by the
  // visible member ids) so they're correct at any group size; the stat cards
  // above stay on the bounded leaderboard aggregate.
  const memberIds = useMemo(() => pages.rows.map((r: any) => r.id).filter(Boolean), [pages.rows]);
  const pageRollups = useMemberRollups(id, memberIds);

  // Leaders of THIS group — badged, shielded from Remove, and not offered "Make
  // leader". Derived from the group record (the directory row has no per-group role).
  const leaderIds = useMemo(() => new Set<string>([
    ...((group.leaders ?? []).map((l: any) => l.id)),
    ...((group.leaderIds ?? [])),
  ].filter(Boolean)), [group]);

  const memberCount = group.memberCount ?? 0;
  const leaderCount = (group.leaders ?? group.leaderIds ?? []).length;
  const activeCount = rollups.filter((r: any) => Number(r.points) > 0).length;
  const groupPoints = rollups.reduce((sum: number, r: any) => sum + Number(r.points ?? 0), 0);
  const fmtPoints = (n: number) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n));

  const doExport = async () => {
    try {
      // Cursor-following (13k+ members do not fit in one response).
      const n = await exportPagedCsv(`/groups/${id}/members`, `group-members_${group.name ?? id}.csv`);
      onMsg(`Exported ${n} members.`);
    } catch (e) { onMsg((e as Error).message); }
  };

  return (
    <>
      <div className="grid cols-4 mb-16">
        <div className="card stat"><div className="label">Members</div>
          <div className="value" data-testid="stat-members">{memberCount}</div></div>
        <div className="card stat"><div className="label">Leaders</div>
          <div className="value" data-testid="stat-leaders">{leaderCount}</div></div>
        <div className="card stat"><div className="label">Active (qtr)</div>
          <div className="value" data-testid="stat-active">{scoringLive ? activeCount : "—"}</div>
          {scoringLive && memberCount > 0 && (
            <div className="trend up">{Math.round((activeCount / memberCount) * 100)}%</div>)}</div>
        <div className="card stat"><div className="label">Group Points (Qtr)</div>
          <div className="value" data-testid="stat-points">{scoringLive ? fmtPoints(groupPoints) : "—"}</div></div>
      </div>

      <div className="card pad-0">
        <div className="flex between" style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
          <b>Members</b>
          <span className="btn-row" style={{ alignItems: "center" }}>
            <input className="input" style={{ width: 280 }}
                   placeholder="Search by name, email, skills, or bio…"
                   data-testid="group-member-search" value={q}
                   onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }} />
            <button className="btn sm primary" data-testid="group-member-search-btn"
                    onClick={doSearch}>Search</button>
            <button className="btn sm" data-testid="export-group-members" onClick={doExport}>⬇ Export</button>
          </span>
        </div>
        <div style={{ padding: "0 14px" }}>
          {activeSearch === null ? (
            <p className="faint" data-testid="group-member-prompt" style={{ padding: "16px 4px" }}>
              Search this group's members by name, email, skills, or bio — or click Search with an
              empty box to list everyone in {group.name ?? "the group"}.
            </p>
          ) : pages.error ? <ErrorState message={pages.error} /> :
          <DataTable id="group-members" rows={pages.rows}
            infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                        hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "members" }}
            emptyLabel="No members match your search."
            columns={[
              { key: "name", header: "Member", render: (m: any) => (
                <Link to={`/directory/${m.id}`} className="name-cell">
                  <Avatar firstName={m.firstName} lastName={m.lastName} src={m.avatar} size="sm" />
                  <b>{`${m.firstName ?? ""} ${m.lastName ?? ""}`.trim() || m.email}</b>
                </Link>) },
              { key: "email", header: "Email", render: (m: any) => (
                m.email || <span className="faint small">—</span>) },
              // Role WITHIN this group (leaders are listed alongside members);
              // derived from the group record, not the directory row.
              { key: "roleInGroup", header: "Role in group", render: (m: any) => (
                leaderIds.has(m.id)
                  ? <span className="badge blue">User Group Leader</span>
                  : <span className="badge gray">Member</span>) },
              { key: "points", header: "Points (Qtr)", render: (m: any) => {
                const p = pageRollups.rollupById.get(m.id)?.points;
                return p == null ? <span className="faint small">—</span> : p;
              } },
              { key: "tier", header: "Tier", render: (m: any) => {
                const t = pageRollups.rollupById.get(m.id)?.tier;
                if (!t) return <span className="faint small">—</span>;
                return <span className={tierClass(t)}>{tierIcon(t)} {t}</span>;
              } },
              { key: "act", header: "", render: (m: any) => (canAssign || canRemove)
                ? <span className="btn-row">
                    {canAssign && !leaderIds.has(m.id) &&
                      <button className="btn sm" data-testid="assign-leader"
                              onClick={() => onAct(`/groups/${id}/leaders`, "POST", { memberId: m.id })}>Make leader</button>}
                    {canRemove && !leaderIds.has(m.id) && <button className="btn sm danger" data-testid="remove-member"
                              onClick={() => {
                                const name = `${m.firstName ?? ""} ${m.lastName ?? ""}`.trim() || m.email || m.id;
                                onConfirm({
                                  title: `Remove "${name}" from ${group.name}?`,
                                  body: (
                                    <><p>⚠️ This will immediately remove them from the group and they will lose access to its forums.</p>
                                    <p>Any <b>pending contribution submissions</b> and <b>pending certification claims</b> they have credited to this group will be automatically rejected.</p>
                                    <p>Earned points, tier badges, and approved certifications are not affected.</p>
                                    <p>This cannot be undone. The member can rejoin the group afterwards.</p></>
                                  ),
                                  confirmLabel: "Remove Member",
                                  cancelLabel: "Keep Member",
                                  onConfirm: () => onAct(`/groups/${id}/members/${m.id}`, "DELETE"),
                                });
                              }}>Remove</button>}
                  </span> : null },
            ]} />}
        </div>
      </div>
      {!scoringLive && (
        <p className="faint small mt-12" data-testid="scoring-pending">
          Points and tier come from the Contributions &amp; Scoring service, which is not live yet — those
          columns and the two right-hand stats show “—” until it is.
        </p>
      )}
    </>
  );
}

function Requests({ id, nonce, onAct }: { id: string; nonce: number; onAct: any }) {
  const reqs = useApi<{ items: any[] }>(`/groups/${id}/requests?_=${nonce}`);
  if (reqs.loading) return <Loading />;
  if (reqs.comingSoon) return <ComingSoon feature="Join requests" />;
  if (reqs.error) return <ErrorState message={reqs.error} />;
  // Reject requires a reason (US-1.21); the member is notified and may re-request.
  const reject = (r: any) => {
    const reason = window.prompt("Reason for rejecting this request (required):", "");
    if (reason === null) return; // cancelled
    onAct(`/groups/${id}/requests/${r.id}`, "POST", { decision: "reject", reason });
  };
  return (
    <div className="card">
      <div className="card-head"><h3>Join Requests</h3></div>
      <DataTable id="join-requests" rows={reqs.data?.items ?? []} columns={[
        { key: "member", header: "Member", render: (r) => r.memberName || r.memberEmail || r.memberId },
        { key: "status", header: "Status", render: (r) => <span className="badge amber">{r.status}</span> },
        { key: "act", header: "Decision", render: (r) => <span className="btn-row">
          <button className="btn sm primary" data-testid="approve-request" onClick={() => onAct(`/groups/${id}/requests/${r.id}`, "POST", { decision: "approve" })}>Approve</button>
          <button className="btn sm danger" data-testid="reject-request" onClick={() => reject(r)}>Reject</button></span> },
      ]} />
    </div>
  );
}

function History({ id }: { id: string }) {
  // Scoped to this group (US-1.34 supports groupId filtering server-side) and
  // PAGED: a 13k-member group's history is tens of thousands of events and the
  // unpaged branch resolves a display name for every row. Newest first.
  //
  // Infinite scroll rather than Prev/Next + a Rows dropdown: history is an
  // append-only stream read newest-first, so "page 7 of 214" is not a place
  // anyone means to return to, and the cursor is opaque (it cannot be turned
  // into a page number anyway). Passing `infinite` also drops the Rows control
  // and renders the progress bar, skeleton, "Loading more…" row and
  // "All N loaded" footer — same as the Members tab above.
  const pages = useInfinitePages<any>(`/membership-history?groupId=${encodeURIComponent(id)}`);

  if (pages.comingSoon) return <ComingSoon feature="Membership history" />;
  if (pages.error) return <ErrorState message={pages.error} />;
  const fmt = (iso?: string) => iso
    ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "—";
  return (
    <div className="card">
      <div className="card-head"><h3>Membership History</h3></div>
      <DataTable id="membership-history" rows={pages.rows}
        infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                    hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "entries" }}
        emptyLabel="No membership history for this group yet."
        columns={[
          { key: "member", header: "Member", render: (h) => h.memberName || h.memberId },
          { key: "group", header: "Group", render: (h) => h.groupName || h.groupId },
          { key: "type", header: "Event", render: (h) => <span className="badge blue">{h.type}</span> },
          { key: "at", header: "When", render: (h) => fmt(h.at) },
        ]} />
    </div>
  );
}
