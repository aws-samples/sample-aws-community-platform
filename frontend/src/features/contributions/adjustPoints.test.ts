import { describe, expect, it } from "vitest";
import {
  DELTA_LIMIT,
  groupOptionsFor,
  parseSignedDelta,
  quarterTotal,
  reversedIdsOf,
  sanitizeDeltaInput,
} from "./adjustPoints";

describe("parseSignedDelta", () => {
  it("accepts an explicit positive sign", () => {
    expect(parseSignedDelta("+10")).toEqual({ ok: true, value: 10 });
  });

  it("accepts an explicit negative sign", () => {
    expect(parseSignedDelta("-5")).toEqual({ ok: true, value: -5 });
  });

  it("returns a NUMBER, not a string", () => {
    // Regression pin for the defect this rework fixes: the old screen submitted
    // the string "10" through FormModal, and the server's require_int rejected
    // every adjustment with a 400. If this ever becomes a string again, the
    // screen silently stops working for every leader.
    const parsed = parseSignedDelta("+10");
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(typeof parsed.value).toBe("number");
    expect(JSON.stringify({ delta: parsed.value })).toBe('{"delta":10}');
  });

  it("rejects a bare number because the sign is mandatory", () => {
    const parsed = parseSignedDelta("10");
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.reason).toMatch(/\+/);
  });

  it("tolerates surrounding whitespace", () => {
    expect(parseSignedDelta("  +7  ")).toEqual({ ok: true, value: 7 });
  });

  it.each(["0", "+0", "-0"])("rejects zero (%s)", (raw) => {
    const parsed = parseSignedDelta(raw);
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    // "0" fails the sign rule; "+0"/"-0" must fail the non-zero rule.
    if (raw !== "0") expect(parsed.reason).toMatch(/zero/i);
  });

  it("rejects a magnitude above the server bound", () => {
    expect(parseSignedDelta(`+${DELTA_LIMIT + 1}`).ok).toBe(false);
    expect(parseSignedDelta(`-${DELTA_LIMIT + 1}`).ok).toBe(false);
  });

  it("accepts the bound itself", () => {
    expect(parseSignedDelta(`+${DELTA_LIMIT}`)).toEqual({ ok: true, value: DELTA_LIMIT });
  });

  it.each(["", "   ", "+", "-", "+1.5", "-2.0", "+1e3", "++1", "1-", "+ 1", "abc", "+10abc"])(
    "rejects malformed input (%s)",
    (raw) => {
      expect(parseSignedDelta(raw).ok).toBe(false);
    },
  );

  it("rejects null and undefined", () => {
    expect(parseSignedDelta(null).ok).toBe(false);
    expect(parseSignedDelta(undefined).ok).toBe(false);
  });
});

describe("sanitizeDeltaInput", () => {
  it("keeps a sign in the first position and digits after it", () => {
    expect(sanitizeDeltaInput("+10")).toBe("+10");
    expect(sanitizeDeltaInput("-25")).toBe("-25");
  });

  it("drops letters and symbols", () => {
    expect(sanitizeDeltaInput("+1a0!")).toBe("+10");
    expect(sanitizeDeltaInput("abc")).toBe("");
  });

  it("drops a sign that is not in the first position", () => {
    expect(sanitizeDeltaInput("1+0")).toBe("10");
    expect(sanitizeDeltaInput("+1-0")).toBe("+10");
  });

  it("keeps a lone sign so the field can be typed into progressively", () => {
    expect(sanitizeDeltaInput("+")).toBe("+");
    expect(sanitizeDeltaInput("-")).toBe("-");
  });

  it("does not clamp magnitude — the bound is explained, not silently applied", () => {
    // Rewriting the number would change what the leader typed without saying so;
    // parseSignedDelta rejects it with a message instead.
    expect(sanitizeDeltaInput("+999999999")).toBe("+999999999");
  });

  it("handles null and undefined", () => {
    expect(sanitizeDeltaInput(null)).toBe("");
    expect(sanitizeDeltaInput(undefined)).toBe("");
  });
});

