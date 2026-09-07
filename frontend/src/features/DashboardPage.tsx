import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { canHoldOwnCertifications } from "../roles";
import type { CurrentUser, Role } from "../roles";
import { useApi } from "../lib/useApi";
import { apiFetch } from "../lib/apiClient";
import { refreshMembershipClaims } from "../lib/refreshMembership";
import { useGroupName } from "../lib/useGroupName";
import { ComingSoon, ErrorState, Loading } from "../components/States";
import AnnouncementPanel from "../components/AnnouncementPanel";
import ShoutoutsSection from "../components/ShoutoutsSection";
import { Leaderboard } from "./ContributionsPage";
import { pendingAwaitingApproval } from "./pendingCount";
import { deriveMilestones, getNextMilestone } from "../components/ProgressTimeline";

// Member home — mirrors the member home mockup: a snapshot
// stat row plus the Upcoming Events and Forum Activity aggregators. Everything
// except the Forum Activity panel is wired to live services; Forums is still a
// mock, so that one panel stays illustrative until the Forums module lands.
export default function DashboardPage({ user }: { user: CurrentUser }) {
  const isMember = user.role === "Member";
  // Fetch the member's profile to get their real name
  const profile = useApi<any>("/members/me");
  const displayName = profile.data?.firstName || user.name.split(" ")[0];
  return (
    <>
      {isMember && <OnboardingBanner />}
      <AnnouncementPanel />
      <div className="page-head flex between">
        <div>
          <h1>Welcome back, {displayName} 👋</h1>
          <p>Your community activity at a glance. Points and tiers are tracked separately per user group.</p>
        </div>
        <span className="btn-row">
          {/* Leaders do not earn points, so there is no "My Contributions" view
              for them — the Contributions page opens on their approvals queue.
              Showing the button would promise a screen that does not exist. */}
          {isMember && (
            <Link className="btn sm primary" to="/contributions" data-testid="home-contributions">My Contributions</Link>
          )}
        </span>
      </div>

      <StatRow isMember={isMember} role={user.role} />

      {isMember && <JourneyTeaser />}

      <ShoutoutsSection role={user.role} />

      {isMember && (
        <div className="card mb-16" style={{ padding: 0 }}>
          <div style={{ padding: "14px 18px" }}>
            <Leaderboard role={user.role} />
          </div>
        </div>
      )}

      <div className="grid cols-2 mb-16">
        <UpcomingEventsPanel />
        <RecentForumActivity />
      </div>
    </>
  );
}

