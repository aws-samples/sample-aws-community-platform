// Role model (mutually exclusive) — drives role-aware navigation (US-1.12).
export type Role = "Administrator" | "CommunityLeader" | "UserGroupLeader" | "Member";

export interface CurrentUser {
  name: string;
  initials: string;
  role: Role;
}

/** Whether this role can hold certification claims of its OWN.
 *
 * Only Member and UserGroupLeader carry `submit certification-claim`,
 * `view own-certification-submission` and `display badge` in the permission
 * matrix. A CommunityLeader is a verifier, not a claimant, and an Administrator
 * is not a community participant — so for them the API correctly refuses
 * /certifications/claims/me with 403.
 *
 * Exists because two components called that endpoint unconditionally, producing
 * a guaranteed 403 and a console error on every dashboard and profile load for a
 * CommunityLeader. The displayed result was already 0/empty, so gating the call
 * changes nothing a user sees — it just stops asking a question the server is
 * always going to refuse, and stops that noise masking a real 403.
 */
export function canHoldOwnCertifications(role: Role): boolean {
  return role === "Member" || role === "UserGroupLeader";
}

// Pending-work indicators on nav items. The nav declares WHICH counter an item
// shows; AppLayout owns fetching the counts (one place, role-gated) so a new
// badge never means a new fetch scattered through the tree.
export type NavBadge = "contributions" | "certifications" | "joinRequests";

export interface NavItem {
  label: string;
  path: string;
  icon: string;
  group: "Main" | "Manage" | "Review Queue" | "Community" | "Account" | "Admin" | "Engage" | "My Journey" | "Discover";
  badge?: NavBadge;
}

// Nav per role, mirroring the design mockups' sidebars.
const MEMBER_NAV: NavItem[] = [
  { label: "Home", path: "/", icon: "🏠", group: "Main" },
  // ENGAGE — interactive/social items: things a member does with others.
  { label: "Events", path: "/events", icon: "📅", group: "Engage" },
  { label: "Forums", path: "/forums", icon: "💬", group: "Engage" },
  { label: "User Groups", path: "/groups", icon: "👥", group: "Engage" },
  // MY JOURNEY — personal tracking and identity: progress and profile.
  { label: "Certifications", path: "/certifications", icon: "🎓", group: "My Journey" },
  { label: "My Contributions", path: "/contributions", icon: "🏆", group: "My Journey" },
  { label: "My Profile", path: "/profile", icon: "🪪", group: "My Journey" },
  // DISCOVER — browsing/exploration: things a member reads or explores passively.
  { label: "Member Directory", path: "/directory", icon: "📇", group: "Discover" },
  { label: "Content Library", path: "/content-library", icon: "📚", group: "Discover" },
  { label: "What's New in AWS", path: "/whats-new", icon: "🆕", group: "Discover" },
  // Preferences (/settings) now lives in the top-right profile menu, not the sidebar.
];

