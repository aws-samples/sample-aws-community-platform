import { useEffect, useState } from "react";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import FormModal from "../components/FormModal";
import DataTable, { loadRowsPref } from "../components/DataTable";
import VerifiedBadgesCard from "../components/VerifiedBadgesCard";
import TierBadgesCard from "../components/TierBadgesCard";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import { TIMEZONE_OPTIONS, timezoneOptions } from "../lib/timezones";
import { tierClass, tierIcon } from "../lib/tiers";
import Avatar from "../components/Avatar";
import ProgressTimeline, { deriveMilestones, getNextMilestone } from "../components/ProgressTimeline";
import { timeAgo } from "../components/ShoutoutsSection";
import type { Role } from "../roles";
import { useTheme } from "../lib/useTheme";

// Singleton-object screens (GET returns one object, not a list).

// My Profile (US-3.1 view, US-3.2 edit). Revamped UI — full-width hero banner,
// completeness bar, 2-column content, full-width shoutouts section.
// All existing functionality is preserved; only the layout changes.
export function ProfilePage() {
  const [nonce, setNonce] = useState(0);
  const [edit, setEdit] = useState(false);

  const { data, loading, error, comingSoon } = useApi<any>(`/members/me?_=${nonce}`);
  // Group names rather than raw ids; falls back to the id if /groups degrades.
  const groupsApi = useApi<{ items: any[] }>("/groups");
  // Own received shoutouts (US-13 — my-received endpoint)
  const shoutoutsApi = useApi<{ items: any[] }>("/shoutouts/my-received?limit=6");

  // Cross-group points — ALL hooks must be called before any early returns (Rules of Hooks).
  const m = data ?? {};
  const groups: any[] = m.groups ?? [];
  const quarter: string = m.rollup?.quarter ?? "";
  const groupIds = groups.map((g: any) => g.groupId).filter(Boolean);
  const groupKey = groupIds.slice().sort().join(",") + "|" + quarter;

  const [crossGroupPoints, setCrossGroupPoints] = useState<number | null>(null);
  useEffect(() => {
    if (!data) return; // no profile loaded yet
    if (!groupIds.length) { setCrossGroupPoints(0); return; }
    let cancelled = false;
    setCrossGroupPoints(null);
    Promise.all(
      groupIds.map((gid: string) =>
        apiFetch<{ points?: number }>(`/contributions/me?groupId=${encodeURIComponent(gid)}&quarter=${encodeURIComponent(quarter)}`)
          .then((d) => Number(d?.points ?? 0))
          .catch(() => 0)
      )
    ).then((vals) => {
      if (!cancelled) setCrossGroupPoints(vals.reduce((a, b) => a + b, 0));
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupKey]);

  // Early returns after all hooks
  if (loading) return <Loading />;
  if (comingSoon) return <ComingSoon feature="My Profile" />;
  if (error) return <ErrorState message={error} />;

  const tiers: any[] = m.tiers ?? [];
  const activitySummary = m.activitySummary ?? {};
  const skills: string[] = m.skills ?? [];
  const shoutouts: any[] = shoutoutsApi.data?.items ?? [];

  const groupName = (gid: string) =>
    (groupsApi.data?.items ?? []).find((g: any) => g.id === gid)?.name ?? gid;

  // Derive timeline milestones from existing profile data (unchanged logic)
  const profileWithGroupNames = {
    ...m,
    groups: groups.map((g: any) => ({ ...g, groupName: groupName(g.groupId) })),
    tiers: tiers.map((t: any) => ({ ...t, groupName: groupName(t.groupId) })),
  };
  const milestones = deriveMilestones(profileWithGroupNames);
  const nextMilestone = getNextMilestone(profileWithGroupNames);

  // Profile completeness — count filled optional fields
  const filledFields = [m.bio, (skills.length > 0), m.professionalRole, m.avatar, m.city].filter(Boolean).length;
  const totalFields = 5;
  const completePct = Math.round((filledFields / totalFields) * 100);
  const missingChips: { label: string; field: string }[] = [
    ...(!m.bio ? [{ label: "+ Bio", field: "bio" }] : []),
    ...(skills.length === 0 ? [{ label: "+ Skills", field: "skills" }] : []),
    ...(!m.professionalRole ? [{ label: "+ Professional role", field: "professionalRole" }] : []),
    ...(!m.avatar ? [{ label: "+ Avatar photo", field: "avatar" }] : []),
  ];

  return (
    <>
      {/* ── Edit Profile modal (FormModal — unchanged) ─────────────────── */}
      {edit && (
        <FormModal
          title="Edit Profile"
          path="/members/me"
          method="PUT"
          onClose={() => setEdit(false)}
          onSaved={() => setNonce((n) => n + 1)}
          initial={{
            city: m.city ?? "", country: m.country ?? "",
            professionalRole: m.professionalRole ?? "",
            timezone: m.timezone ?? "", bio: m.bio ?? "",
            skills: skills.join(", "),
            avatar: m.avatar ?? "",
            awsProject: m.awsProject ? "true" : "",
          }}
          fields={[
            { name: "city", label: "City" },
            { name: "country", label: "Country" },
            { name: "professionalRole", label: "Professional role" },
            { name: "timezone", label: "Time zone", type: "select", options: timezoneOptions(m.timezone) },
            // Profile picture is placed ABOVE the tall Bio textarea so its
            // "Choose File" control stays within the modal fold on short
            // viewports (otherwise it opened below the fold, under the footer,
            // and clicks landed on Save/Cancel — the file dialog never opened).
            { name: "avatar", label: "Profile picture", type: "image", uploadPath: "/members/me/avatar-upload" },
            { name: "bio", label: "Bio", type: "textarea", counter: true, maxLength: 2000,
              hint: "Plain text. Line breaks are preserved." },
            { name: "skills", label: "Skills / tags", type: "tags" },
            { name: "awsProject", label: "Part of an AWS project", type: "checkbox" },
          ]}
        />
      )}

      {/* ── Page header — Edit Profile lives here (no hero overlap) ──────── */}
      <div className="page-head flex between" style={{ padding: "14px 24px 10px", marginBottom: 0 }}>
        <div><h1>My Profile</h1><p>Your community profile — visible to other members.</p></div>
        <button className="btn primary" data-testid="edit-profile" onClick={() => setEdit(true)}>
          ✏️ Edit Profile
        </button>
      </div>

      {/* ── Hero banner ─────────────────────────────────────────────────── */}
      <div className="profile-hero">
        <div className="profile-hero-row">

          {/* Avatar */}
          <Avatar
            firstName={m.firstName}
            lastName={m.lastName}
            src={m.avatar}
            size="xl"
          />

          {/* Name / email / role+tier badges */}
          <div className="profile-hero-identity">
            <h2>{m.firstName} {m.lastName}</h2>
            <div className="phi-email">
              {m.email}
              <span
                title="Email and role are managed by the administrator."
                style={{ cursor: "default", fontSize: 11, opacity: 0.7 }}
              >ℹ️</span>
            </div>
            <div className="phi-badges">
              <span className="badge gray">{m.role}</span>
              {/* Surface the best current tier inline for at-a-glance recognition */}
              {tiers.length > 0 && (() => {
                const ORDER = ["Gold", "Silver", "Bronze", "Rising"];
                const best = tiers.slice().sort((a, b) =>
                  ORDER.indexOf(a.tier) - ORDER.indexOf(b.tier))[0];
                return (
                  <span className={tierClass(best.tier)}>
                    {tierIcon(best.tier)} {best.tier} · {groupName(best.groupId)}
                  </span>
                );
              })()}
            </div>
          </div>

          {/* 4 activity stats */}
          <div className="profile-hero-stats">
            <div className="phs-nums">
              {[
                { n: activitySummary.eventsAttended ?? 0,  l: "Events attended" },
                { n: activitySummary.forumPosts ?? 0,      l: "Forum posts" },
                { n: activitySummary.contributions ?? 0,   l: "Contributions" },
                { n: activitySummary.certifications ?? 0,  l: "Certifications" },
              ].map((s) => (
                <div key={s.l} className="phs-num">
                  <div className="phs-n">{s.n}</div>
                  <div className="phs-l">{s.l}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Facts grid */}
          <div className="profile-hero-facts">
            <div className="phf-cell">
              <div className="phf-label">Location</div>
              <div className="phf-val">{[m.city, m.country].filter(Boolean).join(", ") || "—"}</div>
            </div>
            <div className="phf-cell">
              <div className="phf-label">Professional role</div>
              <div className="phf-val">{m.professionalRole || "—"}</div>
            </div>
            <div className="phf-cell">
              <div className="phf-label">Time zone</div>
              <div className="phf-val">{m.timezone || "—"}</div>
            </div>
            <div className="phf-cell">
              <div className="phf-label">AWS project</div>
              <div className="phf-val">
                <span className={"badge " + (m.awsProject ? "green" : "gray")}>
                  {m.awsProject ? "Yes" : "No"}
                </span>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* ── Profile completeness bar ─────────────────────────────────────── */}
      {completePct < 100 && (
        <div className="profile-completeness">
          <div className="pc-row">
            <span className="pc-label">Profile completeness</span>
            <div className="pc-bar">
              <div className="pc-fill" style={{ width: `${completePct}%` }} />
            </div>
            <span className="pc-pct">{completePct}%</span>
          </div>
          {missingChips.length > 0 && (
            <div className="pc-chips">
              {missingChips.map((c) => (
                <button key={c.field} className="pc-chip" onClick={() => setEdit(true)}>
                  {c.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Body: Journey + two-col + shoutouts ─────────────────────────── */}
      <div className="profile-body">

        {/* Journey timeline — full width (existing ProgressTimeline component) */}
        <div style={{ marginBottom: 14 }}>
          <ProgressTimeline milestones={milestones} nextMilestone={nextMilestone} />
        </div>

        {/* Two-column section */}
        <div className="profile-two-col">

          {/* ── Left column: Bio + Skills + Groups + Score + Tiers ──────── */}
          <div>
            {/* Bio & Skills */}
            <div className="card mb-16" data-testid="profile-bio-card">
              <div className="card-head"><h3>Bio &amp; Skills</h3></div>
              {m.bio
                ? <p className="muted mt-0" style={{ whiteSpace: "pre-wrap" }}>{m.bio}</p>
                : <p className="faint small mt-0">No bio yet — use Edit Profile to add one.</p>}
              {skills.length > 0 ? (
                <div className="flex wrap" style={{ gap: 6 }}>
                  {skills.map((s: string) => (
                    <span key={s} className="skill-badge">{s}</span>
                  ))}
                </div>
              ) : <p className="faint small mb-0">No skills or tags yet.</p>}
              {skills.length === 0 && (
                <p className="faint small mt-6 mb-0">
                  Tip: add skills like Lambda, CDK, or Bedrock to appear in skill-based searches.
                </p>
              )}
            </div>

            {/* Groups + Contribution score + Tiers */}
            <div className="card" data-testid="profile-card">
              <div className="section-label">User Groups · joined</div>
              {groups.length === 0
                ? <p className="faint small">No group memberships yet.</p>
                : groups.map((g) => (
                  <div key={g.groupId} className="profile-group-row">
                    <span className="small">{groupName(g.groupId)}</span>
                    <span className="faint small nowrap">{g.joinedAt ? g.joinedAt.slice(0, 10) : "—"}</span>
                  </div>
                ))
              }

              {(m.rollup || groups.length > 0) && (
                <>
                  <div className="divider" />
                  <div className="profile-contrib-block">
                    <div>
                      <div className="pcb-label">Contribution score</div>
                      <div className="pcb-num">
                        {crossGroupPoints === null ? "…" : crossGroupPoints}
                      </div>
                    </div>
                    <div className="pcb-meta">
                      {quarter || "Current quarter"} · across {groups.length} group{groups.length !== 1 ? "s" : ""}<br />
                      <span className="faint small">Current quarter total</span>
                    </div>
                  </div>
                </>
              )}

              {tiers.length > 0 && (
                <>
                  <div className="divider" />
                  <div className="section-label">Tier by group</div>
                  {tiers.map((t) => (
                    <div key={t.groupId} className={"profile-tier-tile " + (t.tier ?? "").toLowerCase()}>
                      <div>
                        <div className="ptt-group">{groupName(t.groupId)}</div>
                        <div className="ptt-qtr">{m.rollup?.quarter ?? ""}</div>
                      </div>
                      <span className={tierClass(t.tier)}>{tierIcon(t.tier)} {t.tier}</span>
                    </div>
                  ))}
                </>
              )}

              <div className="divider" />
              <p className="faint small text-c mt-8 mb-0">Email and role are managed by the administrator.</p>
            </div>
          </div>

          {/* ── Right column: Verified Badges + Tier Badges ─────────────── */}
          <div>
            {/* US-5.9: verified certification badges */}
            <VerifiedBadgesCard ownRole={m.role} />
            {/* US-6.12: historical per-group/per-quarter tier badges */}
            <TierBadgesCard memberId={m.id} />
          </div>

        </div>{/* /two-col */}

        {/* ── Shoutouts received — full width ─────────────────────────── */}
        <div className="card" data-testid="profile-shoutouts">
          <div className="flex between" style={{ marginBottom: 12 }}>
            <div>
              <h3 style={{ margin: "0 0 2px" }}>👏 Shoutouts Received</h3>
              {shoutouts.length > 0 && (
                <span className="faint small">{shoutouts.length} recent shoutout{shoutouts.length !== 1 ? "s" : ""}</span>
              )}
            </div>
          </div>

          {shoutoutsApi.loading && <p className="faint small">Loading shoutouts…</p>}
          {!shoutoutsApi.loading && shoutouts.length === 0 && (
            <p className="faint small text-c" style={{ padding: "20px 0" }}>
              No shoutouts yet — be the first to recognise a community member!
            </p>
          )}
          {shoutouts.length > 0 && (
            <>
              <div className="profile-shoutout-grid">
                {shoutouts.map((s: any) => (
                  <div key={s.id} className="profile-shoutout-item">
                    <div className="psi-head">
                      <div className="avatar sm" style={{ flexShrink: 0 }}>
                        {(s.senderName ?? "?").split(" ").map((w: string) => w[0] ?? "").join("").slice(0, 2).toUpperCase()}
                      </div>
                      <span className="psi-from">{s.senderName ?? "—"}</span>
                      <span className="psi-time">{timeAgo(s.createdAt)}</span>
                    </div>
                    <div className="psi-msg">"{s.message}"</div>
                    {s.reactionCount > 0 && (
                      <div className="psi-reactions">👏 {s.reactionCount} reaction{s.reactionCount !== 1 ? "s" : ""}</div>
                    )}
                  </div>
                ))}
              </div>
              <div style={{ textAlign: "center", marginTop: 10 }}>
                <a href="/shoutouts" className="btn ghost" style={{ fontSize: 12.5 }}>
                  View all shoutouts →
                </a>
              </div>
            </>
          )}
        </div>

      </div>{/* /profile-body */}
    </>
  );
}

// Preferences (US-8.15 email prefs, US-8.16 time zone) — renamed from
// "Settings" per user request 2026-08-04; File Sharing (US-8.13) moved to its
// own nav item + dedicated screen (FileSharingPage below) for CL/UGL. Email is
// the only mutable channel — in-portal notifications are always delivered.
export function SettingsPage() {
  return (
    <>
      <div className="page-head"><h1>Preferences</h1>
        <p>Choose your appearance and time zone.</p></div>

      <ThemeCard />
      <TimeZoneCard />
    </>
  );
}

function ThemeCard() {
  const [theme, setTheme] = useTheme();

  return (
    <div className="card mb-16" style={{ maxWidth: 680 }} data-testid="theme-card">
      <h3>Appearance</h3>
      <p className="faint small" style={{ marginBottom: 16 }}>
        Choose how the portal looks. Your preference is saved locally on this device.
      </p>
      <div className="flex" style={{ gap: 12 }}>
        <button
          data-testid="theme-light"
          onClick={() => setTheme("light")}
          style={{
            flex: 1, padding: "14px 16px", borderRadius: "var(--radius)",
            border: `2px solid ${theme === "light" ? "var(--primary)" : "var(--border)"}`,
            background: theme === "light" ? "var(--primary-light)" : "var(--surface-2)",
            cursor: "pointer", textAlign: "left", transition: "border-color 0.15s",
          }}
        >
          <div style={{ fontSize: 22, marginBottom: 6 }}>☀️</div>
          <div style={{ fontWeight: 600, color: "var(--text)" }}>Light</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            Clean white background
          </div>
          {theme === "light" && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--primary)", fontWeight: 600 }}>
              ✓ Active
            </div>
          )}
        </button>
        <button
          data-testid="theme-dark"
          onClick={() => setTheme("dark")}
          style={{
            flex: 1, padding: "14px 16px", borderRadius: "var(--radius)",
            border: `2px solid ${theme === "dark" ? "var(--primary)" : "var(--border)"}`,
            background: theme === "dark" ? "var(--primary-light)" : "var(--surface-2)",
            cursor: "pointer", textAlign: "left", transition: "border-color 0.15s",
          }}
        >
          <div style={{ fontSize: 22, marginBottom: 6 }}>🌙</div>
          <div style={{ fontWeight: 600, color: "var(--text)" }}>Dark</div>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            Easy on the eyes at night
          </div>
          {theme === "dark" && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--primary)", fontWeight: 600 }}>
              ✓ Active
            </div>
          )}
        </button>
      </div>
    </div>
  );
}

// Dedicated File Sharing screen (US-8.13) — own nav item for CL/UGL.
export function FileSharingPage({ role }: { role?: Role }) {
  return (
    <>
      <div className="page-head"><h1>File Sharing</h1>
        <p>Share secure upload links with external parties and manage what they upload.</p></div>
      <FileShareCard role={role} />
    </>
  );
}

function TimeZoneCard() {
  const settings = useApi<any>("/settings");
  const [tz, setTz] = useState<string | null>(null);
  const [tzSaved, setTzSaved] = useState(false);
  const saveTz = async () => {
    try { await apiFetch("/members/me", { method: "PUT", body: JSON.stringify({ timezone: tz }) }); setTzSaved(true); } catch { setTzSaved(true); }
  };
  return (
    <div className="card mb-16" style={{ maxWidth: 680 }} data-testid="timezone-card">
      <h3>🕒 Time Zone</h3>
      <div className="field">
        <label>My time zone</label>
        <select className="select" data-testid="my-timezone" value={tz ?? settings.data?.defaultTimezone ?? "UTC"}
                onChange={(e) => setTz(e.target.value)}>
          {TIMEZONE_OPTIONS.map((z) => <option key={z.value} value={z.value}>{z.label}</option>)}
        </select>
        <div className="hint">All dates and times across the portal are shown in this time zone. Defaults to the community time zone set by the administrator until you change it.</div>
      </div>
      <div className="flex between"><span></span>
        <button className="btn primary" data-testid="save-timezone" onClick={saveTz}>Save Time Zone</button></div>
      {tzSaved && (
        <p className="small flex between mt-8 mb-0" style={{ color: "var(--success)" }}>
          <span>Time zone saved.</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setTzSaved(false)}>✕</button>
        </p>
      )}
    </div>
  );
}

// Secure external file-share slots (US-8.13, reworked 2026-08-04) — CL/UGL only.
// One record = one file slot (folder + file name). "Copy Link" mints a FRESH
// short-lived presigned PUT server-side and copies a ready-to-run curl command
// (curl-only upload per user decision — no separate upload page). "Open" shows
// the folder's contents with fresh download URLs. No expiry — Delete is the
// kill switch (stops all future Copy Link mints immediately).
const _fmtDate = (iso?: string) => iso
  ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "—";
const _fmtSize = (n?: number) => n == null ? "—"
  : n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`;

function FileShareCard({ role }: { role?: Role }) {
  const isCL = role === "CommunityLeader";
  const [nonce, setNonce] = useState(0);
  // Server-side cursor pagination (perf rework 2026-08-04): the community-wide
  // CL listing can be long, so pages are fetched one at a time. `uploaded` now
  // arrives on the record (kept current by the S3 event consumer) rather than
  // being recomputed from the bucket per request.
  const [pageSize, setPageSize] = useState(() => loadRowsPref("file-share"));
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  useEffect(() => { setCursorStack([]); }, [pageSize]);
  const params = new URLSearchParams({ limit: String(pageSize), _: String(nonce) });
  const cursor = cursorStack[cursorStack.length - 1];
  if (cursor) params.set("cursor", cursor);
  const links = useApi<{ items: any[]; cursor?: string }>(`/settings/file-share?${params.toString()}`);
  const [open, setOpen] = useState(false);
  const [viewLink, setViewLink] = useState<any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Copy Link = fetch a fresh 1h presigned PUT + full curl command, copy the command.
  const copy = async (l: any) => {
    try {
      const u = await apiFetch<{ curl: string }>(`/settings/file-share/${l.id}/upload-url`);
      await navigator.clipboard.writeText(u.curl);
      setCopiedId(l.id); setTimeout(() => setCopiedId(null), 1500);
    } catch (e) { setMsg((e as Error).message || "Could not copy the upload command."); }
  };
  // Deactivate: stops new upload commands immediately; row + files stay.
  const deactivate = async (id: string) => {
    try { await apiFetch(`/settings/file-share/${id}/revoke`, { method: "POST" }); refresh(); }
    catch (e) { setMsg((e as Error).message); }
  };
  // Delete: permanently removes the link AND the uploaded file (confirmed first).
  const [confirmDelete, setConfirmDelete] = useState<any | null>(null);
  const [deleting, setDeleting] = useState(false);
  const doDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await apiFetch(`/settings/file-share/${confirmDelete.id}`, { method: "DELETE" });
      setConfirmDelete(null); refresh();
    } catch (e) { setMsg((e as Error).message); setConfirmDelete(null); }
    finally { setDeleting(false); }
  };
  const items = links.data?.items ?? [];
  const serverPaging = {
    fetching: links.fetching,
    hasMore: Boolean(links.data?.cursor),
    canPrev: cursorStack.length > 0,
    onNext: () => { if (links.data?.cursor) setCursorStack((s) => [...s, links.data!.cursor!]); },
    onPrev: () => setCursorStack((s) => s.slice(0, -1)),
    onPageSizeChange: setPageSize,
  };
  // Back to page 1 after a mutation — the row we changed may no longer belong
  // on the page we are viewing.
  const refresh = () => { setCursorStack([]); setNonce((n) => n + 1); };

  if (links.comingSoon) return <ComingSoon feature="File sharing" />;

  return (
    <div data-testid="file-share">
      <div className="card mb-16" style={{ background: "var(--info-bg)", padding: 10 }}>
        <span className="small" style={{ color: "var(--info)" }}>ℹ Create a file slot in the community S3 bucket and share the upload
          command with an external AWS PSA. <b>Copy Link</b> copies a ready-to-run <b>curl</b> command that uploads one file
          (valid for 1 hour — copy again anytime for a fresh one). Uploads are <b>write-only</b> to that exact file;
          use <b>Open</b> to view and download what was uploaded, <b>Deactivate</b> to stop uploads immediately,
          and <b>Delete</b> to remove the link and its file for good.</span>
      </div>
      <div className="flex between mb-12"><h3 className="mb-0">File Share Links</h3>
        <button className="btn primary sm" data-testid="create-share-link" onClick={() => setOpen(true)}>＋ Create Share Link</button></div>
      {msg && (
        <p className="small flex between mb-8" style={{ color: "var(--danger)" }} role="alert">
          <span>{msg}</span>
          <button className="icon-btn" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button>
        </p>
      )}
      <div className="card">
        {links.error ? <ErrorState message={links.error} /> : (
          <DataTable id="file-share" rows={items} server={serverPaging} columns={[
            { key: "folder", header: "Folder",
              render: (l: any) => <><b>{l.folder}</b>{l.note && <div className="faint small">{l.note}</div>}</> },
            { key: "file", header: "File", render: (l: any) => l.fileName },
            // Created By is meaningful only on the community-wide CL listing —
            // a UserGroupLeader sees exclusively their own slots, so the column
            // would repeat the same name on every row.
            ...(isCL ? [{ key: "createdBy", header: "Created By",
              render: (l: any) => l.createdByEmail
                ? <span title={l.createdByEmail}>{l.createdByEmail}</span>
                : <span className="faint" title="Created before creator details were recorded.">—</span> }] : []),
            { key: "created", header: "Created", render: (l: any) => _fmtDate(l.createdAt) },
            { key: "status", header: "Status", render: (l: any) => (
              <>
                <span className={`badge ${l.revoked ? "gray" : "green"}`}>{l.revoked ? "Deactivated" : "Active"}</span>
                {l.uploaded
                  ? <span className="badge blue" style={{ marginLeft: 6 }}
                          title={`${_fmtSize(l.sizeBytes)} • uploaded ${_fmtDate(l.uploadedAt)} — use Open to download it.`}>✓ Uploaded</span>
                  : !l.revoked && <span className="badge gray" style={{ marginLeft: 6 }} title="No file received yet.">Awaiting upload</span>}
              </>
            ) },
            { key: "actions", header: "Actions", render: (l: any) => (
              <span className="btn-row">
                <button className="btn sm" disabled={l.revoked} title={l.revoked ? "Deactivated links cannot be copied." : undefined} onClick={() => copy(l)}>
                  {copiedId === l.id ? "✓ Copied" : "📋 Copy Link"}</button>
                <button className="btn sm" data-testid="open-share-folder" onClick={() => setViewLink(l)}>Open</button>
                {!l.revoked && <button className="btn sm" data-testid="deactivate-share-link" onClick={() => deactivate(l.id)}>Deactivate</button>}
                <button className="btn danger sm" data-testid="delete-share-link" onClick={() => setConfirmDelete(l)}>Delete</button>
              </span>
            ) },
          ]} />
        )}
      </div>
      <p className="faint small mt-12"><b>Deactivate</b> immediately stops new upload commands (one copied in the last hour may
        still complete); the file stays and Open keeps working. <b>Delete</b> permanently removes the link and its uploaded file.</p>
      {open && <CreateShareLinkModal onClose={() => setOpen(false)}
        onCreated={(l) => { setOpen(false); refresh(); copy(l); }} />}
      {viewLink && <ShareFolderModal link={viewLink} onClose={() => setViewLink(null)} />}
      {confirmDelete && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 140, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <div className="card" style={{ width: 460, maxWidth: "92vw" }} role="alertdialog" aria-modal="true" data-testid="confirm-delete-modal">
            <div className="card-head"><h3>Delete share link?</h3>
              <button className="icon-btn" aria-label="Close" onClick={() => setConfirmDelete(null)}>✕</button></div>
            <p className="small">This permanently deletes the link for <b>{confirmDelete.folder}/{confirmDelete.fileName}</b>
              {confirmDelete.uploaded ? <> <b>and the uploaded file in the bucket</b></> : null}. This cannot be undone.</p>
            <p className="small faint">To only stop further uploads while keeping the file, use Deactivate instead.</p>
            <div className="btn-row mt-12">
              <button className="btn danger" disabled={deleting} data-testid="confirm-delete" onClick={doDelete}>
                {deleting ? "Deleting…" : "Delete link & file"}</button>
              <button className="btn" onClick={() => setConfirmDelete(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// "Open" — owner-side folder view (US-8.13 view/download): objects in the
// slot's folder with fresh 5-minute presigned GET download URLs.
function ShareFolderModal({ link, onClose }: { link: any; onClose: () => void }) {
  const files = useApi<{ items: any[] }>(`/settings/file-share/${link.id}/files`);
  const items = files.data?.items ?? [];
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 560, maxWidth: "92vw" }} data-testid="share-folder-modal">
        <div className="card-head"><h3>📁 {link.folder}</h3><button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button></div>
        {files.loading && <Loading />}
        {files.error && <ErrorState message={files.error} />}
        {!files.loading && !files.error && (
          items.length === 0 ? <p className="faint small">No files uploaded yet.</p> : (
            <table className="tbl">
              <thead><tr><th>File</th><th>Size</th><th>Uploaded</th><th></th></tr></thead>
              <tbody>
                {items.map((f) => (
                  <tr key={f.name}>
                    <td>{f.name}</td>
                    <td>{_fmtSize(f.sizeBytes)}</td>
                    <td>{_fmtDate(f.uploadedAt)}</td>
                    <td>{f.downloadUrl && <a className="btn sm" href={f.downloadUrl} target="_blank" rel="noreferrer">Download</a>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
        <p className="faint small mt-12">Download links are freshly generated and valid for about 5 minutes.</p>
        <div className="btn-row mt-12"><button className="btn" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}

function CreateShareLinkModal({ onClose, onCreated }: { onClose: () => void; onCreated: (link: any) => void }) {
  // Bucket is predefined (foundation FileShareBucket) — readonly, mirrors the
  // mockup. Folder: pick an existing one from the bucket or create a new one.
  const meta = useApi<{ bucket: string; folders: string[] }>("/settings/file-share/folders");
  const NEW = "__new__";
  const [folderSel, setFolderSel] = useState(NEW);
  const [newFolder, setNewFolder] = useState("");
  const [fileName, setFileName] = useState("");
  const [note, setNote] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const folders = meta.data?.folders ?? [];
  const folder = folderSel === NEW ? newFolder.trim() : folderSel;
  const create = async () => {
    if (!folder) { setError("Folder name is required."); return; }
    if (!fileName.trim()) { setError("File name is required."); return; }
    setCreating(true); setError(null);
    try {
      const link = await apiFetch("/settings/file-share", { method: "POST",
        body: JSON.stringify({ folder, fileName: fileName.trim(), note }) });
      onCreated(link);
    } catch (e) { setError((e as Error).message); } finally { setCreating(false); }
  };
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,.4)", zIndex: 130, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div className="card" style={{ width: 520, maxWidth: "92vw" }} data-testid="share-link-modal">
        <div className="card-head"><h3>Create Share Link</h3><button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button></div>
        <div className="field"><label>Bucket</label>
          <input className="input" data-testid="share-bucket" value={meta.data?.bucket ?? ""} readOnly disabled />
          <div className="hint">Predefined community bucket (created during infrastructure provisioning).</div></div>
        <div className="field"><label>Folder</label>
          <select className="select" data-testid="share-folder-select" value={folderSel} onChange={(e) => setFolderSel(e.target.value)}>
            <option value={NEW}>＋ New folder…</option>
            {folders.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
          {folderSel === NEW && (
            <input className="input mt-8" data-testid="share-folder" placeholder="e.g. psa-reinvent-assets"
                   value={newFolder} onChange={(e) => setNewFolder(e.target.value)} />)}
          <div className="hint">Allowed: letters, numbers, hyphens. The uploader can only write this one file inside this folder.</div></div>
        <div className="field"><label>File name</label>
          <input className="input" data-testid="share-file-name" placeholder="e.g. booth-assets.zip"
                 value={fileName} onChange={(e) => setFileName(e.target.value)} />
          <div className="hint">Must be unique within the folder. The upload command writes to exactly this file.</div></div>
        <div className="field"><label>Note (optional)</label>
          <input className="input" data-testid="share-note" placeholder="e.g. re:Invent booth assets from PSA"
                 value={note} onChange={(e) => setNote(e.target.value)} /></div>
        <div className="card" style={{ background: "var(--warning-bg)", padding: 10 }}>
          <span className="small" style={{ color: "var(--warning)" }}>⚠ Anyone with the copied command can upload this file until you delete the link. Each copied command works for 1 hour — copy a fresh one anytime. Share it only with the intended recipient.</span></div>
        {error && <p className="small" style={{ color: "var(--danger)" }} role="alert">{error}</p>}
        <div className="btn-row mt-12">
          <button className="btn primary" disabled={creating} data-testid="share-submit" onClick={create}>
            {creating ? "Creating…" : "Create & Copy Link"}</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

// What's New in AWS moved to features/whats-new/ (real client-side RSS feed,
// replacing the sample-array mock that used to live here).
