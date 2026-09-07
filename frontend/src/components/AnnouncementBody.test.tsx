import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AnnouncementBody from "./AnnouncementBody";

/**
 * NFR-AN-SEC-1/2 — announcement bodies are authored Markdown, reach every
 * recipient's browser, and are NOT sanitized server-side (body.py length-bounds
 * only). AnnouncementBody is the only control in front of the DOM, so a
 * regression here is stored XSS.
 *
 * Unlike the previous renderBody (which returned a sanitized HTML string), this
 * renders React elements — there is no HTML string and no dangerouslySetInnerHTML
 * to inspect. The tests therefore render the component to static markup the way
 * React itself would, parse THAT into a real DOM tree, and assert on the tree:
 * no live hostile element or attribute survives, and legitimate Markdown still
 * renders. Escaped hostile input legitimately still contains the literal text
 * "<script>" or "javascript:", so substring checks would mislead — the tree is
 * what proves inertness.
 */

/** Render the component and parse the result into an inspectable DOM subtree. */
function parse(body: string): HTMLElement {
  // Build the DOM with DOMParser rather than assigning to an element's
  // innerHTML: the test needs an inspectable element tree, not an HTML sink, and
  // DOMParser keeps this file free of innerHTML/outerHTML (bosco/react-html-all).
  const doc = new DOMParser().parseFromString(
    renderToStaticMarkup(<AnnouncementBody body={body} />),
    "text/html",
  );
  return doc.body;
}

/** Every attribute name present anywhere in the fragment, lowercased. */
function allAttrNames(root: HTMLElement): string[] {
  const names: string[] = [];
  root.querySelectorAll("*").forEach((el) => {
    for (const attr of Array.from(el.attributes)) names.push(attr.name.toLowerCase());
  });
  return names;
}

describe("AnnouncementBody — raw HTML never becomes live markup", () => {
  it("does not emit a script element, keeping surrounding prose as text", () => {
    const el = parse("Before\n\n<script>window.__pwned=1</script>\n\nAfter");
    expect(el.querySelector("script")).toBeNull();
    // Payload survives only as inert text.
    expect(el.textContent).toContain("Before");
    expect(el.textContent).toContain("After");
  });

  it("does not emit an img with an onerror handler", () => {
    const el = parse('<img src=x onerror="window.__pwned=1">');
    expect(el.querySelector("img")).toBeNull();
    expect(allAttrNames(el)).not.toContain("onerror");
  });

  it("does not emit svg, iframe, object, embed or style", () => {
    for (const payload of [
      "<svg onload=window.__pwned=1></svg>",
      '<iframe src="https://evil.example"></iframe>',
      "<style>body{display:none}</style>",
      '<object data="https://evil.example"></object>',
      '<embed src="https://evil.example">',
    ]) {
      const el = parse(payload);
      expect(el.querySelector("svg, iframe, style, object, embed")).toBeNull();
    }
  });

  it("emits no event-handler attributes for any payload", () => {
    const el = parse('<a href="#" onclick="window.__pwned=1">x</a>\n\n<div onmouseover=1>y</div>');
    expect(allAttrNames(el).filter((n) => n.startsWith("on"))).toEqual([]);
  });
});

describe("AnnouncementBody — unsafe URL schemes never reach an href", () => {
  it("drops a javascript: link from Markdown link syntax", () => {
    const el = parse("[click](javascript:window.__pwned=1)");
    const hrefs = Array.from(el.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.some((h) => h.toLowerCase().startsWith("javascript:"))).toBe(false);
  });

  it("drops a data: link from Markdown link syntax", () => {
    const el = parse("[click](data:text/html;base64,PHNjcmlwdD4x)");
    const hrefs = Array.from(el.querySelectorAll("a")).map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.some((h) => h.toLowerCase().startsWith("data:"))).toBe(false);
  });

  it("does not emit a live anchor from a raw HTML javascript: anchor", () => {
    const el = parse('<a href="javascript:window.__pwned=1">click</a>');
    expect(el.querySelector("a")).toBeNull();
  });
});

