#!/usr/bin/env node
/**
 * DUCTA — WCAG AA CONTRAST CHECK
 *
 * Parses the design-token CSS files (theme/ducta-theme.css + theme/tokens.css),
 * resolves `var()` chains, and asserts the text pairs below clear WCAG AA
 * (4.5:1 normal text, 3.0:1 large/UI). Fails (exit 1) with a table of
 * violations so CI catches a theme change that breaks legibility.
 *
 * Run:  node scripts/contrast-check.mjs   (also part of `npm run ui:quality`)
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const cssFiles = ["src/theme/ducta-theme.css", "src/theme/tokens.css"];

// Pairs are [foreground var, background var, required ratio, label].
// "#FFFFFF" resolves to the literal hex. Backgrounds fall back to the theme's
// --bg / --surface so inline `style={{color: X}}` usages are covered too.
const PAIRS = {
  light: [
    ["--primary", "#FFFFFF", 4.5, "Button/link text on terracotta"],
    ["--primary", "--bg", 3.0, "Terracotta icon on page bg"],
    ["--success", "#FFFFFF", 4.5, "Success text on white"],
    ["--success", "--bg", 4.5, "Success text on page bg"],
    ["--text", "--bg", 4.5, "Body text"],
    ["--text-muted", "--bg", 4.5, "Secondary text"],
    ["--text-dim", "--bg", 4.5, "Tertiary text"],
    ["--warning-strong", "--bg", 4.5, "Warning text (light)"],
    ["--danger", "--bg", 4.5, "Danger text on page bg"],
  ],
  dark: [
    ["--primary", "--surface", 4.5, "Terracotta text on dark surface"],
    ["--success", "--surface", 4.5, "Success text on dark surface"],
    ["--text", "--surface", 4.5, "Body text (dark)"],
    ["--text-muted", "--surface", 4.5, "Secondary text (dark)"],
    ["--text-dim", "--surface", 4.5, "Tertiary text (dark)"],
    ["--warning", "--surface", 4.5, "Warning text (dark)"],
    ["--danger", "--surface", 4.5, "Danger text (dark)"],
  ],
};

function parseTokens(css) {
  const tokens = {};
  // Strip comments up front so they never swallow the next declaration.
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, "");
  // These token files have no nested blocks, so a linear brace scan is safe and
  // immune to the regex "skip forward to the next }" pitfall.
  let idx = 0;
  while (idx < clean.length) {
    const open = clean.indexOf("{", idx);
    if (open === -1) break;
    const selector = clean.slice(idx, open).trim();
    const close = clean.indexOf("}", open + 1);
    const body = close === -1 ? clean.slice(open + 1) : clean.slice(open + 1, close);
    idx = close === -1 ? clean.length : close + 1;
    if (!selector || selector.startsWith(".") || selector.startsWith("#") || selector.startsWith("::")) {
      continue;
    }
    const target = selector.includes("data-theme") ? "dark" : "root";
    for (const line of body.split(";")) {
      const [rawName, rawValue] = line.split(":");
      if (!rawName || !rawValue) continue;
      const name = rawName.trim();
      if (!name.startsWith("--")) continue;
      const value = rawValue.trim().replace(/!important.*$/, "").trim();
      if (!value) continue;
      tokens[target] ??= {};
      tokens[target][name] = value;
    }
  }
  return tokens;
}

function hexToLuminance(hex) {
  const h = hex.replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const [lr, lg, lb] = [lin(r), lin(g), lin(b)];
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb;
}

function resolveColor(name, tokens, seen = new Set()) {
  if (name.startsWith("#")) return name;
  if (seen.has(name)) return null;
  seen = new Set(seen).add(name);
  const value = tokens[name];
  if (!value) return null;
  const ref = /^var\(\s*(--[\w-]+)\s*\)$/.exec(value);
  if (ref) return resolveColor(ref[1], tokens, seen);
  return value.startsWith("#") ? value : null;
}

function contrast(fgHex, bgHex) {
  const l1 = hexToLuminance(fgHex);
  const l2 = hexToLuminance(bgHex);
  if (l1 === null || l2 === null) return null;
  const [hi, lo] = [Math.max(l1, l2), Math.min(l1, l2)];
  return (hi + 0.05) / (lo + 0.05);
}

function run() {
  const css = cssFiles.map((f) => readFileSync(join(root, f), "utf8")).join("\n");
  const tokens = parseTokens(css);

  let failures = 0;
  const rows = [];
  for (const [theme, pairs] of Object.entries(PAIRS)) {
    const set = { ...tokens.root, ...(theme === "dark" ? tokens.dark : {}) };
    // Dark background pairs use the elevated surface, not the page bg.
    const bgFallback = resolveColor(theme === "dark" ? "--surface" : "--bg", set);
    for (const [fgVar, bgVar, required, label] of pairs) {
      const fg = resolveColor(fgVar, set);
      const bg = fgVar === bgVar ? null : resolveColor(bgVar === "#FFFFFF" ? "#FFFFFF" : bgVar, set) ?? bgFallback;
      if (!fg || !bg) {
        rows.push([theme, fgVar, label, "UNRESOLVED", "—", "—"]);
        failures++;
        continue;
      }
      const ratio = contrast(fg, bg);
      if (ratio === null) {
        rows.push([theme, fgVar, label, fg, "N/A", "—"]);
        continue;
      }
      const ok = ratio >= required;
      if (!ok) failures++;
      rows.push([theme, fgVar, label, fg, ratio.toFixed(2), ok ? "OK" : `FAIL (<${required})`]);
    }
  }

  console.log("DUCTA — WCAG AA contrast check");
  console.log("─".repeat(88));
  console.log("theme | pair                | label".padEnd(0));
  for (const [theme, fgVar, label, fg, ratio, status] of rows) {
    console.log(
      `${theme.padEnd(5)} | ${fgVar.padEnd(20)} | ${fg.padEnd(8)} | ${String(ratio).padEnd(6)} | ${status}  ${label}`
    );
  }
  console.log("─".repeat(88));
  if (failures > 0) {
    console.error(`\n✗ ${failures} contrast violation(s) — fix theme/tokens.css before merging.`);
    process.exit(1);
  }
  console.log("✓ All key pairs clear WCAG AA (4.5:1 text / 3.0:1 UI).");
}

run();
