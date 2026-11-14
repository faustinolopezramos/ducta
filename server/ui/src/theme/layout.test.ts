import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The app's scroll chain, asserted against the stylesheets themselves.
 *
 * jsdom does not do layout, so a rendering test cannot catch this class of bug.
 * What can be checked is the rule that produces it: in a flex column an item
 * defaults to `min-height: auto` and refuses to shrink below its content, so an
 * `overflow-y: auto` pane without `min-height: 0` never scrolls — it grows past
 * its container and is clipped by whichever ancestor sets `overflow: hidden`.
 *
 * That is exactly what happened to `.ducta-content`: every module longer than
 * the viewport had its bottom silently cut off, with no scrollbar to reveal it.
 *
 * Only base rules are considered. These stylesheets put top-level rules at
 * column 0 and indent anything inside an `@media` block, which is a sturdier
 * way to tell them apart here than hand-rolling a CSS parser.
 */

const THEME_DIR = __dirname;

interface Rule {
  selectors: string[];
  body: string;
}

/** Top-level rules of a stylesheet, in source order. */
function baseRules(source: string): Rule[] {
  // Comments first: a banner comment sits at column 0 too, so leaving them in
  // makes the scan swallow one and glue it onto the selector that follows.
  const css = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: Rule[] = [];
  // A selector list starting at column 0, then everything up to the first `}`.
  const re = /^([^\s@}][^{}]*)\{([^{}]*)\}/gm;
  let match: RegExpExecArray | null;
  while ((match = re.exec(css)) !== null) {
    rules.push({
      selectors: match[1].split(",").map((s) => s.trim()).filter(Boolean),
      body: match[2],
    });
  }
  return rules;
}

function readRules(file: string): Rule[] {
  return baseRules(readFileSync(join(THEME_DIR, file), "utf8"));
}

function bodyOf(rules: Rule[], selector: string): string | null {
  const hit = rules.find((r) => r.selectors.includes(selector));
  return hit ? hit.body : null;
}

describe("the app's scroll pane", () => {
  const layout = readRules("layout.css");

  it("lets the content pane shrink below its content", () => {
    const body = bodyOf(layout, ".ducta-content");
    expect(body, ".ducta-content rule not found").not.toBeNull();
    expect(body).toMatch(/min-height:\s*0/);
    expect(body).toMatch(/overflow-y:\s*auto/);
  });

  it("lets the column that holds it shrink too", () => {
    const body = bodyOf(layout, ".ducta-main-container");
    expect(body, ".ducta-main-container rule not found").not.toBeNull();
    expect(body).toMatch(/min-height:\s*0/);
  });

  it("keeps the chrome above the pane from being squashed", () => {
    // Without this the header and breadcrumbs give up their height to a tall
    // page instead of the pane absorbing the slack.
    for (const selector of [".ducta-header", ".ducta-breadcrumbs"]) {
      const body = bodyOf(layout, selector);
      expect(body, `${selector} rule not found`).not.toBeNull();
      expect(body).toMatch(/flex-shrink:\s*0/);
    }
  });

  it("still clips at the root, which is what makes the pane necessary", () => {
    const body = bodyOf(layout, ".ducta-app-layout");
    expect(body, ".ducta-app-layout rule not found").not.toBeNull();
    expect(body).toMatch(/overflow:\s*hidden/);
  });
});

describe("the page container", () => {
  // It lives beside the component rather than in theme/, so it is read by path.
  const rules = baseRules(
    readFileSync(join(THEME_DIR, "..", "components", "ui", "PageContainer.css"), "utf8")
  );

  it("declares an explicit width", () => {
    // The router wraps every page in `.page-transition`, a flex column. A flex
    // item with `auto` cross-axis margins stops stretching and is sized to its
    // content, so `margin-inline: auto` alone collapsed each module to the
    // width of its widest child and centred it — a narrow strip of UI on a wide
    // screen. `width: 100%` is what makes the module fill the window.
    const body = rules.find((r) => r.selectors.includes(".page-container"))?.body;
    expect(body, ".page-container rule not found").toBeTruthy();
    expect(body).toMatch(/width:\s*100%/);
  });
});

describe("every flex scroll pane in the theme", () => {
  it("declares min-height: 0", () => {
    const offenders: string[] = [];

    for (const file of readdirSync(THEME_DIR).filter((f) => f.endsWith(".css"))) {
      for (const rule of readRules(file)) {
        const scrolls = /overflow(-y)?:\s*(auto|scroll)/.test(rule.body);
        const grows = /flex:\s*1|flex-grow:\s*1/.test(rule.body);
        const canShrink = /min-height:\s*0/.test(rule.body);
        if (scrolls && grows && !canShrink) {
          offenders.push(`${file}: ${rule.selectors.join(", ")}`);
        }
      }
    }

    expect(
      offenders,
      "these grow with their content instead of scrolling — add `min-height: 0`:\n" +
        offenders.join("\n")
    ).toEqual([]);
  });
});
