import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { useDebounced } from "../lib/useDebounced";
import { apiFetch } from "../lib/apiClient";
import DataTable from "../components/DataTable";
import { useInfinitePages } from "../lib/useInfinitePages";
import { ComingSoon, EmptyState, ErrorState, EventCardSkeleton } from "../components/States";
import ToastStack, { useToasts } from "../components/ToastStack";
import EventModal, { DELIVERY_MODES, EVENT_TYPES } from "./EventModal";
import { groupNameFrom, useGroupName } from "../lib/useGroupName";
import { currentQuarter, quarterRange, trailingQuarters } from "../lib/quarters";
import { dateOnly, download, toCsv } from "../lib/exportCsv";
import EventIdeasTab from "./EventIdeasTab";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import type { Role } from "../roles";

// Events landing screen (US-2.13/2.20). Role-shaped, per the mockups:
//  * Community Leader / User Group Leader -> management table. CL has a Scope
//    column; the UGL mockup omits it because the group is implied.
//  * Member -> card grid with status tabs.
// Filters, search, server-side pagination, cancel confirmations and empty
// states are all present — the mockups lacked them (gaps G12/G16/G19) and every
// other list in this portal already has them.

export interface EventItem {
  id: string; title: string; description?: string; type: string; deliveryMode: string;
  status: string; groupId?: string | null; startsAt?: string; endsAt?: string;
  rsvpYesCount?: number; attendedCount?: number; canManage?: boolean;
  attendancePoints?: number; myRsvp?: string | null; myAttended?: boolean;
}

const TYPE_BADGE: Record<string, string> = {
  Workshop: "blue", Meetup: "purple", Hackathon: "amber", Webinar: "blue",
  Presentation: "purple", Conference: "blue", Social: "gray", "AMA / Fireside Chat": "gray",
};

export function statusBadge(status: string): string {
  // Unified with the list (mockup gap G2 had Upcoming as green on one screen).
  return status === "Completed" ? "green" : status === "Cancelled" ? "red" : "blue";
}

// Group ids are internal — screens resolve them to names via useGroupName /
// groupNameFrom (lib/useGroupName) instead of ever rendering the raw id.

// An event owns a span. Show a single moment when start and end land on the same
// day (the common case), and a full date range for a multi-day event.
function whenRange(startsAt?: string, endsAt?: string): string {
  if (!startsAt) return "TBD";
  const start = new Date(startsAt);
  if (Number.isNaN(start.getTime())) return "TBD";
  if (!endsAt) return start.toLocaleString();
  const end = new Date(endsAt);
  if (Number.isNaN(end.getTime())) return start.toLocaleString();
  const sameDay = start.toDateString() === end.toDateString();
  return sameDay
    ? `${start.toLocaleString()} – ${end.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`
    : `${start.toLocaleString()} – ${end.toLocaleString()}`;
}

