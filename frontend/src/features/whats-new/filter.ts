import { toPlainText } from "./feedParser";
import type { FeedFilter, FeedItem } from "./types";

/**
 * Client-side search and category filtering (US-11.4).
 *
 * Search matches title, summary AND details — the story requires all three, and
 * the shipped mock only matched title plus category, so a term appearing solely
 * in an announcement's body found nothing.
 */

/**
 * Distinct category labels present in the feed, alphabetical (DW-9), blanks
 * excluded so items with no <category> never contribute an empty filter option.
 * Sorted with a locale comparator so labels like "Amazon EC2" and "AWS Lambda"
 * order predictably.
 */
export function collectCategories(items: FeedItem[]): string[] {
  const seen = new Set<string>();
  for (const item of items) {
    for (const category of item.categories) {
      const label = category.trim();
      if (label) seen.add(label);
    }
  }
  return Array.from(seen).sort((a, b) => a.localeCompare(b, "en"));
}

function matchesQuery(item: FeedItem, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    item.title,
    item.summary,
    toPlainText(item.detailsHtml),
  ].join(" ").toLowerCase();
  return haystack.includes(needle);
}

function matchesCategory(item: FeedItem, category: string): boolean {
  // Exact match, not substring: "Compute" must not also select
  // "Confidential Computing".
  return !category || item.categories.includes(category);
}

/** Search and category filter combine (US-11.4); results update immediately. */
export function filterItems(items: FeedItem[], filter: FeedFilter): FeedItem[] {
  const needle = filter.q.trim().toLowerCase();
  const category = filter.category.trim();
  if (!needle && !category) return items;
  return items.filter((item) => matchesQuery(item, needle) && matchesCategory(item, category));
}
