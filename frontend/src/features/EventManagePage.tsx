import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { exportEndpointCsv } from "../lib/exportCsv";
import DataTable from "../components/DataTable";
import PeoplePicker, { type PickedPerson } from "../components/PeoplePicker";
import Toggle from "../components/Toggle";
import { ComingSoon, EmptyState, ErrorState, Loading } from "../components/States";
import Banner from "../components/Banner";
import EventModal from "./EventModal";
import { statusBadge } from "./EventsPage";
import { groupNameFrom } from "../lib/useGroupName";
import ConfirmModal, { type ConfirmOptions } from "../components/ConfirmModal";
import type { Role } from "../roles";

// Leader-facing manage screen (the leader/UGL event-manage mockups):
// five stat cards + Attendance / RSVP List / Materials / MS Teams / Designations.
// Designations is new — the mockups counted presenters and organizers in the stat
// cards but offered no way to set them after creation, and no organizer field at
// all (gap G17).
type Tab = "attendance" | "rsvps" | "materials" | "teams" | "designations";

export default function EventManagePage({ role, ledGroupId }: { role: Role; ledGroupId?: string }) {
  const { id = "" } = useParams();
  const [tab, setTab] = useState<Tab>("attendance");
  const [nonce, setNonce] = useState(0);
  const [msg, setMsg] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);

  const ev = useApi<any>(`/events/${id}?_=${nonce}`);
  // Real groups for the edit modal's Scope field (name display for UGL,
  // dropdown for CL) — fetched only once the modal can actually open.
  const groupsApi = useApi<{ items: { id: string; name: string }[] }>("/groups");
  const groupOptions = (groupsApi.data?.items ?? []).map((g) => ({ id: g.id, name: g.name }));
  const reload = () => setNonce((n) => n + 1);
  // The header shows the group's NAME — the raw group id is internal and never
  // rendered (same /groups list the edit modal already needs).
  const scopeName = (gid?: string | null) => gid ? groupNameFrom(groupOptions, gid) : "Community-wide";

  if (ev.loading) return <Loading />;
  if (ev.comingSoon) return <ComingSoon feature="Event management" />;
  if (ev.error) return <ErrorState message={ev.error} />;
  const e = ev.data ?? {};

  if (!e.canManage) {
    return (
      <>
        <div className="breadcrumb"><Link to="/events">Events</Link> › {e.title}</div>
        <EmptyState message="You do not have permission to manage this event." />
      </>
    );
  }

  const cancelEvent = () => setConfirm({
    title: `Cancel "${e.title}"?`,
    body: (
      <><p>⚠️ Everyone who RSVP'd will be <b>notified by email</b>. The event stays visible with a Cancelled badge.</p>
      <p>This cannot be undone.</p></>
    ),
    confirmLabel: "Cancel Event",
    cancelLabel: "Keep Event",
    onConfirm: async () => {
      await apiFetch(`/events/${id}`, { method: "DELETE" });
      setMsg("Event cancelled. Attendees have been notified.");
      reload();
    },
  });

  const markCompleted = async () => {
    // BR-L2 / US-2.19: only past-dated events can be completed. Surface the
    // reason explicitly instead of leaving the click to a silently-disabled
    // button that gives no feedback.
    if (!past) {
      setMsg("This event can't be marked completed yet — only events whose date " +
             "has passed can be completed. It's currently scheduled for " +
             `${e.startsAt ? new Date(e.startsAt).toLocaleDateString() : "a future date"}.`);
      return;
    }
    try {
      await apiFetch(`/events/${id}/complete`, { method: "POST" });
      setMsg("Event marked completed.");
      reload();
    } catch (err) { setMsg((err as Error).message); }
  };

  const past = Boolean(e.startsAt && new Date(e.startsAt) < new Date());
  const turnout = e.rsvpYesCount ? Math.round((100 * (e.attendedCount ?? 0)) / e.rsvpYesCount) : null;

  return (
    <>
      <div className="breadcrumb"><Link to="/events">Events</Link> › {e.title}</div>
      <div className="page-head flex between">
        <div>
          <h1>{e.title}</h1>
          <p>{e.type} · {scopeName(e.groupId)} ·{" "}
            {e.startsAt ? new Date(e.startsAt).toLocaleDateString() : "TBD"} ·{" "}
            <span className={`badge ${statusBadge(e.status)}`}>{e.status}</span></p>
        </div>
        <div className="btn-row">
          <Link className="btn" to={`/events/${id}`} data-testid="view-public">View as member</Link>
          {e.status === "Upcoming" && (
            <>
              <button className="btn" data-testid="edit-event" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn" data-testid="mark-completed"
                      title={past ? undefined : "Only events whose date has passed can be completed"}
                      onClick={markCompleted}>Mark Completed</button>
              <button className="btn danger" data-testid="cancel-event" onClick={cancelEvent}>Cancel Event</button>
            </>
          )}
        </div>
      </div>

      <Banner message={msg} onDismiss={() => setMsg(null)} />

      <div className="grid cols-4 mb-16" style={{ gridTemplateColumns: "repeat(5, 1fr)" }}>
        <div className="card stat"><div className="label">RSVP'd Yes</div>
          <div className="value" data-testid="stat-rsvp-yes">{e.rsvpYesCount ?? 0}</div></div>
        <div className="card stat"><div className="label">Attended</div>
          <div className="value" data-testid="stat-attended">{e.attendedCount ?? 0}</div>
          {turnout !== null && <div className="trend">{turnout}% turnout</div>}</div>
        <div className="card stat"><div className="label">Presenters</div>
          <div className="value">{e.presenterCount ?? 0}</div></div>
        <div className="card stat"><div className="label">Organizers</div>
          <div className="value">{e.organizerCount ?? 0}</div></div>
        <div className="card stat"><div className="label">Points Awarded</div>
          <div className="value">{e.pointsAwarded ?? "—"}</div></div>
      </div>

      <div className="tabs">
        {([["attendance", "Attendance"], ["rsvps", "RSVP List"], ["materials", "Materials"],
           ["teams", "MS Teams"], ["designations", "Designations"]] as [Tab, string][])
          .map(([key, label]) => (
            <div key={key} className={"tab" + (tab === key ? " active" : "")}
                 data-testid={`tab-${key}`} onClick={() => setTab(key)}>{label}</div>
          ))}
      </div>

      {tab === "attendance" && <AttendanceTab id={id}
                                              onDone={(m) => { setMsg(m); reload(); }}
                                              nonce={nonce} />}
      {tab === "rsvps" && <RsvpTab id={id} nonce={nonce} />}
      {tab === "materials" && <MaterialsTab id={id} nonce={nonce}
                                            onDone={(m) => { setMsg(m); reload(); }} />}
      {tab === "teams" && <TeamsTab id={id} onDone={(m) => { setMsg(m); reload(); }} nonce={nonce} />}
      {tab === "designations" && <DesignationsTab id={id} nonce={nonce}
                                                  disabled={e.status === "Completed"}
                                                  onDone={(m) => { setMsg(m); reload(); }} />}

      {editing && (
        <EventModal mode="edit" role={role} ledGroupId={ledGroupId} groups={groupOptions}
                    initial={e} onClose={() => setEditing(false)} onSaved={reload} />
      )}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

// ------------------------------------------------------------------ attendance

function AttendanceTab(props: {
  id: string; nonce: number;
  onDone: (msg: string) => void;
}) {
  const rsvps = useApi<{ items: any[] }>(`/events/${props.id}/rsvps?_=${props.nonce}`);
  const [importing, setImporting] = useState(false);

  const mark = async (userId: string) => {
    try {
      const result = await apiFetch<{ recorded: number }>(`/events/${props.id}/attendance`, {
        method: "POST", body: JSON.stringify({ userIds: [userId] }),
      });
      props.onDone(result.recorded
        ? "Attendance recorded. The event is now marked completed and points were awarded."
        : "That member was already recorded as attended.");
    } catch (err) { props.onDone((err as Error).message); }
  };

  if (rsvps.loading) return <Loading />;
  if (rsvps.comingSoon) return <ComingSoon feature="Attendance" />;
  if (rsvps.error) return <ErrorState message={rsvps.error} />;
  const rows = rsvps.data?.items ?? [];

  return (
    <div className="card">
      <div className="flex between mb-12">
        <h3 className="mb-0">Record Attendance</h3>
        <div className="btn-row">
          <button className="btn" data-testid="import-csv" onClick={() => setImporting(true)}>
            ⬆ Upload CSV
          </button>
        </div>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="Nobody has RSVP'd yet, so there is no attendance to record." />
      ) : (
        <DataTable id="attendance" rows={rows} columns={[
          { key: "member", header: "Member", render: (r) => r.userName || r.userEmail || r.userId },
          { key: "rsvp", header: "RSVP",
            render: (r) => <span className={`badge ${r.response === "yes" ? "green" : "red"}`}>
              {r.response === "yes" ? "Yes" : "No"}</span> },
          { key: "attended", header: "Attended",
            render: (r) => (r.attended
              ? <span className="badge green">✓ Attended</span>
              : <button className="btn sm" data-testid={`mark-${r.userId}`}
                        onClick={() => mark(r.userId)}>Mark attended</button>) },
          { key: "points", header: "Points",
            render: (r) => (typeof r.pointsAwarded === "number" ? `+${r.pointsAwarded}` : "—") },
        ]} />
      )}

      <p className="faint small mt-12 mb-0">
        Recording attendance automatically marks the event completed and awards attendance points,
        plus delivery and organize points to designees who hold the Member role. Leaders may be
        designated but do not earn.
      </p>

      {importing && <AttendanceImportModal id={props.id} onClose={() => setImporting(false)}
                                           onDone={props.onDone} />}
    </div>
  );
}

