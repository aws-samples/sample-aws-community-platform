import { describe, expect, it } from "vitest";
import { voteCountPhrase } from "./eventIdeas";

// Declining an idea permanently deletes it and its votes, so this fragment is
// part of a confirmation the leader relies on to understand what is destroyed.
// Wrong wording here is a correctness problem, not a cosmetic one.
describe("voteCountPhrase", () => {
  it("quantifies a normal count", () => {
    expect(voteCountPhrase(5)).toBe("all 5 votes");
  });

  it("does not say '1 votes'", () => {
    expect(voteCountPhrase(1)).toBe("all 1 vote");
  });

  it("does not say 'all 0 votes' for an unvoted idea", () => {
    expect(voteCountPhrase(0)).toBe("all votes");
  });

  it("falls back to the plural when the idea is not loaded", () => {
    // The confirmation can open for an idea that is not in the current page,
    // so the count may be missing entirely.
    expect(voteCountPhrase(undefined)).toBe("all votes");
    expect(voteCountPhrase(null)).toBe("all votes");
  });

  it("tolerates junk rather than emitting NaN", () => {
    expect(voteCountPhrase("abc")).toBe("all votes");
    expect(voteCountPhrase(-3)).toBe("all votes");
  });

  it("accepts a numeric string, as the API may send one", () => {
    expect(voteCountPhrase("4")).toBe("all 4 votes");
    expect(voteCountPhrase("1")).toBe("all 1 vote");
  });
});
