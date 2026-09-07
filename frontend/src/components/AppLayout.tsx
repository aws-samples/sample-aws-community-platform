import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import type { CurrentUser, NavBadge } from "../roles";
import { navForRole } from "../roles";
import { useApi } from "../lib/useApi";
import { onNavCountsRefresh } from "../lib/navCounts";

// Close a dropdown when the user clicks (mousedown) anywhere outside it.
// Returns a ref to attach to the dropdown's outer element.
function useClickOutside<T extends HTMLElement>(active: boolean, onClose: () => void) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!active) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [active, onClose]);
  return ref;
}

// Clickable avatar → profile menu (top-right). Shows the member's real first/
// last name (from /members/me) with Edit Profile + Preferences, and folds Sign
// out in here. Administrators have no member record or preferences, so they get
// a name + Sign out only.
function UserMenu({ user, onSignOut }: { user: CurrentUser; onSignOut?: () => void }) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const isAdmin = user.role === "Administrator";
  // Real name only exists for member-backed roles; skip the call for admins.
  const me = useApi<any>("/members/me", !isAdmin);
  const fullName = [me.data?.firstName, me.data?.lastName].filter(Boolean).join(" ") || user.name;
  const go = (path: string) => { setOpen(false); navigate(path); };
  const ref = useClickOutside<HTMLDivElement>(open, () => setOpen(false));
  return (
    <div style={{ position: "relative" }} ref={ref}>
      <button className="avatar as-button" title={user.name} data-testid="user-menu-button"
              aria-label={`Account menu for ${fullName || user.name}`}
              aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}
              style={me.data?.avatar ? { padding: 0, overflow: "hidden" } : undefined}>
        {me.data?.avatar
          ? <img src={me.data.avatar} alt=""
                 style={{ width: "100%", height: "100%", objectFit: "cover", borderRadius: "inherit" }} />
          : user.initials}
      </button>
      {open && (
        <div className="dropdown-panel" style={{ display: "block", position: "absolute", right: 0, zIndex: 40, width: 240 }}
             role="menu" data-testid="user-menu">
          <div className="dd-head" style={{ display: "block" }}>
            <div data-testid="user-menu-name">{fullName}</div>
            <div className="faint small" style={{ fontWeight: 400 }}>{user.role}</div>
          </div>
          {!isAdmin && (
            <>
              <button className="menu-item" role="menuitem" data-testid="menu-edit-profile" onClick={() => go("/profile")}>🪪 Edit Profile</button>
              <button className="menu-item" role="menuitem" data-testid="menu-preferences" onClick={() => go("/settings")}>⚙️ Preferences</button>
            </>
          )}
          {onSignOut && (
            <button className="menu-item" role="menuitem" data-testid="menu-signout"
                    onClick={() => { setOpen(false); onSignOut(); }}>↩ Sign out</button>
          )}
        </div>
      )}
    </div>
  );
}

// Breakpoint at which the sidebar auto-collapses (matches the CSS rule below).
const MOBILE_BREAKPOINT = 768;

