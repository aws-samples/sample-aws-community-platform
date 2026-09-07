import { describe, expect, it } from "vitest";
import { parseFeed } from "./feedParser";
import { sanitizeFeedHtml } from "./sanitize";
import { loadHostileFeed } from "./__fixtures__/loadFixture";

/**
 * DW-3 / DV-1 — feed markup is third-party content reached over a URL an
 * Administrator can change, so it is sanitized unconditionally before it can
 * reach the DOM. US-11.5's literal "rendered as-is" is deliberately not honoured;
 * the same use case's security note requires this.
 */
const items = parseFeed(loadHostileFeed());

function detailsFor(titleFragment: string): string {
  const item = items.find((i) => i.title.includes(titleFragment));
  if (!item) throw new Error(`fixture item not found: ${titleFragment}`);
  return sanitizeFeedHtml(item.detailsHtml);
}

describe("sanitizeFeedHtml — neutralizes injection vectors", () => {
  it("removes script tags but keeps surrounding prose", () => {
    const html = detailsFor("Script tag");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("__pwned");
    expect(html).toContain("Benign opening paragraph.");
    expect(html).toContain("Benign closing paragraph.");
  });

  it("strips inline event handlers", () => {
    const html = detailsFor("Inline event handler");
    expect(html).not.toContain("onmouseover");
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("__pwned");
  });

  it("strips javascript: URLs from links", () => {
    const html = detailsFor("javascript:");
    expect(html.toLowerCase()).not.toContain("javascript:");
    expect(html).not.toContain("__pwned");
  });

  it("removes iframe, object and embed", () => {
    const html = detailsFor("Embedded iframe");
    expect(html).not.toContain("<iframe");
    expect(html).not.toContain("<object");
    expect(html).not.toContain("<embed");
    expect(html).not.toContain("evil.invalid");
  });

  it("removes style blocks and inline style attributes", () => {
    const html = detailsFor("Inline style");
    expect(html).not.toContain("<style");
    expect(html).not.toContain("style=");
    expect(html).not.toContain("position:fixed");
    // Content is kept, only the styling hook is removed.
    expect(html).toContain("Covering overlay");
  });

  it("removes svg-borne scripts", () => {
    const html = detailsFor("SVG script");
    expect(html).not.toContain("<svg");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("__pwned");
  });
});

describe("sanitizeFeedHtml — preserves legitimate formatting", () => {
  const html = detailsFor("Benign formatting");

  it("keeps text formatting tags", () => {
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>italic</em>");
    expect(html).toContain("<code>inline code</code>");
  });

  it("keeps lists", () => {
    expect(html).toContain("<ul>");
    expect(html).toContain("<li>First</li>");
  });

  it("keeps safe links and their href", () => {
    expect(html).toContain('href="https://aws.amazon.com/ec2/"');
    expect(html).toContain("real link");
  });

  it("forces links to open in a new tab safely (US-11.5)", () => {
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});

describe("sanitizeFeedHtml — edge cases", () => {
  it("returns an empty string for empty input", () => {
    expect(sanitizeFeedHtml("")).toBe("");
  });

  it("passes plain text through unchanged", () => {
    expect(sanitizeFeedHtml("Just text.")).toBe("Just text.");
  });
});
