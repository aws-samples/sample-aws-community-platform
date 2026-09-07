import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { domainsFieldValue, parseDomains } from "../lib/domains";
import { useAsyncExport } from "../lib/useAsyncExport";
import DataTable from "../components/DataTable";
import FormModal from "../components/FormModal";
import EditUserModal from "../components/EditUserModal";
import BulkImportModal from "../components/BulkImportModal";
import AsyncExportPanel from "../components/AsyncExportPanel";
import Toggle from "../components/Toggle";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import Banner from "../components/Banner";
import { TIMEZONES } from "../lib/timezones";
import { groupNameFrom } from "../lib/useGroupName";

// Sortable columns for the admin user table.
// User Groups is deliberately excluded — sort-by-group is ambiguous for
// multi-group members and requires group-name denormalisation in the index.
type SortKey = "name" | "email" | "role" | "status";

// identity-access stores "Active"/"Inactive" but the OpenSearch-backed listing
// normalises status to lowercase ("active"/"inactive"). Compare case-insensitively
// so the status badge and the Enable/Disable action are correct on both paths.
const isActive = (status: unknown) => String(status ?? "").toLowerCase() === "active";

// The filter set applied to a result page. Kept separate from the draft state bound
// to the inputs so that changing a dropdown never re-queries on its own.
type Filters = { q: string; role: string; status: string; groupId: string };
const EMPTY_FILTERS: Filters = { q: "", role: "", status: "", groupId: "" };