export default function EventsPage({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  const [tab, setTab] = useState<"list" | "library" | "ideas">("list");
  const isLeader = role === "CommunityLeader" || role === "UserGroupLeader";

  // BR-A1: Administrators have no event permissions at all — not even read. The
  // nav already omits Events for them; this guards a direct URL.
  if (role === "Administrator") {
    return (
      <>
        <div className="page-head"><h1>Events</h1></div>
        <EmptyState message="Administrators do not participate in events." />
      </>
    );
  }

  return (
    <>
      <div className="page-head flex between">
        <div>
          <h1>Events</h1>
          <p>{isLeader
            ? "Create and manage events, or search content from past events."
            : "Browse events from your user groups and community-wide events."}</p>
        </div>
        <div className="btn-row">
          <Link className="btn" to="/events/calendar" data-testid="events-calendar-link">📆 Calendar view</Link>
        </div>
      </div>

      <div className="tabs" style={{ marginBottom: 16 }}>
        <div className={"tab" + (tab === "list" ? " active" : "")} data-testid="tab-events"
             onClick={() => setTab("list")}>{isLeader ? "Manage Events" : "📅 Browse Events"}</div>
        <div className={"tab" + (tab === "ideas" ? " active" : "")} data-testid="tab-ideas"
             onClick={() => setTab("ideas")}>💡 Event Ideas</div>
      </div>

      {tab === "list" && (isLeader
        ? <LeaderEventsList role={role} ledGroupId={ledGroupId} />
        : <MemberEventsBrowser />)}
      {tab === "ideas" && <EventIdeasTab role={role} ledGroupId={ledGroupId} />}
    </>
  );
}

// ---------------------------------------------------------------- leader list

function LeaderEventsList({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  const [searchParams] = useSearchParams();
  const [nonce, setNonce] = useState(0);
  const { toasts, success, error: toastMsg, dismissToast } = useToasts();
  const [search, setSearch] = useState("");
  const [fStatus, setFStatus] = useState("Upcoming");
  const [fType, setFType] = useState("");
  const [fGroup, setFGroup] = useState("");
  // Quarter filter defaults to the CURRENT quarter so a leader lands on the
  // period they are running, not the whole history. A ?quarter= link (from the
  // dashboard's Group Events figure) opens on that period instead, so the count
  // clicked and the list shown always agree.
  const [fQuarter, setFQuarter] = useState(() => {
    const linked = searchParams.get("quarter");
    return linked && trailingQuarters(8).includes(linked) ? linked : currentQuarter();
  });
  const [exporting, setExporting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<EventItem | null>(null);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);

  const q = useDebounced(search, 300);

  // Real groups for the modal: the CL Scope dropdown lists them, and the UGL
  // readonly Scope field shows the led group's name. This list being hardcoded
  // to [] was half of the "cannot save an Event" defect.
  const groupsApi = useApi<{ items: { id: string; name: string }[] }>("/groups");
  const groupOptions = (groupsApi.data?.items ?? []).map((g) => ({ id: g.id, name: g.name }));
  const gname = (gid?: string | null) => groupNameFrom(groupOptions, gid);

  // Query string for the current filter set, shared by the table and the export
  // so the CSV can never disagree with what is on screen.
  const filterParams = useMemo(() => {
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (fStatus) params.set("status", fStatus);
    if (fType) params.set("type", fType);
    if (fGroup) params.set("groupId", fGroup);
    const range = quarterRange(fQuarter);
    if (range) { params.set("from", range.from); params.set("to", range.to); }
    return params;
  }, [q, fStatus, fType, fGroup, fQuarter]);

  // Endpoint for the infinite list (hook appends limit/cursor). A filter change
  // rebuilds filterParams → new endpoint → reset to page 1; reload() bumps the
  // nonce after a create/edit/cancel to refresh in place.
  const endpoint = useMemo(() => {
    const params = new URLSearchParams(filterParams);
    params.set("_", String(nonce));
    return `/events?${params.toString()}`;
  }, [filterParams, nonce]);

  const pages = useInfinitePages<EventItem>(endpoint);
  const { rows, error, comingSoon } = pages;

  const reload = () => setNonce((n) => n + 1);
  const resetFilter = (apply: () => void) => { apply(); };

  // Export exactly what the current filters select (US-7.11). Presenter and
  // organizer NAMES are not on the list rows — only counts are — so they are
  // resolved per event from its designations. That is N extra requests, which is
  // acceptable for a user-initiated export of one filtered page-set but would
  // not be for the table itself; they run a few at a time rather than all at once.
  const doExport = async () => {
    setExporting(true);
    try {
      const events: EventItem[] = [];
      let cur: string | undefined;
      do {
        const params = new URLSearchParams(filterParams);
        params.set("limit", "200");
        if (cur) params.set("cursor", cur);
        const page = await apiFetch<{ items: EventItem[]; cursor?: string }>(
          `/events?${params.toString()}`);
        events.push(...(page.items ?? []));
        cur = page.cursor;
      } while (cur && events.length < 5000);

      const names = new Map<string, { presenters: string[]; organizers: string[] }>();
      for (let i = 0; i < events.length; i += 5) {
        const batch = events.slice(i, i + 5);
        await Promise.all(batch.map(async (e) => {
          try {
            const res = await apiFetch<{ items: any[] }>(`/events/${e.id}/designations`);
            const rows = res.items ?? [];
            names.set(e.id, {
              presenters: rows.filter((d) => d.kind === "presenter")
                .map((d) => d.displayName || d.userId).filter(Boolean),
              organizers: rows.filter((d) => d.kind === "organizer")
                .map((d) => d.displayName || d.userId).filter(Boolean),
            });
          } catch { /* a failed lookup leaves that event's names blank */ }
        }));
      }

      const rows = events.map((e) => ({
        "Event Name": e.title ?? "",
        "Description": e.description ?? "",
        "Type": e.type ?? "",
        "Status": e.status ?? "",
        "Date": dateOnly(e.startsAt),
        "Presenters": (names.get(e.id)?.presenters ?? []).join("; "),
        "Organizer": (names.get(e.id)?.organizers ?? []).join("; "),
        "RSVP / Attended": `${e.rsvpYesCount ?? 0} / ${e.attendedCount ?? 0}`,
      }));
      download(`events_${fQuarter || "all"}${fStatus ? `_${fStatus}` : ""}.csv`, toCsv(rows));
      success(`Exported ${rows.length} event${rows.length === 1 ? "" : "s"}.`);
    } catch (err) {
      toastMsg((err as Error).message);
    } finally { setExporting(false); }
  };

  const cancelEvent = (row: EventItem) => setConfirm({
    title: `Cancel "${row.title}"?`,
    body: (
      <><p>⚠️ Everyone who RSVP'd will be <b>notified by email</b>. The event stays visible with a Cancelled badge.</p>
      <p>This cannot be undone.</p></>
    ),
    confirmLabel: "Cancel Event",
    cancelLabel: "Keep Event",
    onConfirm: async () => {
      await apiFetch(`/events/${row.id}`, { method: "DELETE" });
      success(`"${row.title}" was cancelled and attendees were notified.`);
      reload();
    },
  });

  if (comingSoon) return <ComingSoon feature="Events" />;

  return (
    <>
      <div className="flex between mb-16" style={{ gap: 12, flexWrap: "wrap" }}>
        <div className="flex" style={{ gap: 8, flexWrap: "wrap" }}>
          <input className="input" style={{ width: 220 }} placeholder="🔍 Search events…"
                 data-testid="events-search" value={search}
                 onChange={(e) => resetFilter(() => setSearch(e.target.value))} />
          <select className="select" style={{ width: "auto" }} data-testid="events-status-filter"
                  value={fStatus} onChange={(e) => resetFilter(() => setFStatus(e.target.value))}>
            <option value="">All statuses</option>
            {["Upcoming", "Completed", "Cancelled"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className="select" style={{ width: "auto" }} data-testid="events-type-filter"
                  value={fType} onChange={(e) => resetFilter(() => setFType(e.target.value))}>
            <option value="">All event types</option>
            {EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}
          </select>
          <select className="select" style={{ width: "auto" }} data-testid="events-quarter-filter"
                  value={fQuarter} onChange={(e) => resetFilter(() => setFQuarter(e.target.value))}>
            <option value="">All quarters</option>
            {trailingQuarters(8).map((qq, i) => (
              <option key={qq} value={qq}>{qq}{i === 0 ? " (current)" : ""}</option>
            ))}
          </select>
          {role === "CommunityLeader" && (
            <select className="select" style={{ width: "auto" }}
                    data-testid="events-group-filter" value={fGroup}
                    onChange={(e) => resetFilter(() => setFGroup(e.target.value))}>
              <option value="">All groups</option>
              {groupOptions.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          )}
        </div>
        <span className="btn-row">
          <button className="btn" data-testid="export-events" disabled={exporting} onClick={doExport}>
            {exporting ? "Exporting…" : "⬇ Export"}
          </button>
          <button className="btn primary" data-testid="create-event" onClick={() => setCreating(true)}>
            ＋ Create Event
          </button>
        </span>
      </div>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
      {error && <ErrorState message={error} />}

      {!error && (
        <div className="card">
          <DataTable
            id="events"
            rows={rows}
            infinite={{ loadingInitial: pages.loadingInitial, loadingMore: pages.loadingMore,
                        hasMore: pages.hasMore, onLoadMore: pages.loadMore, unit: "events" }}
            emptyLabel={q || fType || fGroup
              ? "No events match your search or filters."
              : "No events yet. Create the first one."}
            columns={[
              {
                key: "title", header: "Event",
                render: (e) => (
                  <div>
                    <span className={`badge ${TYPE_BADGE[e.type] ?? "blue"}`}>{e.type}</span>{" "}
                    <Link to={`/events/${e.id}`}><b>{e.title}</b></Link>
                  </div>
                ),
              },
              { key: "type", header: "Type", render: (e) => e.type },
              ...(role === "CommunityLeader"
                ? [{ key: "scope", header: "Scope", render: (e: EventItem) => gname(e.groupId) }]
                : []),
              { key: "date", header: "Date", render: (e) => whenRange(e.startsAt, e.endsAt) },
              {
                key: "rsvp", header: "RSVP / Attended",
                render: (e) => `${e.rsvpYesCount ?? 0} / ${e.attendedCount ? e.attendedCount : "—"}`,
              },
              {
                key: "status", header: "Status",
                render: (e) => <span className={`badge ${statusBadge(e.status)}`}>{e.status}</span>,
              },
              {
                key: "act", header: "",
                render: (e) => {
                  // The API computes canManage per caller (BR-A4/A5) — a UGL
                  // cannot manage community-wide events or other groups' events,
                  // so those rows get a read-only View link instead of buttons
                  // that would only produce a 403.
                  if (e.status === "Cancelled") return <span className="faint">—</span>;
                  if (!e.canManage) {
                    return <Link className="btn sm" to={`/events/${e.id}`}
                                 data-testid={`view-${e.id}`}>View</Link>;
                  }
                  if (e.status === "Completed") {
                    return <Link className="btn sm" to={`/events/${e.id}/manage`}
                                 data-testid={`view-${e.id}`}>View</Link>;
                  }
                  return (
                    <span className="btn-row">
                      <Link className="btn sm" to={`/events/${e.id}/manage`}
                            data-testid={`manage-${e.id}`}>Manage</Link>
                      <button className="btn sm" data-testid={`edit-${e.id}`}
                              onClick={() => setEditing(e)}>Edit</button>
                      <button className="btn sm danger" data-testid={`cancel-${e.id}`}
                              onClick={() => cancelEvent(e)}>Cancel</button>
                    </span>
                  );
                },
              },
            ]}
          />
        </div>
      )}

      {role === "UserGroupLeader" && (
        <p className="faint small mt-12">
          You manage events for the group you lead. You can also edit or cancel any event scoped to
          your group, even one a Community Leader created.
        </p>
      )}

      {creating && (
        <EventModal mode="create" role={role} ledGroupId={ledGroupId} groups={groupOptions}
                    onClose={() => setCreating(false)} onSaved={reload} />
      )}
      {editing && (
        <EventModal mode="edit" role={role} ledGroupId={ledGroupId} groups={groupOptions}
                    initial={editing} onClose={() => setEditing(null)} onSaved={reload} />
      )}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

// ---------------------------------------------------------------- member cards

function MemberEventsBrowser() {
  const [status, setStatus] = useState("Upcoming");
  const [search, setSearch] = useState("");
  const [fType, setFType] = useState("");
  const [fMode, setFMode] = useState("");
  const [nonce, setNonce] = useState(0);
  const { toasts, success, error: toastError, dismissToast } = useToasts();
  const q = useDebounced(search, 300);

  const params = new URLSearchParams({ status, limit: "60", _: String(nonce) });
  if (q) params.set("q", q);
  if (fType) params.set("type", fType);
  if (fMode) params.set("deliveryMode", fMode);

  const { data, loading, error, comingSoon } = useApi<{ items: EventItem[] }>(`/events?${params.toString()}`);
  const rows = data?.items ?? [];
  const gname = useGroupName();

  const rsvp = async (id: string, response: "yes" | "no") => {
    try {
      await apiFetch(`/events/${id}/rsvp`, { method: "POST", body: JSON.stringify({ response }) });
      success(response === "yes"
        ? "You're going! A calendar invite is on its way."
        : "Thanks — RSVP recorded as not going.");
      setNonce((n) => n + 1);
    } catch (err) { toastError((err as Error).message); }
  };

  if (comingSoon) return <ComingSoon feature="Events" />;

  return (
    <>
      <div className="card mb-16">
        <div className="flex wrap between" style={{ gap: 12 }}>
          <div className="tabs" style={{ border: "none", margin: 0 }}>
            {["Upcoming", "Completed", "Cancelled"].map((s) => (
              <div key={s} className={"tab" + (status === s ? " active" : "")}
                   data-testid={`status-tab-${s.toLowerCase()}`} onClick={() => setStatus(s)}>{s}</div>
            ))}
          </div>
          <div className="flex wrap" style={{ gap: 12 }}>
            <input className="input" style={{ width: 220 }} placeholder="🔍 Search events…"
                   data-testid="member-events-search" value={search}
                   onChange={(e) => setSearch(e.target.value)} />
            <select className="select" style={{ width: "auto" }} data-testid="member-type-filter"
                    value={fType} onChange={(e) => setFType(e.target.value)}>
              <option value="">All event types</option>
              {EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            <select className="select" style={{ width: "auto" }} data-testid="member-mode-filter"
                    value={fMode} onChange={(e) => setFMode(e.target.value)}>
              <option value="">All delivery modes</option>
              {DELIVERY_MODES.map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
        </div>
      </div>

      <ToastStack toasts={toasts} onDismiss={dismissToast} />
      {error && <ErrorState message={error} />}

      {loading && !error && <EventCardSkeleton />}

      {!loading && !error && (
        <div className="grid cols-3" data-testid="member-events-grid">
          {rows.map((e) => <EventCard key={e.id} event={e} onRsvp={rsvp} groupName={gname} />)}
        </div>
      )}
      {!loading && !error && rows.length === 0 && (
        <EmptyState message={q || fType || fMode
          ? "No events match your search."
          : `No ${status.toLowerCase()} events to show.`} />
      )}
    </>
  );
}

function EventCard({ event, onRsvp, groupName }: {
  event: EventItem; onRsvp: (id: string, r: "yes" | "no") => void;
  groupName: (gid?: string | null) => string;
}) {
  const cancelled = event.status === "Cancelled";
  const body = (
    <>
      <div className="flex between mb-8">
        <span className={`badge ${TYPE_BADGE[event.type] ?? "blue"}`}>{event.type}</span>
        <span className={`badge ${cancelled ? "red" : "gray"}`}>
          {cancelled ? "Cancelled" : event.deliveryMode}</span>
      </div>
      <h3 className="mb-8">{event.title}</h3>
      <div className="faint small">📅 {whenRange(event.startsAt, event.endsAt)}</div>
      <div className="faint small mb-12">
        {event.groupId ? `👥 ${groupName(event.groupId)}` : "🌐 Community-wide"}</div>
      {cancelled ? (
        <div className="faint small">Cancelled by organizer · attendees notified</div>
      ) : (
        <div className="flex between" style={{ alignItems: "center" }}>
          {event.status === "Completed" ? (
            <span className={`badge ${event.myAttended ? "green" : "gray"}`}>
              {event.myAttended ? "✓ You attended" : "Completed"}</span>
          ) : event.myRsvp === "yes" ? (
            <span className="badge green" data-testid={`rsvpd-${event.id}`}>✓ You RSVP'd</span>
          ) : (
            <span className="btn-row">
              <button className="btn sm primary" data-testid={`rsvp-yes-${event.id}`}
                      onClick={(ev) => { ev.preventDefault(); onRsvp(event.id, "yes"); }}>RSVP</button>
            </span>
          )}
          {/* Points tag is OMITTED when the value is unavailable — a scoring
              outage hides the tag rather than rendering a misleading "+0 pts". */}
          {typeof event.attendancePoints === "number" && (
            <span className="tag">+{event.attendancePoints} pts to attend</span>
          )}
        </div>
      )}
    </>
  );
  if (cancelled) return <div className="card">{body}</div>;
  return <Link className="card" to={`/events/${event.id}`} style={{ color: "var(--text)" }}>{body}</Link>;
}

// ------------------------------------------------------------ content library
// ContentLibraryTab has been removed (US-2.20 rework 2026-08-18).
// The Content Library is now a standalone page at /content-library.
// See frontend/src/features/ContentLibraryPage.tsx.
