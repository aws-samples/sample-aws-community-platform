import { useEffect, useMemo, useState } from "react";
import { useApi } from "../../lib/useApi";
import { ErrorState, Loading } from "../../components/States";
import { FeedFetchError, fetchFeed } from "./fetchFeed";
import { FeedParseError, parseFeed } from "./feedParser";
import { collectCategories, filterItems } from "./filter";
import FeedItemRow from "./FeedItemRow";
import type { FeedError, FeedItem } from "./types";

/**
 * What's New in AWS (Module 11 — US-11.3, 11.4, 11.5, 11.6, 11.7).
 *
 * Frontend-only by design: the browser fetches a CORS-enabled RSS mirror
 * directly (DW-1) and parses it client-side. There is no backend service, no
 * persistence and no caching — the feed is re-fetched on every mount, which is
 * the requirement (US-11.7), not an oversight.
 *
 * The nav item that reaches this page is gated on `whatsNewEnabled` in
 * AppLayout, and Administrators never see it (US-11.2/11.6). The disabled state
 * below is the direct-URL backstop for someone who bookmarked the route.
 */

/** AWS-branded hero header shared across all page states. */
function WnHero() {
  return (
    <div className="wn-hero">
      <div className="wn-hero-icon" aria-hidden="true">🆕</div>
      <div className="wn-hero-text">
        <h1>What's New in AWS</h1>
        <p>
          The latest AWS product announcements and feature launches, loaded fresh on every visit.
          Search or filter by service category, then click any item to read the details.
        </p>
        <div className="wn-hero-badge">
          <span className="wn-hero-dot" aria-hidden="true" />
          Live feed · refreshed on load
        </div>
      </div>
    </div>
  );
}

export default function WhatsNewPage() {
  const settings = useApi<{ whatsNewEnabled?: boolean; whatsNewFeedUrl?: string }>("/settings");
  const feedUrl = settings.data?.whatsNewFeedUrl?.trim() ?? "";
  const enabled = settings.data?.whatsNewEnabled !== false;

  const [items, setItems] = useState<FeedItem[] | null>(null);
  const [feedError, setFeedError] = useState<FeedError | null>(null);
  const [loadingFeed, setLoadingFeed] = useState(false);

  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");

  useEffect(() => {
    if (!enabled || !feedUrl) return;
    let cancelled = false;

    setLoadingFeed(true);
    setFeedError(null);

    fetchFeed(feedUrl)
      .then((xml) => parseFeed(xml))
      .then((parsed) => {
        if (!cancelled) setItems(parsed);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof FeedFetchError) setFeedError(err.detail);
        else if (err instanceof FeedParseError) setFeedError({ kind: "parse", message: err.message });
        else setFeedError({ kind: "parse", message: "The feed could not be read." });
        setItems(null);
      })
      .finally(() => {
        if (!cancelled) setLoadingFeed(false);
      });

    return () => { cancelled = true; };
  }, [enabled, feedUrl]);

  const categories = useMemo(() => collectCategories(items ?? []), [items]);
  const visible = useMemo(
    () => filterItems(items ?? [], { q, category }),
    [items, q, category],
  );

  const visibleCount = visible.length;

  if (settings.loading) return <Loading />;

  // US-11.6 — feature switched off. Nav already hides it; this covers direct navigation.
  if (!enabled) {
    return (
      <>
        <WnHero />
        <div className="card" data-testid="wn-disabled">
          <p className="faint small mb-0">This feature is currently disabled by your Administrator.</p>
        </div>
      </>
    );
  }

  // US-11.6 — enabled but unconfigured is a neutral empty state, never an error.
  if (!feedUrl) {
    return (
      <>
        <WnHero />
        <div className="card" data-testid="wn-not-configured">
          <p className="faint small mb-0">
            No feed has been configured yet. An Administrator can set the feed URL in Settings.
          </p>
        </div>
      </>
    );
  }

  return (
    <>
      <WnHero />

      {/* Sticky toolbar — search icon inside input, category select, live count pill */}
      <div className="wn-toolbar-wrap">
        <div className="wn-toolbar-card">
          <div className="wn-search-wrap">
            <span className="wn-search-icon" aria-hidden="true">🔍</span>
            <input
              className="wn-search-input"
              type="search"
              placeholder="Search announcements…"
              data-testid="wn-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <select
            className="wn-cat-select"
            data-testid="wn-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
          >
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          {items !== null && (
            <div className="wn-count-pill" aria-live="polite">
              <span className="wn-count-num" data-testid="wn-count">{visibleCount}</span>
              <span>{visibleCount === 1 ? "announcement" : "announcements"}</span>
            </div>
          )}
        </div>
      </div>

      {loadingFeed && items === null && (
        <div className="wn-loading" data-testid="wn-loading">
          <div className="wn-spinner" aria-hidden="true" />
          <span>Loading the latest AWS announcements…</span>
        </div>
      )}

      {/* Three distinct outcomes kept distinct: the feed failed, the feed is
          genuinely empty, or the filters excluded everything. Collapsing them
          into one "nothing here" message is what makes a CORS misconfiguration
          look like a quiet feature failure. */}
      {feedError && (
        <ErrorState
          message={
            `${feedError.message} The AWS feed could not be displayed; the rest of the portal is unaffected.`
          }
        />
      )}

      {!feedError && items !== null && items.length === 0 && (
        <div className="wn-empty">
          <div className="wn-empty-icon" aria-hidden="true">📭</div>
          <div className="wn-empty-title">No announcements yet</div>
          <div className="wn-empty-sub">The feed loaded successfully but contains no announcements.</div>
        </div>
      )}

      {!feedError && items !== null && items.length > 0 && (
        <>
          {visible.length === 0
            ? (
              <div className="wn-empty">
                <div className="wn-empty-icon" aria-hidden="true">🔍</div>
                <div className="wn-empty-title">No results</div>
                <div className="wn-empty-sub">No announcements match your search or category filter.</div>
              </div>
            )
            : (
              <ul className="wn-feed" data-testid="whats-new">
                {visible.map((item) => <FeedItemRow key={item.id} item={item} />)}
              </ul>
            )}
        </>
      )}
    </>
  );
}
