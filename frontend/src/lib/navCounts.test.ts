import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bumpNavCounts, onNavCountsRefresh } from "./navCounts";

describe("navCounts pub/sub", () => {
  const unsubscribers: Array<() => void> = [];
  afterEach(() => { unsubscribers.splice(0).forEach((u) => u()); });

  const subscribe = (fn: () => void) => { unsubscribers.push(onNavCountsRefresh(fn)); };

  it("notifies every subscriber when bumped", () => {
    const a = vi.fn();
    const b = vi.fn();
    subscribe(a);
    subscribe(b);
    bumpNavCounts();
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("stops notifying after unsubscribe", () => {
    // AppLayout returns this from useEffect, so a leak here would keep calling
    // setState on an unmounted shell.
    const fn = vi.fn();
    const off = onNavCountsRefresh(fn);
    off();
    bumpNavCounts();
    expect(fn).not.toHaveBeenCalled();
  });

  it("is safe to bump with nobody listening", () => {
    expect(() => bumpNavCounts()).not.toThrow();
  });
});

describe("every screen that empties a badge-backed queue bumps the nav counts", () => {
  /* THE REGRESSION GUARD.
   *
   * The sidebar's pending-count pills are fetched by AppLayout and share no
   * cache with the screens that act on those queues, so a screen must announce
   * a decision via bumpNavCounts() or the pill goes stale. That is invisible
   * locally: the screen's own list refetches from its local nonce and looks
   * right, while the sidebar keeps the old number.
   *
   * It shipped exactly that way — a UGL who approved the last join request saw
   * "Pending Join Requests (0)" on the page and "(1)" on My Group in the nav.
   *
   * This repo has no React Testing Library, so the call site cannot be asserted
   * by rendering. Reading the source is the available guard, and it is the same
   * approach already used for the scheduled-jobs infra drift test.
   */
  const OWNERS: Array<[string, string]> = [
    ["features/MyGroupPage.tsx", "UGL join-request decisions; member removal also rejects their pending submissions and claims"],
    ["features/GroupDetailPage.tsx", "member removal and group soft-delete reject pending submissions and claims"],
    ["features/pages.tsx", "CL groups + join requests, including group soft-delete"],
    ["features/CertificationsPage.tsx", "certification verification decisions"],
    ["features/ContributionsPage.tsx", "contribution approval decisions"],
  ];

  it.each(OWNERS)("%s calls bumpNavCounts (%s)", (relPath) => {
    const src = readFileSync(join(__dirname, "..", relPath), "utf8");
    expect(src).toContain('from "../lib/navCounts"');
    expect(src).toMatch(/bumpNavCounts\(\)/);
  });
});
