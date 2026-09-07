import type { FeedError } from "./types";

/**
 * Fetch the raw feed XML from the Administrator-configured URL (US-11.7).
 *
 * DW-13 — this deliberately uses plain `fetch`, NOT the app's `apiFetch`.
 * `apiFetch` prefixes the portal API base URL and attaches the caller's Cognito
 * JWT; pointing that at a third-party host would leak a portal bearer token to
 * whatever URL an Administrator typed into Settings. So: no Authorization
 * header, credentials omitted, and the response body treated as untrusted input
 * that still has to clear the sanitizer before it reaches the DOM.
 *
 * No caching, no persistence, no retry — the page fetches on every load by
 * requirement (US-11.3/11.7).
 */

export const FEED_TIMEOUT_MS = 10_000;

export class FeedFetchError extends Error {
  readonly detail: FeedError;

  constructor(detail: FeedError) {
    super(detail.message);
    this.name = "FeedFetchError";
    this.detail = detail;
  }
}

export async function fetchFeed(
  url: string,
  timeoutMs: number = FEED_TIMEOUT_MS,
): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let res: Response;
  try {
    res = await fetch(url, {
      method: "GET",
      credentials: "omit", // DW-13 — never send portal cookies/credentials off-origin
      redirect: "follow",
      signal: controller.signal,
      headers: { Accept: "application/rss+xml, application/xml, text/xml" },
    });
  } catch (err) {
    // A CORS rejection, DNS failure, offline browser and an abort all land here
    // with no status code. Say so plainly rather than implying the feed is empty.
    const aborted = (err as Error)?.name === "AbortError";
    throw new FeedFetchError({
      kind: "network",
      message: aborted
        ? `The feed did not respond within ${Math.round(timeoutMs / 1000)} seconds.`
        : "The feed could not be reached. It may be offline, or the URL may not allow "
          + "cross-origin requests (CORS).",
    });
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    throw new FeedFetchError({
      kind: "http",
      status: res.status,
      message: `The feed URL returned HTTP ${res.status}.`,
    });
  }

  return res.text();
}
