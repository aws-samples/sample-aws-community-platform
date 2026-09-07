import { refreshSession } from "./apiClient";
import { updateSessionToken } from "./session";

// Re-mint the ID token after a change to the caller's own group membership.
//
// Why this is needed at all: group membership is carried in the ID token as the
// `member_group_ids` claim, stamped by Cognito's pre-token-generation trigger at
// issuance. The server reads that claim to decide what a Member may see — the
// member directory and the event ideas feed are both scoped by it. So joining a
// group updates the database but NOT the token in the browser, and the member
// keeps being told they are not in the group they just joined. Refreshing the
// token re-runs the trigger and picks up the new membership.
//
// Deliberately fire-and-forget and deliberately silent:
//
//   - It NEVER throws. `refreshSession` swallows its own failures and returns
//     null. A join that succeeded must not surface an error because the optional
//     token refresh behind it did not.
//   - It is a NO-OP when no refresh token is held: after a page reload (the token
//     is memory-only by design) and for every OTP-gated sign-in (no refresh token
//     is issued on that path). Those users keep the membership their current token
//     has until they sign in again, which is what the "sign out and back in" hint
//     in the empty states is for.
//
// It also does not fix membership changed by SOMEONE ELSE — a leader approving a
// join request, or an admin assigning groups. The affected member is not in the
// browser when that happens, so nothing here can run for them.
export async function refreshMembershipClaims(): Promise<void> {
  const token = await refreshSession();
  // Keep the persisted copy in step with the in-memory bearer that
  // `refreshSession` already installed, so a reload does not resurrect the
  // pre-refresh token and its stale claims.
  if (token) updateSessionToken(token);
}
