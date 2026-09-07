import { useRef, useState } from "react";

// Personal Progress Timeline (US-12.1–12.10) — horizontal scrollable journey road.
// Pure observer of existing profile data. Never awards points. Display-only.
//
// Performance contract:
// - ≤3 DOM nodes per milestone (connector + dot + icon)
// - CSS overflow-x: auto (GPU-composited scroll, no JS listeners)
// - Tooltip: one element repositioned on hover, data already in memory

export interface Milestone {
  id: string;
  icon: string;
  title: string;
  detail?: string;
  date: string;
  category: "membership" | "contribution" | "certification" | "event" | "social" | "tier" | "meta";
}

// Derive milestones from existing profile data (backfill approach — US-12.9)
export function deriveMilestones(profile: any): Milestone[] {
  const milestones: Milestone[] = [];
  const groups: any[] = profile.groups ?? [];
  const activity = profile.activitySummary ?? {};
  const tiers: any[] = profile.tiers ?? [];
  const createdAt = profile.createdAt || profile.joinedAt;

  if (createdAt) {
    milestones.push({ id: "joined-community", icon: "🎉", title: "Joined the community",
      detail: "Welcome aboard! Your journey begins here.", date: createdAt, category: "membership" });
  }

  if (profile.bio && (profile.skills ?? []).length > 0) {
    milestones.push({ id: "profile-complete", icon: "✨", title: "Profile completed",
      detail: "Added bio, skills, and personal details.", date: profile.updatedAt || createdAt || "", category: "meta" });
  }

  for (const g of groups) {
    milestones.push({ id: `joined-group-${g.groupId}`, icon: "👥",
      title: `Joined ${g.groupName || g.groupId}`,
      detail: "Unlocked group forums, events, and leaderboard.", date: g.joinedAt || "", category: "membership" });
  }
  if (groups.length >= 2) {
    milestones.push({ id: "multi-group", icon: "🌐", title: "Multi-group member",
      detail: `Active in ${groups.length} groups simultaneously.`, date: "", category: "membership" });
  }

  const posts = Number(activity.forumPosts ?? 0);
  if (posts >= 1) milestones.push({ id: "first-post", icon: "💬", title: "First forum post", detail: "Started contributing to discussions.", date: "", category: "contribution" });
  if (posts >= 10) milestones.push({ id: "10-posts", icon: "🗣️", title: "Active discussant", detail: "10 forum posts — an active voice.", date: "", category: "contribution" });
  if (posts >= 25) milestones.push({ id: "25-posts", icon: "📢", title: "Prolific poster", detail: "25 posts — your insights matter!", date: "", category: "contribution" });

  const events = Number(activity.eventsAttended ?? 0);
  if (events >= 1) milestones.push({ id: "first-event", icon: "📅", title: "First event attended", detail: "Showed up and engaged.", date: "", category: "event" });
  if (events >= 5) milestones.push({ id: "5-events", icon: "🎪", title: "Regular attendee", detail: "5 events — a familiar face!", date: "", category: "event" });
  if (events >= 10) milestones.push({ id: "10-events", icon: "🌟", title: "Event enthusiast", detail: "10 events — never misses the action.", date: "", category: "event" });
  if (events >= 25) milestones.push({ id: "25-events", icon: "💎", title: "Community fixture", detail: "25 events attended!", date: "", category: "event" });

  const certs = Number(activity.certifications ?? 0);
  if (certs >= 1) milestones.push({ id: "first-cert", icon: "🎓", title: "First certification", detail: "Verified credential earned.", date: "", category: "certification" });
  if (certs >= 3) milestones.push({ id: "3-certs", icon: "🏆", title: "Multi-certified", detail: "3 certifications verified!", date: "", category: "certification" });
  if (certs >= 5) milestones.push({ id: "5-certs", icon: "👑", title: "Certification champion", detail: "5+ certifications — true expert.", date: "", category: "certification" });

  for (const t of tiers) {
    if (t.tier && t.tier !== "Rising") {
      milestones.push({ id: `tier-${t.groupId}-${t.tier}`,
        icon: t.tier === "Gold" ? "🥇" : t.tier === "Silver" ? "🥈" : "🏅",
        title: `Reached ${t.tier} tier`, detail: `In ${t.groupName || t.groupId}.`, date: "", category: "tier" });
    }
  }

  const contribs = Number(activity.contributions ?? 0);
  if (contribs >= 1) milestones.push({ id: "first-contrib", icon: "📝", title: "First contribution approved", detail: "Your work recognized by a leader.", date: "", category: "contribution" });
  if (contribs >= 5) milestones.push({ id: "5-contribs", icon: "⭐", title: "Consistent contributor", detail: "5 contributions approved.", date: "", category: "contribution" });

  // Sort chronologically: oldest first (left) → newest (right) for the road
  milestones.sort((a, b) => {
    if (a.date && b.date) return a.date.localeCompare(b.date);
    if (a.date && !b.date) return -1;
    if (!a.date && b.date) return 1;
    return 0;
  });

  return milestones;
}

