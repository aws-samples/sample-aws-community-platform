import { useMemo, useState } from "react";
import { useApi } from "../../lib/useApi";
import { useInfinitePages } from "../../lib/useInfinitePages";
import { useAsyncExport } from "../../lib/useAsyncExport";
import { dateOnly } from "../../lib/exportCsv";
import AsyncExportPanel from "../../components/AsyncExportPanel";
import DataTable from "../../components/DataTable";
import MultiSelect from "../../components/MultiSelect";
import PeoplePicker, { type PickedPerson } from "../../components/PeoplePicker";
import { groupNameFrom } from "../../lib/useGroupName";
import { pillarLabel } from "../../lib/pillars";
import { trailingQuarters } from "../../lib/quarters";
import type { Role } from "../../roles";
import {
  ACTIVITY_CATEGORY_OPTIONS,
  SOURCE_OPTIONS,
  buildLedgerQuery,
  ledgerFilterFields,
} from "./pointLedger";

// Point Ledger (US-7.9): a CL/UGL view of individual point entries for one group
// and quarter, with member / source / activity-type filters, cursor pagination,
// and CSV export. Every read stays on the group+quarter index — no all-groups /
// custom-range scan (deliberate scope, per the requirements). Nothing loads until
// the user clicks Search.
export default function PointLedgerPanel({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  const isUgl = role === "UserGroupLeader";
  const groupsApi = useApi<{ items: { id: string; name: string }[] }>("/groups");
  const groups = groupsApi.data?.items ?? [];

  const quarters = useMemo(() => trailingQuarters(8), []);
  const [quarter, setQuarter] = useState(quarters[0]);
  // A UGL is locked to their led group; a CL must choose (no default → no load).
  const [group, setGroup] = useState(isUgl ? (ledGroupId ?? "") : "");
  const groupId = isUgl ? (ledGroupId ?? "") : group;

  const [person, setPerson] = useState<PickedPerson[]>([]);
  const member = person[0];
  // Source is no longer a user-facing filter (removed per US-7.9 refinement) —
  // send all sources so the query stays unfiltered on that dimension.
  const sources = SOURCE_OPTIONS.map((o) => o.value);
  const [categories, setCategories] = useState<string[]>(ACTIVITY_CATEGORY_OPTIONS.map((o) => o.value));

  // Search is now explicit — the query only fires when the user clicks Search.
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  // The filters the table is actually showing, snapshotted at Search. The export
  // must use these rather than the live dropdowns, or the CSV would not match the
  // rows on screen when someone changes a filter without searching again.
  const [appliedFilters, setAppliedFilters] = useState<Record<string, string>>({});

  const filterState = { groupId, quarter, memberId: member?.id, sources, categories };
  const baseQuery = buildLedgerQuery(filterState);

  const doSearch = () => {
    setActiveQuery(baseQuery);
    setAppliedFilters(ledgerFilterFields(filterState));
  };

  // Async CSV export, same job pattern as Admin > Users. Deliberately not
  // persisted: navigating away loses the link (the job still finishes and its
  // file expires unread) and re-exporting is cheap.
  const {
    job: exportJob, error: exportError, running: exportRunning,
    start: startExport, reset: resetExport,
  } = useAsyncExport("/contributions/group-ledger/export");

  // Infinite scroll: accumulate cursor pages of the ledger. Disabled until a
  // Search fires (activeQuery set) and a group is chosen.
  const endpoint = activeQuery && groupId
    ? `/contributions/group-ledger?${activeQuery}` : null;
  const pages = useInfinitePages<any>(endpoint);
  const { rows, error } = pages;

  const groupName = (id?: string | null) => groupNameFrom(groups, id);

  // groupName travels with the request because this service stores group IDs and
  // never names — the CSV's user_group column needs the display name, and the
  // worker has no way to resolve it. Display-only: it cannot change which rows
  // are exported.
  const doExport = () => startExport({
    ...appliedFilters,
    groupName: groupName(groupId),
  });

  return (
    <div className="card">
      <div className="card-head"><h3>Point Ledger</h3>
        <span className="btn-row">
          {/* Export feedback lives in AsyncExportPanel below, not in a one-line
              message — a multi-minute job needs progress, not a toast. */}
          <button className="btn" data-testid="pl-export" disabled={exportRunning || !activeQuery}
                  onClick={doExport}>
            {exportRunning ? "Preparing export…" : "⬇ Export CSV"}
          </button>
        </span>
      </div>

      <AsyncExportPanel job={exportJob} error={exportError} noun="entries"
                        onRetry={doExport} onDismiss={resetExport} />

      <div className="flex" style={{ gap: 10, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 12 }}>
        {/* Group — required. UGL locked to their led group. */}
        <div className="field" style={{ margin: 0 }}>
          <label>User group *</label>
          {isUgl ? (
            <input className="input" data-testid="pl-group" value={groupName(groupId)} disabled />
          ) : (
            <select className="select" data-testid="pl-group" value={group}
                    onChange={(e) => setGroup(e.target.value)}>
              <option value="">Select a group…</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          )}
        </div>
        <div className="field" style={{ margin: 0 }}>
          <label>Quarter</label>
          <select className="select" data-testid="pl-quarter" value={quarter}
                  onChange={(e) => setQuarter(e.target.value)}>
            {quarters.map((q, i) => <option key={q} value={q}>{q}{i === 0 ? " (current)" : ""}</option>)}
          </select>
        </div>
        <MultiSelect label="Activity type" testId="pl-activity" options={ACTIVITY_CATEGORY_OPTIONS}
                     selected={categories} onChange={setCategories} />
        <div style={{ width: 220, maxWidth: "100%", margin: 0 }}>
          <PeoplePicker label="Member (optional)" testId="pl-member" selected={person}
                        onChange={(next) => setPerson(next.slice(-1))}
                        groupId={groupId || undefined} />
        </div>
        <div style={{ margin: 0, paddingTop: 20 }}>
          <button className="btn primary" data-testid="pl-search" disabled={!groupId}
                  onClick={doSearch}>Search</button>
        </div>
      </div>

      {!activeQuery ? (
        <p className="faint" data-testid="pl-pick-group" style={{ padding: "16px 0" }}>
          {groupId
            ? "Set your filters and click Search to load the point ledger."
            : "Select a user group, then click Search to view its point ledger."}
        </p>
      ) : error ? (
        <p className="small" style={{ color: "var(--danger)" }}>{error}</p>
      ) : (
        <DataTable id="point-ledger" rows={rows}
          infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                      hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "entries" }}
          emptyLabel="No point entries match these filters."
          columns={[
            { key: "memberName", header: "Member", render: (r: any) => r.memberName || "Unknown member" },
            { key: "memberEmail", header: "Email", render: (r: any) => r.memberEmail || "—" },
            { key: "points", header: "Points", render: (r: any) => <b>{Number(r.points) > 0 ? "+" : ""}{r.points}</b> },
            { key: "activity", header: "Activity", render: (r: any) => r.activity || "—" },
            { key: "earnedDate", header: "Date", render: (r: any) => dateOnly(r.earnedDate) },
            // Secondary columns — available via Column Settings, hidden by default.
            { key: "group", header: "Group", defaultHidden: true, render: () => groupName(groupId) },
            { key: "source", header: "Source", defaultHidden: true, render: (r: any) => <span className="badge">{r.source}</span> },
            { key: "pillar", header: "Pillar", defaultHidden: true, render: (r: any) => pillarLabel(r.pillar) },
          ]} />
      )}
    </div>
  );
}
