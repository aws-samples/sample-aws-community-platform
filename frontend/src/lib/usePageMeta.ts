/**
 * usePageMeta — sets document.title dynamically per page.
 * Format: "<Page Name> — AWS Community Portal"
 * Falls back to "AWS Community Portal" when no title is provided.
 */
import { useEffect } from "react";

const SITE_NAME = "AWS Community Portal";

export function usePageMeta(pageTitle?: string) {
  useEffect(() => {
    document.title = pageTitle ? `${pageTitle} — ${SITE_NAME}` : SITE_NAME;
    // Restore on unmount so navigating back sets a clean title
    return () => { document.title = SITE_NAME; };
  }, [pageTitle]);
}
