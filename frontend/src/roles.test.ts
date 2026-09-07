import { describe, expect, it } from "vitest";

import { canHoldOwnCertifications } from "./roles";
import type { Role } from "./roles";

// Pins the role split that two components got wrong. DashboardPage and
// VerifiedBadgesCard both called /certifications/claims/me unconditionally,
// which the API refuses with 403 for a CommunityLeader — a guaranteed failed
// request and console error on every dashboard and profile load.
//
// The split is not arbitrary: in the certifications permission matrix, Member
// and UserGroupLeader carry `submit certification-claim`,
// `view own-certification-submission` and `display badge`. CommunityLeader
// carries none of them (it is a verifier, not a claimant) and Administrator is
// not a community participant. If that matrix changes, this test should be the
// thing that notices.
describe("canHoldOwnCertifications", () => {
  it.each<Role>(["Member", "UserGroupLeader"])("allows %s", (role) => {
    expect(canHoldOwnCertifications(role)).toBe(true);
  });

  it.each<Role>(["CommunityLeader", "Administrator"])("excludes %s", (role) => {
    expect(canHoldOwnCertifications(role)).toBe(false);
  });

  it("covers every role in the union exactly once", () => {
    const all: Role[] = ["Administrator", "CommunityLeader", "UserGroupLeader", "Member"];
    const allowed = all.filter(canHoldOwnCertifications);
    // Exactly the two claimant roles — guards against a new role silently
    // defaulting to "allowed" and reintroducing the 403.
    expect(allowed.sort()).toEqual(["Member", "UserGroupLeader"]);
  });
});