/**
 * `img` is off the allow-list on purpose: a Markdown image needs no raw HTML, so
 * "no raw HTML" does not stop it. An embedded remote image beacons each
 * recipient's IP, user-agent and read time to a chosen host. Not XSS, but not
 * the intended reach of an internal notice.
 */
describe("AnnouncementBody — no author-triggered external requests", () => {
  it("drops a remote image from Markdown image syntax", () => {
    const el = parse("![alt](https://evil.example/pixel.png)");
    expect(el.querySelector("img")).toBeNull();
    // Serialize with XMLSerializer (not .innerHTML) to assert the URL string is
    // absent anywhere in the rendered markup, without an innerHTML reference.
    expect(new XMLSerializer().serializeToString(el)).not.toContain("evil.example");
  });

  it("drops a remote image written as raw HTML", () => {
    const el = parse('<img src="https://evil.example/pixel.png">');
    expect(el.querySelector("img")).toBeNull();
  });

  it("emits no element carrying a remote subresource URL", () => {
    const el = parse(
      "![a](https://evil.example/a.png)\n\n" +
      "<video src=\"https://evil.example/v.mp4\"></video>\n\n" +
      "<audio src=\"https://evil.example/a.mp3\"></audio>\n\n" +
      "<source srcset=\"https://evil.example/s.png\">",
    );
    expect(el.querySelectorAll("img, video, audio, source, picture, track").length).toBe(0);
    // Anchors are fine: they need a click and leak nothing on render.
    for (const el2 of Array.from(el.querySelectorAll("*"))) {
      for (const attr of Array.from(el2.attributes)) {
        if (attr.name.toLowerCase() === "href") continue;
        expect(attr.value).not.toContain("evil.example");
      }
    }
  });
});

describe("AnnouncementBody — legitimate Markdown still renders", () => {
  it("renders emphasis, code and lists", () => {
    const el = parse("**bold** and _em_ and `code`\n\n- a\n- b");
    expect(el.querySelector("strong")?.textContent).toBe("bold");
    expect(el.querySelector("em")?.textContent).toBe("em");
    expect(el.querySelector("code")?.textContent).toBe("code");
    expect(Array.from(el.querySelectorAll("li")).map((li) => li.textContent)).toEqual(["a", "b"]);
  });

  it("renders https links, hardened with target and rel", () => {
    const a = parse("[link](https://aws.amazon.com)").querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://aws.amazon.com");
    // Link hardening (US-11.5 parity): open in a new tab, no window handle back.
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("autolinks a bare URL (remark-gfm)", () => {
    const a = parse("see https://aws.amazon.com for more").querySelector("a");
    expect(a?.getAttribute("href")).toBe("https://aws.amazon.com");
  });

  // Guards the allow-list against being too NARROW: every element here is one an
  // author produces with ordinary Markdown (GFM tables + strikethrough
  // included), so none may be silently swallowed.
  it("renders every non-image construct authored Markdown produces", () => {
    const el = parse(
      "# h1\n\n## h2\n\n### h3\n\n#### h4\n\n##### h5\n\n###### h6\n\n" +
      "para with ~~strike~~\n\n" +
      "> quote\n\n" +
      "- ul\n\n1. ol\n\n" +
      "```\nfenced\n```\n\n" +
      "| left | right |\n|:-----|------:|\n| a    | b     |\n\n" +
      "---\n",
    );
    for (const tag of [
      "h1", "h2", "h3", "h4", "h5", "h6", "p", "del", "blockquote",
      "ul", "ol", "li", "pre", "code", "table", "thead", "tbody", "tr", "th", "td", "hr",
    ]) {
      expect(el.querySelector(tag), `expected <${tag}> to survive`).not.toBeNull();
    }
  });

  it("preserves soft line breaks (remark-breaks parity with breaks:true)", () => {
    expect(parse("line one\nline two").querySelector("br")).not.toBeNull();
  });

  it("renders text containing comparison operators without corrupting it", () => {
    expect(parse("5 < 6 & 7 > 2").textContent).toContain("5 < 6 & 7 > 2");
  });

  it("renders nothing for empty input", () => {
    expect(parse("").querySelector("*")).toBeNull();
  });
});