// Administrator: user management (list, add via form, edit role/groups, disable, bulk import).
// OpenSearch-backed (2026-08-19): globally sorted, full-text search, all filters
// in one query. Infinite scroll replaces Prev/Next pagination. Table stays empty
// until the admin actively submits a search/filter — this also absorbs any
// OpenSearch cold-start latency (see AdminSettingsPage warmup below).
// Search is explicit: typing in the box and changing the role/status/group
// dropdowns only stages a filter change; nothing is queried until Search is
// clicked (or Enter is pressed in the search box).
export function AdminUsersPage() {
  const [nonce, setNonce] = useState(0);
  const [editing, setEditing] = useState<any | null>(null);
  const [importing, setImporting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  // Draft filter state — bound to the search box and the dropdowns. Editing these
  // does NOT fetch anything; they are only a staging area for the next submit.
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [groupFilter, setGroupFilter] = useState("");

  // Filters actually applied to the current result set. Snapshotted from the draft
  // state when the admin clicks Search (or presses Enter in the search box), so the
  // table, the load-more pages and the CSV export all agree on one set of filters.
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);

  // Sort state — server-side; changing sort resets to page 1.
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const groups = useApi<{ items: any[] }>("/groups");
  // System-wide default time zone (Admin > Settings) pre-selects the Add User form.
  const settings = useApi<any>("/settings");
  const defaultTz: string = settings.data?.defaultTimezone ?? "UTC";

  // Infinite scroll state — mirrors DirectoryPage pattern.
  const [rows, setRows] = useState<any[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingInitial, setLoadingInitial] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  // hasSearched: table stays empty until the admin actively submits a query.
  // This absorbs the OpenSearch cold-start (10 s) while the admin is setting filters.
  const [hasSearched, setHasSearched] = useState(false);

  // Async CSV export. Deliberately not persisted: navigating away loses the link
  // (product decision) — the job still finishes server-side and its file expires
  // unread, and re-exporting is cheap.
  const {
    job: exportJob, error: exportError, running: exportRunning,
    start: startExport, reset: resetExport,
  } = useAsyncExport("/users/export");

  const abortRef = useRef<AbortController | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const LIMIT = 50;

  // Filters are passed in rather than read from state so a submit can build the
  // request from the values it just captured, without waiting for a re-render.
  const buildPath = (f: Filters, cur: string | null) => {
    const params = new URLSearchParams({ limit: String(LIMIT) });
    if (f.q) params.set("q", f.q);
    if (f.role) params.set("role", f.role);
    if (f.status) params.set("status", f.status);
    if (f.groupId) params.set("groupId", f.groupId);
    params.set("sort", sortKey);
    params.set("sortDir", sortDir);
    if (cur) params.set("cursor", cur);
    if (nonce) params.set("_", String(nonce));
    return `/users?${params.toString()}`;
  };

  const fetchPage = useCallback(async (path: string, append: boolean) => {
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    try {
      const res = await apiFetch<{ items: any[]; cursor?: string }>(path);
      setRows((prev) => append ? [...prev, ...(res.items ?? [])] : (res.items ?? []));
      setCursor(res.cursor ?? null);
      setHasMore(Boolean(res.cursor));
      setFetchError(null);
    } catch (e: any) {
      if (e?.name !== "AbortError") setFetchError((e as Error).message);
    } finally {
      setLoadingInitial(false);
      setLoadingMore(false);
    }
  }, []); // eslint-disable-line

  // Re-fetch the already-applied filters when the sort changes, or when a mutation
  // bumps the nonce (enable/disable/edit) and the visible page needs refreshing.
  // Filters are deliberately NOT dependencies here — see doSearch.
  useEffect(() => {
    if (!hasSearched) return;
    setRows([]); setCursor(null); setHasMore(false);
    setLoadingInitial(true); setFetchError(null);
    fetchPage(buildPath(applied, null), false);
  }, [sortKey, sortDir, nonce]); // eslint-disable-line

  // The only entry point that applies filter changes: the Search button and Enter
  // in the search box. Draft values are captured up front and used for this request
  // directly, so the fetch never runs against a stale snapshot.
  const doSearch = () => {
    const next: Filters = {
      q: q.trim(), role: roleFilter, status: statusFilter, groupId: groupFilter,
    };
    setApplied(next);
    if (!hasSearched) setHasSearched(true);
    setRows([]); setCursor(null); setHasMore(false);
    setLoadingInitial(true); setFetchError(null);
    fetchPage(buildPath(next, null), false);
  };

  const loadMore = useCallback(() => {
    if (!hasMore || loadingMore || loadingInitial) return;
    setLoadingMore(true);
    fetchPage(buildPath(applied, cursor), true);
  }, [hasMore, loadingMore, loadingInitial, cursor, buildPath, applied]); // eslint-disable-line

  // Infinite scroll sentinel — fires loadMore when the bottom of the list is visible.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) loadMore();
    }, { rootMargin: "200px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [loadMore]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
    // Sort change triggers re-fetch via the useEffect above (only if hasSearched).
  };

  const sortIndicator = (key: SortKey) => {
    if (sortKey !== key) return <span className="sort-ind">⇅</span>;
    return <span className="sort-ind">{sortDir === "asc" ? "▲" : "▼"}</span>;
  };

  const disable = async (id: string) => {
    try { await apiFetch(`/users/${id}/disable`, { method: "POST" }); setMsg("User disabled."); setNonce((n) => n + 1); }
    catch (e) { setMsg((e as Error).message); }
  };
  const enable = async (id: string) => {
    try { await apiFetch(`/users/${id}/enable`, { method: "POST" }); setMsg("User enabled."); setNonce((n) => n + 1); }
    catch (e) { setMsg((e as Error).message); }
  };
  // Async CSV export (replaces the single-request download, which timed out at
  // 25k users — the listing exceeded API Gateway's 29 s ceiling and the response
  // exceeded Lambda's 6 MB payload limit). Sends the filters currently applied to
  // the table, so the CSV matches what the admin is looking at rather than always
  // dumping the whole roster.
  // Uses the applied filters, not the draft dropdown values, so the CSV matches the
  // rows on screen even if the admin has changed a dropdown without hitting Search.
  const doExport = () => startExport({
    ...(applied.q ? { q: applied.q } : {}),
    ...(applied.role ? { role: applied.role } : {}),
    ...(applied.status ? { status: applied.status } : {}),
  });
  // Column definitions — Name/Email/Role/Status are sortable server-side.
  // User Groups is display-only (multi-value, ambiguous sort order).
  const columns = [
    {
      key: "email", header: "Email",
      sortValue: (u: any) => u.email,
      render: (u: any) => u.email,
    },
    {
      key: "name", header: "Name",
      sortValue: (u: any) => `${u.lastName ?? ""} ${u.firstName ?? ""}`,
      render: (u: any) => `${u.firstName ?? ""} ${u.lastName ?? ""}`,
    },
    {
      key: "role", header: "Role",
      sortValue: (u: any) => u.role,
      render: (u: any) => <span className="badge blue">{u.role}</span>,
    },
    {
      key: "groups", header: "User Groups",
      // No sortValue — group sort not supported (multi-value, ambiguous).
      render: (u: any) => {
        const ids: string[] = u.groupIds ?? [];
        if (ids.length === 0) return <span className="faint">—</span>;
        const names = ids.map((gid: string) => groupNameFrom(groups.data?.items ?? [], gid));
        const shown = names.slice(0, 3);
        const isUgl = u.role === "UserGroupLeader";
        return (
          <span className="flex wrap" style={{ gap: 4 }} data-testid={`user-groups-${u.id}`}>
            {shown.map((n, i) => <span key={i} className="tag">{n}{isUgl ? " · leads" : ""}</span>)}
            {names.length > shown.length && <span className="faint small">+{names.length - shown.length} more</span>}
          </span>
        );
      },
    },
    {
      key: "status", header: "Status",
      sortValue: (u: any) => u.status,
      render: (u: any) => <span className={"badge " + (isActive(u.status) ? "green" : "red")}>{u.status}</span>,
    },
    {
      key: "act", header: "",
      render: (u: any) => (
        <span className="btn-row">
          <button className="btn sm" data-testid="edit-user" onClick={() => setEditing(u)}>Edit</button>
          {isActive(u.status)
            ? <button className="btn sm danger" data-testid="disable-user" onClick={() => disable(u.id)}>Disable</button>
            : <button className="btn sm" data-testid="enable-user" onClick={() => enable(u.id)}>Enable</button>}
        </span>
      ),
    },
  ];

  return (
    <>
      <div className="page-head flex between">
        <div><h1>Users</h1><p>Manage users, roles, and group membership.</p></div>
        <span className="btn-row">
          <button className="btn primary" data-testid="export-users"
                  disabled={exportRunning} onClick={doExport}>
            {exportRunning ? "Preparing export…" : "⬇ Export CSV"}
          </button>
          <button className="btn primary" data-testid="bulk-import" onClick={() => setImporting(true)}>⬆ Bulk Import</button>
          <button className="btn primary" data-testid="add-user" onClick={() => setAdding(true)}>＋ Add User</button>
        </span>
      </div>
      <Banner message={msg} onDismiss={() => setMsg(null)} />

      <AsyncExportPanel job={exportJob} error={exportError} noun="users"
                        onRetry={doExport} onDismiss={resetExport} />

      {/* Filter bar */}
      <div className="card mb-16">
        <div className="flex" style={{ gap: 10 }}>
          <input
            className="input" placeholder="🔍 Search by name, email, or professional role…"
            data-testid="user-search" value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") doSearch(); }}
          />
          <select className="select" style={{ width: "auto" }} data-testid="user-role-filter"
                  value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
            <option value="">All roles</option>
            <option value="Member">Member</option>
            <option value="UserGroupLeader">User Group Leader</option>
            <option value="CommunityLeader">Community Leader</option>
            <option value="Administrator">Administrator</option>
          </select>
          <select className="select" style={{ width: "auto" }} data-testid="user-status-filter"
                  value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">Any status</option>
            <option value="Active">Active</option>
            <option value="Inactive">Inactive</option>
          </select>
          <select className="select" style={{ width: "auto" }} data-testid="user-group-filter"
                  value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
            <option value="">All groups</option>
            {(groups.data?.items ?? []).map((g: any) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </select>
          <button className="btn primary" data-testid="user-search-submit" onClick={doSearch}>Search</button>
        </div>
      </div>

      {/* Table */}
      <div className="card">
        {fetchError ? <ErrorState message={fetchError} /> : (
          <>
            {/* Empty state before first search */}
            {!hasSearched && (
              <div className="faint small" style={{ padding: "32px 4px", textAlign: "center" }}>
                Set your search terms and filters above, then click Search.
              </div>
            )}

            {/* Results table with server-controlled sort headers */}
            {hasSearched && (
              <>
                <div style={{ overflowX: "auto" as const }}>
                  <table className="tbl" data-testid="table-admin-users">
                    <thead>
                      <tr>
                        {/* Sortable columns */}
                        {(["email", "name", "role", "status"] as SortKey[]).map((col) => (
                          <th key={col} className="sortable" style={{ cursor: "pointer" }}
                              onClick={() => handleSort(col)}>
                            {columns.find((c) => c.key === col)!.header} {sortIndicator(col)}
                          </th>
                        ))}
                        {/* Non-sortable columns */}
                        <th>User Groups</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {loadingInitial
                        ? Array.from({ length: 5 }, (_, i) => (
                            <tr key={`sk-${i}`} aria-hidden="true"
                                data-testid={i === 0 ? "admin-users-skeleton" : undefined}>
                              {columns.map((c) => (
                                <td key={c.key}>
                                  <span style={{ display: "inline-block", width: "70%", height: 12,
                                                 borderRadius: 4, background: "var(--border, #e2e5ea)" }} />
                                </td>
                              ))}
                            </tr>
                          ))
                        : rows.map((u, i) => (
                            <tr key={u.id ?? i}>
                              <td>{u.email}</td>
                              <td>{u.firstName ?? ""} {u.lastName ?? ""}</td>
                              <td><span className="badge blue">{u.role}</span></td>
                              <td><span className={"badge " + (isActive(u.status) ? "green" : "red")}>{u.status}</span></td>
                              <td>
                                {(() => {
                                  const ids: string[] = u.groupIds ?? [];
                                  if (ids.length === 0) return <span className="faint">—</span>;
                                  const names = ids.map((gid: string) => groupNameFrom(groups.data?.items ?? [], gid));
                                  const shown = names.slice(0, 3);
                                  const isUgl = u.role === "UserGroupLeader";
                                  return (
                                    <span className="flex wrap" style={{ gap: 4 }}
                                          data-testid={`user-groups-${u.id}`}>
                                      {shown.map((n, j) => <span key={j} className="tag">{n}{isUgl ? " · leads" : ""}</span>)}
                                      {names.length > shown.length && <span className="faint small">+{names.length - shown.length} more</span>}
                                    </span>
                                  );
                                })()}
                              </td>
                              <td>
                                <span className="btn-row">
                                  <button className="btn sm" data-testid="edit-user" onClick={() => setEditing(u)}>Edit</button>
                                  {isActive(u.status)
                                    ? <button className="btn sm danger" data-testid="disable-user" onClick={() => disable(u.id)}>Disable</button>
                                    : <button className="btn sm" data-testid="enable-user" onClick={() => enable(u.id)}>Enable</button>}
                                </span>
                              </td>
                            </tr>
                          ))}
                    </tbody>
                  </table>
                </div>

                {/* Load-more status */}
                {loadingMore && (
                  <div className="faint small" style={{ padding: "12px 4px", textAlign: "center" }}
                       data-testid="admin-users-loading-more">Loading more…</div>
                )}
                {!loadingInitial && !loadingMore && rows.length === 0 && (
                  <div className="faint small" style={{ padding: "14px 4px" }}>
                    No users match the current filters.
                  </div>
                )}

                {/* Infinite scroll sentinel — IntersectionObserver fires loadMore */}
                {hasMore && !loadingMore && <div ref={sentinelRef} style={{ height: 1 }} />}
              </>
            )}
          </>
        )}
      </div>

      {editing && <EditUserModal user={editing} onClose={() => setEditing(null)} onSaved={() => setNonce((n) => n + 1)} />}
      {importing && <BulkImportModal onClose={() => { setImporting(false); setNonce((n) => n + 1); }} />}
      {adding && (
        <FormModal
          title="Add User"
          path="/users"
          method="POST"
          intro={<>ℹ️ Select the new user's <b>role</b> below. They set their own password via <b>Forgot password</b> on the login page (a welcome email is sent).</>}
          onClose={() => setAdding(false)}
          onSaved={(r: any) => { setMsg(`User ${r?.email ?? ""} created. They set their own password via "Forgot password" on the login page (a welcome email was sent).`); setNonce((n) => n + 1); }}
          initial={{ role: "Member", timeZone: defaultTz }}
          fields={[
            { name: "email", label: "Work email", required: true },
            { name: "firstName", label: "First name", required: true },
            { name: "lastName", label: "Last name", required: true },
            { name: "role", label: "Role", type: "select", required: true, options: [
              { value: "Member", label: "Member" },
              { value: "UserGroupLeader", label: "User Group Leader" },
              { value: "CommunityLeader", label: "Community Leader" },
              { value: "Administrator", label: "Administrator" },
            ] },
            { name: "city", label: "City" },
            { name: "country", label: "Country" },
            { name: "professionalRole", label: "Professional role" },
            { name: "timeZone", label: "Time zone", type: "select", options: TIMEZONES },
            { name: "awsProject", label: "Part of an AWS project", type: "checkbox" },
          ]}
        />
      )}
    </>
  );
}

export function AdminSettingsPage() {
  const { data, loading, error, comingSoon } = useApi<any>("/settings");
  const [values, setValues] = useState<Record<string, any> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Raw text while the admin is typing; null means "show the canonical value".
  // MUST be declared with the other hooks, above the early returns below.
  const [domainsDraft, setDomainsDraft] = useState<string | null>(null);

  // OpenSearch warmup: fire a cheap background query as soon as the admin
  // lands on the Settings page (which is now the admin landing page). By the
  // time the admin navigates to the Users tab (~10-12 s of human interaction),
  // the OpenSearch collection will have warmed up from scale-to-zero and the
  // first real user search will return without cold-start delay.
  useEffect(() => {
    apiFetch("/users?limit=1").catch(() => {}); // fire-and-forget, ignore errors
  }, []);

  if (loading) return <Loading />;
  if (comingSoon) return <ComingSoon feature="Settings" />;
  if (error) return <ErrorState message={error} />;

  const s = values ?? data ?? {};
  const set = (k: string, v: unknown) => { setValues({ ...s, [k]: v }); setSaved(false); };
  // Multiple domains are entered comma-separated. The field is edited as RAW TEXT
  // and only normalised on blur, because parsing on every keystroke made a comma
  // impossible to type: "amazon.com," parsed to ["amazon.com"] (filter(Boolean)
  // drops the empty tail), which re-rendered this controlled input as
  // "amazon.com" and swallowed the character the admin had just pressed. The same
  // applied to the space after a comma. Reported from the deployed app 2026-08-11.
  const domainsText: string = domainsFieldValue(domainsDraft, s.allowedEmailDomains);
  const setDomains = (text: string) => {
    setDomainsDraft(text);   // what the admin sees — kept verbatim, commas intact
    // Still parsed on every change so Save works even without blurring first.
    set("allowedEmailDomains", parseDomains(text));
  };
  // Drop the draft on blur so the field re-syncs to the canonical "a.com, b.com".
  const commitDomains = () => setDomainsDraft(null);

  const save = async () => {
    setSaving(true); setSaveError(null);
    try {
      // Platform-locked settings are always persisted at their fixed values,
      // regardless of any stale loaded state (the UI controls are disabled).
      const payload = { ...s, teamsEnabled: false, llmDuplicateDetectionEnabled: false, bedrockModel: "anthropic.claude-3-5-sonnet" };
      await apiFetch("/settings", { method: "PUT", body: JSON.stringify(payload) });
      setSaved(true);
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const residualDays = Number(s.otpIntervalDays ?? 0);

  return (
    <>
      <div className="page-head flex between">
        <div><h1>System Settings</h1><p>Central configuration. Administrators do not participate in community activities.</p></div>
        <button className="btn primary" data-testid="save-settings" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save Settings"}
        </button>
      </div>
      <Banner message={saved ? "Settings saved. Changes take effect immediately." : null} onDismiss={() => setSaved(false)} />
      <Banner message={saveError} kind="error" onDismiss={() => setSaveError(null)} />

      <div className="grid cols-2" data-testid="admin-settings">
        <div className="card">
          <h3>🔑 Community Access &amp; Sign-in</h3>
          <p className="faint small mb-12">
            Community users sign in with email + password, plus periodic email OTP
            re-verification. There is no corporate SSO.
          </p>

          <div className="flex between mb-12">
            <span>Allow self-registration</span>
            <Toggle testId="self-registration-toggle" checked={s.selfRegistrationEnabled !== false}
                    onChange={(v) => set("selfRegistrationEnabled", v)} />
          </div>

          <div className="field">
            <label>Allowed email domains</label>
            <input className="input" data-testid="allowed-domains" value={domainsText}
                   onChange={(e) => setDomains(e.target.value)} onBlur={commitDomains}
                   placeholder="company.com, partner.org"
                   disabled={s.selfRegistrationEnabled === false} />
            <div className="hint">
              Comma-separated. Self-registration is rejected for any email whose domain isn't on this
              list. At least one domain must be configured while self-registration is enabled.
            </div>
          </div>

          <div className="divider" />
          <h4 className="mb-8">🔐 Email OTP re-verification</h4>
          <div className="form-row">
            <div className="field">
              <label>Re-verification interval (days)</label>
              <input className="input" type="number" min={1} data-testid="otp-interval"
                     value={String(s.otpIntervalDays ?? "")}
                     onChange={(e) => set("otpIntervalDays", Number(e.target.value))} />
            </div>
          </div>
          <div className="card mb-0" style={{ background: "var(--surface-2)", borderColor: "var(--border)", padding: 10 }}>
            <span className="small">
              ℹ️ A departed employee's residual access is bounded by the re-verification interval
              (currently ~{Math.round(residualDays)} days worst case), plus up to an hour for a
              sign-in session already in progress. For immediate cutoff, disable the user in
              User Management.
            </span>
          </div>
        </div>

        <div className="card">
          <h3>🎨 Community Branding</h3>
          <div className="field"><label>Portal name</label>
            <input className="input" data-testid="community-name" value={s.communityName ?? ""}
                   onChange={(e) => set("communityName", e.target.value)} /></div>
          <div className="field"><label>Logo URL</label>
            <input className="input" value={s.logoUrl ?? ""} placeholder="https://…/logo.png"
                   onChange={(e) => set("logoUrl", e.target.value)} /></div>
          <div className="divider" />
          <div className="field mb-0"><label>System-wide default time zone</label>
            <select className="select" data-testid="system-timezone" value={s.defaultTimezone ?? "UTC"}
                    onChange={(e) => set("defaultTimezone", e.target.value)}>
              {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
            </select>
            <div className="hint">Applied to new users and anyone who hasn't set their own.</div>
          </div>
        </div>

        <div className="card">
          <h3>✉️ Email Configuration</h3>
          <div className="field"><label>Sender display name</label>
            <input className="input" data-testid="sender-name" value={s.senderName ?? ""}
                   onChange={(e) => set("senderName", e.target.value)} placeholder="AWS Community Portal" /></div>
          <div className="field"><label>Sender email (SES-verified)</label>
            <input className="input" data-testid="sender-email" value={s.senderEmail ?? ""}
                   onChange={(e) => set("senderEmail", e.target.value)} placeholder="noreply@company.com" /></div>
          <a className="btn sm" href="/admin/email-templates">Manage templates →</a>
        </div>

        <div className="card">
          <h3>👏 Shoutout Weekly Quotas</h3>
          <p className="faint small">Maximum number of shoutouts each role can send per calendar week (resets Monday).</p>
          <div className="grid cols-3" style={{ gap: 12 }}>
            <div className="field mb-0">
              <label>Member</label>
              <input className="input" type="number" min={0} max={100} data-testid="shoutout-limit-member"
                     value={String(s.shoutoutLimitMember ?? 3)}
                     onChange={(e) => set("shoutoutLimitMember", Number(e.target.value))} />
            </div>
            <div className="field mb-0">
              <label>User Group Leader</label>
              <input className="input" type="number" min={0} max={100} data-testid="shoutout-limit-ugl"
                     value={String(s.shoutoutLimitUgl ?? 6)}
                     onChange={(e) => set("shoutoutLimitUgl", Number(e.target.value))} />
            </div>
            <div className="field mb-0">
              <label>Community Leader</label>
              <input className="input" type="number" min={0} max={100} data-testid="shoutout-limit-cl"
                     value={String(s.shoutoutLimitCl ?? 10)}
                     onChange={(e) => set("shoutoutLimitCl", Number(e.target.value))} />
            </div>
          </div>
        </div>

        <div className="card">
          <h3>📹 MS Teams Integration</h3>
          <div className="flex between mb-12">
            <span>Enable attendance tracking</span>
            <Toggle testId="teams-enabled" checked={false} disabled onChange={() => {}} />
          </div>
          <div className="field mb-0"><label>Tenant ID</label>
            <input className="input" data-testid="teams-tenant" value={s.teamsTenantId ?? ""}
                   placeholder="contoso.onmicrosoft.com" disabled /></div>
          <p className="faint small mt-8 mb-0">🔒 Locked by platform policy — MS Teams integration is disabled.</p>
        </div>

        <div className="card">
          <h3>🤖 LLM Duplicate Post Analysis</h3>
          <div className="flex between">
            <span>Analyze new posts for duplicates</span>
            <Toggle testId="llm-dup" checked={false} disabled onChange={() => {}} />
          </div>
          <p className="faint small mt-8 mb-0">🔒 Locked by platform policy — LLM duplicate-post analysis is disabled.</p>
        </div>

        <div className="card">
          <h3>🧠 Amazon Bedrock Model</h3>
          <div className="field mb-0"><label>Model ID (all AI features)</label>
            <select className="select" data-testid="bedrock-model" value="anthropic.claude-3-5-sonnet" disabled onChange={() => {}}>
              <option value="anthropic.claude-3-5-sonnet">anthropic.claude-3-5-sonnet</option>
              <option value="anthropic.claude-3-haiku">anthropic.claude-3-haiku</option>
              <option value="amazon.titan-text-premier">amazon.titan-text-premier</option>
            </select>
            <div className="hint">🔒 Locked by platform policy — fixed to Claude 3.5 Sonnet.</div>
          </div>
        </div>

        <div className="card">
          <h3>🆕 What's New in AWS Feed</h3>
          <div className="flex between mb-12">
            <span>Show the AWS announcements feed</span>
            <Toggle testId="feed-enabled" checked={s.whatsNewEnabled !== false} onChange={(v) => set("whatsNewEnabled", v)} />
          </div>
          <div className="field mb-0"><label>Feed URL (RSS/Atom XML)</label>
            <input className="input" value={s.whatsNewFeedUrl ?? ""} placeholder="https://…/feed.xml"
                   onChange={(e) => set("whatsNewFeedUrl", e.target.value)} disabled={s.whatsNewEnabled === false} />
            <div className="hint">Must be CORS-enabled. Disabled hides the nav item and page for everyone.</div>
          </div>
        </div>

        <div className="card">
          <h3>🔎 Platform Features</h3>
          <div className="flex between">
            <span>Semantic search (OpenSearch + embeddings)</span>
            <Toggle testId="semantic-search" checked={false} disabled onChange={() => {}} />
          </div>
          <p className="faint small mt-8 mb-0">Not available yet — semantic search is planned for a future release and is disabled platform-wide.</p>
        </div>
      </div>
    </>
  );
}

export function EmailTemplatesPage() {
  const { data, loading, error, comingSoon } = useApi<{ items: any[] }>("/settings/email-templates");
  const [editing, setEditing] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  if (loading) return <Loading />;
  if (comingSoon) return <ComingSoon feature="Email Templates" />;
  if (error) return <ErrorState message={error} />;
  return (
    <>
      <div className="page-head"><h1>Email Templates</h1><p>Customize transactional email subject and content.</p></div>
      <Banner message={msg} onDismiss={() => setMsg(null)} />
      <div className="card">
        <DataTable id="email-templates" rows={data?.items ?? []} columns={[
          { key: "name", header: "Template", render: (t) => <b>{t.name}</b> },
          { key: "subject", header: "Subject", render: (t) => t.subject },
          { key: "act", header: "", render: (t) => <button className="btn sm" data-testid="edit-template" onClick={() => setEditing(t)}>Edit</button> },
        ]} />
      </div>
      {editing && <FormModal title={`Edit "${editing.name}"`} path={`/settings/email-templates/${editing.id}`} method="PUT"
        initial={{ subject: editing.subject }} onClose={() => setEditing(null)} onSaved={() => setMsg("Template saved.")}
        fields={[{ name: "subject", label: "Subject", required: true }, { name: "body", label: "Body", type: "textarea" }]} />}
    </>
  );
}