// Sum of current-quarter points across ALL the member's groups (the mockup's
// "Points This Quarter · across my groups"). There is no cross-group total on
// the API, so we fan out one /contributions/me call per group and add them up.
function useCrossGroupPoints(groups: string[], enabled: boolean): number | null {
  const [total, setTotal] = useState<number | null>(null);
  const key = enabled ? groups.slice().sort().join(",") : "";
  useEffect(() => {
    if (!enabled) { setTotal(null); return; }
    if (groups.length === 0) { setTotal(0); return; }
    let cancelled = false;
    setTotal(null);
    Promise.all(groups.map((g) =>
      apiFetch<{ points?: number }>(`/contributions/me?groupId=${encodeURIComponent(g)}`)
        .then((d) => Number(d?.points ?? 0)).catch(() => 0)))
      .then((vals) => { if (!cancelled) setTotal(vals.reduce((a, b) => a + b, 0)); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);
  return total;
}

// The four headline stats. Points/groups/certs work for any community role;
// "Pending" (the member's own work awaiting a leader) is Member-only on the API,
// so it is fetched only for members and shown as 0 otherwise.
function StatRow({ isMember, role }: { isMember: boolean; role: Role }) {
  const me = useApi<{ groups?: string[] }>("/contributions/me");
  const groups = me.data?.groups ?? [];
  const ready = !me.loading && !me.error && !me.comingSoon;
  const points = useCrossGroupPoints(groups, ready);
  // Gated for the same reason `subs` below is: /certifications/claims/me is
  // scoped to roles that can hold their OWN claims. It was previously fetched
  // unconditionally, so a CommunityLeader took a guaranteed 403 on every load.
  const certs = useApi<{ items?: { status: string }[] }>(
    "/certifications/claims/me", canHoldOwnCertifications(role));
  const claims = certs.data?.items ?? [];
  const verified = claims.filter((c) => c.status === "Approved").length;
  const subs = useApi<{ items?: { status: string }[] }>("/contributions/submissions", isMember);
  // "Pending" counts BOTH pending contribution submissions and pending
  // certification claims. It used to count contributions only, so a member with
  // (say) three certification claims awaiting verification and no pending
  // contribution saw "0 awaiting approval" while three items genuinely sat in a
  // leader's queue — and the tile sits immediately beside the Certifications
  // tile, which makes the omission read as "nothing of mine is waiting".
  // `claims` is already fetched above for the Certifications tile, so this costs
  // no extra request.
  const pending = pendingAwaitingApproval(subs.data?.items, claims);
  // Still loading while EITHER source is in flight, so the tile never briefly
  // shows a half-count that looks authoritative.
  const pendingLoading = subs.loading || certs.loading;
  const show = (v: number | null | undefined, loading: boolean) => (loading || v == null ? "…" : v);

  return (
    <div className="grid cols-4 mb-16">
      <div className="card stat"><div className="ic-bubble">📈</div><div className="label">Points This Quarter</div>
        <div className="value" data-testid="stat-points">{show(points, !ready)}</div><div className="trend up">across my groups</div></div>
      <div className="card stat"><div className="ic-bubble">👥</div><div className="label">My User Groups</div>
        <div className="value" data-testid="stat-groups">{show(ready ? groups.length : null, me.loading)}</div><div className="trend">active memberships</div></div>
      <div className="card stat"><div className="ic-bubble">🎓</div><div className="label">Certifications</div>
        <div className="value" data-testid="stat-certs">{show(certs.comingSoon ? 0 : verified, certs.loading)}</div><div className="trend">verified badges</div></div>
      <div className="card stat"><div className="ic-bubble">📝</div><div className="label">Pending</div>
        <div className="value" data-testid="stat-pending">{isMember ? show(subs.comingSoon && certs.comingSoon ? 0 : pending, pendingLoading) : 0}</div><div className="trend">awaiting approval</div></div>
    </div>
  );
}

// Short date like "Jun 12, 2026" from an ISO timestamp.
function fmtDate(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const EVENT_BADGE: Record<string, string> = {
  Workshop: "blue", Meetup: "purple", Hackathon: "amber", Webinar: "blue", Conference: "amber",
};

function UpcomingEventsPanel() {
  const groupName = useGroupName();
  const { data, loading, comingSoon, error } = useApi<{ items: any[] }>("/events?status=Upcoming&limit=5");
  const items = (data?.items ?? []).slice(0, 4);
  return (
    <div className="card">
      <div className="card-head"><h3>Upcoming Events</h3><Link className="small" to="/events" data-testid="home-events-viewall">View all →</Link></div>
      {loading ? <Loading /> : comingSoon ? <ComingSoon feature="Events" /> : error ? <ErrorState message={error} /> : items.length === 0 ? (
        <p className="faint small mb-0">No upcoming events.</p>
      ) : (
        <ul className="clean">
          {items.map((ev) => (
            <li key={ev.id} className="flex between">
              <div>
                <div className="flex"><span className={"badge " + (EVENT_BADGE[ev.type] ?? "gray")}>{ev.type}</span> <b>{ev.title}</b></div>
                <div className="faint small mt-8">{fmtDate(ev.startsAt)} · {ev.deliveryMode} · {ev.groupId ? groupName(ev.groupId) : "Community-wide"}</div>
              </div>
              <Link className="btn sm" to={`/events/${ev.id}`}>View</Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// First-time login experience (US-3.6). Shown to Members whose profile has no
// group memberships yet — presents available groups to join (open groups join
// immediately; approval-required groups submit a join request, US-1.7/1.8) or
// skip. Dismissal (skip or "Done") is remembered for the session via
// localStorage so it doesn't reappear on every dashboard visit once acted on.
function OnboardingBanner() {
  const DISMISS_KEY = "onboarding-dismissed";
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(DISMISS_KEY) === "true");
  const [joined, setJoined] = useState<Record<string, "joined" | "requested">>({});
  const profile = useApi<{ groups?: { groupId: string }[] }>("/members/me");
  const groups = useApi<{ items: any[] }>("/groups");

  const dismiss = () => { localStorage.setItem(DISMISS_KEY, "true"); setDismissed(true); };
  const join = async (g: any) => {
    try {
      await apiFetch(`/groups/${g.id}/join`, { method: "POST" });
      setJoined((j) => ({ ...j, [g.id]: g.approvalRequired ? "requested" : "joined" }));
      // This is the FIRST group a member joins (the banner only renders when they
      // have none), so it is the case where a stale token hurts most: without the
      // refresh their directory and event ideas feed stay empty right after
      // onboarding told them they had joined. Approval-required groups grant
      // nothing yet, so there is no claim to pick up.
      if (!g.approvalRequired) await refreshMembershipClaims();
    } catch {
      // Best-effort — a failed join here isn't fatal to onboarding; the member
      // can always join later from the User Groups page.
    }
  };

  if (dismissed || profile.loading || profile.comingSoon) return null;
  const hasGroups = (profile.data?.groups ?? []).length > 0;
  if (hasGroups) return null; // already joined at least one group — not a first-time member

  return (
    <div className="card mb-16" data-testid="onboarding-banner">
      <div className="page-head flex between" style={{ marginBottom: 8 }}>
        <div><h3 style={{ margin: 0 }}>Welcome! Join a user group to get started</h3>
          <p className="faint small mb-0">Pick one or more groups now, or skip and join later from User Groups.</p></div>
        <button className="btn sm" data-testid="onboarding-skip" onClick={dismiss}>Skip for now</button>
      </div>
      {groups.comingSoon ? null : (
        <ul className="clean">
          {(groups.data?.items ?? []).map((g) => {
            const state = joined[g.id];
            return (
              <li key={g.id} className="flex between mb-8">
                <div><b>{g.name}</b><div className="faint small">{g.description}</div></div>
                {state === "joined" ? <span className="badge green">Joined</span>
                  : state === "requested" ? <span className="badge amber">Requested — pending approval</span>
                  : <button className="btn sm primary" data-testid={`onboarding-join-${g.id}`} onClick={() => join(g)}>
                      {g.approvalRequired ? "Request to join" : "Join"}
                    </button>}
              </li>
            );
          })}
        </ul>
      )}
      <div className="btn-row" style={{ justifyContent: "flex-end" }}>
        <button className="btn primary sm" data-testid="onboarding-done" onClick={dismiss}>Done</button>
      </div>
    </div>
  );
}


// Recent Forum Activity — fetches latest posts across the member's accessible forums.
function RecentForumActivity() {
  const { data, loading } = useApi<{ items: any[] }>("/forums/search?q=*&limit=5");
  // Fallback: if search with * doesn't work, fetch from first channel
  const forums = useApi<{ items: any[] }>("/forums");
  const [posts, setPosts] = useState<any[]>([]);

  useEffect(() => {
    if (data?.items?.length) {
      setPosts(data.items.slice(0, 5));
    } else if (forums.data?.items?.length) {
      // Get posts from the first channel of first forum
      const firstChannel = forums.data.items[0]?.channels?.[0];
      if (firstChannel) {
        apiFetch<any>(`/channels/${firstChannel.id}/posts?limit=5&sort=newest`)
          .then((r) => setPosts(r.items ?? []))
          .catch(() => {});
      }
    }
  }, [data, forums.data]);

  return (
    <div className="card">
      <div className="card-head"><h3>Recent Forum Activity</h3><Link className="small" to="/forums">Open forums →</Link></div>
      {loading ? <p className="faint small">Loading…</p> : posts.length === 0 ? (
        <p className="faint small">No recent forum activity.</p>
      ) : (
        <ul className="clean">
          {posts.map((p) => (
            <li key={p.id}>
              <div className="flex">
                <div className="avatar sm">{(p.authorName || p.authorId || "?").slice(0, 2).toUpperCase()}</div>
                <div>
                  <Link to={`/forums/post/${p.id}`}><b>{p.authorName || p.authorId}</b> posted "{p.title}"</Link>
                  <div className="faint small">{timeAgo(p.createdAt)}</div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function timeAgo(iso: string): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// Journey teaser on Home page (US-12.4) — compact: last milestone + next milestone + link to full road.
function JourneyTeaser() {
  const profile = useApi<any>("/members/me");
  const groupsApi = useApi<{ items: any[] }>("/groups");
  if (profile.loading || !profile.data) return null;

  const m = profile.data;
  const groupName = (gid: string) => (groupsApi.data?.items ?? []).find((g: any) => g.id === gid)?.name ?? gid;
  const enriched = { ...m, groups: (m.groups ?? []).map((g: any) => ({ ...g, groupName: groupName(g.groupId) })),
    tiers: (m.tiers ?? []).map((t: any) => ({ ...t, groupName: groupName(t.groupId) })) };
  const milestones = deriveMilestones(enriched);
  const next = getNextMilestone(enriched);
  const last = milestones.length > 0 ? milestones[milestones.length - 1] : null;

  if (!last && !next) return null;

  return (
    <div className="card mb-16" style={{ padding: "12px 16px" }} data-testid="journey-teaser">
      <div className="flex between" style={{ alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, flex: 1 }}>
          {last && (
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 18 }}>{last.icon}</span>
              <div>
                <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 500 }}>Last milestone</div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{last.title}</div>
              </div>
            </div>
          )}
          {next && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, opacity: 0.7 }}>
              <span style={{ fontSize: 18 }}>{next.icon}</span>
              <div>
                <div style={{ fontSize: 11, color: "var(--muted)", fontWeight: 500 }}>Next</div>
                <div style={{ fontSize: 12 }}>{next.message}</div>
                {/* micro progress bar */}
                <div style={{ marginTop: 3, height: 3, width: 80, borderRadius: 2, background: "var(--border)" }}>
                  <div style={{ height: "100%", width: `${Math.round(next.progress * 100)}%`, background: "var(--info, #0369a1)", borderRadius: 2 }} />
                </div>
              </div>
            </div>
          )}
        </div>
        <Link className="btn sm" to="/profile" style={{ whiteSpace: "nowrap" }}>View my journey →</Link>
      </div>
    </div>
  );
}
