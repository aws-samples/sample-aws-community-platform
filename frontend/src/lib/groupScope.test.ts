import { describe, expect, it } from "vitest";
import { groupFilterOptions, type ScopedGroup } from "./groupScope";

// A Member must not be offered a group they are not in: the server scopes both the
// member directory and the event ideas feed by group membership, so such an option
// could only ever produce a 403.

const GROUPS: ScopedGroup[] = [
  { id: "g-joined", name: "Joined", myState: "member" },
  { id: "g-pending", name: "Pending", myState: "requested" },
  { id: "g-open", name: "Not joined" },              // myState absent
  { id: "g-null", name: "Explicit null", myState: null },
  { id: "g-also-joined", name: "Also joined", myState: "member" },
];

describe("groupFilterOptions", () => {
  it("keeps only groups a Member actually belongs to", () => {
    expect(groupFilterOptions(GROUPS, "Member").map((g) => g.id))
      .toEqual(["g-joined", "g-also-joined"]);
  });

  it("excludes a group with a PENDING join request", () => {
    // The regression this guards: `myState` is truthy for "requested" too, so a
    // truthiness check would offer a group the member has merely asked to join and
    // has no access to. Access begins at approval, not at request.
    expect(groupFilterOptions(GROUPS, "Member").map((g) => g.id))
      .not.toContain("g-pending");
  });

  it("returns everything for a Community Leader", () => {
    expect(groupFilterOptions(GROUPS, "CommunityLeader")).toHaveLength(GROUPS.length);
  });

  it("returns everything for a User Group Leader", () => {
    // Explicitly unchanged: a UGL keeps the directory-wide view they already had.
    expect(groupFilterOptions(GROUPS, "UserGroupLeader")).toHaveLength(GROUPS.length);
  });

  it("returns everything for an Administrator", () => {
    expect(groupFilterOptions(GROUPS, "Administrator")).toHaveLength(GROUPS.length);
  });

  it("does not narrow when the role is unknown", () => {
    // Only the Member role is scoped server-side, so an absent role must not be
    // treated as Member — that would empty the dropdown on any screen that omits it.
    expect(groupFilterOptions(GROUPS, undefined)).toHaveLength(GROUPS.length);
  });

  it("yields an empty list for a Member in no groups", () => {
    const none: ScopedGroup[] = [{ id: "g-open", myState: null }];
    expect(groupFilterOptions(none, "Member")).toEqual([]);
  });

  it("does not mutate the input", () => {
    const input = [...GROUPS];
    groupFilterOptions(input, "Member");
    expect(input).toEqual(GROUPS);
  });
});
