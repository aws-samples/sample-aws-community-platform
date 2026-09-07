import { describe, expect, it } from "vitest";

import { pendingAwaitingApproval } from "./pendingCount";

// Regression cover for the Member dashboard "Pending — awaiting approval" tile.
//
// Observed live: a member held 3 pending certification claims and 1 pending
// contribution, and the tile read "1". Earlier in the same session, with 2
// pending claims and 0 pending contributions, it read "0" — i.e. the tile said
// nothing was awaiting approval while two claims sat in a leader's queue.
// The count considered contribution submissions only.

const sub = (status: string) => ({ status });
const claim = (status: string) => ({ status });

describe("pendingAwaitingApproval", () => {
  it("counts pending certification claims, not just contributions", () => {
    // THE defect: no pending contributions, two pending claims. Was 0.
    expect(pendingAwaitingApproval([], [claim("Pending"), claim("Pending")])).toBe(2);
  });

  it("sums both sources", () => {
    // The exact live shape that reported 1.
    const subs = [sub("Pending"), sub("Approved"), sub("Approved")];
    const claims = [claim("Pending"), claim("Pending"), claim("Pending"), claim("Approved")];
    expect(pendingAwaitingApproval(subs, claims)).toBe(4);
  });

  it("counts pending contributions when there are no claims", () => {
    expect(pendingAwaitingApproval([sub("Pending")], [])).toBe(1);
  });

  it("ignores settled statuses on both sides", () => {
    // Approved/Rejected/Withdrawn/Verified are decided — nothing is awaiting
    // anyone, so none of them may inflate the tile.
    const subs = [sub("Approved"), sub("Rejected"), sub("Withdrawn")];
    const claims = [claim("Approved"), claim("Rejected"), claim("Verified")];
    expect(pendingAwaitingApproval(subs, claims)).toBe(0);
  });

  it("is exact about the status string", () => {
    // Guards against a case/substring match creeping in and counting e.g.
    // "PendingScan" (a certifications scan state) as awaiting approval.
    expect(pendingAwaitingApproval([], [claim("pending"), claim("PENDING")])).toBe(0);
    expect(pendingAwaitingApproval([], [claim("PendingScan")])).toBe(0);
  });

  it("treats missing and malformed data as zero rather than throwing", () => {
    // The tile renders before either request resolves, so undefined must be safe.
    expect(pendingAwaitingApproval(undefined, undefined)).toBe(0);
    expect(pendingAwaitingApproval(null, null)).toBe(0);
    expect(pendingAwaitingApproval([{}], [{ status: null }])).toBe(0);
  });
});
