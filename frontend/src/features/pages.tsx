import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import DataTable, { loadRowsPref } from "../components/DataTable";
import ColumnSettings from "../components/ColumnSettings";
import GroupModal from "../components/GroupModal";
import Toggle from "../components/Toggle";
import { useApi } from "../lib/useApi";
import { useInfinitePages } from "../lib/useInfinitePages";
import { useDebounced } from "../lib/useDebounced";
import { apiFetch } from "../lib/apiClient";
import { bumpNavCounts } from "../lib/navCounts";
import { refreshMembershipClaims } from "../lib/refreshMembership";
import { groupFilterOptions } from "../lib/groupScope";
import { useAsyncExport } from "../lib/useAsyncExport";
import AsyncExportPanel from "../components/AsyncExportPanel";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import Banner from "../components/Banner";
import ToastStack, { useToasts } from "../components/ToastStack";
import AnnouncementModal from "./AnnouncementModal";
import { ShoutoutModal } from "../components/ShoutoutsSection";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import type { Role } from "../roles";

const isLeaderRole = (r: Role) => r === "CommunityLeader" || r === "UserGroupLeader";

// All columns in the Member Directory, in their default display order.
// "act" is the shoutout button column — always last, never hidden.
const DIR_COLS = [
  { key: "name",       label: "Name" },
  { key: "email",      label: "Email" },
  { key: "role",       label: "Role" },
  { key: "groups",     label: "User Groups" },
  { key: "country",    label: "Country" },
  { key: "city",       label: "City" },
  { key: "awsProject", label: "AWS Project" },
  { key: "status",     label: "Status" },
  { key: "act",        label: "Actions" },
];

// Columns hidden by default — user can enable via the column selector.
const DIR_DEFAULT_HIDDEN = ["country", "city", "awsProject", "status"];

// Column prefs key (localStorage). Mirrors the tblprefs: convention used by DataTable.
const DIR_PREFS_KEY = "tblprefs:member-directory";

interface DirColPrefs {
  order: string[];
  hidden: string[];
}

function loadDirPrefs(): DirColPrefs {
  try {
    const raw = localStorage.getItem(DIR_PREFS_KEY);
    if (raw) return JSON.parse(raw) as DirColPrefs;
  } catch { /* ignore */ }
  return { order: DIR_COLS.map((c) => c.key), hidden: DIR_DEFAULT_HIDDEN };
}

