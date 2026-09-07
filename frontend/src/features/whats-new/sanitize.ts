import DOMPurify from "dompurify";

/**
 * Sanitization policy for feed-provided markup (DW-3, deviation DV-1).
 *
 * US-11.5 literally says the <description> is "rendered as-is". The same use
 * case's security note requires the design phase to address sanitization before
 * injecting feed HTML into the DOM, and measurement settled it: the official AWS
 * feed carries HTML in 100 of 100 descriptions. This is third-party content from
 * a source we do not control, reached over a URL an Administrator can change,
 * so it is sanitized unconditionally. Announcements set the same precedent.
 *
 * The allow-list is permissive enough to keep announcements readable — the
 * formatting AWS actually uses is <p> and <a>, plus lists and <code> in longer
 * entries — while removing every script-bearing construct.
 */

const ALLOWED_TAGS = [
  "p", "br", "strong", "b", "em", "i", "u", "small",
  "ul", "ol", "li",
  "code", "pre",
  "h3", "h4", "h5",
  "blockquote", "span",
  "a",
];

const ALLOWED_ATTR = ["href", "title", "target", "rel"];

/**
 * Force every surviving link to open in a new tab without handing the opened
 * page a window reference (US-11.5 requires the original AWS page open in a new
 * tab; rel prevents reverse-tabnabbing). Registered once at module load.
 */
let hookInstalled = false;

function installHook(): void {
  if (hookInstalled) return;
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A") {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
  hookInstalled = true;
}

/**
 * Sanitize feed markup for rendering.
 *
 * DOMPurify drops `javascript:` and other unsafe URI schemes from href by
 * default, and strips inline event handlers and <style>; ALLOWED_ATTR omitting
 * "style" also removes inline styling so feed content cannot restyle the portal.
 */
export function sanitizeFeedHtml(markup: string): string {
  if (!markup) return "";
  installHook();
  return DOMPurify.sanitize(markup, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "input", "svg", "math"],
    FORBID_ATTR: ["style", "srcset", "formaction"],
    ALLOW_DATA_ATTR: false,
    KEEP_CONTENT: true,
  });
}
