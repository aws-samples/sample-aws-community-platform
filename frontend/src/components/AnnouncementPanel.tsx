import { useMemo, useState } from "react";
import { useApi } from "../lib/useApi";
import { dismiss, isDismissed, pruneTo } from "../lib/dismissedAnnouncements";
import AnnouncementBody from "./AnnouncementBody";

// Recipient announcement panel (US-10.4/10.5). Renders on the landing pages
// (Member Home + leader analytics dashboards). The backend returns only
// announcements targeted to the caller, active and non-hidden, newest-first —
// the client does NOT compute targeting. Collapsed by default with an active
// count badge. Bodies are NOT server-sanitized — AnnouncementBody in
// ./AnnouncementBody renders the authored Markdown to React elements under an
// explicit allow-list (NFR-AN-SEC-2); see that module for the policy. It renders
// no HTML string, so there is no dangerouslySetInnerHTML anywhere in this path.
// Dismissal is client-side only (localStorage), never a server call (BR-11).
interface Announcement {
  id: string;
  title: string;
  body?: string;
  source?: string;
  authorName?: string;
  authorRoleLabel?: string;
  createdAt?: string;
  expiresAt?: string;
}

function fmtDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// Expiry is a calendar date (stored as end-of-day UTC), not a wall-clock instant.
// Format it in UTC so the day shown matches the date the author picked.
function fmtExpiry(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? ""
    : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

export default function AnnouncementPanel() {
  const [open, setOpen] = useState(false);
  const [nonce, setNonce] = useState(0);
  const { data, comingSoon, error } = useApi<{ items: Announcement[] }>(`/announcements?view=panel&_=${nonce}`);

  const visible = useMemo(() => {
    const items = data?.items ?? [];
    pruneTo(items.map((a) => a.id));
    return items.filter((a) => !isDismissed(a.id));
  }, [data, nonce]);

  // Silently render nothing if the service is unavailable or has no announcements
  // for this user — the panel is a supplementary widget, never a blocker.
  if (comingSoon || error || visible.length === 0) return null;

  const onDismiss = (id: string) => { dismiss(id); setNonce((n) => n + 1); };

  return (
    <div className="card mb-16" data-testid="announcement-panel">
      <div className="card-head" style={{ cursor: "pointer", margin: 0 }} onClick={() => setOpen((o) => !o)}
           data-testid="announcement-panel-toggle">
        <h3 style={{ margin: 0 }}>
          <span>{open ? "▾" : "▸"}</span> 📣 Announcements{" "}
          <span className="badge purple" style={{ marginLeft: 4 }}>{visible.length}</span>
        </h3>
        <span className="faint small">Click to expand · dismiss to clear from your view</span>
      </div>
      {open && (
        <div data-testid="announcement-panel-body">
          <div className="divider" />
          {visible.map((a) => (
            <div className="announce-card" key={a.id} data-testid={`announcement-${a.id}`}>
              <div className="ac-head">
                <div>
                  <div className="ac-title">{a.title}</div>
                  <div className="ac-meta">
                    {[a.source, a.authorName && `${a.authorName}${a.authorRoleLabel ? ` (${a.authorRoleLabel})` : ""}`,
                      fmtDate(a.createdAt)].filter(Boolean).join(" · ")}
                    {a.expiresAt ? ` · expires ${fmtExpiry(a.expiresAt)}` : ""}
                  </div>
                </div>
                <button className="ac-dismiss" title="Dismiss" data-testid={`announcement-dismiss-${a.id}`}
                        onClick={() => onDismiss(a.id)}>✕</button>
              </div>
              {a.body && (
                <div className="ac-body">
                  <AnnouncementBody body={a.body} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
