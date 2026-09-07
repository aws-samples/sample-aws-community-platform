import { useMemo, useState } from "react";
import { useApi } from "../../lib/useApi";
import { useInfinitePages } from "../../lib/useInfinitePages";
import { exportPagedCsv, dateOnly } from "../../lib/exportCsv";
import DataTable from "../../components/DataTable";
import MultiSelect from "../../components/MultiSelect";
import { groupNameFrom } from "../../lib/useGroupName";
import { trailingQuarters } from "../../lib/quarters";
import type { Role } from "../../roles";
import type { CertDefinition } from "./types";
import {
  ALL_STATUS_VALUES,
  STATUS_OPTIONS,
  buildLedgerQuery,
  certLedgerStatusLabel,
  exportFilename,
  toExportRow,
} from "./certLedger";

// Certification Ledger (Certification Ledger enhancement, 2026-08-12): a CL/UGL
// member-wise list of granted certifications for one earned quarter, filtered by
// group / certification / status / member, cursor-paginated, with CSV export.
// Every read is a single-quarter GSI4 partition query (no scan). Nothing loads
// until a filter is chosen (A10=C): a CL must pick a group (or "All groups"); a
// UGL is pre-scoped to their led group and loads the current quarter on open.
const GROUP_ALL = "__ALL__";

