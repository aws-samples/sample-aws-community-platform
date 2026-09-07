// What's New in AWS (Module 11) — client-side RSS feed feature.
// Frontend-only by design: no backend service, no persistence, no caching.
export { default as WhatsNewPage } from "./WhatsNewPage";
export { parseFeed, sortItems, buildSummary, splitCategoryText, parsePubDate } from "./feedParser";
export { collectCategories, filterItems } from "./filter";
export { sanitizeFeedHtml } from "./sanitize";
export { fetchFeed, FeedFetchError } from "./fetchFeed";
export type { FeedItem, FeedFilter, FeedError } from "./types";
