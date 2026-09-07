import { setAuthToken } from "./apiClient";
import type { Role } from "../roles";

// Per-tab session persistence (Option A, 2026-08-12). The auth token used to
// live only in React state + an in-memory apiClient variable, so a page reload
// or same-tab deep link started a fresh JS context and dropped the user to the
// login screen. We now persist the minimal session in **sessionStorage**:
//   - survives reload and same-tab navigation
//   - is per-tab and cleared when the tab closes (NOT written to disk, NOT shared
//     across tabs / browser restarts) — the conservative choice that keeps a
//     short-lived Cognito JWT off persistent storage and matches the "no
//     remember-me" stance. A 401 still forces a clean re-login.
// (New-tab / bookmark deep links remain a login → follow-up is the refresh-token
// silent-renewal flow, which needs Identity to expose a refresh token.)

export interface Session {
  token: string;
  role: Role;
  // UserGroupLeader only — the single group they lead (BR-G7).
  ledGroupId?: string;
  // Real name from the login response — used for avatar initials.
  firstName?: string;
  lastName?: string;
}

const KEY = "cp.session";

/** Parse the stored session WITHOUT touching the in-memory auth token.
 *
 *  Separate from `loadSession` because that function's token-priming side effect
 *  is wrong for any caller that is mid-update: reading in order to write a NEW
 *  token would re-install the OLD one as the active bearer on the way past. */
function readSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    if (!s || typeof s.token !== "string" || !s.role) return null;
    return s;
  } catch {
    return null;
  }
}

/** Restore the session from sessionStorage and prime the in-memory auth token
 *  so the first fetch after a reload is authenticated. Returns null when absent
 *  or malformed. */
export function loadSession(): Session | null {
  const s = readSession();
  if (s) setAuthToken(s.token);
  return s;
}

export function saveSession(s: Session): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* storage unavailable (private mode / disabled) — degrade to in-memory only */
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}

/** Replace the stored token, keeping the rest of the session as-is.
 *
 * Used after a mid-session ID-token refresh (group join/leave): the in-memory
 * bearer is updated by `refreshSession`, and this keeps the persisted copy in
 * step so a reload does not resurrect the pre-refresh token and its stale
 * group claims. A no-op when there is no stored session.
 *
 * Note what is NOT written here: the refresh token. It stays in memory only,
 * which is the whole reason `Session` has no field for it. */
export function updateSessionToken(token: string): Session | null {
  const current = readSession();
  if (!current) return null;
  const next = { ...current, token };
  saveSession(next);
  return next;
}