export default function CertificationLedgerPanel({ role, ledGroupId }: {
  role: Role; ledGroupId?: string;
}) {
  const isUgl = role === "UserGroupLeader";
  const groupsApi = useApi<{ items: { id: string; name: string }[] }>("/groups");
  const groups = groupsApi.data?.items ?? [];
  const catalogApi = useApi<{ items: CertDefinition[] }>("/certifications?includeInactive=true");
  const certs = catalogApi.data?.items ?? [];

  const quarters = useMemo(() => trailingQuarters(8), []);
  const [quarter, setQuarter] = useState(quarters[0]);
  // CL: "" = nothing chosen yet (no load); GROUP_ALL = all groups; else a group.
  const [group, setGroup] = useState(isUgl ? (ledGroupId ?? "") : "");
  const [certId, setCertId] = useState("");
  const [statuses, setStatuses] = useState<string[]>([...ALL_STATUS_VALUES]);
  // Free-text member name, not a directory pick. The picker required selecting
  // an exact member from a typeahead before the filter applied at all, so a
  // partial name — or typing and hitting Search without clicking a result —
  // filtered nothing. The name is matched server-side against the name already
  // denormalised on each claim.
  const [memberName, setMemberName] = useState("");

  const [msg, setMsg] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Search is explicit — nothing loads until the user clicks Search.
  const [activeQuery, setActiveQuery] = useState<string | null>(null);

  const chosen = isUgl ? Boolean(ledGroupId) : group !== "";
  const groupIdParam = isUgl ? ledGroupId : (group === GROUP_ALL ? undefined : group);

  const baseQuery = buildLedgerQuery({
    quarter, groupId: groupIdParam, certId: certId || undefined,
    memberName, statuses,
  });

  const doSearch = () => setActiveQuery(baseQuery);

  // Infinite scroll over cursor pages; disabled until Search fires and a scope
  // is chosen. A new Search swaps `activeQuery`, resetting the list to page 1.
  const endpoint = activeQuery && chosen ? `/certifications/ledger?${activeQuery}` : null;
  const pages = useInfinitePages<any>(endpoint);
  const { rows, error } = pages;

  const groupName = (id?: string | null) => groupNameFrom(groups, id);
  const scopeLabel = isUgl
    ? groupName(ledGroupId)
    : (group === GROUP_ALL ? "All groups" : groupName(group));

  const doExport = async () => {
    if (!activeQuery) return;
    setExporting(true); setMsg(null);
    try {
      const n = await exportPagedCsv(`/certifications/ledger?${activeQuery}`,
        exportFilename(scopeLabel, quarter, memberName.trim() || undefined), {
          transform: (row) => toExportRow(row, groupName),
        });
      setMsg(`Exported ${n} row${n === 1 ? "" : "s"}.`);
    } catch (e) { setMsg((e as Error).message); }
    finally { setExporting(false); }
  };

  const statusBadge = (status?: string) => {
    const label = certLedgerStatusLabel(status);
    const cls = status === "Expired" ? "badge gray"
      : status === "Revoked" ? "badge red" : "badge green";
    return <span className={cls}>{label}</span>;
  };

  return (
    <div className="card">
      <div className="card-head"><h3>Certification Ledger</h3>
        <span className="btn-row">
          {msg && <span className="small faint">{msg}</span>}
          <button className="btn" data-testid="cert-ledger-export" disabled={exporting || !activeQuery}
                  onClick={doExport}>{exporting ? "Exporting…" : "⬇ Export CSV"}</button>
        </span>
      </div>

      <div className="flex" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 12 }}>
        <div className="field" style={{ margin: 0 }}>
          <label>User group{isUgl ? "" : " *"}</label>
          {isUgl ? (
            <input className="input" data-testid="cert-ledger-group" value={groupName(ledGroupId)} disabled />
          ) : (
            <select className="select" data-testid="cert-ledger-group" value={group}
                    onChange={(e) => setGroup(e.target.value)}>
              <option value="">Select…</option>
              <option value={GROUP_ALL}>All groups</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          )}
        </div>
        <div className="field" style={{ margin: 0 }}>
          <label>Certification</label>
          <select className="select" data-testid="cert-ledger-cert" value={certId}
                  onChange={(e) => setCertId(e.target.value)}>
            <option value="">All certificates</option>
            {certs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div className="field" style={{ margin: 0 }}>
          <label>Quarter</label>
          <select className="select" data-testid="cert-ledger-quarter" value={quarter}
                  onChange={(e) => setQuarter(e.target.value)}>
            {quarters.map((q, i) => <option key={q} value={q}>{q}{i === 0 ? " (current)" : ""}</option>)}
          </select>
        </div>
        <MultiSelect label="Status" testId="cert-ledger-status" options={STATUS_OPTIONS}
                     selected={statuses} onChange={setStatuses} />
        <div className="field" style={{ width: 220, maxWidth: "100%", margin: 0 }}>
          <label htmlFor="cert-ledger-member">Member name (optional)</label>
          <input id="cert-ledger-member" className="input" data-testid="cert-ledger-member"
                 placeholder="Type a name…" value={memberName} autoComplete="off"
                 onChange={(e) => setMemberName(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter" && chosen) doSearch(); }} />
        </div>
        <div style={{ margin: 0, paddingTop: 20 }}>
          <button className="btn primary" data-testid="cert-ledger-search" disabled={!chosen}
                  onClick={doSearch}>Search</button>
        </div>
      </div>

      {!activeQuery ? (
        <p className="faint" data-testid="cert-ledger-pick-group" style={{ padding: "16px 0" }}>
          {chosen
            ? "Set your filters and click Search to load the certification ledger."
            : "Select a user group (or \"All groups\"), then click Search to view the certification ledger."}
        </p>
      ) : error ? (
        <p className="small" style={{ color: "var(--danger)" }}>{error}</p>
      ) : (
        <DataTable id="cert-ledger" rows={rows}
          infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                      hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "certifications" }}
          emptyLabel="No certifications match these filters."
          columns={[
            { key: "memberName", header: "Member", render: (r: any) => r.memberName || "Unknown member" },
            { key: "certName", header: "Certification Name", render: (r: any) => r.certName || r.certId },
            { key: "certificationDate", header: "Certification Date", render: (r: any) => dateOnly(r.certificationDate) },
            { key: "creditedGroupId", header: "User Group", render: (r: any) => groupName(r.creditedGroupId) },
            { key: "status", header: "Status", render: (r: any) => statusBadge(r.status) },
            { key: "certCategory", header: "Category", render: (r: any) => r.certCategory || "—" },
            { key: "expiresAt", header: "Expires On", render: (r: any) => (r.expiresAt ? dateOnly(r.expiresAt) : "—") },
          ]} />
      )}
    </div>
  );
}
