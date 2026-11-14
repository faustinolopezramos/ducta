#!/usr/bin/env node
/**
 * DUCTA UI — QUALITY GATE (`npm run ui:quality`)
 *
 * Fail-fast checks that keep the design system honest. Each check exits 1 on
 * violation so the gate can run in CI:
 *
 *   1. WCAG AA contrast on the design-token pairs (scripts/contrast-check.mjs)
 *   2. No legacy hardcoded colors in the tokens compatibility map (tokens.ts)
 *
 * Run:  npm run ui:quality
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
let failed = false;

function fail(msg) {
  console.error(`✗ ${msg}`);
  failed = true;
}

// ── Check 1: WCAG AA contrast ────────────────────────────────────────────────
console.log("▶ Contrast check (WCAG AA)");
try {
  execFileSync(process.execPath, ["scripts/contrast-check.mjs"], {
    cwd: root,
    stdio: "inherit",
  });
} catch {
  failed = true;
}

// ── Check 2: legacy hardcoded colors in tokens.ts ────────────────────────────
console.log("\n▶ Legacy token values");
const tokensTs = readFileSync(join(root, "src/theme/tokens.ts"), "utf8");
const LEGACY_PATTERNS = [
  ["#7928CA", "legacy purple hex"],
  ["rgba(245, 166, 35", "legacy amber rgb"],
  ["rgba(0, 112, 243)", "legacy Vercel blue"],
];
for (const [pattern, label] of LEGACY_PATTERNS) {
  if (tokensTs.includes(pattern)) {
    fail(`tokens.ts still contains ${label} (${pattern}) — derive it from a theme token instead.`);
  }
}
// The whole compatibility map must reference theme tokens, not raw hex/rgb.
const HARDCODED = /(?:^|,\s*)(?:purple|amberA10|amberA12|amberA15|amberA20|amberA30|blueA12|blueA15|blueA30|slateA12|grayA12|purpleA15|orangeA15|blue)\s*:\s*"(?:#|rgba)/m;
if (HARDCODED.test(tokensTs)) {
  fail("tokens.ts compatibility map contains a hardcoded color — use var()/color-mix() on theme tokens.");
}

// ── Summary ──────────────────────────────────────────────────────────────────
console.log("");
if (failed) {
  console.error("✗ ui:quality FAILED — fix the violations above.");
  process.exit(1);
}
console.log("✓ ui:quality passed (contrast + token hygiene).");