// CSV-only by design: the xlsx/SheetJS dependency carries unpatched
// high-severity CVEs and was removed from this repo during the Identity & Access
// bulk-import work (BR-T7).
function AttendanceImportModal(props: { id: string; onClose: () => void; onDone: (m: string) => void }) {
  const [csv, setCsv] = useState("");
  const [report, setReport] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const result = await apiFetch<any>(`/events/${props.id}/attendance/import`, {
        method: "POST", body: JSON.stringify({ csv }),
      });
      setReport(result);
      if (result.matched) props.onDone(`${result.matched} attendee(s) recorded from the CSV.`);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };

  const onFile = async (file?: File) => { if (file) setCsv(await file.text()); };

  return (
    <div role="dialog" aria-modal="true" aria-label="Upload attendance CSV"
         style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                  display: "flex", alignItems: "center", justifyContent: "center", padding: 30 }}>
      <div className="card" style={{ width: 620, maxWidth: "94vw", maxHeight: "90vh", overflowY: "auto" }}>
        <div className="card-head"><h3>⬆ Upload attendance CSV</h3>
          <button className="icon-btn" aria-label="Close" onClick={props.onClose}>✕</button></div>

        {error && <div className="banner error" role="alert">{error}</div>}

        <p className="small muted">
          The file needs an <code>email</code> column. Every row is reported back, so unmatched
          addresses are visible rather than silently skipped. CSV only.
        </p>
        <div className="field"><label htmlFor="att-file">CSV file</label>
          <input id="att-file" className="input" type="file" accept=".csv,text/csv"
                 data-testid="attendance-file" onChange={(e) => onFile(e.target.files?.[0])} /></div>
        <div className="field"><label htmlFor="att-csv">…or paste CSV</label>
          <textarea id="att-csv" className="textarea" rows={5} data-testid="attendance-csv"
                    placeholder={"email\nmember@example.com"} value={csv}
                    onChange={(e) => setCsv(e.target.value)} /></div>

        {report && (
          <div className="card" style={{ background: "var(--surface-2)", padding: 12 }}>
            <div className="small mb-8">
              <b>{report.matched}</b> matched · <b>{report.unmatched}</b> unmatched
              of <b>{report.total}</b> row(s)
            </div>
            <table className="tbl"><thead><tr><th>Row</th><th>Email</th><th>Result</th><th>Detail</th></tr></thead>
              <tbody>{(report.rows ?? []).map((r: any) => (
                <tr key={r.row}><td>{r.row}</td><td>{r.email || "—"}</td>
                  <td><span className={`badge ${r.result === "matched" ? "green" : "amber"}`}>{r.result}</span></td>
                  <td className="faint small">{r.message}</td></tr>
              ))}</tbody></table>
          </div>
        )}

        <div className="btn-row">
          <button className="btn primary" data-testid="attendance-import-submit"
                  disabled={busy || !csv.trim()} onClick={submit}>
            {busy ? "Importing…" : "Import"}</button>
          <button className="btn" onClick={props.onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------- RSVPs

function RsvpTab({ id, nonce }: { id: string; nonce: number }) {
  const rsvps = useApi<{ items: any[]; yesCount?: number; noCount?: number }>(
    `/events/${id}/rsvps?_=${nonce}`);
  if (rsvps.loading) return <Loading />;
  if (rsvps.comingSoon) return <ComingSoon feature="RSVP list" />;
  if (rsvps.error) return <ErrorState message={rsvps.error} />;
  const rows = rsvps.data?.items ?? [];
  return (
    <div className="card">
      <div className="flex between mb-12">
        <h3 className="mb-0">RSVP List
          <span className="faint small"> · {rsvps.data?.yesCount ?? 0} yes,
            {" "}{rsvps.data?.noCount ?? 0} no</span></h3>
        <button className="btn" data-testid="export-rsvps"
                onClick={() => exportEndpointCsv(`/events/${id}/rsvps`, "event-rsvps.csv")}>
          ⬇ Export CSV</button>
      </div>
      {rows.length === 0 ? <EmptyState message="No RSVPs yet." /> : (
        <DataTable id="rsvps" rows={rows} columns={[
          // Name/email/role are stamped on the RSVP row from the member's JWT
          // claims at RSVP time; rows written before that change show "—".
          { key: "name", header: "Name", render: (r) => r.userName || "—" },
          { key: "email", header: "Email", render: (r) => r.userEmail || "—" },
          { key: "role", header: "Role", render: (r) => r.userRole || "—" },
          { key: "response", header: "Response",
            render: (r) => <span className={`badge ${r.response === "yes" ? "green" : "red"}`}>
              {r.response === "yes" ? "Yes" : "No"}</span> },
        ]} />
      )}
    </div>
  );
}

// ------------------------------------------------------------------- materials

// Presigned-PUT upload with progress. `fetch` cannot report upload progress, so
// the direct-to-S3 PUT uses XMLHttpRequest and streams `upload.onprogress` back
// to the caller — important because recordings can be hundreds of MB and take
// minutes. Content-Type is derived from the File (same as the previous fetch).
function putWithProgress(url: string, file: File, onProgress: (pct: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) onProgress(Math.round((ev.loaded / ev.total) * 100));
    };
    xhr.onload = () =>
      (xhr.status >= 200 && xhr.status < 300)
        ? resolve()
        : reject(new Error(`Upload failed (${xhr.status}).`));
    xhr.onerror = () => reject(new Error("Upload failed — network error."));
    xhr.onabort = () => reject(new Error("Upload cancelled."));
    xhr.send(file);
  });
}

