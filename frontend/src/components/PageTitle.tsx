/**
 * PageTitle — sets document.title based on the current route.
 * Rendered once inside AppLayout; updates on every navigation automatically.
 */
import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const SITE_NAME = "AWS Community Portal";

// Route path prefix → human-readable page title.
// More specific prefixes must come before their parent (e.g. /events/calendar before /events).
const ROUTE_TITLES: Array<[string | RegExp, string]> = [
  // Auth / home
  ["/", "Home"],
  // Events
  [/^\/events\/[^/]+\/manage/, "Manage Event"],
  [/^\/events\/[^/]+/, "Event Detail"],
  ["/events/calendar", "Event Calendar"],
  ["/events", "Events"],
  // Content Library
  ["/content-library", "Content Library"],
  // Forums
  [/^\/forums\/post\/[^/]+/, "Forum Thread"],
  [/^\/forums\/channel\/[^/]+/, "Forum Channel"],
  ["/forum-moderation", "Forum Moderation"],
  ["/forums", "Forums"],
  // Certifications
  ["/certifications", "Certifications"],
  // Contributions
  ["/scoring-framework", "Scoring Framework"],
  ["/contributions", "Contributions & Scoring"],
  // Groups
  [/^\/groups\/[^/]+/, "Group Detail"],
  ["/my-group", "My Group"],
  ["/groups", "User Groups"],
  // Directory
  [/^\/directory\/[^/]+/, "Member Profile"],
  ["/directory", "Member Directory"],
  // Other community
  ["/announcements", "Announcements"],
  ["/whats-new", "What's New in AWS"],
  ["/shoutouts", "Shoutouts"],
  // Account
  ["/profile", "My Profile"],
  ["/settings", "Preferences"],
  ["/file-sharing", "File Sharing"],
  // Admin
  ["/admin/email-templates", "Email Templates"],
  ["/admin/nightly-jobs", "Scheduled Jobs"],
  ["/admin/settings", "Admin Settings"],
  ["/admin/users", "User Management"],
];

function resolveTitle(pathname: string): string {
  // Exact "/" match first
  if (pathname === "/") return "Home";
  for (const [pattern, title] of ROUTE_TITLES) {
    if (pattern === "/") continue; // handled above
    if (typeof pattern === "string") {
      if (pathname === pattern || pathname.startsWith(pattern + "/")) return title;
    } else {
      if (pattern.test(pathname)) return title;
    }
  }
  return "";
}

export default function PageTitle() {
  const { pathname } = useLocation();

  useEffect(() => {
    const page = resolveTitle(pathname);
    document.title = page ? `${page} — ${SITE_NAME}` : SITE_NAME;
  }, [pathname]);

  return null; // renders nothing, side-effect only
}