// Shell matching the design mockups: topbar + role-aware sidebar.
export default function AppLayout({ user, children, onSwitchRole, ledGroupId }: { user: CurrentUser; children: React.ReactNode; onSwitchRole?: () => void; ledGroupId?: string }) {
  // Start collapsed if the viewport is already narrow (SSR-safe guard).
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== "undefined" && window.innerWidth < MOBILE_BREAKPOINT
  );

  // Auto-collapse / auto-expand as the viewport crosses the mobile breakpoint.
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    const handler = (e: MediaQueryListEvent) => setSidebarCollapsed(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  // Close the sidebar on mobile when the user navigates to a new page.
  const location = useLocation();
  useEffect(() => {
    if (window.innerWidth < MOBILE_BREAKPOINT) setSidebarCollapsed(true);
  }, [location.pathname]);
  const settings = useApi<any>("/settings");
  // Cache-buster bumped when a decision elsewhere changes a leader's pending
  // queues, so these independently-fetched nav pills refresh immediately (they
  // don't share the queue screens' state). See lib/navCounts.
  const [navNonce, setNavNonce] = useState(0);
  useEffect(() => onNavCountsRefresh(() => setNavNonce((n) => n + 1)), []);
  // Pending-work counts behind the nav indicators (and the bell line for
  // verifications, US-5.7 Option 2A). All are computed counts, fetched only for
  // the roles that actually own that queue — never stored notifications.
  const isLeader = user.role === "CommunityLeader" || user.role === "UserGroupLeader";
  const isUgl = user.role === "UserGroupLeader";
  const verifyApi = useApi<{ count: number }>(
    `/certifications/verifications?countOnly=true&_=${navNonce}`, isLeader);
  const verifyCount = isLeader ? verifyApi.data?.count ?? 0 : 0;
  // Pending contribution approvals — the service scopes a UGL's queue to their
  // led group, so the count is already the right one for this leader.
  const approvalsApi = useApi<{ count: number }>(
    `/contributions/approvals?countOnly=true&_=${navNonce}`, isLeader);
  // Pending join requests for the group a UGL leads (returns pending only).
  const joinApi = useApi<{ count: number; total?: number }>(
    `/groups/${ledGroupId}/requests?_=${navNonce}`, isUgl && !!ledGroupId);
  const badgeCounts: Record<NavBadge, number> = {
    certifications: verifyCount,
    contributions: isLeader ? approvalsApi.data?.count ?? 0 : 0,
    joinRequests: isUgl ? joinApi.data?.total ?? joinApi.data?.count ?? 0 : 0,
  };
  // What's New nav item is hidden portal-wide when the Admin disables the
  // feature (US-11.6) — Administrators never see it regardless (they don't
  // participate in community activities), same as navForRole already excludes it for them.
  const whatsNewEnabled = settings.data?.whatsNewEnabled !== false;
  const nav = navForRole(user.role).filter((n) => whatsNewEnabled || n.path !== "/whats-new");
  const groups = Array.from(new Set(nav.map((n) => n.group)));

  return (
    <>
      <div className="topbar">
        <button className="icon-btn" title="Toggle sidebar" data-testid="sidebar-toggle"
                aria-label="Toggle navigation sidebar"
                style={{ fontSize: 20, marginRight: 4 }}
                onClick={() => setSidebarCollapsed((v) => !v)}>
          ☰
        </button>
        <a className="brand" href="/">
          {settings.data?.logoUrl
            ? <img className="logo" src={settings.data.logoUrl} alt={settings.data?.communityName || "AWS Community Portal"} />
            : <span className="logo">D</span>}
          {" "}{settings.data?.communityName || "AWS Community Portal"}</a>
        <div className="spacer" />
        <div className="top-actions">
          <div className="role-pill" data-testid="role-pill">{user.role}</div>
          <UserMenu user={user} onSignOut={onSwitchRole} />
        </div>
      </div>

      <div className="layout">
        {/* Backdrop: tapping outside the sidebar closes it on mobile */}
        {!sidebarCollapsed && (
          <div className="sidebar-backdrop" aria-hidden="true"
               onClick={() => setSidebarCollapsed(true)} />
        )}
        <aside className={"sidebar" + (sidebarCollapsed ? " collapsed" : "")} data-testid="sidebar">
          {groups.map((g) => (
            <div className="nav-group" key={g}>
              {g !== "Main" && <h6>{g}</h6>}
              {nav.filter((n) => n.group === g).map((n) => (
                <NavLink key={n.path} to={n.path} end={n.path === "/"}
                         className={({ isActive }) => "nav-link" + (isActive ? " active" : "")}
                         data-testid={`nav-${n.label.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
                  <span className="ic">{n.icon}</span> {n.label}
                  {/* Pending-work indicator; hidden entirely at zero so the
                      sidebar stays quiet when there is nothing to review. */}
                  {n.badge && badgeCounts[n.badge] > 0 && (
                    <span className="pill"
                          title={`${badgeCounts[n.badge]} pending`}
                          data-testid={n.badge === "certifications" ? "nav-verify-pill" : `nav-pill-${n.badge}`}>
                      {badgeCounts[n.badge]}</span>)}
                </NavLink>
              ))}
            </div>
          ))}
        </aside>

        <main className="content">{children}</main>
      </div>
    </>
  );
}
