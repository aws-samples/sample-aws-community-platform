import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { bumpNavCounts } from "../lib/navCounts";
import DataTable from "../components/DataTable";
import Avatar from "../components/Avatar";
import ToastStack, { useToasts } from "../components/ToastStack";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import { tierClass, tierIcon } from "../lib/tiers";
import { dateOnly, exportPagedCsv } from "../lib/exportCsv";
import { useAsyncExport } from "../lib/useAsyncExport";
import AsyncExportPanel from "../components/AsyncExportPanel";
import { useInfinitePages } from "../lib/useInfinitePages";
import { useMemberRollups } from "../lib/useMemberRollups";
import { currentQuarter, trailingQuarters } from "../lib/quarters";

// "My Group" — the User Group Leader's single-group screen, built to the
// UGL group mockup.
//
// A UGL leads exactly one group (US-1.12, BR-G7), so this replaces the User
// Groups directory in their sidebar: there is no group list and no group
// switcher, the heading IS the group name, and the group id comes from the
// session rather than the URL. Scope of what a UGL may do here follows the
// permission matrix and the stories:
//   - manage members of the led group only (US-1.16) and remove them (US-1.17)
//   - decide join requests for the led group only (US-1.21)
//   - create/manage forums within their own group (US-4.1–4.4/4.14)
//   - NOT edit group configuration (US-1.18) — hence no Edit/Delete buttons,
//     matching the mockup's "Group settings are managed by a Community Leader."
export default function MyGroupPage({ ledGroupId }: { ledGroupId?: string }) {
  const [nonce, setNonce] = useState(0);
  // Deep-linkable: the dashboard's "Group Points" figure links straight to this
  // tab for the quarter it was counted for (?tab=points&quarter=YYYY-Qn).
  const [searchParams] = useSearchParams();
  const linkedTab = searchParams.get("tab");
  const linkedQuarter = searchParams.get("quarter") || "";
  const [tab, setTab] = useState<"overview" | "requests" | "points">(
    linkedTab === "points" ? "points" : linkedTab === "requests" ? "requests" : "overview");
  const { toasts, success, error: toastError, dismissToast } = useToasts();

  // Bridge for child components that use the legacy onMsg(string) pattern.
  // Success messages are short and descriptive; error messages come from catch blocks.
  const onMsg = (m: string) => {
    // Heuristic: API errors typically start with uppercase and contain specific patterns
    const isError = /^(The |An |Cannot |Failed|Unable|Invalid|Forbidden|Not found|Unauthorized)/i.test(m)
      || m.includes("error") || m.includes("Error");
    if (isError) toastError(m); else success(m);
  };

  const g = useApi<any>(ledGroupId ? `/groups/${ledGroupId}?_=${nonce}` : "", Boolean(ledGroupId));
  // Pending-request COUNT for the tab badge + heading (shown while any tab is
  // open). limit=1 returns the true `total` cheaply; the Requests table loads
  // its own infinite-scroll pages.
  const reqs = useApi<{ count: number; total?: number }>(
    ledGroupId ? `/groups/${ledGroupId}/requests?limit=1&_=${nonce}` : "", Boolean(ledGroupId));

  const act = async (path: string, method: "POST" | "DELETE" = "POST", body?: unknown) => {
    try {
      await apiFetch(path, { method, body: body ? JSON.stringify(body) : undefined });
      success("Action completed successfully.");
      setNonce((n) => n + 1);
      // The local nonce only refetches THIS page. The sidebar's pending-count
      // pills are fetched independently by AppLayout and share no cache, so
      // without this a UGL who approved the last join request kept seeing (1)
      // on My Group while this page correctly showed 0.
      //
      // Fired for every action through this funnel, not just join decisions:
      // removing a member auto-rejects their pending contribution submissions
      // and certification claims (see the confirm copy in Members), so the
      // Contributions and Certifications pills go stale on that path too.
      bumpNavCounts();
    } catch (e) { toastError((e as Error).message); }
  };

  // A UserGroupLeader always has a led group (it is what makes them one), so
  // this is a stale-session guard rather than an expected state.
  if (!ledGroupId) {
    return (
      <>
        <div className="page-head"><h1>My Group</h1></div>
        <div className="card" data-testid="no-led-group">
          <p className="muted mb-0">
            Your account is not currently assigned to a user group. A Community Leader assigns
            group leadership (US-1.10) — once assigned, sign in again and your group will appear here.
          </p>
        </div>
      </>
    );
  }

  if (g.loading) return <Loading />;
  if (g.comingSoon) return <ComingSoon feature="My Group" />;
  if (g.error) return <ErrorState message={g.error} />;
  const grp = g.data ?? {};
  const pendingCount = reqs.data?.total ?? reqs.data?.count ?? 0;

  return (
    <>
      {/* Mockup: the heading is the group name, not the literal "My Group". */}
      <div className="page-head flex between">
        <div>
          <h1>{grp.name}</h1>
          <p>
            View group details and manage members, forums, events, and join requests.
            Group settings are managed by a Community Leader.
          </p>
        </div>
      </div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (tab === "overview" ? " active" : "")} data-testid="tab-overview"
             onClick={() => setTab("overview")}>Overview</div>
        <div className={"tab" + (tab === "points" ? " active" : "")} data-testid="tab-points"
             onClick={() => setTab("points")}>Group Points</div>
        <div className={"tab" + (tab === "requests" ? " active" : "")} data-testid="tab-requests"
             onClick={() => setTab("requests")}>
          Join Requests {pendingCount > 0 && <span className="badge red">{pendingCount}</span>}
        </div>
      </div>

      {tab === "overview" && (
        <Overview group={grp} groupId={ledGroupId} nonce={nonce} onAct={act} />
      )}
      {tab === "points" && (
        <GroupPoints group={grp} groupId={ledGroupId} onMsg={onMsg}
                     initialQuarter={linkedQuarter} />
      )}
      {tab === "requests" && (
        <Requests group={grp} groupId={ledGroupId} nonce={nonce}
                  total={pendingCount} onAct={act} />
      )}
    </>
  );
}