// Next milestone suggestion (US-12.2)
export function getNextMilestone(profile: any): { icon: string; message: string; progress: number } | null {
  const activity = profile.activitySummary ?? {};
  const groups: any[] = profile.groups ?? [];
  const posts = Number(activity.forumPosts ?? 0);
  const events = Number(activity.eventsAttended ?? 0);
  const certs = Number(activity.certifications ?? 0);
  const contribs = Number(activity.contributions ?? 0);

  const candidates: { icon: string; message: string; progress: number; remaining: number }[] = [];

  if (groups.length === 0) {
    candidates.push({ icon: "👥", message: "Join a user group to start your journey", progress: 0, remaining: 1 });
  }
  if (posts === 0 && groups.length > 0) {
    candidates.push({ icon: "💬", message: "Write your first forum post", progress: 0, remaining: 1 });
  } else if (posts > 0 && posts < 10) {
    candidates.push({ icon: "🗣️", message: `${10 - posts} more post${10 - posts === 1 ? "" : "s"} to reach Active Discussant`, progress: posts / 10, remaining: 10 - posts });
  } else if (posts >= 10 && posts < 25) {
    candidates.push({ icon: "📢", message: `${25 - posts} more post${25 - posts === 1 ? "" : "s"} to reach Prolific Poster`, progress: posts / 25, remaining: 25 - posts });
  }
  if (events === 0) {
    candidates.push({ icon: "📅", message: "Attend your first event", progress: 0, remaining: 1 });
  } else if (events < 5) {
    candidates.push({ icon: "🎪", message: `${5 - events} more event${5 - events === 1 ? "" : "s"} to reach Regular Attendee`, progress: events / 5, remaining: 5 - events });
  } else if (events < 10) {
    candidates.push({ icon: "🌟", message: `${10 - events} more to reach Event Enthusiast`, progress: events / 10, remaining: 10 - events });
  }
  if (certs === 0) {
    candidates.push({ icon: "🎓", message: "Get your first certification verified", progress: 0, remaining: 1 });
  } else if (certs < 3) {
    candidates.push({ icon: "🏆", message: `${3 - certs} more certification${3 - certs === 1 ? "" : "s"} to reach Multi-Certified`, progress: certs / 3, remaining: 3 - certs });
  }
  if (contribs === 0 && groups.length > 0) {
    candidates.push({ icon: "📝", message: "Submit your first contribution", progress: 0, remaining: 1 });
  } else if (contribs > 0 && contribs < 5) {
    candidates.push({ icon: "⭐", message: `${5 - contribs} more to reach Consistent Contributor`, progress: contribs / 5, remaining: 5 - contribs });
  }

  if (candidates.length === 0) return null;
  candidates.sort((a, b) => b.progress - a.progress || a.remaining - b.remaining);
  return candidates[0];
}

// Category colors
const CATEGORY_COLORS: Record<string, string> = {
  membership: "#3b82f6",
  contribution: "#10b981",
  certification: "#8b5cf6",
  event: "#f59e0b",
  social: "#ec4899",
  tier: "#f97316",
  meta: "#6b7280",
};

function formatDate(iso: string): string {
  if (!iso) return "";
  try { return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }); }
  catch { return iso.slice(0, 10); }
}