function MaterialsTab({ id, nonce, onDone }: { id: string; nonce: number; onDone: (m: string) => void }) {
  const mats = useApi<{ items: any[] }>(`/events/${id}/materials?_=${nonce}`);
  const links = useApi<{ items: any[] }>(`/events/${id}/upload-links?_=${nonce}`);
  const [addingLink, setAddingLink] = useState(false);
  const [creatingUpload, setCreatingUpload] = useState(false);
  const [linkName, setLinkName] = useState("");
  const [linkUrl, setLinkUrl] = useState("");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [confirm, setConfirm] = useState<ConfirmOptions | null>(null);

  // Direct-to-S3: mint a short-lived presigned PUT, upload the bytes straight to
  // the bucket, then confirm the metadata row. Bytes never traverse Lambda, so a
  // 500 MB recording is not bound by the API Gateway payload limit.
  const uploadFile = async (file?: File) => {
    if (!file) return;
    setUploading(true);
    setProgress(0);
    try {
      const target = await apiFetch<{ url: string; key: string }>(
        `/events/${id}/materials/upload-url`,
        { method: "POST", body: JSON.stringify({ fileName: file.name, sizeBytes: file.size }) });
      await putWithProgress(target.url, file, setProgress);
      await apiFetch(`/events/${id}/materials`, {
        method: "POST",
        body: JSON.stringify({ name: file.name, kind: "file", s3Key: target.key }),
      });
      onDone(`"${file.name}" uploaded. It becomes visible to members once the malware scan passes.`);
    } catch (err) { onDone((err as Error).message); } finally { setUploading(false); setProgress(0); }
  };

  const addLink = async () => {
    try {
      await apiFetch(`/events/${id}/materials`, {
        method: "POST",
        body: JSON.stringify({ name: linkName, kind: "link", link: linkUrl }),
      });
      setAddingLink(false); setLinkName(""); setLinkUrl("");
      onDone("Link added.");
    } catch (err) { onDone((err as Error).message); }
  };

  const remove = (m: any) => setConfirm({
    title: `Remove "${m.name}"?`,
    body: (
      <><p>⚠️ This permanently deletes the file from storage. This cannot be undone.</p></>
    ),
    confirmLabel: "Remove File",
    cancelLabel: "Keep File",
    onConfirm: async () => {
      await apiFetch(`/events/${id}/materials/${m.id}`, { method: "DELETE" });
      onDone(`"${m.name}" removed.`);
    },
  });

  const createUploadLink = async (fileName: string, note: string) => {
    try {
      await apiFetch(`/events/${id}/upload-links`,
        { method: "POST", body: JSON.stringify({ fileName, note }) });
      setCreatingUpload(false);
      onDone(`Upload slot "${fileName}" created. Use Copy Link to get the upload URL.`);
    } catch (err) { onDone((err as Error).message); }
  };

  const revoke = (link: any) => setConfirm(
    link.uploaded ? {
      title: "Remove upload slot?",
      body: <><p>⚠️ This permanently removes the upload slot <b>and the uploaded file</b> from S3. This cannot be undone.</p></>,
      confirmLabel: "Remove Slot & File",
      cancelLabel: "Keep",
      onConfirm: async () => {
        await apiFetch(`/events/${id}/upload-links/${link.id}`, { method: "DELETE" });
        onDone("Upload slot and file removed.");
      },
    } : {
      title: "Deactivate upload slot?",
      body: <><p>⚠️ The presigned URL will stop working immediately. The slot row stays and can still be deleted later.</p></>,
      confirmLabel: "Deactivate Slot",
      cancelLabel: "Keep",
      onConfirm: async () => {
        await apiFetch(`/events/${id}/upload-links/${link.id}`, { method: "DELETE" });
        onDone("Upload slot deactivated.");
      },
    }
  );

  if (mats.loading) return <Loading />;
  if (mats.comingSoon) return <ComingSoon feature="Materials" />;

  return (
    <>
      <div className="card">
        <div className="flex between mb-12"><h3 className="mb-0">📎 Event Materials</h3>
          <div className="btn-row">
            <button className="btn sm" data-testid="refresh-materials"
                    onClick={() => onDone("")}>🔄 Refresh</button>
            <label className="btn" style={{ cursor: uploading ? "default" : "pointer",
                                             opacity: uploading ? 0.6 : 1 }}>
              {uploading ? "Uploading…" : "⬆ Upload file"}
              <input type="file" hidden data-testid="material-file" disabled={uploading}
                     onChange={(e) => uploadFile(e.target.files?.[0])} />
            </label>
            <button className="btn" data-testid="add-link" disabled={uploading}
                    onClick={() => setAddingLink(true)}>
              🔗 Add link</button>
          </div></div>
        <p className="faint small" style={{ marginTop: -6 }}>
          Upload slides, agendas or recordings, or add external links. Everyone who can view this
          event can download them. Files are stored in the community S3 bucket and are hidden from
          members until the malware scan passes.
        </p>

        {uploading && (
          <div className="mb-12" data-testid="upload-progress">
            <div className="flex between small mb-8" style={{ color: "var(--text-muted)" }}>
              <span>Uploading… please keep this tab open.</span><span>{progress}%</span>
            </div>
            <div className="progress"><div className="bar"
                 style={{ width: `${progress}%`, transition: "width .2s ease" }} /></div>
          </div>
        )}

        {(mats.data?.items ?? []).length === 0 ? (
          <EmptyState message="No materials yet." />
        ) : (
          <table className="tbl"><thead>
            <tr><th>Material</th><th>Type</th><th>Size</th><th>Status</th><th>Added</th><th>Actions</th></tr>
          </thead><tbody>
            {(mats.data?.items ?? []).map((m) => (
              <tr key={m.id}>
                <td>{m.kind === "link" ? "🔗" : "📄"} {m.name}</td>
                <td>{m.contentType}</td>
                <td>{m.sizeBytes ? `${Math.round(m.sizeBytes / 1024)} KB` : "—"}</td>
                <td><span className={`badge ${m.scanState === "Clean" ? "green"
                    : m.scanState === "Quarantined" ? "red" : "amber"}`}>
                  {m.scanState === "PendingScan" ? "Scanning…" : m.scanState}</span></td>
                <td>{m.addedAt ? new Date(m.addedAt).toLocaleDateString() : "—"}</td>
                <td className="btn-row">
                  {m.downloadUrl && <a className="small" href={m.downloadUrl} target="_blank"
                                       rel="noreferrer">View</a>}
                  {m.downloadUrl && <a className="small" href={m.downloadUrl} download>Download</a>}
                  {m.link && <a className="small" href={m.link} target="_blank" rel="noreferrer">Open</a>}
                  <button className="btn sm danger" data-testid={`remove-material-${m.id}`}
                          onClick={() => remove(m)}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody></table>
        )}
        <p className="faint small mt-12 mb-0">
          Members who RSVP'd are emailed when material is added after the event.
          Allowed: PDF, PPT(X), DOC(X), XLS(X), PNG, JPG, MP4 — up to 500 MB.
        </p>
      </div>

      <div className="card mt-16">
        <div className="flex between mb-12"><h3 className="mb-0">🔐 External Upload Links</h3>
          <div className="btn-row">
            <button className="btn sm" data-testid="refresh-upload-links"
                    onClick={() => onDone("")}>🔄 Refresh</button>
            <button className="btn primary" data-testid="create-upload-link"
                    onClick={() => setCreatingUpload(true)}>🔗 Create upload link</button>
          </div></div>
        <p className="faint small" style={{ marginTop: -6 }}>
          Creates a write-only upload slot so an external contributor without a portal
          account can upload a specific file into this event's materials folder. Use
          <b> Copy Link</b> to get a fresh presigned PUT URL (valid 60 minutes). Recipients
          can only upload to their named file — they cannot list, view or delete anything.
        </p>

        {(links.data?.items ?? []).length === 0 ? (
          <EmptyState message="No external upload slots for this event." />
        ) : (
          <table className="tbl"><thead>
            <tr><th>File</th><th>Created</th><th>Status</th><th>Actions</th></tr>
          </thead><tbody>
            {(links.data?.items ?? []).map((l) => (
              <tr key={l.id}>
                <td>{l.fileName}</td>
                <td>{l.createdAt ? new Date(l.createdAt).toLocaleDateString() : "—"}</td>
                <td>
                  <span className={`badge ${l.revoked ? "gray" : "green"}`}>
                    {l.revoked ? "Deactivated" : "Active"}</span>
                  {" "}
                  {!l.revoked && (
                    <span className={`badge ${l.uploaded ? "blue" : "amber"}`}>
                      {l.uploaded ? "Uploaded" : "Awaiting upload"}</span>
                  )}
                </td>
                <td className="btn-row">
                  {!l.uploaded && !l.revoked && <CopyLinkButton eventId={id} linkId={l.id} />}
                  {l.uploaded && <OpenFileButton eventId={id} linkId={l.id} />}
                  {l.uploaded && <button className="btn sm danger" data-testid={`remove-slot-${l.id}`}
                                         onClick={() => revoke(l)}>Remove</button>}
                  {!l.uploaded && !l.revoked && <button className="btn sm danger" data-testid={`revoke-${l.id}`}
                                         onClick={() => revoke(l)}>Deactivate</button>}
                </td>
              </tr>
            ))}
          </tbody></table>
        )}
        <p className="faint small mt-12 mb-0">
          Each Copy Link mints a fresh 60-minute presigned PUT URL. The bucket is not
          public — only the named file can be written through the URL.
        </p>
      </div>

      {addingLink && (
        <div role="dialog" aria-modal="true" aria-label="Add link"
             style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                      display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 480, maxWidth: "94vw" }}>
            <div className="card-head"><h3>🔗 Add link</h3>
              <button className="icon-btn" aria-label="Close" onClick={() => setAddingLink(false)}>✕</button></div>
            <div className="field"><label htmlFor="ml-name">Title</label>
              <input id="ml-name" className="input" data-testid="link-name" value={linkName}
                     onChange={(e) => setLinkName(e.target.value)} /></div>
            <div className="field"><label htmlFor="ml-url">URL</label>
              <input id="ml-url" className="input" data-testid="link-url" placeholder="https://…"
                     value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} />
              <div className="hint">Must be an https:// URL.</div></div>
            <div className="btn-row">
              <button className="btn primary" data-testid="link-submit"
                      disabled={!linkName.trim() || !linkUrl.trim()} onClick={addLink}>Add</button>
              <button className="btn" onClick={() => setAddingLink(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {creatingUpload && <CreateUploadLinkModal onClose={() => setCreatingUpload(false)}
                                                onCreate={createUploadLink} />}
      {confirm && <ConfirmModal {...confirm} onClose={() => setConfirm(null)} />}
    </>
  );
}

function OpenFileButton({ eventId, linkId }: { eventId: string; linkId: string }) {
  const [busy, setBusy] = useState(false);
  const open = async () => {
    setBusy(true);
    try {
      const res = await apiFetch<{ items: { downloadUrl?: string }[] }>(
        `/events/${eventId}/upload-links/${linkId}/files`);
      const url = res.items?.[0]?.downloadUrl;
      if (url) window.open(url, "_blank");
    } catch { /* ignore */ }
    finally { setBusy(false); }
  };
  return (
    <button className="btn sm" data-testid={`open-${linkId}`} disabled={busy}
            onClick={open}>{busy ? "…" : "Open"}</button>
  );
}

function CopyLinkButton({ eventId, linkId }: { eventId: string; linkId: string }) {
  const [busy, setBusy] = useState(false);
  const [curl, setCurl] = useState<string | null>(null);
  const copyLink = async () => {
    setBusy(true);
    try {
      const res = await apiFetch<{ curl: string; url: string }>(
        `/events/${eventId}/upload-links/${linkId}/url`);
      setCurl(res.curl);
      navigator.clipboard?.writeText(res.curl);
    } catch (e) { setCurl(`Error: ${(e as Error).message}`); }
    finally { setBusy(false); }
  };
  return (
    <>
      <button className="btn sm" data-testid={`copy-link-${linkId}`}
              disabled={busy} onClick={copyLink}>
        {busy ? "…" : "📋 Copy Link"}
      </button>
      {curl && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                      display: "flex", alignItems: "center", justifyContent: "center" }}
             onClick={() => setCurl(null)}>
          <div className="card" style={{ width: 600, maxWidth: "94vw", padding: 16 }}
               onClick={(e) => e.stopPropagation()}>
            <div className="card-head"><h3>Upload command (copied)</h3>
              <button className="icon-btn" aria-label="Close" onClick={() => setCurl(null)}>✕</button></div>
            <p className="small faint">This presigned URL expires in 60 minutes. Share it with the external contributor.</p>
            <textarea className="textarea" readOnly value={curl}
                      style={{ fontFamily: "monospace", fontSize: 12, minHeight: 80 }}
                      data-testid="curl-command" />
            <div className="btn-row mt-12">
              <button className="btn primary" onClick={() => { navigator.clipboard?.writeText(curl); }}>
                Copy again</button>
              <button className="btn" onClick={() => setCurl(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function CreateUploadLinkModal(props: {
  onClose: () => void; onCreate: (fileName: string, note: string) => void;
}) {
  const [fileName, setFileName] = useState("");
  const [note, setNote] = useState("");
  return (
    <div role="dialog" aria-modal="true" aria-label="Create upload link"
         style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130,
                  display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 520, maxWidth: "94vw" }}>
        <div className="card-head"><h3>🔗 Create Upload Link</h3>
          <button className="icon-btn" aria-label="Close" onClick={props.onClose}>✕</button></div>
        <p className="small muted">
          Creates a temporary, <b>write-only</b> link for an external contributor to upload
          one specific file into this event's materials folder. The contributor does not need
          a portal account.
        </p>
        <div className="field"><label htmlFor="ul-filename">Filename *</label>
          <input id="ul-filename" className="input" data-testid="upload-filename"
                 placeholder="e.g. keynote-slides.pdf" value={fileName}
                 onChange={(e) => setFileName(e.target.value)} />
          <div className="hint">The exact filename the contributor will upload. Must be unique within this event's materials.</div>
        </div>
        <div className="field"><label htmlFor="ul-note">Note to recipient (optional)</label>
          <textarea id="ul-note" className="textarea" data-testid="upload-note" value={note}
                    placeholder="e.g. Please upload your final slides here."
                    onChange={(e) => setNote(e.target.value)} /></div>
        <p className="faint small" style={{ marginTop: 8 }}>This link expires in <b>60 minutes</b> and allows one upload.</p>
        <div className="btn-row">
          <button className="btn primary" data-testid="upload-generate"
                  disabled={!fileName.trim()}
                  onClick={() => props.onCreate(fileName.trim(), note)}>Generate link</button>
          <button className="btn" onClick={props.onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------- Teams

function TeamsTab({ id, nonce, onDone }: { id: string; nonce: number; onDone: (m: string) => void }) {
  const batch = useApi<any>(`/events/${id}/attendance/teams?_=${nonce}`);
  const [overrides, setOverrides] = useState<Record<string, { include: boolean; matchedUserId?: string }>>({});

  // 503 means the integration is switched off — hide the whole tab rather than
  // showing an error, since the capability is a deployment choice not a fault.
  if (batch.loading) return <Loading />;
  if (batch.comingSoon) return <ComingSoon feature="MS Teams attendance" />;
  if (batch.error) {
    return <div className="card"><EmptyState
      message="MS Teams attendance is not available for this event. It requires the integration to be enabled and the event to be a virtual or hybrid Teams meeting." /></div>;
  }

  const participants = batch.data?.participants ?? [];

  const apply = async () => {
    try {
      const payload = participants.map((p: any) => ({
        email: p.email,
        include: overrides[p.email]?.include ?? p.include,
        matchedUserId: overrides[p.email]?.matchedUserId ?? p.matchedUserId,
      }));
      const result = await apiFetch<{ recorded: number }>(
        `/events/${id}/attendance/teams/apply`,
        { method: "POST", body: JSON.stringify({ participants: payload }) });
      onDone(`${result.recorded} attendee(s) recorded and points awarded.`);
    } catch (err) { onDone((err as Error).message); }
  };

  return (
    <div className="card">
      <div className="flex between mb-12"><h3 className="mb-0">MS Teams Attendance</h3>
        <span className="flex" style={{ gap: 8 }}>
          <span className="badge green">{batch.data?.matchedCount ?? 0} matched</span>
          <span className="badge amber">{batch.data?.unmatchedCount ?? 0} unmatched</span>
        </span></div>
      <p className="muted" style={{ marginTop: -6 }}>
        Participants are matched to members <b>by email</b>. Review the matches and adjust before
        applying — <b>points are awarded only when you choose "Apply &amp; Award Points"</b>.
      </p>

      {participants.length === 0 ? (
        <EmptyState message="No Teams participants were returned for this meeting." />
      ) : (
        <table className="tbl"><thead>
          <tr><th>Teams participant</th><th>Email</th><th>Join</th><th>Leave</th><th>Duration</th>
            <th>Matched member</th><th>Include</th></tr>
        </thead><tbody>
          {participants.map((p: any) => (
            <tr key={p.email}>
              <td>{p.displayName || p.email}</td>
              <td>{p.email}</td>
              <td>{p.joinTime ?? "—"}</td>
              <td>{p.leaveTime ?? "—"}</td>
              <td>{p.durationMinutes ? `${p.durationMinutes} min` : "—"}</td>
              {/* Matching is by email (adjacent column) — the internal user id
                  adds nothing a human can read, so it is not rendered. */}
              <td>{p.matchStatus === "matched"
                ? <span className="badge green">✓ Matched</span>
                : <span className="badge amber">No match</span>}</td>
              <td><Toggle checked={overrides[p.email]?.include ?? p.include}
                          label={`Include ${p.email}`} labelHidden
                          testId={`include-${p.email}`}
                          onChange={(on) => setOverrides((o) => ({
                            ...o, [p.email]: { ...o[p.email], include: on } }))} /></td>
            </tr>
          ))}
        </tbody></table>
      )}

      <p className="faint small mt-12">
        Unmatched participants — external guests, or a different work email — earn nothing unless you
        match them to a member. Unmatched rows start excluded on purpose.
      </p>
      <div className="btn-row">
        <button className="btn primary" data-testid="teams-apply"
                disabled={Boolean(batch.data?.appliedAt) || participants.length === 0}
                onClick={apply}>
          {batch.data?.appliedAt ? "Already applied" : "✓ Apply & Award Points"}</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- designations

function DesignationsTab(props: {
  id: string; nonce: number; disabled: boolean; onDone: (m: string) => void;
}) {
  const current = useApi<{ items: any[] }>(`/events/${props.id}/designations?_=${props.nonce}`);
  const [presenters, setPresenters] = useState<PickedPerson[]>([]);
  const [organizers, setOrganizers] = useState<PickedPerson[]>([]);
  const [externals, setExternals] = useState<string[]>([]);
  const [seeded, setSeeded] = useState(false);

  // Seed the pickers from the current designations ONCE per tab visit — the
  // PUT is replace-style, so starting from empty would wipe existing designees
  // the moment someone saved a single addition.
  useEffect(() => {
    if (seeded || current.loading || !current.data) return;
    const rows = current.data.items ?? [];
    const toPerson = (d: any): PickedPerson => (
      { id: d.userId, name: d.displayName ?? d.userId, role: d.roleAtDesignation ?? "Member" });
    setPresenters(rows.filter((d) => d.kind === "presenter" && !d.external).map(toPerson));
    setOrganizers(rows.filter((d) => d.kind === "organizer").map(toPerson));
    setExternals(rows.filter((d) => d.kind === "presenter" && d.external)
      .map((d) => d.displayName));
    setSeeded(true);
  }, [seeded, current.loading, current.data]);

  const save = async () => {
    try {
      await apiFetch(`/events/${props.id}/designations`, {
        method: "PUT",
        body: JSON.stringify({
          presenters: presenters.map((p) => p.id),
          organizers: organizers.map((p) => p.id),
          externalPresenters: externals,
        }),
      });
      props.onDone("Designations updated.");
    } catch (err) { props.onDone((err as Error).message); }
  };

  if (current.loading) return <Loading />;
  const rows = current.data?.items ?? [];

  return (
    <div className="card">
      <div className="card-head"><h3>🎤 Presenters &amp; Organizers</h3></div>
      <p className="small muted">
        Presenters earn delivery points and organizers earn organize points when the event is
        completed — but only designees who hold the Member role. Leaders can be designated and will
        appear on the event, they simply do not earn.
      </p>

      {rows.length === 0 ? <EmptyState message="Nobody designated yet." /> : (
        <table className="tbl"><thead><tr><th>Person</th><th>Role on event</th>
          <th>Role held</th><th>Earns points</th></tr></thead>
          <tbody>{rows.map((d) => (
            <tr key={`${d.kind}-${d.userId}`}>
              <td>{d.displayName ?? d.userId}
                {d.external && <span className="badge amber" style={{ marginLeft: 6 }}>External</span>}</td>
              <td><span className="badge purple">{d.kind}</span></td>
              <td>{d.external ? "—" : d.roleAtDesignation ?? "unverified"}</td>
              <td>{d.pointsEligible ? <span className="badge green">Yes</span>
                : <span className="faint small" data-testid={`ineligible-${d.userId}`}>
                    {d.ineligibleReason}</span>}</td>
            </tr>
          ))}</tbody></table>
      )}

      {props.disabled ? (
        <p className="faint small mt-12 mb-0">
          This event is completed, so designations are locked — the awards have already been issued.
        </p>
      ) : (
        <>
          <div className="divider" />
          <PeoplePicker label="Presenters / facilitators" testId="designate-presenters"
                        selected={presenters} onChange={setPresenters}
                        allowExternal externals={externals} onExternalsChange={setExternals}
                        hint="Search members and leaders, or add an external presenter by name." />
          <PeoplePicker label="Organizers" testId="designate-organizers"
                        selected={organizers} onChange={setOrganizers} />
          <div className="btn-row">
            <button className="btn primary" data-testid="designations-save" onClick={save}>
              Save designations</button>
          </div>
          <p className="faint small mt-8 mb-0">
            Saving replaces the current lists.
          </p>
        </>
      )}
    </div>
  );
}