// ---------------- Overview tab ----------------

function Overview({ group, groupId, nonce, onAct }: {
  group: any; groupId: string; nonce: number;
  onAct: (p: string, m?: "POST" | "DELETE", b?: unknown) => void;
}) {
  const forums = useApi<{ items: any[] }>("/forums");
  const leaders = group.leaders ?? [];
  const leaderNames = leaders
    .map((l: any) => `${l.firstName ?? ""} ${l.lastName ?? ""}`.trim() || l.id)
    .filter(Boolean);
  const forumList = forums.data?.items ?? [];
  const channelCount = forumList.reduce((n: number, f: any) => n + (f.channels?.length ?? 0), 0);
  const fmtMonth = (iso?: string) => (iso
    ? new Date(iso).toLocaleDateString(undefined, { month: "short", year: "numeric" }) : "—");

  return (
    <>
      <div className="grid cols-2 mb-16">
        <div className="card" data-testid="group-details">
          <h3>Group Details</h3>
          <div className="flex between"><span className="muted">Name</span><b>{group.name}</b></div>
          <div className="flex between"><span className="muted">Members</span>
            <b data-testid="detail-member-count">{group.memberCount ?? 0}</b></div>
          <div className="flex between"><span className="muted">Leaders</span>
            <b>{leaderNames.length ? leaderNames.join(", ") : "—"}</b></div>
          <div className="flex between"><span className="muted">Forums</span>
            <b>{forums.comingSoon || forums.error
              ? "—"
              : `${forumList.length} (${channelCount} channel${channelCount === 1 ? "" : "s"})`}</b></div>
          <div className="flex between"><span className="muted">Created</span>
            <b>{fmtMonth(group.createdAt)}</b></div>
          <div className="flex between"><span className="muted">Joining</span>
            <span className="badge blue">{group.approvalRequired ? "Approval required" : "Open"}</span></div>
        </div>

        <div className="card" data-testid="forums-card">
          <h3>Forums &amp; Channels</h3>
          {forums.comingSoon || forums.error ? (
            <p className="faint small">Forums are not available right now.</p>
          ) : forumList.length === 0 ? (
            <p className="faint small">No forums yet.</p>
          ) : (
            <ul className="clean">
              {forumList.map((f: any) => (
                <li key={f.id} className="flex between">
                  <span>{(f.channels ?? []).map((c: any) => `# ${c.name}`).join(" · ") || f.name}</span>
                  <Link className="small" to="/forums">Manage</Link>
                </li>
              ))}
            </ul>
          )}
          {/* Creation itself lives on the Forums screen — this is the entry
              point the mockup shows, not a second implementation of it. */}
          <Link className="btn sm mt-12" to="/forums" data-testid="create-forum-channel">
            ＋ Create Forum / Channel
          </Link>
          <p className="faint small mt-12 mb-0">
            You can create, edit, delete forums and pin posts within your own group only.
          </p>
        </div>
      </div>

      <Members groupId={groupId} group={group} nonce={nonce} onAct={onAct} />

      <p className="faint small mt-12">
        Removed members are notified by email and can rejoin later. They lose access to this
        group's forums.
      </p>
    </>
  );
}

