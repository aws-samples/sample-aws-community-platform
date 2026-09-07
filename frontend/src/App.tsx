import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import DashboardPage from "./features/DashboardPage";
import EventsPage from "./features/EventsPage";
import EventDetailPage from "./features/EventDetailPage";
import EventManagePage from "./features/EventManagePage";
import EventCalendarPage from "./features/EventCalendarPage";
import ContentLibraryPage from "./features/ContentLibraryPage";
import { ComingSoon } from "./components/States";
import {
  AnnouncementsPage, DirectoryPage, GroupsPage,
} from "./features/pages";
import ForumsPage from "./features/ForumsPage";
import ForumChannelPage from "./features/ForumChannelPage";
import ForumThreadPage from "./features/ForumThreadPage";
import ForumModerationPage from "./features/ForumModerationPage";
import GroupDetailPage from "./features/GroupDetailPage";
import MyGroupPage from "./features/MyGroupPage";
import MemberDetailPage from "./features/MemberDetailPage";
import ContributionsPage from "./features/ContributionsPage";
import UglDashboardPage from "./features/UglDashboardPage";
import CLDashboardPage from "./features/CLDashboardPage";
import CertificationsPage from "./features/CertificationsPage";
import { FileSharingPage, ProfilePage, SettingsPage } from "./features/singletons";
import { WhatsNewPage } from "./features/whats-new";
import { AdminUsersPage, AdminSettingsPage, EmailTemplatesPage } from "./features/admin";
import AdminNightlyJobsPage from "./features/AdminNightlyJobsPage";
import ShoutoutsPage from "./features/ShoutoutsPage";
import AuthScreen from "./features/AuthScreen";
import { setAuthToken, setRefreshToken, setSessionExpiredHandler } from "./lib/apiClient";
import { useTheme } from "./lib/useTheme";
import PageTitle from "./components/PageTitle";
import { type Session, clearSession, loadSession, saveSession } from "./lib/session";
import type { CurrentUser, Role } from "./roles";

// Display name/initials are placeholders until the profile endpoint is wired;
// the role and session token come from the real Identity & Access login (US-1.2/1.32).
const DISPLAY: Record<Role, Pick<CurrentUser, "name" | "initials">> = {
  Member: { name: "Member", initials: "ME" },
  CommunityLeader: { name: "Community Leader", initials: "CL" },
  UserGroupLeader: { name: "User Group Leader", initials: "UG" },
  Administrator: { name: "Administrator", initials: "AD" },
};

