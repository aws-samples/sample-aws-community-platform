// Shared types for the What's New in AWS feed (Module 11, US-11.3-11.5, 11.7).
//
// The feed is a CORS-enabled RSS 2.0 mirror of the official AWS "Recent
// Announcements" feed (DW-1). Everything here describes parsed, in-memory
// state only — nothing about this feature is persisted or cached (US-11.7).

/** One parsed <item> from the feed. */
export interface FeedItem {
  /** Stable identity for React keys: <guid>, else <link>, else title+date. Never an array index. */
  id: string;
  title: string;
  /** <item><link> — the original AWS page. May be empty if the feed omits it. */
  link: string;
  /** Parsed <pubDate>. null when absent or unparseable; such items sort last (DW-8). */
  pubDate: Date | null;
  /** Human-readable category labels. Empty for items with no <category> (8% of upstream). */
  categories: string[];
  /** Plain-text summary derived from <description>, truncated for the list row (US-11.3). */
  summary: string;
  /** Full <description> markup, UNSANITIZED. Must pass through sanitize.ts before reaching the DOM (DW-3). */
  detailsHtml: string;
}

/**
 * Why a feed load failed. The UI renders a different message per kind so an
 * Administrator can tell a CORS/mirror problem from a genuinely empty feed —
 * a browser CORS rejection surfaces to JS as an opaque TypeError with no
 * status code, which is otherwise indistinguishable from an outage.
 */
export type FeedErrorKind = "network" | "http" | "parse";

export interface FeedError {
  kind: FeedErrorKind;
  message: string;
  /** Present only for kind === "http". */
  status?: number;
}

/** Active filter state for the list (US-11.4). Empty strings mean "no filter". */
export interface FeedFilter {
  q: string;
  category: string;
}
