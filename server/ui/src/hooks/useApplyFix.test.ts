import { describe, expect, it } from "vitest";
import { replaceInText } from "./useApplyFix";

describe("replaceInText", () => {
  const yaml = "nodes:\n  a:\n    descripton: x\n    inputs: {raw: raw_ordrs}\n";

  it("replaces on the problem's line", () => {
    expect(replaceInText(yaml, 3, "descripton", "description")).toBe(
      "nodes:\n  a:\n    description: x\n    inputs: {raw: raw_ordrs}\n",
    );
  });

  it("falls back to the first whole-word occurrence when the line moved", () => {
    expect(replaceInText(yaml, 1, "raw_ordrs", "raw_orders")).toContain("{raw: raw_orders}");
  });

  it("never touches a longer name that merely contains the word", () => {
    expect(replaceInText("a: silver.x_y\nb: x\n", null, "x", "z")).toBe("a: silver.x_y\nb: z\n");
  });

  it("is null when the word is gone", () => {
    expect(replaceInText(yaml, 3, "nothing", "x")).toBeNull();
  });
});
