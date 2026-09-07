import { describe, expect, it } from "vitest";
import {
  CANDIDATE_LIMIT,
  LEADER_ROLE,
  assembleCandidates,
  buildLeaderQuery,
} from "./leaderPicker";

const ugl = (id: string, first = "U", last = id) =>
  ({ id, firstName: first, lastName: last, email: `${id}@x.com`, role: LEADER_ROLE });

describe("buildLeaderQuery", () => {
  it("always filters by the UserGroupLeader role server-side", () => {
    const params = new URL(`https://x${buildLeaderQuery("")}`).searchParams;
    expect(params.get("role")).toBe("UserGroupLeader");
  });

  it("always sends limit, which is what selects the indexed path", () => {
    // Not cosmetic: without `limit` the directory endpoint takes its unpaged
    // full-scan branch, which returned HTTP 502 after ~28 s at 25k members.
    for (const term of ["", "load", "  "]) {
      const params = new URL(`https://x${buildLeaderQuery(term)}`).searchParams;
      expect(params.get("limit")).toBe(String(CANDIDATE_LIMIT));
    }
  });

  it("passes the search term through as q, trimmed", () => {
    const params = new URL(`https://x${buildLeaderQuery("  ravi  ")}`).searchParams;
    expect(params.get("q")).toBe("ravi");
  });

  it("omits q entirely when the term is blank", () => {
    // A blank q must not become a match on the empty string — the unsearched
    // state is a plain role-filtered page.
    for (const blank of ["", "   ", "\t"]) {
      const params = new URL(`https://x${buildLeaderQuery(blank)}`).searchParams;
      expect(params.has("q")).toBe(false);
    }
  });

  it("encodes terms that would otherwise break the query string", () => {
    const q = new URL(`https://x${buildLeaderQuery("a&b=c d+e")}`).searchParams.get("q");
    expect(q).toBe("a&b=c d+e");
  });

  it("targets /members, the endpoint a Community Leader is allowed to call", () => {
    // GET /users?role=… is Administrator-only (list/admin-member-list), so a CL
    // would be refused there.
    expect(buildLeaderQuery("x").startsWith("/members?")).toBe(true);
  });
});

describe("assembleCandidates", () => {
  it("returns the search hits when creating a group with none assigned", () => {
    const out = assembleCandidates({ hits: [ugl("a"), ugl("b")], allGroups: [] });
    expect(out.map((c) => c.id)).toEqual(["a", "b"]);
  });

  it("excludes UserGroupLeaders who already lead another group (BR-G7)", () => {
    const out = assembleCandidates({
      hits: [ugl("a"), ugl("busy"), ugl("b")],
      allGroups: [{ id: "g-1", leaderIds: ["busy"] }],
    });
    expect(out.map((c) => c.id)).toEqual(["a", "b"]);
  });

  it("does not exclude the edited group's own leaders as 'assigned elsewhere'", () => {
    const out = assembleCandidates({
      hits: [ugl("mine"), ugl("free")],
      currentLeaderIds: ["mine"],
      groupLeaders: [ugl("mine")],
      allGroups: [{ id: "g-1", leaderIds: ["mine"] }],
      editingGroupId: "g-1",
    });
    expect(out.map((c) => c.id)).toEqual(["mine", "free"]);
  });

  it("pins current leaders first and keeps them even when the search misses them", () => {
    // The regression this guards: a server-side search can legitimately exclude a
    // current leader (outside the page, or not matching the term). If the form
    // then renders it unchecked-and-absent, saving silently drops that leader.
    const out = assembleCandidates({
      hits: [ugl("stranger")],
      currentLeaderIds: ["mine"],
      groupLeaders: [ugl("mine")],
      allGroups: [{ id: "g-1", leaderIds: ["mine"] }],
      editingGroupId: "g-1",
    });
    expect(out.map((c) => c.id)).toEqual(["mine", "stranger"]);
  });

  it("does not list a pinned leader twice when the search also returns them", () => {
    const out = assembleCandidates({
      hits: [ugl("mine"), ugl("other")],
      currentLeaderIds: ["mine"],
      groupLeaders: [ugl("mine")],
      editingGroupId: "g-1",
      allGroups: [{ id: "g-1", leaderIds: ["mine"] }],
    });
    expect(out.map((c) => c.id)).toEqual(["mine", "other"]);
  });

  it("ignores stale group leaders no longer in currentLeaderIds", () => {
    // The leader was unchecked in this session: it must not reappear pinned.
    const out = assembleCandidates({
      hits: [ugl("free")],
      currentLeaderIds: [],
      groupLeaders: [ugl("removed")],
      editingGroupId: "g-1",
      allGroups: [{ id: "g-1", leaderIds: ["removed"] }],
    });
    expect(out.map((c) => c.id)).toEqual(["free"]);
  });

  it("excludes leaders of several other groups at once", () => {
    const out = assembleCandidates({
      hits: [ugl("a"), ugl("b1"), ugl("b2"), ugl("c")],
      allGroups: [{ id: "g-1", leaderIds: ["b1"] }, { id: "g-2", leaderIds: ["b2"] }],
    });
    expect(out.map((c) => c.id)).toEqual(["a", "c"]);
  });

  it("copes with groups that have no leaderIds and with no groups loaded yet", () => {
    // groupsApi may still be in flight on first render.
    expect(assembleCandidates({ hits: [ugl("a")] }).map((c) => c.id)).toEqual(["a"]);
    expect(assembleCandidates({
      hits: [ugl("a")], allGroups: [{ id: "g-1" }],
    }).map((c) => c.id)).toEqual(["a"]);
  });

  it("returns nothing when every candidate is committed elsewhere", () => {
    const out = assembleCandidates({
      hits: [ugl("busy")],
      allGroups: [{ id: "g-1", leaderIds: ["busy"] }],
    });
    expect(out).toEqual([]);
  });
});