// Auth gate: unauthenticated users see the real AuthScreen (US-1.2 login,
// US-1.32 OTP, US-1.30 self-registration). On sign-in the API-issued role
// drives role-aware nav + RBAC-style gating. "Switch role" logs out (US-1.3).
export default function App() {
  // Apply persisted theme (light/dark) immediately — must be before any render.
  useTheme();

  // Restore a persisted session on load (sessionStorage) so a reload / same-tab
  // deep link stays signed in; the initializer also primes the in-memory auth
  // token before any child fetch runs.
  const [session, setSession] = useState<Session | null>(() => loadSession());
  const [expired, setExpired] = useState(false);
  const navigate = useNavigate();

  // Any 401 from the API (expired Cognito token) drops back to sign-in with
  // a clear message instead of per-page fetch errors.
  useEffect(() => {
    setSessionExpiredHandler(() => {
      setAuthToken(null);
      setRefreshToken(null);
      clearSession();
      setSession(null);
      setExpired(true);
      navigate("/", { replace: true });
    });
    return () => setSessionExpiredHandler(null);
  }, [navigate]);

  if (!session) {
    return (
      <>
        {expired && (
          <div className="card" role="alert" style={{ maxWidth: 460, margin: "24px auto 0", padding: "10px 14px", background: "var(--warning-bg)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="small">Your session expired. Please sign in again.</span>
            <button className="icon-btn" aria-label="Dismiss" onClick={() => setExpired(false)}>✕</button>
          </div>
        )}
        {/* Land every fresh session on the role's own landing page ("/"), never
            on whatever URL the previous session left behind (e.g. an Admin's
            /admin/users lingering into a Community Leader login). */}
        <AuthScreen onSignedIn={(s) => { setExpired(false); saveSession(s); setSession(s); navigate("/", { replace: true }); }} />
      </>
    );
  }
  const role = session.role;
  // Derive initials from real name stored in session (firstName + lastName).
  // Falls back to role-based placeholder if name is absent (e.g. older sessions).
  const sessionInitials = (() => {
    const f = (session.firstName || "").trim();
    const l = (session.lastName || "").trim();
    if (f && l) return (f[0] + l[0]).toUpperCase();
    if (f) return f.slice(0, 2).toUpperCase();
    return DISPLAY[role].initials;
  })();
  const sessionName = session.firstName && session.lastName
    ? `${session.firstName} ${session.lastName}`
    : DISPLAY[role].name;
  const user: CurrentUser = { name: sessionName, initials: sessionInitials, role };

  const logout = () => {
    setAuthToken(null);
    // Dropped on the way out too: leaving a refresh token in memory would let a
    // subsequent refresh mint a working bearer for the user who just signed out.
    setRefreshToken(null);
    clearSession();
    setSession(null);
    navigate("/", { replace: true });
  };

  // Client-side route guard (US-1.12): admin screens are Administrator-only.
  // Non-admins deep-linking (or landing on a stale URL) get their own landing
  // page instead of a permission error. Backend authZ still enforces for real.
  const adminOnly = (el: React.ReactElement) =>
    role === "Administrator" ? el : <Navigate to="/" replace />;
  const leaderOnly = (el: React.ReactElement) =>
    role === "CommunityLeader" || role === "UserGroupLeader" ? el : <Navigate to="/" replace />;
  // My Group is scoped to the single group a UGL leads; every other role reaches
  // groups through /groups instead.
  const uglOnly = (el: React.ReactElement) =>
    role === "UserGroupLeader" ? el : <Navigate to="/groups" replace />;

  // Nightly Jobs: Administrators and Community Leaders (community-wide operators).
  const adminOrCL = (el: React.ReactElement) =>
    role === "Administrator" || role === "CommunityLeader" ? el : <Navigate to="/" replace />;

  return (
    <AppLayout user={user} onSwitchRole={logout} ledGroupId={session.ledGroupId}>
      <PageTitle />
      <Routes>
        {/* Landing page per role: Admins land on Settings (the Users table uses
            OpenSearch which needs a warm-up query fired on Settings mount before
            the admin navigates there). UGL gets their group dashboard (US-7.2),
            everyone else the member/CL home. */}
        <Route path="/" element={
          role === "Administrator" ? <AdminSettingsPage />
            : role === "UserGroupLeader" ? <UglDashboardPage ledGroupId={session.ledGroupId} />
              : role === "CommunityLeader" ? <CLDashboardPage />
                : <DashboardPage user={user} />} />
        {/* ledGroupId reaches the event screens so a UGL's create/edit modal can
            scope to their led group — without it every UGL save was a 403. */}
        <Route path="/events" element={<EventsPage role={role} ledGroupId={session.ledGroupId} />} />
        {/* Literal path before the templated one, or /events/calendar
            would be captured as an event id. */}
        <Route path="/events/calendar" element={<EventCalendarPage role={role} />} />
        <Route path="/events/:id" element={<EventDetailPage role={role} />} />
        <Route path="/events/:id/manage" element={<EventManagePage role={role} ledGroupId={session.ledGroupId} />} />
        {/* Content Library — standalone page (US-2.20 rework), hidden from Admins */}
        {role !== "Administrator" && (
          <Route path="/content-library" element={<ContentLibraryPage role={role} />} />
        )}
        <Route path="/forums" element={<ForumsPage role={role} ledGroupId={session.ledGroupId} />} />
        <Route path="/forums/channel/:id" element={<ForumChannelPage role={role} />} />
        <Route path="/forums/post/:id" element={<ForumThreadPage role={role} />} />
        <Route path="/certifications" element={<CertificationsPage role={role} ledGroupId={session.ledGroupId} />} />
        {/* ledGroupId scopes a UGL's leaderboard to the group they LEAD — a
            leader is not a member of it, so it cannot be derived from
            /contributions/me's membership list. */}
        <Route path="/contributions" element={<ContributionsPage role={role} ledGroupId={session.ledGroupId} />} />
        {/* CL sidebar "Scoring Framework" (Manage group). Same screen as
            /contributions, landing on the framework tab — a distinct path so the
            sidebar can highlight one entry at a time. Leader-only: a UGL sees it
            read-only (BR-F6), members never configure the framework. */}
        <Route path="/scoring-framework" element={leaderOnly(
          <ContributionsPage role={role} ledGroupId={session.ledGroupId} variant="framework" />)} />
        {/* Review Queue > Forum Moderation — nav entry exists now; the screen
            lands with the Forums module, so this is a deliberate placeholder. */}
        <Route path="/forum-moderation" element={leaderOnly(<ForumModerationPage role={role} />)} />
        {/* UGL entry point (replaces "User Groups" in their sidebar). The URL
            stays /my-group so nav highlighting works and the screen never
            depends on a group id in the address bar. */}
        <Route path="/my-group" element={uglOnly(<MyGroupPage ledGroupId={session.ledGroupId} />)} />
        <Route path="/groups" element={<GroupsPage role={role} />} />
        <Route path="/groups/:id" element={<GroupDetailPage role={role} />} />
        <Route path="/directory" element={<DirectoryPage role={role} />} />
        <Route path="/directory/:id" element={<MemberDetailPage role={role} />} />
        <Route path="/announcements" element={<AnnouncementsPage role={role} ledGroupId={session.ledGroupId} />} />
        <Route path="/whats-new" element={<WhatsNewPage />} />
        <Route path="/shoutouts" element={<ShoutoutsPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/file-sharing" element={leaderOnly(<FileSharingPage role={role} />)} />
        <Route path="/admin/users" element={adminOnly(<AdminUsersPage />)} />
        <Route path="/admin/settings" element={adminOnly(<AdminSettingsPage />)} />
        <Route path="/admin/email-templates" element={adminOnly(<EmailTemplatesPage />)} />
        <Route path="/admin/nightly-jobs" element={adminOrCL(<AdminNightlyJobsPage />)} />
        <Route path="*" element={<ComingSoon feature="This page" />} />
      </Routes>
    </AppLayout>
  );
}
