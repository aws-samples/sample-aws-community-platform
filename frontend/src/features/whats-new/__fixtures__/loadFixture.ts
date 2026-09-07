import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

/**
 * Fixture loading for the What's New tests.
 *
 * `import.meta.url` is not a file: URL under the jsdom test environment, so
 * fixtures are resolved from the repository root instead. The root is found by
 * walking up from the working directory until the canonical sample feed is
 * visible, which keeps the tests working whether they are launched from
 * `frontend/` (npm test) or from the repo root (make test).
 */

function repoRoot(): string {
  let dir = process.cwd();
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(resolve(dir, "infra/whats-new-feed/whats-new-sample.xml"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(
    `Could not locate the repository root from ${process.cwd()} — `
    + "infra/whats-new-feed/whats-new-sample.xml was not found.",
  );
}

/**
 * The canonical mirror sample (DW-15). Read from infra/ rather than a copy so
 * the reference feed handed to the mirror maintainer and the feed under test
 * cannot drift apart.
 */
export function loadSampleFeed(): string {
  return readFileSync(resolve(repoRoot(), "infra/whats-new-feed/whats-new-sample.xml"), "utf8");
}

/**
 * The adversarial fixture for sanitizer tests. Deliberately lives in the
 * frontend test tree, not in infra/, so it can never be published as mirror
 * content.
 */
export function loadHostileFeed(): string {
  return readFileSync(
    resolve(repoRoot(), "frontend/src/features/whats-new/__fixtures__/hostile-feed.xml"),
    "utf8",
  );
}
