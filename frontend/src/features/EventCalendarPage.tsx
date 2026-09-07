import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { ComingSoon, EmptyState, ErrorState, Loading } from "../components/States";
import { EVENT_TYPES } from "./EventModal";
import type { EventItem } from "./EventsPage";
import type { Role } from "../roles";

// Event calendar (US-2.9). Month / Week / List, all three functional — the
// mockups left Week and List inert and made the chips unclickable (gap G15).
// A Community Leader gets the group filter; UGL and Member do not, matching
// their mockups. Hand-built CSS grid rather than a calendar dependency: the
// design is a static 7-column month grid and a library would be disproportionate.
const TYPE_COLOUR: Record<string, string> = {
  Workshop: "var(--primary)", Meetup: "var(--accent)", Hackathon: "var(--warning)",
  Webinar: "var(--info)", Presentation: "var(--success)", Conference: "var(--primary)",
  Social: "var(--text-faint)", "AMA / Fireside Chat": "var(--text-faint)",
};

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function monthBounds(cursor: Date) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
  return { first, last };
}

function isoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export default function EventCalendarPage({ role }: { role: Role }) {
  const [cursor, setCursor] = useState(() => new Date());
  const [view, setView] = useState<"month" | "week" | "list">("month");
  const [fType, setFType] = useState("");
  const [fGroup, setFGroup] = useState("");

  if (role === "Administrator") {
    return (
      <>
        <div className="page-head"><h1>Event Calendar</h1></div>
        <EmptyState message="Administrators do not participate in events." />
      </>
    );
  }

  const { first, last } = monthBounds(cursor);
  // The window is widened by a week either side so the month grid's leading and
  // trailing days (and the week view) have data.
  const from = new Date(first); from.setDate(from.getDate() - 7);
  const to = new Date(last); to.setDate(to.getDate() + 7);

  const params = new URLSearchParams({ from: isoDate(from), to: isoDate(to), status: "Upcoming" });
  if (fType) params.set("type", fType);
  if (fGroup) params.set("groupId", fGroup);

  const { data, loading, error, comingSoon } = useApi<{ items: EventItem[] }>(
    `/events/calendar?${params.toString()}`);

  const events = data?.items ?? [];

  // A multi-day event (e.g. a hackathon) is placed on every calendar day it
  // covers, from its start date through its end date inclusive, so it is visible
  // across its whole run rather than only on the day it starts.
  const byDay = useMemo(() => {
    const map: Record<string, EventItem[]> = {};
    for (const e of events) {
      if (!e.startsAt) continue;
      const start = new Date(e.startsAt);
      if (Number.isNaN(start.getTime())) continue;
      const end = e.endsAt ? new Date(e.endsAt) : start;
      const day = new Date(start.getFullYear(), start.getMonth(), start.getDate());
      const endDay = Number.isNaN(end.getTime())
        ? day
        : new Date(end.getFullYear(), end.getMonth(), end.getDate());
      // Guard bounds the loop even if endsAt is somehow far past startsAt.
      for (let guard = 0; day <= endDay && guard < 400; guard += 1) {
        const key = isoDate(day);
        (map[key] ??= []).push(e);
        day.setDate(day.getDate() + 1);
      }
    }
    return map;
  }, [events]);

  const cells = useMemo(() => {
    const start = new Date(first);
    start.setDate(start.getDate() - start.getDay()); // back to Sunday
    return Array.from({ length: 42 }, (_, i) => {
      const day = new Date(start);
      day.setDate(start.getDate() + i);
      return day;
    });
  }, [first.getTime()]);

  const weekCells = useMemo(() => {
    const start = new Date(cursor);
    start.setDate(start.getDate() - start.getDay());
    return Array.from({ length: 7 }, (_, i) => {
      const day = new Date(start);
      day.setDate(start.getDate() + i);
      return day;
    });
  }, [cursor.getTime()]);

  const label = view === "week"
    ? `Week of ${weekCells[0].toLocaleDateString(undefined, { month: "short", day: "numeric" })}`
    : cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" });

  const step = (delta: number) => {
    const next = new Date(cursor);
    if (view === "week") next.setDate(next.getDate() + delta * 7);
    else next.setMonth(next.getMonth() + delta);
    setCursor(next);
  };

  const chip = (e: EventItem) => (
    <Link key={e.id} to={`/events/${e.id}`} data-testid={`cal-chip-${e.id}`}
          title={`${e.title} — ${e.type}`}
          style={{ display: "block", fontSize: 11, borderRadius: 5, padding: "2px 5px",
                   marginTop: 4, color: "#fff", whiteSpace: "nowrap", overflow: "hidden",
                   textOverflow: "ellipsis",
                   background: TYPE_COLOUR[e.type] ?? "var(--primary)" }}>
      {e.startsAt ? new Date(e.startsAt).toLocaleTimeString(undefined,
        { hour: "numeric", minute: "2-digit" }) : ""} {e.title}
    </Link>
  );

  const dayCell = (day: Date, dim: boolean) => {
    const key = isoDate(day);
    return (
      <div key={key} style={{ background: "var(--surface-2)", border: "1px solid var(--border)",
                              borderRadius: 8, minHeight: 88, padding: 6, fontSize: 12,
                              opacity: dim ? 0.4 : 1 }}>
        <div style={{ fontWeight: 700, color: "var(--text-muted)" }}>{day.getDate()}</div>
        {(byDay[key] ?? []).map(chip)}
      </div>
    );
  };

  return (
    <>
      <div className="page-head flex between">
        <div><h1>Event Calendar</h1>
          <p>{role === "CommunityLeader"
            ? "All events — community-wide and across every user group."
            : "Events from your groups plus community-wide events."}</p></div>
        <Link className="btn" to="/events" data-testid="calendar-list-link">☰ List view</Link>
      </div>

      <div className="card mb-16">
        <div className="flex between wrap" style={{ gap: 12 }}>
          <div className="flex" style={{ gap: 8, alignItems: "center" }}>
            <button className="btn sm" data-testid="cal-prev" aria-label="Previous"
                    onClick={() => step(-1)}>‹</button>
            <b style={{ fontSize: 16 }} data-testid="cal-label">{label}</b>
            <button className="btn sm" data-testid="cal-next" aria-label="Next"
                    onClick={() => step(1)}>›</button>
            <button className="btn sm" data-testid="cal-today"
                    onClick={() => setCursor(new Date())}>Today</button>
          </div>
          <div className="tabs" style={{ border: "none", margin: 0 }}>
            {(["month", "week", "list"] as const).map((v) => (
              <div key={v} className={"tab" + (view === v ? " active" : "")}
                   data-testid={`cal-view-${v}`} onClick={() => setView(v)}>
                {v[0].toUpperCase() + v.slice(1)}</div>
            ))}
          </div>
          <div className="flex" style={{ gap: 8 }}>
            <select className="select" style={{ width: "auto" }} data-testid="cal-type-filter"
                    value={fType} onChange={(e) => setFType(e.target.value)}>
              <option value="">All event types</option>
              {EVENT_TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
            {role === "CommunityLeader" && (
              <input className="input" style={{ width: 150 }} placeholder="Group id"
                     data-testid="cal-group-filter" value={fGroup}
                     onChange={(e) => setFGroup(e.target.value)} />
            )}
          </div>
        </div>
      </div>

      {comingSoon && <ComingSoon feature="Calendar" />}
      {error && <ErrorState message={error} />}
      {loading && <Loading />}

      {!loading && !error && !comingSoon && (
        <div className="card">
          <div className="flex mb-12 wrap" style={{ gap: 10 }}>
            {Object.entries(TYPE_COLOUR).slice(0, 5).map(([type, colour]) => (
              <span key={type} className="badge" style={{ background: colour, color: "#fff" }}>{type}</span>
            ))}
          </div>

          {view === "list" ? (
            events.length === 0 ? <EmptyState message="No events in this period." /> : (
              <ul className="clean" data-testid="cal-list">
                {[...events].sort((a, b) => (a.startsAt ?? "").localeCompare(b.startsAt ?? ""))
                  .map((e) => (
                    <li key={e.id} className="flex between">
                      <span><span className="badge blue">{e.type}</span>{" "}
                        <Link to={`/events/${e.id}`}><b>{e.title}</b></Link></span>
                      <span className="faint small">
                        {e.startsAt ? new Date(e.startsAt).toLocaleString() : "TBD"}</span>
                    </li>
                  ))}
              </ul>
            )
          ) : (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(7,1fr)", gap: 6 }}>
                {DOW.map((d) => (
                  <div key={d} style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                                        color: "var(--text-faint)", textAlign: "center",
                                        padding: "6px 0" }}>{d}</div>
                ))}
                {(view === "month" ? cells : weekCells).map((day) =>
                  dayCell(day, view === "month" && day.getMonth() !== cursor.getMonth()))}
              </div>
              {events.length === 0 && (
                <EmptyState message="No events this period." />
              )}
            </>
          )}
        </div>
      )}
    </>
  );
}