function saveDirPrefs(p: DirColPrefs) {
  try { localStorage.setItem(DIR_PREFS_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

// Sortable columns for the Member Directory.
// User Groups and Actions are excluded from sort.
type DirSortKey = "firstName" | "lastName" | "email" | "role" | "city" | "country" | "status" | "awsProject";

// Member Directory (US-3.4 browse, US-3.5 search + filters).
// OpenSearch-backed: full-text search, all-column server-side sort, infinite scroll.
// No data loads on page mount — user must click Search to trigger the first fetch.
export function DirectoryPage({ role }: { role?: Role } = {}) {
  // Filter state
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [certFilter, setCertFilter] = useState("");

  // Sort state — default firstName A→Z, always applied
  const [sortKey, setSortKey] = useState<DirSortKey>("firstName");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // Column visibility & order prefs (persisted in localStorage)
  const [colPrefs, setColPrefs] = useState<DirColPrefs>(loadDirPrefs);
  const saveColPrefs = (p: DirColPrefs) => { setColPrefs(p); saveDirPrefs(p); };

  const [msg, setMsg] = useState<string | null>(null);
  const [shoutoutTarget, setShoutoutTarget] = useState<{ id: string; name: string } | null>(null);
  const [shoutoutDone, setShoutoutDone] = useState<string | null>(null);

  const groups = useApi<{ items: any[] }>("/groups");
  const certs = useApi<{ items: any[] }>("/certifications");
  const showCertFilter = role !== "CommunityLeader";
  const debouncedQ = useDebounced(q, 300);

  // Infinite scroll state
  const [rows, setRows] = useState<any[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingInitial, setLoadingInitial] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [dirComingSoon, setDirComingSoon] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const BATCH = 25;

  const buildPath = (cur: string | null) => {
    const params = new URLSearchParams({ limit: String(BATCH) });
    if (debouncedQ) params.set("q", debouncedQ);
    if (roleFilter) params.set("role", roleFilter);
    if (groupFilter) params.set("groupId", groupFilter);
    if (showCertFilter && certFilter) params.set("certId", certFilter);
    params.set("sort", sortKey);
    params.set("sortDir", sortDir);
    if (cur) params.set("cursor", cur);
    return `/members?${params.toString()}`;
  };

  const fetchPage = useCallback(async (path: string, append: boolean) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    try {
      const res = await apiFetch<{ items: any[]; cursor?: string }>(path);
      setRows(prev => append ? [...prev, ...(res.items ?? [])] : (res.items ?? []));
      setCursor(res.cursor ?? null);
      setHasMore(Boolean(res.cursor));
      setFetchError(null);
    } catch (e: any) {
      if (e?.name === "FeatureNotAvailableError") { setDirComingSoon(true); return; }
      if (e?.name !== "AbortError") setFetchError((e as Error).message);
    } finally {
      setLoadingInitial(false);
      setLoadingMore(false);
    }
  }, []); // eslint-disable-line

  // When filters or sort change and a search has already been submitted, re-fetch from page 1.
  useEffect(() => {
    if (!hasSearched) return;
    setRows([]); setCursor(null); setHasMore(false);
    setLoadingInitial(true); setFetchError(null);
    fetchPage(buildPath(null), false);
  }, [debouncedQ, roleFilter, groupFilter, certFilter, sortKey, sortDir]); // eslint-disable-line

  const doSearch = () => {
    setHasSearched(true);
    setRows([]); setCursor(null); setHasMore(false);
    setLoadingInitial(true); setFetchError(null);
    fetchPage(buildPath(null), false);
  };

  const loadMore = useCallback(() => {
    if (!hasMore || loadingMore || loadingInitial) return;
    setLoadingMore(true);
    fetchPage(buildPath(cursor), true);
  }, [hasMore, loadingMore, loadingInitial, cursor, buildPath]); // eslint-disable-line

  // Infinite scroll sentinel
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) loadMore();
    }, { rootMargin: "200px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  const handleSort = (key: DirSortKey) => {
    if (key === sortKey) {
      setSortDir(d => d === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    // Sort change triggers re-fetch via the useEffect above (only if hasSearched).
  };

  // Async CSV export (replaces the single-request download, which could not
  // survive the directory's growth: the old server path full-scanned the whole
  // table and returned every row in one response, breaching Lambda's 6 MB payload
  // limit and API Gateway's 29 s ceiling well before 25k members).
  //
  // Restricted to Community Leaders and User Group Leaders server-side, so the
  // button is only offered to them. That is a stricter gate than the listing's
  // own group scoping (a Member browses their own groups but cannot export).
  const canExport = role === "CommunityLeader" || role === "UserGroupLeader";
  const {
    job: exportJob, error: exportError, running: exportRunning,
    start: startExport, reset: resetExport,
  } = useAsyncExport("/members/export");

  // Sends the filters currently applied to the table so the CSV matches what the
  // leader is looking at. certId is deliberately not sent: resolving cert holders
  // needs a fan-out with the caller's token, which the async worker does not have.
  const doExport = () => startExport({
    ...(debouncedQ ? { q: debouncedQ } : {}),
    ...(roleFilter ? { role: roleFilter } : {}),
    ...(groupFilter ? { groupId: groupFilter } : {}),
  });

  if (dirComingSoon) return <ComingSoon feature="Directory" />;

  // Compute visible columns from prefs, maintaining saved order.
  // "act" column is always included last and never hidden.
  const allColKeys = DIR_COLS.map((c) => c.key);
  const orderedKeys = [
    ...colPrefs.order.filter((k) => allColKeys.includes(k)),
    ...allColKeys.filter((k) => !colPrefs.order.includes(k)),
  ];
  const visibleKeys = orderedKeys.filter((k) => !colPrefs.hidden.includes(k));
  // "act" is always shown and always last — remove from wherever it is, append at end
  const visibleWithoutAct = visibleKeys.filter((k) => k !== "act");
  const visibleCols = [...visibleWithoutAct, "act"];

  // Column settings items (exclude "act" — it can't be hidden)
  const colSettingsItems = orderedKeys
    .filter((k) => k !== "act")
    .map((k) => ({ key: k, label: DIR_COLS.find((c) => c.key === k)!.label }));

  // Sortable column header helper
  const SortTh = ({ col, label, className }: { col: DirSortKey; label: string; className?: string }) => (
    <th className={["sortable", className].filter(Boolean).join(" ")} style={{ cursor: "pointer" }} onClick={() => handleSort(col)}>
      {col === sortKey
        ? <>{label} <span className="sort-ind">{sortDir === "asc" ? "▲" : "▼"}</span></>
        : <>{label} <span className="sort-ind">⇅</span></>}
    </th>
  );

  const gname = (id: string) =>
    (groups.data?.items ?? []).find((g: any) => g.id === id)?.name ?? id;

  // A Member may only filter by groups they belong to, matching what the server
  // will actually return (GET /members is group-scoped for the Member role, and
  // naming a group you are not in is a 403). The rule itself lives in
  // lib/groupScope so this page and the Event Ideas feed cannot drift apart.
  const isMember = role === "Member";
  const groupOptions = groupFilterOptions(groups.data?.items ?? [], role);

  // Render a single cell by column key
  const renderCell = (m: any, key: string) => {
    const all = groups.data?.items ?? [];
    const led = all.filter((g: any) => (g.leaderIds ?? []).includes(m.id));
    const displayName = `${m.firstName ?? ""} ${m.lastName ?? ""}`.trim();
    switch (key) {
      case "name":
        return (
          <td key="name">
            <Link to={`/directory/${m.id}`}>
              <b>{m.firstName} {m.lastName}</b>
              {m.status === "inactive" && (
                <span className="badge gray" style={{ marginLeft: 6 }}>Inactive</span>
              )}
            </Link>
          </td>
        );
      case "email":
        return <td key="email" className="mobile-hidden">{m.email}</td>;
      case "role":
        return <td key="role" className="mobile-hidden">{m.role}</td>;
      case "groups":
        return (
          <td key="groups" className="mobile-hidden">
            {led.length === 0 && (m.groups ?? []).length === 0
              ? <span className="faint">—</span>
              : <>
                  {led.map((g: any) => (
                    <span key={g.id} className="badge blue" style={{ marginRight: 4 }}>
                      {g.name} · Leader
                    </span>
                  ))}
                  {(m.groups ?? []).map((g: any) => (
                    <span key={g.groupId} className="faint small" style={{ marginRight: 4 }}>
                      {gname(g.groupId)}
                    </span>
                  ))}
                </>}
          </td>
        );
      case "country":
        return <td key="country" className="mobile-hidden">{m.country || <span className="faint">—</span>}</td>;
      case "city":
        return <td key="city" className="mobile-hidden">{m.city || <span className="faint">—</span>}</td>;
      case "awsProject":
        return (
          <td key="awsProject" className="mobile-hidden">
            {m.awsProject
              ? <span className="badge green">Yes</span>
              : <span className="badge gray">No</span>}
          </td>
        );
      case "status":
        return (
          <td key="status" className="mobile-hidden">
            <span className={"badge " + (m.status === "active" ? "green" : "red")}>
              {m.status}
            </span>
          </td>
        );
      case "act":
        return (
          <td key="act">
            {/* Server's verdict, not the row's role: this also covers "not
                yourself" and a UGL's own-group scope, which a role check misses. */}
            {m.canShoutout && (
              <button className="btn sm" title="Give a shoutout"
                onClick={() => setShoutoutTarget({ id: m.id, name: displayName })}>
                👏
              </button>
            )}
          </td>
        );
      default:
        return <td key={key} />;
    }
  };

  // Render a header cell by column key
  const renderHeader = (key: string) => {
    switch (key) {
      case "name":       return <SortTh key="name" col="firstName" label="Name" />;
      case "email":      return <SortTh key="email" col="email" label="Email" className="mobile-hidden" />;
      case "role":       return <SortTh key="role" col="role" label="Role" className="mobile-hidden" />;
      case "groups":     return <th key="groups" className="mobile-hidden">User Groups</th>;
      case "country":    return <SortTh key="country" col="country" label="Country" className="mobile-hidden" />;
      case "city":       return <SortTh key="city" col="city" label="City" className="mobile-hidden" />;
      case "awsProject": return <SortTh key="awsProject" col="awsProject" label="AWS Project" className="mobile-hidden" />;
      case "status":     return <SortTh key="status" col="status" label="Status" className="mobile-hidden" />;
      case "act":        return <th key="act"></th>;
      default:           return <th key={key} />;
    }
  };

  return (
    <>
      <div className="page-head flex between dir-page-head">
        <div>
          <h1>Member Directory</h1>
          <p>Search members by name, email, skills, or bio. Sorted by first name A–Z by default.</p>
        </div>
        {canExport && (
          <button className="btn sm" data-testid="export-members"
                  disabled={exportRunning} onClick={doExport}>
            {exportRunning ? "Preparing export…" : "⬇ Export CSV"}
          </button>
        )}
      </div>

      <AsyncExportPanel job={exportJob} error={exportError} noun="members"
                        onRetry={doExport} onDismiss={resetExport} />
      {/* A Member who belongs to no groups sees nobody, by design. Said plainly
          here rather than left as a silently empty table, because the two states
          are indistinguishable otherwise — and one of them is reachable without
          the member having done anything wrong: group membership rides on the ID
          token, so a member added to a group by a leader keeps an empty directory
          until their next sign-in. */}
      {isMember && !groups.loading && groupOptions.length === 0 && (
        <div className="card mb-16" role="status" style={{ background: "var(--info-bg)", border: "1px solid var(--info)", padding: "10px 14px" }}>
          <span className="small" style={{ color: "var(--info)" }}>
            The directory shows members of the groups you belong to, and you are not in
            any yet. <Link to="/groups">Browse user groups</Link> to join one. If you
            joined or were added just now, sign out and back in to refresh your access.
          </span>
        </div>
      )}
      {msg && (
        <div className="card mb-16" style={{ background: "var(--success-bg)", padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="small" style={{ color: "var(--success)" }}>{msg}</span>
          <button className="icon-btn" onClick={() => setMsg(null)}>✕</button>
        </div>
      )}
      {shoutoutDone && (
        <div className="card mb-16" style={{ background: "var(--success-bg)", padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="small" style={{ color: "var(--success)" }}>{shoutoutDone}</span>
          <button className="icon-btn" onClick={() => setShoutoutDone(null)}>✕</button>
        </div>
      )}

      {/* Filter bar */}
      <div className="card mb-16">
        <div className="dir-filter-bar">
          <input
            className="input"
            placeholder="🔍 Search by name, email, skills, or bio…"
            data-testid="member-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
          />
          <select className="select" style={{ width: "auto" }} data-testid="member-role-filter"
                  value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); }}>
            <option value="">All roles</option>
            <option value="Member">Member</option>
            <option value="UserGroupLeader">User Group Leader</option>
            <option value="CommunityLeader">Community Leader</option>
          </select>
          <select className="select" style={{ width: "auto" }} data-testid="member-group-filter"
                  value={groupFilter} onChange={(e) => { setGroupFilter(e.target.value); }}>
            <option value="">{isMember ? "All my groups" : "All groups"}</option>
            {groupOptions.map((g: any) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          {showCertFilter && (
            <select className="select" style={{ width: "auto" }} data-testid="member-cert-filter"
                    value={certFilter} onChange={(e) => { setCertFilter(e.target.value); }}>
              <option value="">Any certification</option>
              {(certs.data?.items ?? []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <button className="btn primary" data-testid="member-search-submit" onClick={doSearch}>
            Search
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="card">
        {fetchError ? <ErrorState message={fetchError} /> : (
          <>
            {/* Empty state before first search */}
            {!hasSearched && (
              <div className="faint small" style={{ padding: "32px 4px", textAlign: "center" }}>
                Use the search box or filters above to find members.
              </div>
            )}

            {hasSearched && (
              <>
                {/* Toolbar: count + column selector */}
                <div className="tbl-toolbar" style={{ paddingLeft: 0, paddingRight: 0, marginBottom: 6 }}>
                  <div className="tt-left">
                    {!loadingInitial && rows.length > 0 && (
                      <span className="faint small">
                        {rows.length}{hasMore ? " — more available" : " members loaded"}
                      </span>
                    )}
                  </div>
                  <div className="tt-right">
                    <ColumnSettings
                      tableId="member-directory"
                      items={colSettingsItems}
                      hidden={colPrefs.hidden}
                      onReorder={(order) => saveColPrefs({ ...colPrefs, order: [...order, "act"] })}
                      onToggle={(key) => saveColPrefs({
                        ...colPrefs,
                        hidden: colPrefs.hidden.includes(key)
                          ? colPrefs.hidden.filter((k) => k !== key)
                          : [...colPrefs.hidden, key],
                      })}
                      onReset={() => saveColPrefs({
                        order: DIR_COLS.map((c) => c.key),
                        hidden: DIR_DEFAULT_HIDDEN,
                      })}
                    />
                  </div>
                </div>

                {/* Loading progress bar */}
                {(loadingInitial || loadingMore) && (
                  <div style={{ height: 3, background: "var(--border)", borderRadius: 2, marginBottom: 8, overflow: "hidden" }}>
                    <div style={{
                      height: "100%", background: "var(--primary)", borderRadius: 2,
                      width: "60%", animation: "progress-indeterminate 1.4s ease-in-out infinite",
                    }} />
                  </div>
                )}

                <div style={{ overflowX: "auto" as const }}>
                  <table className="tbl" data-testid="table-member-directory">
                    <thead>
                      <tr>{visibleCols.map(renderHeader)}</tr>
                    </thead>
                    <tbody>
                      {loadingInitial
                        ? Array.from({ length: 5 }, (_, i) => (
                            <tr key={`sk-${i}`} aria-hidden="true"
                                data-testid={i === 0 ? "member-directory-skeleton" : undefined}>
                              {visibleCols.map((k) => (
                                <td key={k} className={k !== "name" && k !== "act" ? "mobile-hidden" : undefined}>
                                  <span style={{ display: "inline-block", width: "70%", height: 12,
                                                 borderRadius: 4, background: "var(--border, #e2e5ea)" }} />
                                </td>
                              ))}
                            </tr>
                          ))
                        : rows.map((m) => (
                            <tr key={m.id}>{visibleCols.map((k) => renderCell(m, k))}</tr>
                          ))}
                    </tbody>
                  </table>
                </div>

                {loadingMore && (
                  <div className="faint small" style={{ padding: "12px 4px", textAlign: "center" }}>
                    Loading more…
                  </div>
                )}
                {!loadingInitial && !loadingMore && rows.length === 0 && (
                  <p className="faint" style={{ padding: "16px 0", textAlign: "center" }}>
                    No members match your search or filters.
                  </p>
                )}
                {!loadingInitial && !hasMore && rows.length > 0 && (
                  <div className="faint small" style={{ textAlign: "center", padding: "10px 0" }}>
                    All {rows.length} members loaded
                  </div>
                )}

                {/* Infinite scroll sentinel */}
                {hasMore && !loadingMore && <div ref={sentinelRef} style={{ height: 1 }} />}
              </>
            )}
          </>
        )}
      </div>

      {shoutoutTarget && (
        <ShoutoutModal
          recipientId={shoutoutTarget.id}
          recipientName={shoutoutTarget.name}
          onClose={() => setShoutoutTarget(null)}
          onSent={() => {
            setShoutoutDone(`Shoutout sent to ${shoutoutTarget.name}!`);
            setShoutoutTarget(null);
          }}
        />
      )}

      <style>{`
        @keyframes progress-indeterminate {
          0%   { margin-left: 0;   width: 30%; }
          50%  { margin-left: 40%; width: 40%; }
          100% { margin-left: 100%; width: 10%; }
        }
      `}</style>
    </>
  );
}

// User Groups (US-1.7/1.8/1.11/1.16/1.21). The Community Leader view mirrors
// the leader user-groups mockup: tabs "All Groups" (with
// Leader(s)/Created columns, Edit/Delete, soft-delete grace + Undo Delete) and
// a cross-group "Join Requests" queue. Members/UGLs keep the browse/join list.
const GRACE_DAYS = 14; // US-1.11 — 2-week soft-delete grace period

const daysLeft = (g: any) => {
  if (!g.deletedAt) return 0;
  const elapsed = (Date.now() - new Date(g.deletedAt).getTime()) / 86400000;
  return Math.max(0, Math.ceil(GRACE_DAYS - elapsed));
};
const fmtCreated = (iso?: string) => iso
  ? new Date(iso).toLocaleDateString(undefined, { month: "short", year: "numeric" }) : "—";
const leaderNames = (g: any) => {
  const ls = g.leaders ?? [];
  if (ls.length === 0) return "—";
  const first = `${ls[0].firstName} ${ls[0].lastName}`.trim() || ls[0].id;
  return ls.length > 1 ? `${first} +${ls.length - 1}` : first;
};
const fmtReqDate = (iso?: string) => iso
  ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";

type Act = (path: string, method?: "POST" | "DELETE", body?: unknown, done?: string) => void | Promise<void>;

// High volume (2026-08-08): both Community Leader tables — "All Groups" and the
// cross-group "Join Requests" queue — use server-side cursor pagination, the
// same approach as Admin > User Management (DataTable server mode + limit/cursor
// + a cursor stack for Prev). The Member/UGL browse-and-join card grid stays on
// the unpaged path (that view is naturally bounded and its behavior unchanged).
export function GroupsPage({ role }: { role: Role }) {
  const [nonce, setNonce] = useState(0);
  const [open, setOpen] = useState(false);
  const { toasts, success, error, dismissToast } = useToasts();
  const [editing, setEditing] = useState<any | null>(null);
  const [tab, setTab] = useState<"groups" | "requests">("groups");
  const isCL = role === "CommunityLeader";
  const refresh = () => setNonce((n) => n + 1);

  const act: Act = async (path, method = "POST", body, done = "Done.") => {
    try {
      await apiFetch(path, { method, body: body ? JSON.stringify(body) : undefined });
      success(done);
      refresh();
      // A CL has no join-request pill, but this funnel also carries group
      // soft-delete, which rejects every pending submission and claim in the
      // group — those queues DO have pills.
      bumpNavCounts();
    } catch (e) { error((e as Error).message); }
  };

  // Tab badge = TRUE pending total. Paged mode returns `total`; a tiny limit=1
  // page fetches it cheaply, independent of which tab is currently open.
  const jrCount = useApi<{ total?: number; count: number }>(`/join-requests?limit=1&_=${nonce}`, isCL);
  const pendingCount = isCL ? (jrCount.data?.total ?? jrCount.data?.count ?? 0) : 0;

  return (
    <>
      <div className="page-head flex between">
        <div><h1>User Groups</h1>
          {isCL
            ? <p>Create and manage user groups. Each group needs at least one User Group Leader.</p>
            : <p>Join groups to access their events and forums. You can belong to multiple groups.
                Groups marked <span className="badge amber">Approval required</span> need a leader to approve your request before you join.</p>}
        </div>
        {isCL && <button className="btn primary" data-testid="create-group" onClick={() => setOpen(true)}>＋ Create Group</button>}
      </div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      {isCL && (
        <div className="tabs" style={{ marginBottom: 16 }}>
          <div className={"tab" + (tab === "groups" ? " active" : "")} data-testid="tab-all-groups" onClick={() => setTab("groups")}>All Groups</div>
          <div className={"tab" + (tab === "requests" ? " active" : "")} data-testid="tab-join-requests" onClick={() => setTab("requests")}>
            Join Requests {pendingCount > 0 && <span className="badge red">{pendingCount}</span>}</div>
        </div>
      )}

      {!isCL && <MemberGroupsGrid role={role} nonce={nonce} act={act} />}
      {isCL && tab === "groups" && <AllGroupsTable nonce={nonce} act={act} onEdit={setEditing} />}
      {isCL && tab === "requests" && <CrossGroupRequests nonce={nonce} act={act} />}

      {open && <GroupModal onClose={() => setOpen(false)} onSaved={refresh} />}
      {/* US-1.18 — Edit offers full create-field parity (name, description,
          approval toggle, leader add/change/remove), not just name/description. */}
      {editing && <GroupModal group={editing} onClose={() => setEditing(null)} onSaved={refresh} />}
    </>
  );
}

// Member / UGL browse-and-join grid (unpaged — naturally bounded). Card layout
// per the member groups mockup; behavior unchanged.
function MemberGroupsGrid({ role, nonce, act }: { role: Role; nonce: number; act: Act }) {
  const { data, loading, error, comingSoon } = useApi<{ items: any[] }>(`/groups?_=${nonce}`);
  const [joiningId, setJoiningId] = useState<string | null>(null);
  // Joining/leaving changes the caller's own group membership, which lives in the
  // ID token as a claim the server reads to scope the directory and the ideas
  // feed. Re-mint the token so the new membership takes effect immediately rather
  // than at next sign-in. Awaited before the caller continues, so the very next
  // request already carries the new claims. Never throws — see refreshMembership.
  //
  // Not on `withdraw`: withdrawing a PENDING request never changed membership, so
  // there is no claim to refresh.
  const join = async (g: any) => {
    setJoiningId(g.id);
    try {
      await act(`/groups/${g.id}/join`, "POST", undefined,
        g.approvalRequired ? "Request sent — a leader needs to approve it." : "Joined.");
      // Approval-required groups do NOT grant membership here — the request is
      // merely pending — so there is nothing to pick up until a leader approves.
      if (!g.approvalRequired) await refreshMembershipClaims();
    }
    finally { setJoiningId(null); }
  };
  const withdraw = (g: any) => act(`/groups/${g.id}/join/withdraw`, "POST", undefined, "Join request withdrawn.");
  const leave = async (g: any) => {
    await act(`/groups/${g.id}/leave`, "POST", undefined, "You left the group.");
    await refreshMembershipClaims();
  };
  if (loading) return <Loading />;
  if (comingSoon) return <ComingSoon feature="User Groups" />;
  if (error) return <ErrorState message={error} />;
  const rows = data?.items ?? [];
  return (
        <div className="grid cols-3" data-testid="groups-grid">
          {rows.length === 0 && <p className="faint small">No user groups yet.</p>}
          {rows.map((g) => {
            const state = g.myState;
            const badge = state === "member" ? { cls: "green", label: "Joined" }
              : state === "requested" ? { cls: "amber", label: "Requested" }
              : g.approvalRequired ? { cls: "amber", label: "Approval required" }
              : { cls: "gray", label: "Not joined" };
            const leaders = g.leaders ?? [];
            // Column flex + margin-auto footer keeps the member-count/action
            // row aligned across a grid row when descriptions differ in length.
            return (
              <div className="card" key={g.id} style={{ display: "flex", flexDirection: "column" }}>
                <div className="flex between mb-8">
                  {/* Title links to group detail (kept from the table view — the
                      mockup's static title has nowhere to go). */}
                  <h3 className="mb-0"><Link to={`/groups/${g.id}`}>{g.name}</Link></h3>
                  <span className={`badge ${badge.cls}`}>{badge.label}</span>
                </div>
                <p className="faint small">{g.description}</p>
                {/* US-1.8 — listings show the group's leader(s) by name + email. */}
                <div className="ugl-row faint small mb-12">
                  {leaders.length === 0 ? <>👤 No leader assigned</> : leaders.map((l: any, i: number) => (
                    <div key={l.id}>
                      👤 {i === 0 && "Led by "}<b>{`${l.firstName} ${l.lastName}`.trim() || l.id}</b>
                      {l.email && <> · <a href={`mailto:${l.email}`}>{l.email}</a></>}
                    </div>
                  ))}
                </div>
                <div className="flex between" style={{ marginTop: "auto" }}>
                  <span className="muted small">
                    {state === "requested" ? "⏳ Requested · pending approval" : `👥 ${g.memberCount ?? 0} members`}
                  </span>
                  {/* UGLs lead their group and cannot join others (decided 2026-08-03). */}
                  {role === "Member" && (
                    state === "member"
                      ? <button className="btn sm" data-testid={`leave-${g.id}`} onClick={() => leave(g)}>Leave</button>
                    : state === "requested"
                      ? <button className="btn sm" data-testid={`withdraw-${g.id}`} onClick={() => withdraw(g)}>Withdraw</button>
                      : <button className="btn sm primary" data-testid={`join-${g.id}`}
                          onClick={() => join(g)} disabled={joiningId === g.id}>
                          {joiningId === g.id
                            ? <><span className="spinner-sm" /> {g.approvalRequired ? "Requesting…" : "Joining…"}</>
                            : g.approvalRequired ? "Request to Join" : "Join"}
                        </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
  );
}

// CL "All Groups" management table — server-side cursor pagination (2026-08-08,
// high volume). Rows dropdown = page size, Prev/Next via a cursor stack, shell
// renders immediately with skeleton rows; the server owns order (no client
// sort). includeDeleted=true surfaces soft-deleted grace rows (US-1.11).
function AllGroupsTable({ nonce, act, onEdit }: { nonce: number; act: Act; onEdit: (g: any) => void }) {
  const [pageSize, setPageSize] = useState(() => loadRowsPref("groups"));
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  useEffect(() => { setCursorStack([]); }, [pageSize]);
  const params = new URLSearchParams({ includeDeleted: "true", limit: String(pageSize) });
  const cursor = cursorStack[cursorStack.length - 1];
  if (cursor) params.set("cursor", cursor);
  params.set("_", String(nonce)); // refetch current page after edit/delete/restore
  const { data, error, comingSoon, fetching } =
    useApi<{ items: any[]; cursor?: string }>(`/groups?${params.toString()}`);
  if (comingSoon) return <ComingSoon feature="User Groups" />;
  if (error) return <ErrorState message={error} />;
  const rows = data?.items ?? [];
  const server = {
    fetching,
    hasMore: Boolean(data?.cursor),
    canPrev: cursorStack.length > 0,
    onNext: () => { if (data?.cursor) setCursorStack((s) => [...s, data.cursor!]); },
    onPrev: () => setCursorStack((s) => s.slice(0, -1)),
    onPageSizeChange: setPageSize,
  };
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const del = (g: any) => setConfirm({
    title: `Delete "${g.name}"?`,
    body: (
      <><p>⚠️ This will immediately remove all <b>{g.memberCount ?? 0} members</b>, cancel upcoming events, hide forums, and reject all pending submissions and join requests.</p>
      <p>Earned points, tiers, and approved certifications are not affected.</p>
      <p>You have <b>14 days to undo this</b>. After that, all data is permanently deleted and members must rejoin manually.</p></>
    ),
    confirmLabel: "Delete Group",
    cancelLabel: "Keep Group",
    onConfirm: () => act(`/groups/${g.id}`, "DELETE", undefined, "Group deleted (recoverable for 2 weeks)."),
  });
  return (
    <>
      <div className="card">
        <DataTable id="groups" rows={rows} server={server} emptyLabel="No user groups yet." columns={[
          { key: "name", header: "Group", render: (g) => g.status === "SoftDeleted"
            ? <span><b>{g.name}</b> <span className="badge amber">Restoring</span></span>
            : <Link to={`/groups/${g.id}`}><b>{g.name}</b></Link> },
          { key: "description", header: "Description", render: (g) => g.status === "SoftDeleted"
            ? <span className="muted small">Soft-deleted · {daysLeft(g)} days left in grace</span>
            : <span className="muted small">{g.description}</span> },
          { key: "memberCount", header: "Members", sortValue: (g) => g.memberCount ?? 0, render: (g) => g.memberCount ?? 0 },
          { key: "leaders", header: "Leader(s)", render: (g) => g.status === "SoftDeleted" ? "—" : leaderNames(g) },
          { key: "created", header: "Created", sortValue: (g) => g.createdAt ?? "", render: (g) => fmtCreated(g.createdAt) },
          { key: "act", header: "", render: (g) => g.status === "SoftDeleted"
            ? <button className="btn sm" data-testid="restore-group" onClick={() => act(`/groups/${g.id}/restore`, "POST", undefined, "Group restored. Former members are notified they may rejoin.")}>Undo Delete</button>
            : <span className="btn-row">
                <button className="btn sm" data-testid="edit-group" onClick={() => onEdit(g)}>Edit Group</button>
                <button className="btn sm danger" data-testid="delete-group" onClick={() => del(g)}>Delete</button>
              </span> },
        ]} />
      </div>
      <p className="faint small mt-12">Deleting a group is a soft-delete: data is hidden and recoverable for 2 weeks, then permanently removed. Members are notified on restore.</p>
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

// US-1.21 — CL queue of pending join requests across ALL approval-required
// groups ("You or the group's own leader can decide — whoever acts first").
// Server-side cursor pagination (2026-08-08, high volume); `total` (from the
// paged response) drives the heading + tab badge. Oldest first, server order.
function CrossGroupRequests({ nonce, act }: { nonce: number; act: Act }) {
  const [pageSize, setPageSize] = useState(() => loadRowsPref("cl-join-requests"));
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  useEffect(() => { setCursorStack([]); }, [pageSize]);
  const params = new URLSearchParams({ limit: String(pageSize) });
  const cursor = cursorStack[cursorStack.length - 1];
  if (cursor) params.set("cursor", cursor);
  params.set("_", String(nonce));
  const { data, error, comingSoon, fetching } =
    useApi<{ items: any[]; total?: number; cursor?: string }>(`/join-requests?${params.toString()}`);
  if (comingSoon) return <ComingSoon feature="Join requests" />;
  if (error) return <ErrorState message={error} />;
  const items = data?.items ?? [];
  const total = data?.total ?? items.length;
  const server = {
    fetching,
    hasMore: Boolean(data?.cursor),
    canPrev: cursorStack.length > 0,
    onNext: () => { if (data?.cursor) setCursorStack((s) => [...s, data.cursor!]); },
    onPrev: () => setCursorStack((s) => s.slice(0, -1)),
    onPageSizeChange: setPageSize,
  };
  const reject = (r: any) => {
    const reason = window.prompt("Reason for rejecting this request (required):", "");
    if (reason === null) return;
    act(`/groups/${r.groupId}/requests/${r.id}`, "POST", { decision: "reject", reason }, "Request rejected.");
  };
  return (
    <>
      <div className="card mb-16" style={{ background: "var(--info-bg)", padding: 10 }}>
        <span className="small" style={{ color: "var(--info)" }}>ℹ Pending join requests across all groups that require approval. You or the group's own leader can decide — whoever acts first.</span>
      </div>
      <div className="card pad-0">
        <div style={{ padding: "14px 18px", borderBottom: "1px solid var(--border)" }} className="flex between">
          <b>Pending Join Requests ({total})</b><span className="muted small">Oldest first</span></div>
        <DataTable id="cl-join-requests" rows={items} server={server} emptyLabel="No pending join requests." columns={[
          { key: "member", header: "Member", render: (r) => r.memberName || r.memberEmail || r.memberId },
          { key: "group", header: "Group", render: (r) => r.groupName || r.groupId },
          { key: "requested", header: "Requested", sortValue: (r) => r.requestedAt ?? "", render: (r) => fmtReqDate(r.requestedAt) },
          { key: "message", header: "Message", render: (r) => <span className="muted small">{r.message || "—"}</span> },
          { key: "act", header: "Action", render: (r) => <span className="btn-row">
            <button className="btn success sm" data-testid="approve-request" onClick={() => act(`/groups/${r.groupId}/requests/${r.id}`, "POST", { decision: "approve" }, "Request approved — the member has joined.")}>Approve</button>
            <button className="btn danger sm" data-testid="reject-request" onClick={() => reject(r)}>Reject</button></span> },
        ]} />
      </div>
      <p className="faint small mt-12">Only groups with “Approval required to join” enabled appear here. On approval the member joins immediately; rejection requires a reason. The member is notified either way.</p>
    </>
  );
}

// Author management view (US-10.3). Leaders see the announcements THEY created
// (view=mine): title/audience/created/expiry/email/status, with Edit (own) and
// Delete. A Community Leader can additionally switch to a moderation view
// (scope=all) to delete ANY announcement. Members have no management page — they
// see announcements only in the AnnouncementPanel on their dashboard (US-10.4).
// Dismissal lives on the panel, not here (BR-11).
export function AnnouncementsPage({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  const isLeader = isLeaderRole(role);
  const isCL = role === "CommunityLeader";
  const [nonce, setNonce] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);
  const [moderation, setModeration] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);
  const view = moderation && isCL ? "view=mine&scope=all" : "view=mine";
  // Infinite scroll (the endpoint returns the full set in one page — no cursor —
  // so this renders everything and just adds the loading indicator + drops the
  // Rows dropdown; the nonce reloads after create/edit/delete).
  const pages = useInfinitePages<any>(`/announcements?${view}&_=${nonce}`);
  const { rows, error, comingSoon } = pages;

  const remove = (a: any) => setConfirm({
    title: `Delete "${a.title}"?`,
    body: (
      <><p>⚠️ This will immediately remove the announcement from everyone's view.</p>
      {moderation && isCL && <p>You are deleting this announcement in <b>moderation mode</b>.</p>}
      <p>This cannot be undone.</p></>
    ),
    confirmLabel: "Delete Announcement",
    cancelLabel: "Keep Announcement",
    onConfirm: async () => {
      await apiFetch(`/announcements/${a.id}`, { method: "DELETE" });
      setMsg("Deleted."); setNonce((n) => n + 1);
    },
  });

  if (!isLeader) return <ComingSoon feature="Announcements" />;
  if (comingSoon) return <ComingSoon feature="Announcements" />;
  if (error) return <ErrorState message={error} />;

  const columns: any[] = [
    { key: "title", header: "Title", render: (a: any) => <b>{a.title}</b> },
  ];
  if (isCL) columns.push({ key: "audience", header: "Audience", render: (a: any) => <span className="badge purple">{a.audience || a.source}</span> });
  columns.push(
    { key: "createdAt", header: "Created", render: (a: any) => fmtDay(a.createdAt) },
    { key: "expiresAt", header: "Expiry", render: (a: any) => fmtExpiry(a.expiresAt) },
    { key: "emailSent", header: "Email", render: (a: any) => a.emailSent ? <span className="badge green">Sent</span> : <span className="badge gray">No</span> },
    { key: "status", header: "Status", render: (a: any) => a.status === "Expired" ? <span className="badge gray">Expired</span> : <span className="badge green">Active</span> },
    { key: "act", header: "", render: (a: any) => <span className="btn-row">
        {!moderation && <button className="btn sm" data-testid="edit-announcement" onClick={() => setEditing(a)}>Edit</button>}
        <button className="btn sm danger" data-testid="delete-announcement" onClick={() => remove(a)}>Delete</button>
      </span> },
  );

  return (
    <>
      <div className="page-head flex between">
        <div><h1>Announcements</h1><p>Broadcast to {isCL ? "the whole community or selected user groups" : "your group"}.</p></div>
        <button className="btn primary" data-testid="create-announcement" onClick={() => setCreating(true)}>＋ New Announcement</button>
      </div>
      <Banner message={msg} onDismiss={() => setMsg(null)} />
      {isCL && (
        <div className="flex" style={{ gap: 8, alignItems: "center", marginBottom: 8 }}>
          <Toggle checked={moderation} onChange={setModeration} label="Show all announcements (moderation)"
                  testId="announcement-moderation-toggle" />
          <span className="muted small">As a Community Leader you can delete any announcement for moderation.</span>
        </div>
      )}
      <div className="card">
        <DataTable id="anns" rows={rows}
          infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                      hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "announcements" }}
          emptyLabel="No announcements yet." columns={columns} />
      </div>
      {creating && <AnnouncementModal mode="create" role={role} ledGroupId={ledGroupId}
        onClose={() => setCreating(false)} onSaved={() => setNonce((n) => n + 1)} />}
      {editing && <AnnouncementModal mode="edit" role={role} ledGroupId={ledGroupId} initial={editing}
        onClose={() => setEditing(null)} onSaved={() => setNonce((n) => n + 1)} />}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

function fmtDay(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// Expiry is a calendar date (stored as end-of-day UTC), not a wall-clock instant.
// Format it in UTC so the day shown matches the date the author picked, regardless
// of the viewer's local timezone.
function fmtExpiry(iso?: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—"
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}
