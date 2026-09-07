import { describe, expect, it } from "vitest";
import {
  ACTIVITY_CATEGORY_OPTIONS,
  SOURCE_OPTIONS,
  buildLedgerQuery,
  ledgerFilterFields,
} from "./pointLedger";

const allSources = SOURCE_OPTIONS.map((o) => o.value);
const allCats = ACTIVITY_CATEGORY_OPTIONS.map((o) => o.value);

describe("buildLedgerQuery", () => {
  it("includes group and quarter", () => {
    const q = buildLedgerQuery({ groupId: "g1", quarter: "2026-Q3", sources: allSources, categories: allCats });
    expect(q).toContain("groupId=g1");
    expect(q).toContain("quarter=2026-Q3");
  });

  it("omits source/activityType when all values are selected (== no filter)", () => {
    const q = buildLedgerQuery({ groupId: "g1", quarter: "2026-Q3", sources: allSources, categories: allCats });
    expect(q).not.toContain("source=");
    expect(q).not.toContain("activityType=");
  });

  it("sends a strict subset of sources", () => {
    const q = buildLedgerQuery({ groupId: "g1", quarter: "2026-Q3", sources: ["adjustment"], categories: allCats });
    expect(q).toContain("source=adjustment");
  });

  it("sends a strict subset of categories", () => {
    const q = buildLedgerQuery({ groupId: "g1", quarter: "2026-Q3", sources: allSources, categories: ["certification", "event-delivery"] });
    expect(decodeURIComponent(q)).toContain("activityType=certification,event-delivery");
  });

  it("includes memberId when set", () => {
    const q = buildLedgerQuery({ groupId: "g1", quarter: "2026-Q3", memberId: "m-a", sources: allSources, categories: allCats });
    expect(q).toContain("memberId=m-a");
  });
});

// The table's query string and the async export's POST body are built from this
// one function, so the CSV can never be filtered differently from the rows on
// screen. These assertions are what pin that.
describe("ledgerFilterFields", () => {
  it("produces the same fields the query string encodes", () => {
    const state = {
      groupId: "g1", quarter: "2026-Q3", memberId: "m-a",
      sources: ["adjustment"], categories: ["certification"],
    };
    const fields = ledgerFilterFields(state);
    expect(fields).toEqual({
      groupId: "g1", quarter: "2026-Q3", memberId: "m-a",
      source: "adjustment", activityType: "certification",
    });
    // Round-trip: the query string is just these fields url-encoded.
    expect(buildLedgerQuery(state)).toBe(new URLSearchParams(fields).toString());
  });

  it("omits a filter that selects everything, matching the query string", () => {
    const state = { groupId: "g1", quarter: "2026-Q3", sources: allSources, categories: allCats };
    expect(ledgerFilterFields(state)).toEqual({ groupId: "g1", quarter: "2026-Q3" });
  });

  it("omits an unset member", () => {
    const fields = ledgerFilterFields({
      groupId: "g1", quarter: "2026-Q3", sources: allSources, categories: allCats,
    });
    expect(fields).not.toHaveProperty("memberId");
  });
});