describe("groupOptionsFor", () => {
  const allGroups = [
    { id: "g-serverless", name: "Serverless" },
    { id: "g-ai", name: "AI & ML" },
    { id: "g-data", name: "Data" },
  ];

  it("gives a Community Leader every group the member belongs to", () => {
    const opts = groupOptionsFor({
      memberGroupIds: ["g-serverless", "g-ai"],
      allGroups,
      role: "CommunityLeader",
    });
    expect(opts).toEqual([
      { value: "g-ai", label: "AI & ML" },
      { value: "g-serverless", label: "Serverless" },
    ]);
  });

  it("narrows a User Group Leader to the group they lead (DR-1)", () => {
    const opts = groupOptionsFor({
      memberGroupIds: ["g-serverless", "g-ai", "g-data"],
      allGroups,
      role: "UserGroupLeader",
      ledGroupId: "g-ai",
    });
    // The member's other groups are omitted: selecting one would be a
    // guaranteed 403 from the server (BR-A5).
    expect(opts).toEqual([{ value: "g-ai", label: "AI & ML" }]);
  });

  it("gives a UGL nothing when the member is not in their group", () => {
    expect(groupOptionsFor({
      memberGroupIds: ["g-serverless"],
      allGroups,
      role: "UserGroupLeader",
      ledGroupId: "g-ai",
    })).toEqual([]);
  });

  it("gives a UGL with no led group nothing", () => {
    expect(groupOptionsFor({
      memberGroupIds: ["g-serverless"],
      allGroups,
      role: "UserGroupLeader",
    })).toEqual([]);
  });

  it("returns an empty list for a member in no group (feeds the FR-6 block)", () => {
    expect(groupOptionsFor({ memberGroupIds: [], allGroups, role: "CommunityLeader" })).toEqual([]);
  });

  it("never leaks a raw group id as a label", () => {
    const opts = groupOptionsFor({
      memberGroupIds: ["g-unknown"],
      allGroups,
      role: "CommunityLeader",
    });
    expect(opts).toEqual([{ value: "g-unknown", label: "Unnamed group" }]);
    expect(opts[0].label).not.toContain("g-");
  });

  it("de-duplicates repeated memberships and ignores blanks", () => {
    const opts = groupOptionsFor({
      memberGroupIds: ["g-ai", "g-ai", "", "g-data"],
      allGroups,
      role: "CommunityLeader",
    });
    expect(opts.map((o) => o.value)).toEqual(["g-ai", "g-data"]);
  });

  it("sorts by label so the order is predictable", () => {
    const opts = groupOptionsFor({
      memberGroupIds: ["g-serverless", "g-data", "g-ai"],
      allGroups,
      role: "CommunityLeader",
    });
    expect(opts.map((o) => o.label)).toEqual(["AI & ML", "Data", "Serverless"]);
  });
});

describe("quarterTotal", () => {
  const entries = [
    { id: "l1", groupId: "g-ai", quarter: "2026-Q3", points: 10 },
    { id: "l2", groupId: "g-ai", quarter: "2026-Q3", points: 5 },
    { id: "l3", groupId: "g-ai", quarter: "2026-Q2", points: 100 },
    { id: "l4", groupId: "g-data", quarter: "2026-Q3", points: 50 },
  ];

  it("sums only the matching group and quarter", () => {
    expect(quarterTotal(entries, "g-ai", "2026-Q3")).toBe(15);
  });

  it("includes negative entries and can produce a negative total (BR-J3)", () => {
    const withAdjustment = [...entries, { id: "l5", groupId: "g-ai", quarter: "2026-Q3", points: -40 }];
    expect(quarterTotal(withAdjustment, "g-ai", "2026-Q3")).toBe(-25);
  });

  it("returns 0 when nothing matches", () => {
    expect(quarterTotal(entries, "g-ai", "2025-Q1")).toBe(0);
    expect(quarterTotal([], "g-ai", "2026-Q3")).toBe(0);
  });

  it("coerces numeric strings and ignores unusable values", () => {
    const messy = [
      { id: "l1", groupId: "g-ai", quarter: "2026-Q3", points: "7" },
      { id: "l2", groupId: "g-ai", quarter: "2026-Q3", points: null },
      { id: "l3", groupId: "g-ai", quarter: "2026-Q3", points: "abc" },
    ];
    expect(quarterTotal(messy, "g-ai", "2026-Q3")).toBe(7);
  });

  it("returns 0 on missing inputs rather than throwing", () => {
    expect(quarterTotal(null, "g-ai", "2026-Q3")).toBe(0);
    expect(quarterTotal(entries, "", "2026-Q3")).toBe(0);
    expect(quarterTotal(entries, "g-ai", "")).toBe(0);
  });
});

describe("reversedIdsOf", () => {
  it("marks an entry that has a reversing entry", () => {
    const reversed = reversedIdsOf([
      { id: "l1", points: 10 },
      { id: "l2", points: -10, reverses: "l1" },
    ]);
    expect(reversed.has("l1")).toBe(true);
  });

  it("does not mark an unreversed entry", () => {
    const reversed = reversedIdsOf([{ id: "l1", points: 10 }]);
    expect(reversed.has("l1")).toBe(false);
    expect(reversed.size).toBe(0);
  });

  it("does not mark the reversing entry itself", () => {
    const reversed = reversedIdsOf([
      { id: "l1", points: 10 },
      { id: "l2", points: -10, reverses: "l1" },
    ]);
    expect(reversed.has("l2")).toBe(false);
  });

  it("tracks a chain where a reversal was itself reversed", () => {
    const reversed = reversedIdsOf([
      { id: "l1", points: 10 },
      { id: "l2", points: -10, reverses: "l1" },
      { id: "l3", points: 10, reverses: "l2" },
    ]);
    expect([...reversed].sort()).toEqual(["l1", "l2"]);
  });

  it("handles missing and empty input", () => {
    expect(reversedIdsOf(null).size).toBe(0);
    expect(reversedIdsOf([]).size).toBe(0);
    expect(reversedIdsOf([{ id: "l1", reverses: null }]).size).toBe(0);
  });
});
