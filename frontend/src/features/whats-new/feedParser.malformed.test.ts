import { describe, expect, it } from "vitest";
import { FeedParseError, parseFeed } from "./feedParser";

/**
 * US-11.7 — a feed that cannot be parsed must produce a graceful, legible
 * failure and never break the page. These cases separate "broken" (throws a
 * typed FeedParseError the UI can render) from "empty but valid" (returns []
 * so the UI shows an empty state, not an error).
 */

describe("parseFeed — unusable input throws a typed error", () => {
  it("rejects an empty string", () => {
    expect(() => parseFeed("")).toThrow(FeedParseError);
  });

  it("rejects whitespace only", () => {
    expect(() => parseFeed("   \n  ")).toThrow(FeedParseError);
  });

  it("rejects malformed XML with an unclosed tag", () => {
    expect(() => parseFeed('<?xml version="1.0"?><rss version="2.0"><channel><item><title>x</title>'))
      .toThrow(FeedParseError);
  });

  it("rejects a well-formed document that is not RSS", () => {
    expect(() => parseFeed('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry/></feed>'))
      .toThrow(FeedParseError);
  });

  it("rejects an HTML error page served in place of the feed", () => {
    // A misconfigured mirror commonly returns an HTML 404 body with a 200 status.
    expect(() => parseFeed("<!DOCTYPE html><html><body><h1>Not Found</h1></body></html>"))
      .toThrow(FeedParseError);
  });
});

describe("parseFeed — valid but sparse input degrades gracefully", () => {
  it("returns an empty list for a channel with no items", () => {
    const xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>';
    expect(parseFeed(xml)).toEqual([]);
  });

  it("does not throw when an item is missing every optional field", () => {
    const xml = '<?xml version="1.0"?><rss version="2.0"><channel><item></item></channel></rss>';
    const items = parseFeed(xml);
    expect(items).toHaveLength(1);
    expect(items[0].title).toBe("");
    expect(items[0].link).toBe("");
    expect(items[0].pubDate).toBeNull();
    expect(items[0].categories).toEqual([]);
    expect(items[0].summary).toBe("");
    // Identity still has to be non-empty for a stable React key.
    expect(items[0].id.length).toBeGreaterThan(0);
  });

  it("falls back from guid to link for identity", () => {
    const xml = '<?xml version="1.0"?><rss version="2.0"><channel><item>'
      + "<title>No guid</title><link>https://example.invalid/a</link>"
      + "</item></channel></rss>";
    expect(parseFeed(xml)[0].id).toBe("https://example.invalid/a");
  });

  it("de-duplicates repeated categories", () => {
    const xml = '<?xml version="1.0"?><rss version="2.0"><channel><item>'
      + "<title>Dupes</title><category>Compute</category><category>Compute</category>"
      + "</item></channel></rss>";
    expect(parseFeed(xml)[0].categories).toEqual(["Compute"]);
  });

  it("tolerates an unparseable pubDate without dropping the item", () => {
    const xml = '<?xml version="1.0"?><rss version="2.0"><channel><item>'
      + "<title>Bad date</title><pubDate>yesterday-ish</pubDate>"
      + "</item></channel></rss>";
    const items = parseFeed(xml);
    expect(items).toHaveLength(1);
    expect(items[0].pubDate).toBeNull();
  });
});