// Community Leader. Split into what the leader OPERATES (Manage) versus what
// they consume alongside everyone else (Community), so the community-wide
// configuration surfaces sit together. Manages the whole user-group directory,
// so "User Groups" (the list of every group) is the right entry point.
//
// Group headers render in first-appearance order (see AppLayout), so item order
// here IS the sidebar order: Main -> Manage -> Community -> Account.
const CL_NAV: NavItem[] = [
  { label: "Community Dashboard", path: "/", icon: "📊", group: "Main" },
  { label: "User Groups", path: "/groups", icon: "👥", group: "Manage" },
  { label: "Events", path: "/events", icon: "📅", group: "Manage" },
  { label: "Forums", path: "/forums", icon: "💬", group: "Manage" },
  // Community-wide scoring configuration (US-6.1/6.2, BR-F6 — CL-only to edit).
  // Its own route rather than /contributions?tab=framework so sidebar
  // highlighting can tell the two entries apart.
  { label: "Scoring Framework", path: "/scoring-framework", icon: "🎯", group: "Manage" },
  // Same pending-work indicators as the UGL sidebar — a Community Leader owns
  // these queues community-wide (the services scope each count by role).
  { label: "Certifications", path: "/certifications", icon: "🎓", group: "Manage", badge: "certifications" },
  { label: "Contributions", path: "/contributions", icon: "🏆", group: "Manage", badge: "contributions" },
  { label: "Member Directory", path: "/directory", icon: "📇", group: "Community" },
  { label: "Announcements", path: "/announcements", icon: "📣", group: "Community" },
  { label: "Content Library", path: "/content-library", icon: "📚", group: "Community" },
  { label: "What's New in AWS", path: "/whats-new", icon: "🆕", group: "Community" }, // US-11.2 (CL/UGL/Member)
  { label: "File Sharing", path: "/file-sharing", icon: "🔗", group: "Account" }, // US-8.13 — dedicated screen (CL/UGL)
  { label: "My Profile", path: "/profile", icon: "🪪", group: "Account" }, // self-profile view/edit (GET/PUT /members/me works for all roles)
  // On-demand nightly jobs (community-wide rollups/tiers). CL is a community-wide
  // operator; backend authZ permits Administrator + CommunityLeader.
  { label: "Scheduled Jobs", path: "/admin/nightly-jobs", icon: "🌙", group: "Account" },
  // Preferences (/settings) now lives in the top-right profile menu, not the sidebar.
];

// User Group Leader. Organised around the job rather than mirroring the CL
// sidebar: a UGL's day is "what needs my review?" first, then the group they
// run. A UGL leads exactly one group (US-1.12/BR-G7) and cannot edit group
// configuration (US-1.18), so the entry point is "My Group" (the group they
// lead) rather than a directory of every group.
//
// The three Review Queue / My Group badges surface pending work without making
// the leader open each screen to discover it.
const UGL_NAV: NavItem[] = [
  { label: "Group Dashboard", path: "/", icon: "📊", group: "Main" },
  // Review Queue — approvals/verification work owned by this leader.
  { label: "Contributions", path: "/contributions", icon: "🏆", group: "Review Queue", badge: "contributions" },
  { label: "Certifications", path: "/certifications", icon: "🎓", group: "Review Queue", badge: "certifications" },
  // Menu entry only — Forum Moderation lands with the Forums module.
  { label: "Forum Moderation", path: "/forum-moderation", icon: "🛡️", group: "Review Queue" },
  { label: "My Group", path: "/my-group", icon: "👥", group: "Community", badge: "joinRequests" },
  { label: "Member Directory", path: "/directory", icon: "📇", group: "Community" },
  { label: "Announcements", path: "/announcements", icon: "📣", group: "Community" },
  { label: "Events", path: "/events", icon: "📅", group: "Community" },
  { label: "Forums", path: "/forums", icon: "💬", group: "Community" },
  { label: "Content Library", path: "/content-library", icon: "📚", group: "Community" },
  { label: "What's New in AWS", path: "/whats-new", icon: "🆕", group: "Community" }, // US-11.2 (CL/UGL/Member)
  { label: "File Sharing", path: "/file-sharing", icon: "🔗", group: "Account" }, // US-8.13 (CL/UGL)
  { label: "My Profile", path: "/profile", icon: "🪪", group: "Account" }, // self-profile view/edit (GET/PUT /members/me works for all roles)
  // Preferences (/settings) lives in the top-right profile menu, not the sidebar.
];

const ADMIN_NAV: NavItem[] = [
  { label: "Users", path: "/admin/users", icon: "👤", group: "Admin" },
  { label: "Settings", path: "/admin/settings", icon: "⚙️", group: "Admin" },
  { label: "Email Templates", path: "/admin/email-templates", icon: "✉️", group: "Admin" },
  { label: "Scheduled Jobs", path: "/admin/nightly-jobs", icon: "🌙", group: "Admin" },
];

export function navForRole(role: Role): NavItem[] {
  if (role === "Administrator") return ADMIN_NAV;
  if (role === "Member") return MEMBER_NAV;
  if (role === "UserGroupLeader") return UGL_NAV;
  return CL_NAV;
}
