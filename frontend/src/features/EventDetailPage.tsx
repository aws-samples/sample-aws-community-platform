import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch, apiFetchText, downloadText } from "../lib/apiClient";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import ToastStack, { useToasts } from "../components/ToastStack";
import { statusBadge } from "./EventsPage";
import { useGroupName } from "../lib/useGroupName";
import type { Role } from "../roles";

// Member-facing event detail (US-2.14/2.6/2.8/2.15), laid out per the
// member event-detail mockup: summary card on the left,
// RSVP and calendar panels on the right.
export default function EventDetailPage({ role }: { role: Role }) {
  const { id = "" } = useParams();
  const [nonce, setNonce] = useState(0);
  const { toasts, success, error: toastError, dismissToast } = useToasts();

  const ev = useApi<any>(`/events/${id}?_=${nonce}`);
  const mats = useApi<{ items: any[] }>(`/events/${id}/materials?_=${nonce}`);
  const desigs = useApi<{ items: any[] }>(`/events/${id}/designations?_=${nonce}`);
  const gname = useGroupName();

  // The endpoint sits behind the Cognito authorizer, so the file is fetched
  // with the session token and then handed to the browser as a download.
  const downloadIcs = async () => {
    try {
      const body = await apiFetchText(`/events/${id}/ics`);
      downloadText(`${e.title || "event"}.ics`, body, "text/calendar");
    } catch (err) { toastError((err as Error).message); }
  };

  const rsvp = async (response: "yes" | "no") => {
    try {
      const result = await apiFetch<{ icsAction?: string }>(`/events/${id}/rsvp`, {
        method: "POST", body: JSON.stringify({ response }),
      });
      success(response === "yes"
        ? "You're going! A calendar invite has been sent."
        : result.icsAction === "cancel"
          ? "RSVP updated — event removed from your calendar."
          : "RSVP recorded as not going.");
      setNonce((n) => n + 1);
    } catch (err) { toastError((err as Error).message); }
  };

  if (ev.loading) return <Loading />;
  if (ev.comingSoon) return <ComingSoon feature="Event detail" />;
  if (ev.error) return <ErrorState message={ev.error} />;
  const e = ev.data ?? {};
  const canManage = Boolean(e.canManage);

  return (
    <>
      <div className="breadcrumb"><Link to="/events">Events</Link> › {e.title}</div>
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      <div className="grid cols-2" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
        <div className="card">
          <div className="flex wrap mb-12" style={{ gap: 6 }}>
            <span className="badge blue">{e.type}</span>
            <span className="badge gray">{e.deliveryMode}</span>
            <span className={`badge ${statusBadge(e.status)}`}>{e.status}</span>
            <span className="badge purple">{gname(e.groupId)}</span>
          </div>
          <h1 style={{ margin: "0 0 6px" }}>{e.title}</h1>
          {e.description && <p className="muted">{e.description}</p>}
          <div className="divider" />
          <div className="grid cols-2">
            <div><div className="faint small">STARTS</div>
              <b>{e.startsAt ? new Date(e.startsAt).toLocaleString() : "TBD"}</b></div>
            <div><div className="faint small">ENDS</div>
              <b>{e.endsAt ? new Date(e.endsAt).toLocaleString() : "—"}</b></div>
            <div><div className="faint small">DELIVERY</div>
              <b>{e.deliveryMode}{e.location ? ` · ${e.location}` : ""}</b></div>
            {/* createdBy is a raw internal user id — show the designated
                organizers' display names instead, and omit the field when
                nobody is designated rather than leak the id. */}
            <div><div className="faint small">ORGANIZER</div>
              <b>{(desigs.data?.items ?? []).filter((d) => d.kind === "organizer")
                  .map((d) => d.displayName ?? "—").join(", ") || "—"}</b></div>
          </div>

          {canManage && (
            <>
              <div className="divider" />
              <Link className="btn primary" to={`/events/${id}/manage`} data-testid="go-manage">
                Manage this event →
              </Link>
            </>
          )}

          <div className="divider" />
          <h3>🎤 Presenters / Facilitators</h3>
          {(desigs.data?.items ?? []).filter((d) => d.kind === "presenter").length === 0 ? (
            <p className="faint small">No presenters designated yet.</p>
          ) : (
            <ul className="clean">
              {(desigs.data?.items ?? []).filter((d) => d.kind === "presenter").map((d) => (
                <li key={d.userId} className="flex" style={{ gap: 8, alignItems: "center" }}>
                  {/* External presenters carry a synthetic userId ("ext-1"); show
                      their name and an External badge, never the internal id. */}
                  <span>{d.displayName ?? (d.external ? "External presenter" : d.userId)}</span>
                  {d.external
                    ? <span className="badge amber">External</span>
                    : <span className="badge blue">{d.roleAtDesignation}</span>}
                  {/* The mockup showed "no delivery points (leader)" here; the
                      reason comes from the API so the rule is stated once. */}
                  {!d.pointsEligible && d.ineligibleReason &&
                    <span className="faint small">{d.ineligibleReason}</span>}
                </li>
              ))}
            </ul>
          )}

          <div className="divider" />
          <h3>📎 Materials</h3>
          {mats.loading ? <Loading /> : (
            <ul className="clean" data-testid="materials-list">
              {(mats.data?.items ?? []).map((m) => (
                <li key={m.id} className="flex between">
                  <span className={m.scanState === "Clean" ? "" : "muted"}>
                    {m.kind === "link" ? "🔗" : "📄"} {m.name}
                    {m.scanState === "PendingScan" && <span className="faint small"> · scanning…</span>}
                    {m.scanState === "Quarantined" && <span className="badge red"> Quarantined</span>}
                  </span>
                  {m.scanState === "Clean" ? (
                    <span className="btn-row">
                      {m.link && <a className="small" href={m.link} target="_blank" rel="noreferrer"
                                    data-testid={`open-${m.id}`}>Open</a>}
                      {m.downloadUrl && <a className="small" href={m.downloadUrl} target="_blank"
                                           rel="noreferrer" data-testid={`view-${m.id}`}>View online</a>}
                      {m.downloadUrl && <a className="small" href={m.downloadUrl} download
                                           data-testid={`download-${m.id}`}>Download</a>}
                    </span>
                  ) : <span className="faint small">Pending</span>}
                </li>
              ))}
              {(mats.data?.items ?? []).length === 0 &&
                <li className="faint small">No materials yet.</li>}
            </ul>
          )}
        </div>

        <div>
          <div className="card mb-16">
            <h3>Your RSVP</h3>
            {role === "Administrator" ? (
              <p className="small muted">Administrators do not participate in events.</p>
            ) : e.status !== "Upcoming" ? (
              <p className="small muted">
                This event is {String(e.status).toLowerCase()}, so RSVPs are closed.
              </p>
            ) : (
              <>
                <p className="small muted">
                  Let the organizer know if you're attending. You'll receive a calendar invite.
                </p>
                <div className="btn-row">
                  <button className={"btn" + (e.myRsvp === "yes" ? " success" : "")}
                          style={{ flex: 1 }} data-testid="rsvp-yes"
                          onClick={() => rsvp("yes")}>✓ Going</button>
                  <button className={"btn" + (e.myRsvp === "no" ? " active" : "")}
                          style={{ flex: 1 }} data-testid="rsvp-no"
                          onClick={() => rsvp("no")}>Not going</button>
                </div>
                {e.myRsvp && <p className="small faint mt-8 mb-0" data-testid="my-rsvp">
                  Your current response: <b>{e.myRsvp === "yes" ? "Going" : "Not going"}</b></p>}
              </>
            )}
            <div className="divider" />
            <div className="flex between"><span className="muted">RSVP'd Yes</span>
              <b data-testid="rsvp-yes-count">{e.rsvpYesCount ?? 0}</b></div>
            <div className="flex between"><span className="muted">RSVP'd No</span>
              <b data-testid="rsvp-no-count">{e.rsvpNoCount ?? 0}</b></div>
            {/* Omitted entirely when Contributions is unavailable (BR-P1). */}
            {typeof e.attendancePoints === "number" && (
              <>
                <div className="divider" />
                <div className="flex between"><span className="muted">Points to attend</span>
                  <span className="tag" data-testid="points-tag">+{e.attendancePoints} pts</span></div>
                <p className="small faint mt-8 mb-0">
                  Points are awarded only when your attendance is confirmed — not on RSVP.
                </p>
              </>
            )}
          </div>

          <div className="card">
            <h3>📅 Add to calendar</h3>
            <p className="small muted mb-12">
              A calendar invite (.ics) is emailed automatically when you RSVP "Going".
            </p>
            <button className="btn" style={{ width: "100%" }} data-testid="download-ics"
                    onClick={downloadIcs}>Download .ics</button>
          </div>
        </div>
      </div>
    </>
  );
}
