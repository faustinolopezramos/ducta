import { describe, expect, it } from "vitest";
import { collapseRepeats, logMatcher } from "./logFilter";

const e = (message: string, level = "INFO") => ({ id: message + Math.random(), timestamp: 0, level, message }) as any;

describe("log search", () => {
  it("matches text, or a /regex/", () => {
    expect(logMatcher("spark").test("Starting SPARK session")).toBe(true);
    expect(logMatcher("/node '(silver|gold)\\./").test("node 'silver.clean' failed")).toBe(true);
    expect(logMatcher("/node 'bronze/").test("node 'silver.clean' failed")).toBe(false);
  });
  it("says when the pattern is not a regex", () => {
    const m = logMatcher("/([/");
    expect(m.error).toBeTruthy();
    expect(m.test("anything")).toBe(false);
  });
});

describe("repeats", () => {
  it("folds consecutive identical lines into one with a count", () => {
    const out = collapseRepeats([e("retrying"), e("retrying"), e("retrying"), e("ok"), e("retrying")]);
    expect(out.map((x) => [x.message, x.repeat ?? 1])).toEqual([["retrying", 3], ["ok", 1], ["retrying", 1]]);
  });
});
