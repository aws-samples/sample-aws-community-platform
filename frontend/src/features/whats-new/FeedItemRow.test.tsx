import parse from "html-react-parser";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FeedItemRow from "./FeedItemRow";
import { parseFeed } from "./feedParser";
import { sanitizeFeedHtml } from "./sanitize";
import { loadHostileFeed } from "./__fixtures__/loadFixture";
import type { FeedItem } from "./types";

/**
 * The feed body is third-party HTML from the AWS RSS feed, so unlike announcements
 * (authored Markdown) it cannot be re-rendered from a non-HTML source. It is
 * sanitized by sanitizeFeedHtml (DOMPurify + explicit allow-list) and then PARSED
 * INTO REACT ELEMENTS by html-react-parser instead of being injected with
 * dangerouslySetInnerHTML.
 *
 * That removes the innerHTML sink (bosco/react-dangerouslysetinnerhtml) without
 * changing the security posture: the sanitizer is untouched and its output is the
 * only thing parsed. sanitize.test.ts covers the sanitizer; this file covers the
 * RENDER PATH, and specifically the property the swap had to preserve —
 *
 *   the parsed element tree is identical to the tree the sanitized string
 *   parses to on its own
 *
 * which is what guarantees the feed's look and feel is unchanged under the same
 * CSS. The parity assertions target that mechanism directly: FeedItemRow keeps its
 * expanded/collapsed state internally and renderToStaticMarkup cannot click, so
 * driving the row itself would only ever exercise the collapsed branch.
 */

const items = parseFeed(loadHostileFeed());

function itemFor(titleFragment: string): FeedItem {
  const item = items.find((i) => i.title.includes(titleFragment));
  if (!item) throw new Error(`fixture item not found: ${titleFragment}`);
  return item;
}

/** Exactly what the component renders for a body: parse(sanitize(raw)). */
function renderedBody(raw: string): HTMLElement {
  // Build the DOM with DOMParser rather than assigning to an element's
  // innerHTML: the test only needs a comparable element tree, not an HTML sink,
  // and DOMParser keeps this file free of innerHTML/outerHTML (bosco/react-html-all).
  const markup = renderToStaticMarkup(<div>{parse(sanitizeFeedHtml(raw))}</div>);
  const doc = new DOMParser().parseFromString(markup, "text/html");
  return doc.body.firstElementChild as HTMLElement;
}

/** The tree the sanitized string parses to on its own (the parity reference). */
function referenceBody(raw: string): HTMLElement {
  const doc = new DOMParser().parseFromString(sanitizeFeedHtml(raw), "text/html");
  return doc.body;
}

/** Normalize a subtree to a comparable tag + sorted-attribute skeleton. */
function skeleton(root: ParentNode): string {
  return Array.from(root.querySelectorAll("*"))
    .map((el) => {
      const attrs = Array.from(el.attributes)
        .map((a) => `${a.name}=${a.value}`)
        .sort()
        .join(",");
      return `${el.tagName.toLowerCase()}[${attrs}]`;
    })
    .join("|");
}

describe("feed body render — parsed output matches the sanitized HTML exactly", () => {
  // THE PARITY GUARANTEE, across the whole hostile fixture: every item's parsed
  // tree must equal the tree the sanitized HTML parses to on its own, tag for
  // tag and attribute for attribute. This is the evidence that swapping the
  // render mechanism did not alter formatting, nesting, or link hardening.
  it.each(items.map((i) => [i.title, i] as const))(
    "%s renders an identical DOM",
    (_title, item) => {
      const actual = renderedBody(item.detailsHtml);
      const reference = referenceBody(item.detailsHtml);
      expect(skeleton(actual)).toBe(skeleton(reference));
      expect(actual.textContent).toBe(reference.textContent);
    },
  );
});

describe("feed body render — hostile markup stays neutralized through the parser", () => {
  it("emits no live script, iframe, object, embed, svg or style element", () => {
    for (const item of items) {
      const el = renderedBody(item.detailsHtml);
      expect(
        el.querySelector("script, iframe, object, embed, svg, style"),
        `hostile element survived for: ${item.title}`,
      ).toBeNull();
    }
  });

  it("emits no event-handler attributes and no javascript: hrefs", () => {
    for (const item of items) {
      const el = renderedBody(item.detailsHtml);
      const attrs = Array.from(el.querySelectorAll("*")).flatMap((n) =>
        Array.from(n.attributes),
      );
      expect(attrs.filter((a) => a.name.toLowerCase().startsWith("on"))).toEqual([]);
      for (const a of attrs) {
        expect(a.value.toLowerCase()).not.toContain("javascript:");
      }
    }
  });
});

describe("feed body render — legitimate formatting survives the parser", () => {
  const el = () => renderedBody(itemFor("Benign formatting").detailsHtml);

  it("keeps text formatting elements", () => {
    const body = el();
    expect(body.querySelector("strong")?.textContent).toBe("bold");
    expect(body.querySelector("em")?.textContent).toBe("italic");
    expect(body.querySelector("code")?.textContent).toBe("inline code");
  });

  it("keeps lists", () => {
    const body = el();
    expect(body.querySelector("ul")).not.toBeNull();
    expect(body.querySelector("li")?.textContent).toBe("First");
  });

  it("keeps safe links hardened with target and rel (US-11.5)", () => {
    const a = el().querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://aws.amazon.com/ec2/");
    // The hardening is applied by the DOMPurify hook and must survive parsing.
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("renders nothing for an empty body", () => {
    expect(renderedBody("").childElementCount).toBe(0);
  });
});

describe("FeedItemRow — the row itself no longer injects an HTML string", () => {
  it("renders every fixture with no script element and no javascript: URL", () => {
    for (const item of items) {
      const doc = new DOMParser().parseFromString(
        renderToStaticMarkup(<FeedItemRow item={item} />),
        "text/html",
      );
      const host = doc.body;
      expect(host.querySelector("script")).toBeNull();
      const attrs = Array.from(host.querySelectorAll("*")).flatMap((n) =>
        Array.from(n.attributes),
      );
      for (const a of attrs) {
        expect(a.value.toLowerCase()).not.toContain("javascript:");
      }
    }
    // NOTE: hostile payload TEXT (e.g. "window.__pwned = true;") legitimately
    // appears in the collapsed summary, React-escaped and inert. That is
    // pre-existing behaviour and not an injection — asserting its absence would
    // be wrong, so the assertions above check for live ELEMENTS and URLs instead.
  });
});