// ---------------- Members table ----------------

// Members are searched through the OpenSearch-backed directory (GET /members),
// scoped to this group, so a 28k-member group is served the same way the global
// Member Directory is: full-text over name / email / skills / bio, cursor
// pagination, infinite scroll. Nothing loads until the leader clicks Search
// (an empty query lists the whole group). Points/tier ride the bounded
// per-group leaderboard roll-up, and leaders are badged from the group record.
function Members({ groupId, group, nonce, onAct }: {
  groupId: string; group: any; nonce: number;
  onAct: (p: string, m?: "POST" | "DELETE", b?: unknown) => void;
}) {
  const memberCount = group.memberCount ?? 0;
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const [q, setQ] = useState("");
  // null until the first Search — no data loads on tab open. Holds the committed
  // term so typing doesn't refetch; the `_` nonce reloads after a removal.
  const [activeSearch, setActiveSearch] = useState<string | null>(null);
  const doSearch = () => setActiveSearch(q.trim());

  const endpoint = activeSearch === null ? null
    : `/members?groupId=${encodeURIComponent(groupId)}`
      + (activeSearch ? `&q=${encodeURIComponent(activeSearch)}` : "")
      + `&sort=firstName&sortDir=asc&_=${nonce}`;
  const pages = useInfinitePages<any>(endpoint);

  // Points/tier are hydrated per visible page (BatchGetItem by the page's member
  // ids) — scales to any group size, unlike a top-N leaderboard join.
  const memberIds = useMemo(() => pages.rows.map((r: any) => r.id).filter(Boolean), [pages.rows]);
  const { rollupById, scoringLive } = useMemberRollups(groupId, memberIds);

  // Leaders of THIS group (leadership is not membership, US-1.16) — badged and
  // shielded from Remove. Derived from the group record, not the search row.
  const leaderIds = useMemo(() => new Set<string>([
    ...((group.leaders ?? []).map((l: any) => l.id)),
    ...((group.leaderIds ?? [])),
  ].filter(Boolean)), [group]);

  // Async roster export (same pattern as Admin > Users and the Member Directory).
  // It replaces a client-side walk of the member cursor: that was correct and it
  // did keep to the authoritative DynamoDB roster, but it gave no progress, could
  // not be left unattended, and a 13k-member group meant ~65 sequential requests
  // with the tab pinned open. The work now happens in a worker Lambda; the
  // authoritative-roster choice is preserved server-side, and joinedAt is still
  // trimmed to a date — both now done in export_worker.py rather than here.
  const {
    job: exportJob, error: exportError, running: exportRunning,
    start: startExport, reset: resetExport,
  } = useAsyncExport(`/groups/${groupId}/members/export`);

  // Sends the APPLIED search (activeSearch), not the box contents (q), so the CSV
  // matches the roster actually on screen rather than half-typed input.
  const doExport = () => startExport(activeSearch ? { q: activeSearch } : {});

  const remove = (row: any) => {
    const name = `${row.firstName ?? ""} ${row.lastName ?? ""}`.trim() || row.email || row.id;
    setConfirm({
      title: `Remove "${name}" from ${group.name}?`,
      body: (
        <><p>⚠️ This will immediately remove them from the group and they will lose access to its forums.</p>
        <p>Any <b>pending contribution submissions</b> and <b>pending certification claims</b> they have credited to this group will be automatically rejected.</p>
        <p>Earned points, tier badges, and approved certifications are not affected.</p>
        <p>This cannot be undone. The member can rejoin the group afterwards.</p></>
      ),
      confirmLabel: "Remove Member",
      cancelLabel: "Keep Member",
      onConfirm: () => onAct(`/groups/${groupId}/members/${row.id}`, "DELETE"),
    });
  };

  return (
    <div className="card pad-0">
      <div className="flex between" style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
        <b>Members ({memberCount})</b>
        <span className="btn-row" style={{ alignItems: "center" }}>
          <input className="input" style={{ width: 280 }}
                 placeholder="Search by name, email, skills, or bio…"
                 data-testid="my-group-member-search" value={q}
                 onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }} />
          <button className="btn sm primary" data-testid="my-group-member-search-btn"
                  onClick={doSearch}>Search</button>
          <button className="btn sm" data-testid="export-my-group-members"
                  disabled={exportRunning} onClick={doExport}>
            {exportRunning ? "Preparing export…" : "⬇ Export"}
          </button>
        </span>
      </div>

      <div style={{ padding: "12px 18px 0" }}>
        <AsyncExportPanel job={exportJob} error={exportError} noun="members"
                          onRetry={doExport} onDismiss={resetExport} />
      </div>
      <div style={{ padding: "0 14px" }}>
        {activeSearch === null ? (
          <p className="faint" data-testid="my-group-member-prompt" style={{ padding: "16px 4px" }}>
            Search this group's members by name, email, skills, or bio — or click Search with an
            empty box to list everyone in {group.name ?? "the group"}.
          </p>
        ) : pages.error ? <ErrorState message={pages.error} /> : (
          <DataTable id="my-group-members" rows={pages.rows}
            infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                        hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "members" }}
            emptyLabel="No members match your search."
            columns={[
              { key: "name", header: "Member", render: (row: any) => (
                <Link to={`/directory/${row.id}`} className="name-cell">
                  <Avatar firstName={row.firstName} lastName={row.lastName} src={row.avatar} size="sm" />
                  <b>{`${row.firstName ?? ""} ${row.lastName ?? ""}`.trim() || row.email}</b>
                </Link>) },
              { key: "email", header: "Email", render: (row: any) => (
                row.email || <span className="faint small">—</span>) },
              // Role WITHIN this group — leaders are listed alongside members.
              { key: "roleInGroup", header: "Role", render: (row: any) => (
                leaderIds.has(row.id)
                  ? <span className="badge blue">User Group Leader</span>
                  : <span className="badge gray">Member</span>) },
              { key: "points", header: "Points (Qtr)", render: (row: any) => {
                const p = rollupById.get(row.id)?.points;
                return p == null ? <span className="faint small">—</span> : p;
              } },
              { key: "tier", header: "Tier", render: (row: any) => {
                const t = rollupById.get(row.id)?.tier;
                return t ? <span className={tierClass(t)}>{tierIcon(t)} {t}</span>
                         : <span className="faint small">—</span>;
              } },
              { key: "act", header: "", render: (row: any) => (
                leaderIds.has(row.id) ? null : (
                  <button className="btn sm danger" data-testid="remove-member"
                          onClick={() => remove(row)}>Remove</button>)) },
            ]} />
        )}
      </div>
      {activeSearch !== null && !scoringLive && (
        <p className="faint small" style={{ padding: "0 18px 14px" }} data-testid="scoring-pending">
          Points and tier come from the Contributions &amp; Scoring service, which is not live yet —
          those columns show “—” until it is.
        </p>
      )}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </div>
  );
}

