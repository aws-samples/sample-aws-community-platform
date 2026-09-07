// Generates TypeScript types for every service from contracts/services/<svc>/openapi.yaml
// using openapi-typescript (Q9). Output -> src/generated/<svc>.d.ts (git-ignored).
// Regenerate whenever contracts change so the SPA stays in lockstep (single source of truth).
import { execSync } from "node:child_process";
import { mkdirSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const contractsDir = join(here, "..", "..", "contracts", "services");
const outDir = join(here, "..", "src", "generated");
mkdirSync(outDir, { recursive: true });

if (!existsSync(contractsDir)) {
  console.log("No contracts/services yet — nothing to generate.");
  process.exit(0);
}

for (const svc of readdirSync(contractsDir)) {
  const spec = join(contractsDir, svc, "openapi.yaml");
  if (!existsSync(spec)) continue;
  const out = join(outDir, `${svc}.d.ts`);
  console.log(`Generating types for ${svc} -> src/generated/${svc}.d.ts`);
  execSync(`npx openapi-typescript "${spec}" -o "${out}"`, { stdio: "inherit" });
}
console.log("API types generated.");
