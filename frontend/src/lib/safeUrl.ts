// Render-boundary guard for user-supplied URLs (finding f-74a4a413).
//
// React does NOT sanitize the `href` attribute. A stored `javascript:` URI
// renders as a live link and executes in the VIEWER's session when clicked —
// and the pages that display these links are the leader approval queues, so
// the viewer is a CL/UGL. The write boundary now allow-lists https:// in
// contributions-scoring (require_https_url), but that only protects NEW rows:
// submissions stored before that check shipped still hold whatever the member
// typed. This guard is what covers those, so it must stay even though the
// server also validates.
//
// Deliberately allow-lists rather than blocking `javascript:`. A deny-list has
// to anticipate `data:`, `vbscript:`, `blob:`, control-character padding and
// entity tricks; an allow-list of two schemes has nothing to miss.

const ALLOWED_PROTOCOLS = ["https:", "http:"];

/**
 * The value to put in an `href`, or `undefined` when it cannot be trusted.
 *
 * Returning `undefined` (not "" or "#") is intentional: React omits the
 * attribute entirely, so the element renders as plain non-navigable text
 * instead of a link to the current page.
 */
export function safeHref(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  try {
    // `new URL` resolves the scheme the way the browser will, which is what
    // makes this robust against casing and whitespace padding that a string
    // prefix test would miss.
    const { protocol } = new URL(trimmed);
    return ALLOWED_PROTOCOLS.includes(protocol) ? trimmed : undefined;
  } catch {
    // Relative or malformed. Not resolvable to a safe absolute link.
    return undefined;
  }
}

/**
 * Hostname for display next to a link, or `null` when the URL is untrusted or
 * unparseable.
 *
 * Exists because the call sites were doing `new URL(value).hostname` inline,
 * which THROWS on a malformed stored value and takes the whole table render
 * down with it — a crash, not a degraded cell.
 */
export function safeHostname(raw: unknown): string | null {
  const href = safeHref(raw);
  if (!href) return null;
  try {
    return new URL(href).hostname || null;
  } catch {
    return null;
  }
}

/**
 * Guarded `window.open`. Returns false when the URL was rejected, so the caller
 * can surface a message instead of silently doing nothing.
 *
 * `window.open("javascript:...")` executes in the opener's origin, so this path
 * needs the same allow-list as an href.
 */
export function openSafely(raw: unknown): boolean {
  const href = safeHref(raw);
  if (!href) return false;
  window.open(href, "_blank", "noopener");
  return true;
}