// ---------------- Group Points tab (US-7.9) ----------------

// Every point entry earned in the group for one quarter — auto-tracked awards
// (attendance, forum activity, certifications) as well as approved submissions
// and manual adjustments.
//
// This is the 13k+ row screen, so it is server-paged exactly like Admin > Users
// and the member list: one bounded request per page, the Rows dropdown is the
// page size, and Export walks the cursor rather than asking for everything at once.
function GroupPoints({ group, groupId, onMsg, initialQuarter }: {
  group: any; groupId: string; onMsg: (m: string) => void; initialQuarter?: string;
}) {
  // A quarter arriving from a dashboard link wins over the default; it is
  // validated against the offered list so a hand-edited URL cannot select a
  // period the picker cannot represent.
  const options = trailingQuarters(8);
  const [quarter, setQuarter] = useState(
    initialQuarter && options.includes(initialQuarter) ? initialQuarter : currentQuarter());
  const [exporting, setExporting] = useState(false);
  // Infinite scroll over the group's ledger for the quarter (UGL is scoped to
  // their led group server-side, so only the quarter is sent).
  const pages = useInfinitePages<any>(
    `/contributions/group-ledger?quarter=${encodeURIComponent(quarter)}`);

  const doExport = async () => {
    setExporting(true);
    try {
      const n = await exportPagedCsv(
        `/contributions/group-ledger?quarter=${encodeURIComponent(quarter)}`,
        `group-points_${group.name ?? groupId}_${quarter}.csv`,
        {
          transform: (r) => ({
            "Member Name": r.memberName ?? "",
            "Email": r.memberEmail ?? "",
            "Activity": r.activity ?? "",
            "Date": dateOnly(r.earnedDate),
            "Point value": r.points ?? 0,
          }),
        });
      onMsg(`Exported ${n} point entr${n === 1 ? "y" : "ies"} for ${quarter}.`);
    } catch (e) { onMsg((e as Error).message); }
    finally { setExporting(false); }
  };

  if (pages.comingSoon) return <ComingSoon feature="Group points" />;

  return (
    <div className="card pad-0">
      <div className="flex between" style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
        <b>Group Points</b>
        <span className="btn-row" style={{ alignItems: "center" }}>
          <select className="select" style={{ width: "auto" }} data-testid="group-points-quarter"
                  value={quarter} onChange={(e) => setQuarter(e.target.value)}>
            {options.map((qq, i) => (
              <option key={qq} value={qq}>{qq}{i === 0 ? " (current)" : ""}</option>
            ))}
          </select>
          <button className="btn sm" data-testid="export-group-points"
                  disabled={exporting} onClick={doExport}>
            {exporting ? "Exporting…" : "⬇ Export"}</button>
        </span>
      </div>
      <div style={{ padding: "0 14px" }}>
        {pages.error ? <ErrorState message={pages.error} /> : (
          <DataTable id="group-points" rows={pages.rows}
            infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                        hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "entries" }}
            columns={[
            { key: "memberName", header: "Member Name", render: (r: any) => (
              r.memberId
                ? <Link to={`/directory/${r.memberId}`}>{r.memberName}</Link>
                : r.memberName) },
            { key: "memberEmail", header: "Email", render: (r: any) => (
              r.memberEmail || <span className="faint small">—</span>) },
            { key: "activity", header: "Activity", render: (r: any) => r.activity },
            { key: "earnedDate", header: "Date",
              sortValue: (r: any) => r.earnedDate ?? "",
              render: (r: any) => dateOnly(r.earnedDate) || "—" },
            { key: "points", header: "Point value",
              sortValue: (r: any) => Number(r.points ?? 0),
              render: (r: any) => (
                <b className={"trend " + (Number(r.points) >= 0 ? "up" : "down")}>
                  {Number(r.points) >= 0 ? "+" : ""}{r.points}</b>) },
          ]} />
        )}
      </div>
      <p className="faint small" style={{ padding: "0 18px 14px" }}>
        Every entry earned in {group.name ?? "this group"} during the selected quarter, newest
        first — automatic awards as well as approved submissions and manual adjustments.
        Export includes the whole quarter, not just this page.
      </p>
    </div>
  );
}

