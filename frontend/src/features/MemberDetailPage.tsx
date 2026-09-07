import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import type { Role } from "../roles";
import Avatar from "../components/Avatar";
import DetailedActivitySummary from "../components/DetailedActivitySummary";
import VerifiedBadgesCard from "../components/VerifiedBadgesCard";
import TierBadgesCard from "../components/TierBadgesCard";
import { ShoutoutModal, timeAgo } from "../components/ShoutoutsSection";
import { tierClass, tierIcon } from "../lib/tiers";

// Member detail (US-3.3) — read-only view of another member's profile.
// Layout mirrors ProfilePage (hero banner + completeness-free body) but is
// read-only: no Edit button, no completeness bar.
// Shoutouts: "Give Shoutout" button (Members only) + recent shoutouts received.
// Leader-only: DetailedActivitySummary at the bottom.
export default function MemberDetailPage({ role }: { role?: Role } = {}) {
  const { id = "" } = useParams();
  const [shoutoutOpen, setShoutoutOpen] = useState(false);
  const [shoutoutSent, setShoutoutSent] = useState(false);

  const m = useApi<any>(`/members/${id}`);
  const me = useApi<any>("/members/me");
  const groupsApi = useApi<{ items: any[] }>("/groups");
  const shoutoutsApi = useApi<{ items: any[] }>(`/shoutouts/member/${id}?limit=6`);

  // Cross-group points — compute sum across all the viewed member's current groups.
  // mem.rollup.points only reflects the first group (backend default).
  const mem = m.data ?? {};
  const groups: any[] = mem.groups ?? [];
  const quarter: string = mem.rollup?.quarter ?? "";
  const groupIds = groups.map((g: any) => g.groupId).filter(Boolean);
  const groupKey = groupIds.slice().sort().join(",") + "|" + quarter;
  const [crossGroupPoints, setCrossGroupPoints] = useState<number | null>(null);
  useEffect(() => {
    if (!m.data) return;
    if (!groupIds.length) { setCrossGroupPoints(0); return; }
    let cancelled = false;
    setCrossGroupPoints(null);
    Promise.all(
      groupIds.map((gid: string) =>
        apiFetch<{ points?: number }>(`/contributions/me?memberId=${encodeURIComponent(id)}&groupId=${encodeURIComponent(gid)}&quarter=${encodeURIComponent(quarter)}`)
          .then((d) => Number(d?.points ?? 0))
          .catch(() => 0)
      )
    ).then((vals) => {
      if (!cancelled) setCrossGroupPoints(vals.reduce((a, b) => a + b, 0));
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupKey]);

  if (m.loading) return <Loading />;
  if (m.comingSoon) return <ComingSoon feature="Member profile" />;
  if (m.error) return <ErrorState message={m.error} />;

  const activitySummary = mem.activitySummary ?? {};
  const tiers: any[] = mem.tiers ?? [];
  const skills: string[] = mem.skills ?? [];
  const shoutouts: any[] = shoutoutsApi.data?.items ?? [];

  const allGroups = groupsApi.data?.items ?? [];
  const groupName = (gid: string) => allGroups.find((g: any) => g.id === gid)?.name ?? gid;
  const ledGroups = allGroups.filter((g: any) => (g.leaderIds ?? []).includes(mem.id));

  const isLeader = role === "CommunityLeader" || role === "UserGroupLeader";
  // NOT gated on the viewer's role any more: a leader viewing their own profile through
  // the directory is just as much "self", and the old form made isSelf
  // permanently false for them.
  const isSelf = me.data?.id === id;
  // Server's verdict (US-13.1/13.2/13.11), computed by
  // shoutout_service.can_send_shoutout: sender role, recipient must be a Member,
  // not self, and a UGL only within their led group. Previously this button was
  // keyed off the VIEWER being a Member, which was wrong in both directions —
  // leaders got no button despite being allowed, and a member viewing a leader's
  // profile got one that always failed with "Shoutouts can only be sent to
  // Members." Do not re-derive the rule here.
  const canShoutout = Boolean(mem.canShoutout) && !isSelf;
  const displayName = `${mem.firstName ?? ""} ${mem.lastName ?? ""}`.trim();

  // Best current tier for the hero badge
  const ORDER = ["Gold", "Silver", "Bronze", "Rising"];
  const bestTier = tiers.length > 0
    ? tiers.slice().sort((a, b) => ORDER.indexOf(a.tier) - ORDER.indexOf(b.tier))[0]
    : null;

  return (
    <>
      {/* Give Shoutout modal */}
      {shoutoutOpen && (
        <ShoutoutModal
          recipientId={id}
          recipientName={displayName}
          onClose={() => setShoutoutOpen(false)}
          onSent={() => { setShoutoutOpen(false); setShoutoutSent(true); }}
        />
      )}

      {/* Page header */}
      <div className="page-head flex between" style={{ padding: "14px 24px 10px", marginBottom: 0 }}>
        <div>
          <div className="breadcrumb"><Link to="/directory">← Member Directory</Link></div>
          <h1>{displayName || "Member Profile"}</h1>
          <p>Read-only view — visible to all community members.</p>
        </div>
        {canShoutout && (
          <button className="btn primary" data-testid="give-shoutout"
                  title={`Recognise ${mem.firstName || "this member"} publicly`}
                  onClick={() => setShoutoutOpen(true)}>
            👏 Give Shoutout
          </button>
        )}
      </div>

      {shoutoutSent && (
        <div style={{ margin: "0 24px 10px", padding: "8px 14px", background: "var(--success-bg)",
                      border: "1px solid #bbf7d0", borderRadius: "var(--radius)", fontSize: 13,
                      color: "var(--success)", display: "flex", justifyContent: "space-between" }}>
          <span>👏 Shoutout sent to {displayName}!</span>
          <button style={{ background: "none", border: "none", cursor: "pointer", color: "var(--success)" }}
                  onClick={() => setShoutoutSent(false)}>✕</button>
        </div>
      )}

      {/* Hero banner — same structure as ProfilePage */}
      <div className="profile-hero">
        <div className="profile-hero-row">

          <Avatar firstName={mem.firstName} lastName={mem.lastName} src={mem.avatar} size="xl" />

          <div className="profile-hero-identity">
            <h2>
              {mem.firstName} {mem.lastName}
              {mem.status === "inactive" && (
                <span className="badge gray" style={{ marginLeft: 8, fontSize: 12 }}>Inactive</span>
              )}
            </h2>
            <div className="phi-email">{mem.email}</div>
            <div className="phi-badges">
              <span className="badge">{mem.role}</span>
              {bestTier && (
                <span className={tierClass(bestTier.tier)}>
                  {tierIcon(bestTier.tier)} {bestTier.tier} · {groupName(bestTier.groupId)}
                </span>
              )}
            </div>
          </div>

          {/* 4 activity stats */}
          <div className="profile-hero-stats">
            <div className="phs-nums">
              {[
                { n: activitySummary.eventsAttended ?? 0, l: "Events attended" },
                { n: activitySummary.forumPosts ?? 0,    l: "Forum posts" },
                { n: activitySummary.contributions ?? 0, l: "Contributions" },
                { n: activitySummary.certifications ?? 0,l: "Certifications" },
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
              <div className="phf-val">{[mem.city, mem.country].filter(Boolean).join(", ") || "—"}</div>
            </div>
            <div className="phf-cell">
              <div className="phf-label">Professional role</div>
              <div className="phf-val">{mem.professionalRole || "—"}</div>
            </div>
            <div className="phf-cell">
              <div className="phf-label">Time zone</div>
              <div className="phf-val">{mem.timezone || "—"}</div>
            </div>
            <div className="phf-cell">
              <div className="phf-label">AWS project</div>
              <div className="phf-val">
                <span className={"badge " + (mem.awsProject ? "green" : "gray")}>
                  {mem.awsProject ? "Yes" : "No"}
                </span>
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* Body */}
      <div className="profile-body">
        <div className="profile-two-col">

          {/* Left: Bio + Skills + Groups + Score + Tiers */}
          <div>
            <div className="card mb-16" data-testid="member-bio-card">
              <div className="card-head"><h3>Bio &amp; Skills</h3></div>
              {mem.bio
                ? <p className="muted mt-0" style={{ whiteSpace: "pre-wrap" }}>{mem.bio}</p>
                : <p className="faint small mt-0">This member hasn't added a bio yet.</p>}
              {skills.length > 0 ? (
                <div className="flex wrap" style={{ gap: 6 }}>
                  {skills.map((s) => <span key={s} className="skill-badge">{s}</span>)}
                </div>
              ) : <p className="faint small mb-0">No skills or tags listed.</p>}
            </div>

            <div className="card" data-testid="member-profile-card">
              <div className="section-label">Groups &amp; join dates</div>
              {ledGroups.length === 0 && groups.length === 0 ? (
                <p className="faint small">No group memberships.</p>
              ) : (
                <>
                  {ledGroups.map((g: any) => (
                    <div key={`led-${g.id}`} className="profile-group-row">
                      <span>{g.name}</span><span className="badge blue">Leader</span>
                    </div>
                  ))}
                  {groups.map((g) => (
                    <div key={g.groupId} className="profile-group-row">
                      <span>{groupName(g.groupId)}</span>
                      <b className="small nowrap">{g.joinedAt ? `Joined ${g.joinedAt.slice(0, 10)}` : "—"}</b>
                    </div>
                  ))}
                  <p className="faint small mt-8 mb-0">Join date is recorded per group.</p>
                </>
              )}

              {(mem.rollup || groups.length > 0) && (
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
                        <div className="ptt-qtr">{mem.rollup?.quarter ?? ""}</div>
                      </div>
                      <span className={tierClass(t.tier)}>{tierIcon(t.tier)} {t.tier}</span>
                    </div>
                  ))}
                </>
              )}
            </div>
          </div>

          {/* Right: Verified Badges + Tier Badges */}
          <div>
            {/* US-5.9 */}
            <VerifiedBadgesCard memberId={id} />
            {/* US-6.12 */}
            <TierBadgesCard memberId={id} />
            {/* Leader-only detailed activity */}
            {isLeader && <DetailedActivitySummary memberId={id} />}
          </div>

        </div>

        {/* Shoutouts received — full width */}
        <div className="card" data-testid="member-shoutouts">
          <div className="flex between" style={{ marginBottom: 12 }}>
            <div>
              <h3 style={{ margin: "0 0 2px" }}>👏 Shoutouts Received</h3>
              {shoutouts.length > 0 && (
                <span className="faint small">{shoutouts.length} recent shoutout{shoutouts.length !== 1 ? "s" : ""}</span>
              )}
            </div>
            {/* Was gated on isMember alone — with no !isSelf — so a member
                viewing their OWN profile was offered a shoutout to themselves,
                which the server rejects. */}
            {canShoutout && (
              <button className="btn primary sm" data-testid="give-shoutout-card"
                      onClick={() => setShoutoutOpen(true)}>
                👏 Give Shoutout
              </button>
            )}
          </div>

          {shoutoutsApi.loading && <p className="faint small">Loading shoutouts…</p>}
          {!shoutoutsApi.loading && shoutouts.length === 0 && (
            <p className="faint small text-c" style={{ padding: "20px 0" }}>
              No shoutouts yet — be the first to recognise {mem.firstName || "this member"}!
            </p>
          )}
          {shoutouts.length > 0 && (
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
          )}
        </div>

      </div>
    </>
  );
}
