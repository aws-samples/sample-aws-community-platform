import { describe, expect, it } from "vitest";

import { domainsFieldValue, joinDomains, parseDomains } from "./domains";

// Regression suite for the deployed-app bug (2026-08-11): the comma key did
// nothing in Admin -> Settings -> "Allowed email domains".

describe("domainsFieldValue — the actual defect", () => {
  it("keeps a trailing comma while typing", () => {
    // THE bug. The field previously showed joinDomains(parseDomains(text)), so
    // "amazon.com," became "amazon.com" mid-keystroke and the comma vanished.
    expect(domainsFieldValue("amazon.com,", ["amazon.com"])).toBe("amazon.com,");
  });

  it("keeps the space after a comma while typing", () => {
    expect(domainsFieldValue("amazon.com, ", ["amazon.com"])).toBe("amazon.com, ");
  });

  it("keeps a half-typed second domain", () => {
    expect(domainsFieldValue("amazon.com,cog", ["amazon.com", "cog"]))
      .toBe("amazon.com,cog");
  });

  it("shows the canonical form once editing has been committed", () => {
    expect(domainsFieldValue(null, ["amazon.com", "cognizant.com"]))
      .toBe("amazon.com, cognizant.com");
  });

  it("treats an empty draft as intentional, not as 'show stored'", () => {
    // Clearing the field must not snap the old value back in.
    expect(domainsFieldValue("", ["amazon.com"])).toBe("");
  });
});

describe("parseDomains", () => {
  it("splits, trims and drops empties", () => {
    expect(parseDomains("amazon.com, cognizant.com")).toEqual(["amazon.com", "cognizant.com"]);
    expect(parseDomains("amazon.com,,cognizant.com,")).toEqual(["amazon.com", "cognizant.com"]);
    expect(parseDomains("  amazon.com  ")).toEqual(["amazon.com"]);
    expect(parseDomains("")).toEqual([]);
  });
});

describe("joinDomains", () => {
  it("renders an array canonically and tolerates a bare string or absence", () => {
    expect(joinDomains(["a.com", "b.com"])).toBe("a.com, b.com");
    expect(joinDomains("a.com")).toBe("a.com");
    expect(joinDomains(undefined)).toBe("");
    expect(joinDomains(null)).toBe("");
  });
});