// ---------------- Join Requests tab ----------------

function Requests({ group, groupId, nonce, total, onAct }: {
  group: any; groupId: string; nonce: number; total: number;
  onAct: (p: string, m?: "POST" | "DELETE", b?: unknown) => void;
}) {
  // Infinite scroll over pending requests; a decision bumps `nonce`, resetting
  // the list (and the badge) to reflect the just-approved/rejected row.
  const pages = useInfinitePages<any>(groupId ? `/groups/${groupId}/requests?_=${nonce}` : null);
  if (pages.comingSoon) return <ComingSoon feature="Join requests" />;
  if (pages.error) return <ErrorState message={pages.error} />;
  const items = pages.rows;

  // Rejection requires a reason (US-1.21); the member is notified either way and
  // may request again later.
  const reject = (r: any) => {
    const reason = window.prompt("Reason for rejecting this request (required):", "");
    if (reason === null) return; // cancelled
    if (!reason.trim()) return;
    onAct(`/groups/${groupId}/requests/${r.id}`, "POST", { decision: "reject", reason });
  };

  const fmtDate = (iso?: string) => (iso
    ? new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—");

  return (
    <>
      {group.approvalRequired && (
        <div className="card" style={{ background: "var(--info-bg)", borderColor: "#bae6fd", padding: 10, marginBottom: 16 }}
             data-testid="approval-required-note">
          <span className="small" style={{ color: "var(--info)" }}>
            ℹ This group has <b>Approval required to join</b> enabled. New members must be approved
            by you or a Community Leader before they join.
          </span>
        </div>
      )}
      <div className="card pad-0">
        <div className="flex between" style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }}>
          <b>Pending Join Requests ({total})</b>
          <span className="muted small">Oldest first · either a group leader or a Community Leader can decide</span>
        </div>
        <div style={{ padding: "0 14px" }}>
          <DataTable id="my-group-requests" rows={items}
            infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                        hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "requests" }}
            emptyLabel="No pending join requests." columns={[
            { key: "member", header: "Member", render: (r: any) => (
              <span className="name-cell">
                <Avatar firstName={r.memberName?.split(" ")[0]} lastName={r.memberName?.split(" ")[1]} size="sm" />
                {r.memberName || r.memberEmail || r.memberId}
              </span>) },
            { key: "requestedAt", header: "Requested",
              sortValue: (r: any) => r.requestedAt ?? "",
              render: (r: any) => fmtDate(r.requestedAt) },
            { key: "message", header: "Message", render: (r: any) => (
              <span className="muted small">{r.message || "—"}</span>) },
            { key: "act", header: "Action", render: (r: any) => (
              <span className="btn-row">
                <button className="btn success sm" data-testid="approve-request"
                        onClick={() => onAct(`/groups/${groupId}/requests/${r.id}`, "POST", { decision: "approve" })}>
                  Approve</button>
                <button className="btn danger sm" data-testid="reject-request"
                        onClick={() => reject(r)}>Reject</button>
              </span>) },
          ]} />
        </div>
      </div>
      <p className="faint small mt-12">
        On approval the member joins immediately and their join date is set to now. Rejection
        requires a reason; the member is notified either way and may request again later.
      </p>
    </>
  );
}