/** Horizontal scrollable journey road (US-12.1) */
export default function ProgressTimeline({ milestones, nextMilestone, isOwnProfile = true }: {
  milestones: Milestone[];
  nextMilestone?: { icon: string; message: string; progress: number } | null;
  isOwnProfile?: boolean;
}) {
  const [tooltip, setTooltip] = useState<{ milestone: Milestone; x: number; y: number } | null>(null);
  const roadRef = useRef<HTMLDivElement>(null);

  if (milestones.length === 0 && !nextMilestone) {
    return (
      <div className="card" data-testid="progress-timeline">
        <div className="card-head"><h3>🗺️ My Journey</h3></div>
        <p className="faint small">Your journey starts here — join a group to begin!</p>
      </div>
    );
  }

  const showTooltip = (m: Milestone, e: React.MouseEvent | React.TouchEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const roadRect = roadRef.current?.getBoundingClientRect();
    setTooltip({ milestone: m, x: rect.left - (roadRect?.left ?? 0) + rect.width / 2, y: -8 });
  };
  const hideTooltip = () => setTooltip(null);

  return (
    <div className="card" data-testid="progress-timeline">
      <div className="card-head"><h3>🗺️ My Journey</h3></div>

      {/* Horizontal scrollable road */}
      <div
        ref={roadRef}
        style={{ overflowX: "auto", overflowY: "hidden", position: "relative", padding: "40px 16px 24px" }}
        onMouseLeave={hideTooltip}
      >
        {/* Tooltip (one element, repositioned) */}
        {tooltip && (
          <div style={{
            position: "absolute",
            left: tooltip.x,
            top: tooltip.y,
            transform: "translateX(-50%)",
            background: "var(--surface, #fff)",
            border: "1px solid var(--border, #e2e8f0)",
            borderRadius: "var(--radius, 6px)",
            padding: "8px 12px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
            zIndex: 10,
            whiteSpace: "nowrap",
            pointerEvents: "none",
          }}>
            <div style={{ fontSize: 12, fontWeight: 600 }}>{tooltip.milestone.title}</div>
            {tooltip.milestone.detail && <div style={{ fontSize: 11, color: "var(--muted, #64748b)", marginTop: 2 }}>{tooltip.milestone.detail}</div>}
            {tooltip.milestone.date && <div style={{ fontSize: 10, color: "var(--muted, #64748b)", marginTop: 3 }}>{formatDate(tooltip.milestone.date)}</div>}
          </div>
        )}

        {/* Road track */}
        <div style={{ display: "flex", alignItems: "center", minWidth: "max-content" }}>
          {milestones.map((m, i) => (
            <div key={m.id} style={{ display: "flex", alignItems: "center" }}>
              {/* Connector line (solid for earned) */}
              {i > 0 && (
                <div style={{
                  width: 40,
                  height: 3,
                  background: CATEGORY_COLORS[m.category] || "#6b7280",
                  opacity: 0.4,
                }} />
              )}
              {/* Milestone dot + icon */}
              <div
                style={{ display: "flex", flexDirection: "column", alignItems: "center", cursor: "pointer", position: "relative" }}
                onMouseEnter={(e) => showTooltip(m, e)}
                onTouchStart={(e) => { e.preventDefault(); showTooltip(m, e); }}
                onClick={(e) => showTooltip(m, e)}
              >
                <div style={{
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  background: CATEGORY_COLORS[m.category] || "#6b7280",
                  border: "3px solid var(--surface, #fff)",
                  boxShadow: `0 0 0 2px ${CATEGORY_COLORS[m.category] || "#6b7280"}`,
                  // Last earned milestone pulses (US-12.1 "you are here")
                  animation: (isOwnProfile && i === milestones.length - 1) ? "milestoneGlow 2s ease-in-out infinite" : undefined,
                }} />
                <span style={{ fontSize: 14, marginTop: 6, lineHeight: 1 }}>{m.icon}</span>
              </div>
            </div>
          ))}

          {/* Next milestone (faded, dashed connector) — only on own profile (US-12.5) */}
          {isOwnProfile && nextMilestone && (
            <div style={{ display: "flex", alignItems: "center" }}>
              {/* Dashed connector */}
              <div style={{
                width: 40,
                height: 3,
                backgroundImage: "repeating-linear-gradient(90deg, var(--border, #cbd5e1) 0, var(--border, #cbd5e1) 6px, transparent 6px, transparent 12px)",
              }} />
              {/* Faded next dot */}
              <div
                style={{ display: "flex", flexDirection: "column", alignItems: "center", cursor: "pointer", opacity: 0.4, position: "relative" }}
                onMouseEnter={(e) => {
                  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                  const roadRect = roadRef.current?.getBoundingClientRect();
                  setTooltip({
                    milestone: { id: "next", icon: nextMilestone.icon, title: "Next milestone", detail: nextMilestone.message, date: "", category: "meta" },
                    x: rect.left - (roadRect?.left ?? 0) + rect.width / 2, y: -8,
                  });
                }}
                onMouseLeave={hideTooltip}
              >
                <div style={{
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  border: "2px dashed var(--border, #94a3b8)",
                  background: "var(--surface-2, #f8fafc)",
                }} />
                <span style={{ fontSize: 14, marginTop: 6, lineHeight: 1 }}>{nextMilestone.icon}</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Legend (compact) */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px 14px", padding: "0 4px", marginTop: 4 }}>
        {[
          { color: CATEGORY_COLORS.membership, label: "Membership" },
          { color: CATEGORY_COLORS.contribution, label: "Contribution" },
          { color: CATEGORY_COLORS.event, label: "Event" },
          { color: CATEGORY_COLORS.certification, label: "Certification" },
          { color: CATEGORY_COLORS.tier, label: "Tier" },
        ].map((l) => (
          <span key={l.label} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: "var(--muted, #64748b)" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: l.color, display: "inline-block" }} />
            {l.label}
          </span>
        ))}
      </div>
    </div>
  );
}
