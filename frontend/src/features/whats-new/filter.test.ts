import { describe, expect, it } from "vitest";
import { parseFeed } from "./feedParser";
import { collectCategories, filterItems } from "./filter";
import { loadSampleFeed } from "./__fixtures__/loadFixture";
import type { FeedItem } from "./types";

/** US-11.4 — search and category filter, combinable, immediate. */

const items = parseFeed(loadSampleFeed());

const titles = (list: FeedItem[]) => list.map((i) => i.title);

describe("collectCategories", () => {
  const categories = collectCategories(items);

  it("returns distinct labels in alphabetical order (DW-9)", () => {
    expect(categories).toEqual([...categories].sort((a, b) => a.localeCompare(b, "en")));
    expect(new Set(categories).size).toBe(categories.length);
  });

  it("excludes blanks so the dropdown never offers an empty option", () => {
    expect(categories.every((c) => c.trim().length > 0)).toBe(true);
  });

  it("includes labels only present on one item", () => {
    expect(categories).toContain("Serverless");
    expect(categories).toContain("Security, Identity & Compliance");
  });

  it("returns an empty list for an empty feed", () => {
    expect(collectCategories([])).toEqual([]);
  });
});

describe("filterItems — search", () => {
  it("returns everything when no filter is active", () => {
    expect(filterItems(items, { q: "", category: "" })).toHaveLength(items.length);
  });

  it("matches on title", () => {
    const found = filterItems(items, { q: "DynamoDB", category: "" });
    expect(titles(found)).toEqual(["Amazon DynamoDB reduces on-demand throughput pricing"]);
  });

  it("matches on summary text", () => {
    const found = filterItems(items, { q: "memory-optimized", category: "" });
    expect(titles(found)[0]).toContain("R8i");
  });

  it("matches text that appears only in the details body, not the summary", () => {
    // "Re-indexing" sits deep in the OpenSearch item's body. The old mock
    // searched title + category only and would have missed this.
    const found = filterItems(items, { q: "re-indexing", category: "" });
    expect(titles(found)).toEqual([
      "Amazon OpenSearch Service improves vector search performance and reduces memory footprint",
    ]);
  });

  it("is case-insensitive", () => {
    expect(filterItems(items, { q: "BEDROCK", category: "" })).toHaveLength(1);
    expect(filterItems(items, { q: "bedrock", category: "" })).toHaveLength(1);
  });

  it("ignores surrounding whitespace", () => {
    expect(filterItems(items, { q: "  bedrock  ", category: "" })).toHaveLength(1);
  });

  it("returns nothing when the term matches no item", () => {
    expect(filterItems(items, { q: "zzz-no-such-term", category: "" })).toEqual([]);
  });
});

describe("filterItems — category", () => {
  it("selects only items carrying the exact label", () => {
    const found = filterItems(items, { q: "", category: "Compute" });
    expect(found).toHaveLength(2);
    expect(found.every((i) => i.categories.includes("Compute"))).toBe(true);
  });

  it("matches exactly, not by substring", () => {
    // "Amazon S3" must not be selected by a filter on "Amazon S"
    expect(filterItems(items, { q: "", category: "Amazon S" })).toEqual([]);
  });

  it("handles a label containing a comma", () => {
    const found = filterItems(items, { q: "", category: "Security, Identity & Compliance" });
    expect(titles(found)[0]).toContain("Identity");
  });

  it("excludes items with no categories", () => {
    const found = filterItems(items, { q: "", category: "Storage" });
    expect(titles(found).some((t) => t.includes("Support Center"))).toBe(false);
  });
});

describe("filterItems — combined", () => {
  it("applies search and category together", () => {
    const found = filterItems(items, { q: "Lambda", category: "Compute" });
    expect(titles(found)).toEqual(["AWS Lambda increases the maximum ephemeral storage per function"]);
  });

  it("returns nothing when the two filters do not intersect", () => {
    expect(filterItems(items, { q: "Lambda", category: "Storage" })).toEqual([]);
  });

  it("preserves the feed sort order of surviving items", () => {
    const found = filterItems(items, { q: "Amazon", category: "" });
    const dates = found.map((i) => i.pubDate?.getTime() ?? -Infinity);
    expect(dates).toEqual([...dates].sort((a, b) => b - a));
  });
});
