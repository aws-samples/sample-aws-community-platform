import type { ComponentPropsWithoutRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";

/**
 * Rendering policy for announcement bodies (NFR-AN-SEC-1/2).
 *
 * Bodies are authored and stored as Markdown. The service layer does NOT
 * sanitize: `normalize_body` in services/announcements/src/body.py is
 * length-bounding only. This component is therefore the ONLY thing standing
 * between an authored body and the DOM.
 *
 * WHY THIS RENDERS TO REACT ELEMENTS RATHER THAN AN HTML STRING. The previous
 * implementation ran markdown-it -> HTML string -> DOMPurify -> the string was
 * injected with dangerouslySetInnerHTML. That injection is a HIGH finding
 * (bosco/react-dangerouslysetinnerhtml) even when the string is sanitized,
 * because a scanner cannot see the sanitizer and the pattern recurs on every
 * scan. react-markdown parses the Markdown to an AST and renders React elements
 * directly, so NO HTML STRING IS EVER PRODUCED and there is no innerHTML sink to
 * flag. The finding is eliminated at the source, not suppressed.
 *
 * The security posture is preserved control-for-control:
 *
 *  1. NO raw-HTML support. rehype-raw is deliberately NOT installed, so any raw
 *     HTML embedded in the Markdown source (`<script>`, `<img onerror>`, `<svg
 *     onload>`) is treated as literal text, never parsed into elements. This is
 *     the direct replacement for markdown-it's `html: false`.
 *  2. An EXPLICIT element allow-list (`allowedElements`). Anything react-markdown
 *     could emit that is not on this list is dropped. `unwrapDisallowed` keeps the
 *     text content of a dropped wrapper so prose is never silently swallowed.
 *  3. URL sanitization on links. react-markdown's default `urlTransform` strips
 *     `javascript:`, `data:`, `vbscript:` and other dangerous schemes from href;
 *     it is left at its default (NOT overridden) precisely so that protection
 *     stays in force.
 *  4. Link hardening. The custom `a` renderer forces `target="_blank"` and
 *     `rel="noopener noreferrer"`, preventing reverse-tabnabbing.
 *
 * `img` is intentionally OFF the allow-list. Markdown image syntax needs no raw
 * HTML, so control 1 does not stop it, and an embedded remote image is a beacon
 * that leaks every recipient's IP, user-agent and read time to a third-party
 * host (and punches a hole in any restrictive img-src CSP). Not XSS — no
 * `onerror` can be attached — but not the intended reach of an internal notice.
 * Authors should link to an image instead. Dropped silently, alt text included.
 *
 * AnnouncementBody.test.tsx exercises this policy and MUST be kept in lockstep:
 * relaxing any of the four controls, or adding `img`/`rehype-raw`, is exactly
 * what it exists to catch.
 */

/**
 * Every element react-markdown can emit from authored Markdown under the plugin
 * set below (CommonMark + GFM tables/strikethrough), MINUS `img`. Kept identical
 * in spirit to the tag list the DOMPurify implementation allowed, so this change
 * is a like-for-like swap of mechanism, not of what an author may produce.
 */
const ALLOWED_ELEMENTS = [
  "p", "br", "hr",
  "strong", "em", "del",
  "code", "pre",
  "h1", "h2", "h3", "h4", "h5", "h6",
  "blockquote",
  "ul", "ol", "li",
  "table", "thead", "tbody", "tr", "th", "td",
  "a",
];

// Markdown-authored links carry no target of their own; forcing it here is what
// opens the AWS/destination page in a new tab without handing it a window
// reference. rel is set alongside target — the pair is what prevents
// reverse-tabnabbing, so they travel together or not at all.
function SafeLink({ href, children, ...rest }: ComponentPropsWithoutRef<"a">) {
  return (
    <a {...rest} href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export default function AnnouncementBody({ body }: { body: string }) {
  if (!body) return null;
  return (
    <Markdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      allowedElements={ALLOWED_ELEMENTS}
      unwrapDisallowed
      components={{ a: SafeLink }}
    >
      {body}
    </Markdown>
  );
}
