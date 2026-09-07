import { describe, expect, it } from "vitest";
import { buildSummary, parseFeed, parsePubDate, splitCategoryText } from "./feedParser";
import { collectCategories } from "./filter";
import { loadSampleFeed } from "./__fixtures__/loadFixture";

/**
 * Parsed against the single canonical sample in infra/ (DW-15) rather than a
 * copy, so the reference feed handed to the mirror maintainer and the feed under
 * test cannot drift apart.
 */
const SAMPLE = loadSampleFeed();

describe("parseFeed — canonical sample", () => {
  const items = parseFeed(SAMPLE);

  it("parses every item in the feed", () => {
    expect(items).toHaveLength(9);
  });

  it("sorts newest first (US-11.3), with the undated item last (DW-8)", () => {
    const order = items.map((i) => i.pubDate?.toISOString().slice(0, 10) ?? "undated");
    expect(order).toEqual([
      "2026-08-09", // Bedrock — deliberately mid-document in the source
      "2026-08-08",
      "2026-08-07",
      "2026-08-06",
      "2026-08-05",
      "2026-08-04",
      "2026-08-03",
      "2026-08-02",
      "undated",
    ]);
  });

  it("keeps the undated item visible rather than dropping it (DW-8)", () => {
    const undated = items.filter((i) => i.pubDate === null);
    expect(undated).toHaveLength(1);
    expect(undated[0].title).toContain("CloudWatch");
  });

  it("extracts HTML details from an entity-escaped description", () => {
    const ec2 = items.find((i) => i.title.includes("R8i"))!;
    expect(ec2.detailsHtml).toContain("<p>");
    expect(ec2.detailsHtml).toContain("<a href=");
  });

  it("extracts HTML details from a CDATA-wrapped description", () => {
    const lambda = items.find((i) => i.title.includes("Lambda"))!;
    expect(lambda.detailsHtml).toContain("<p>");
    expect(lambda.detailsHtml).toContain("<code>");
  });

  it("gives every item a non-empty stable id", () => {
    const ids = items.map((i) => i.id);
    expect(ids.every((id) => id.length > 0)).toBe(true);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("contributes no blank facet for the item that has no category", () => {
    const noCategory = items.find((i) => i.title.includes("Support Center"))!;
    expect(noCategory.categories).toEqual([]);
    expect(collectCategories(items).every((c) => c.trim().length > 0)).toBe(true);
  });

  it("preserves a legitimate category label containing a comma (DW-12 guard)", () => {
    const iam = items.find((i) => i.title.includes("Identity"))!;
    // "Security, Identity & Compliance" has a comma but is NOT machine taxonomy,
    // so it must survive intact rather than being split into two bogus facets.
    expect(iam.categories).toContain("Security, Identity & Compliance");
    expect(iam.categories).toContain("AWS Identity & Access Management");
    expect(iam.categories).toHaveLength(2);
  });

  it("decodes entities in titles", () => {
    const iam = items.find((i) => i.title.includes("Identity"))!;
    expect(iam.title).toContain("AWS Identity & Access Management");
    expect(iam.title).not.toContain("&amp;");
  });

  it("derives a plain-text summary with no markup", () => {
    const opensearch = items.find((i) => i.title.includes("OpenSearch"))!;
    expect(opensearch.summary).not.toContain("<");
    expect(opensearch.summary.length).toBeLessThanOrEqual(151);
  });

  it("truncates a long description but not a short one", () => {
    const opensearch = items.find((i) => i.title.includes("OpenSearch"))!;
    const short = items.find((i) => i.title.includes("S3 Express"))!;
    expect(opensearch.summary.endsWith("…")).toBe(true);
    expect(short.summary.endsWith("…")).toBe(false);
    expect(short.summary).toBe("Now available in three additional Regions.");
  });

  it("captures the original AWS link for every item", () => {
    expect(items.every((i) => i.link.startsWith("https://"))).toBe(true);
  });
});

describe("splitCategoryText — DW-12 pattern-gated taxonomy split", () => {
  it("splits an un-normalized upstream taxonomy string", () => {
    expect(splitCategoryText("marketing:marchitecture/compute,general:products/amazon-ec2"))
      .toEqual(["marketing:marchitecture/compute", "general:products/amazon-ec2"]);
  });

  it("does NOT split a human label that happens to contain a comma", () => {
    expect(splitCategoryText("Security, Identity & Compliance"))
      .toEqual(["Security, Identity & Compliance"]);
  });

  it("leaves an ordinary single label untouched", () => {
    expect(splitCategoryText("Amazon EC2")).toEqual(["Amazon EC2"]);
  });

  it("does not split when only some parts look like taxonomy", () => {
    expect(splitCategoryText("Compute, general:products/amazon-ec2"))
      .toEqual(["Compute, general:products/amazon-ec2"]);
  });

  it("drops empty text", () => {
    expect(splitCategoryText("   ")).toEqual([]);
  });
});

describe("parsePubDate", () => {
  it("parses RFC-822 with a GMT zone", () => {
    expect(parsePubDate("Fri, 07 Aug 2026 21:11:00 GMT")?.toISOString())
      .toBe("2026-08-07T21:11:00.000Z");
  });

  it("parses RFC-822 with a numeric offset", () => {
    expect(parsePubDate("Thu, 06 Aug 2026 22:58:00 +0000")?.toISOString())
      .toBe("2026-08-06T22:58:00.000Z");
  });

  it("returns null for absent or unparseable values", () => {
    expect(parsePubDate(undefined)).toBeNull();
    expect(parsePubDate("")).toBeNull();
    expect(parsePubDate("not a date")).toBeNull();
  });
});

describe("buildSummary", () => {
  it("strips markup and collapses whitespace", () => {
    expect(buildSummary("<p>One   two</p>\n<p>three</p>")).toBe("One two three");
  });

  it("adds no ellipsis when nothing was removed", () => {
    expect(buildSummary("<p>Short.</p>")).toBe("Short.");
  });

  it("truncates on a word boundary with an ellipsis", () => {
    const summary = buildSummary(`<p>${"alpha bravo ".repeat(40)}</p>`, 30);
    expect(summary.endsWith("…")).toBe(true);
    expect(summary.length).toBeLessThanOrEqual(31);
    expect(summary).not.toContain("alph…");
  });

  it("decodes HTML entities into text", () => {
    expect(buildSummary("<p>EC2 &amp; S3</p>")).toBe("EC2 & S3");
  });
});
