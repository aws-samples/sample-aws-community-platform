import type { FeedItem } from "./types";

/**
 * RSS 2.0 feed parser for the What's New in AWS feed (US-11.3, US-11.7).
 *
 * RSS 2.0 only (DW-4) — both candidate AWS feeds are RSS 2.0, so Atom support
 * would be dead code. Uses DOMParser rather than hand-rolled string work
 * because real feeds mix CDATA and entity escaping, carry namespaced elements,
 * and put ampersands in titles; all three break naive splitting.
 */

/** Summary length for the collapsed list row (~150 chars per the use case). */
export const SUMMARY_MAX_CHARS = 150;

export class FeedParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FeedParseError";
  }
}

/**
 * DW-12 — defensive split for a feed that has NOT been normalized by our mirror.
 *
 * Our mirror emits one <category> element per label (DW-5), but US-11.1 lets an
 * Administrator point at any URL, including raw upstream, which packs the whole
 * taxonomy into a single comma-joined machine string:
 *
 *   marketing:marchitecture/compute,general:products/amazon-ec2
 *
 * Splitting on commas unconditionally would be a bug: a legitimate normalized
 * label such as "Security, Identity & Compliance" also contains a comma. So the
 * split only fires for text that looks like the machine taxonomy — every token
 * carrying both ':' and '/'. Unmapped tokens keep their raw text so they are
 * visibly wrong and get reported rather than silently dropped (DW-6).
 */
const TAXONOMY_TOKEN = /^[a-z0-9-]+:[a-z0-9-]+\/[a-z0-9._-]+$/i;

export function splitCategoryText(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  if (trimmed.includes(",")) {
    const parts = trimmed.split(",").map((p) => p.trim()).filter(Boolean);
    // Only treat it as a packed taxonomy when EVERY part looks like one.
    if (parts.length > 1 && parts.every((p) => TAXONOMY_TOKEN.test(p))) {
      return parts;
    }
  }
  return [trimmed];
}

/** Strip markup and collapse whitespace, so the summary is text regardless of feed shape. */
export function toPlainText(markup: string): string {
  if (!markup) return "";
  // Parsing as HTML (not regex-stripping) keeps entity decoding correct and
  // cannot execute anything — the fragment is never attached to the document.
  const doc = new DOMParser().parseFromString(markup, "text/html");
  return (doc.body?.textContent ?? "").replace(/\s+/g, " ").trim();
}

/**
 * Truncate on a word boundary, appending an ellipsis ONLY when text was
 * actually removed (the sample's one-line item must not gain a stray "…").
 */
export function buildSummary(markup: string, maxChars: number = SUMMARY_MAX_CHARS): string {
  const text = toPlainText(markup);
  if (text.length <= maxChars) return text;

  const clipped = text.slice(0, maxChars);
  const lastSpace = clipped.lastIndexOf(" ");
  const base = lastSpace > maxChars * 0.6 ? clipped.slice(0, lastSpace) : clipped;
  return `${base.replace(/[\s.,;:!?-]+$/, "")}…`;
}

/** RFC-822 dates (`Fri, 07 Aug 2026 21:11:00 GMT`). Returns null when absent or unparseable. */
export function parsePubDate(raw: string | null | undefined): Date | null {
  if (!raw || !raw.trim()) return null;
  const ms = Date.parse(raw.trim());
  return Number.isNaN(ms) ? null : new Date(ms);
}

function childText(parent: Element, tag: string): string {
  // getElementsByTagName over querySelector: tag names like "dc:creator"
  // are not valid CSS selectors and would throw.
  const el = parent.getElementsByTagName(tag)[0];
  return el?.textContent?.trim() ?? "";
}

/**
 * Parse feed XML into items sorted newest-first, undated items last (DW-8).
 *
 * Throws FeedParseError for input that is not a usable RSS document. An empty
 * but well-formed feed is NOT an error — it returns [] so the UI can show its
 * empty state rather than a failure.
 */
export function parseFeed(xml: string): FeedItem[] {
  if (!xml || !xml.trim()) {
    throw new FeedParseError("The feed response was empty.");
  }

  const doc = new DOMParser().parseFromString(xml, "text/xml");

  // DOMParser reports XML syntax errors as a <parsererror> node instead of throwing.
  if (doc.getElementsByTagName("parsererror").length > 0) {
    throw new FeedParseError("The feed is not valid XML.");
  }
  if (doc.documentElement?.nodeName !== "rss") {
    throw new FeedParseError("The feed is not an RSS 2.0 document.");
  }

  const items = Array.from(doc.getElementsByTagName("item"));
  const parsed: FeedItem[] = items.map((el, index) => {
    const title = childText(el, "title");
    const link = childText(el, "link");
    const guid = childText(el, "guid");
    const pubDate = parsePubDate(childText(el, "pubDate"));

    const categories = Array.from(el.getElementsByTagName("category"))
      .flatMap((c) => splitCategoryText(c.textContent ?? ""));

    const detailsHtml = el.getElementsByTagName("description")[0]?.textContent ?? "";

    return {
      id: guid || link || `${title}|${pubDate?.toISOString() ?? `no-date-${index}`}`,
      title,
      link,
      pubDate,
      categories: Array.from(new Set(categories)),
      summary: buildSummary(detailsHtml),
      detailsHtml,
    };
  });

  return sortItems(parsed);
}

/**
 * Newest first by <pubDate> (US-11.3). Undated items sort last but stay visible
 * and searchable (DW-8) — dropping them would hide feed problems. Stable within
 * equal dates so document order is preserved for same-timestamp items.
 */
export function sortItems(items: FeedItem[]): FeedItem[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const at = a.item.pubDate?.getTime();
      const bt = b.item.pubDate?.getTime();
      if (at === undefined && bt === undefined) return a.index - b.index;
      if (at === undefined) return 1;
      if (bt === undefined) return -1;
      return bt - at || a.index - b.index;
    })
    .map(({ item }) => item);
}
