import { describe, expect, it } from "vitest";
import { paramValueHint } from "./RunChecksModal";

describe("paramValueHint", () => {
  it("describes a parameter's value from its schema", () => {
    expect(paramValueHint({ type: "string", enum: ["psi", "ks"] })).toBe("psi | ks");
    expect(paramValueHint({ type: "number", minimum: 0, maximum: 1 })).toBe("number 0–1");
    expect(paramValueHint({ type: "array" })).toBe("[list]");
    expect(paramValueHint({ type: ["number", "string"] })).toBe("number or string");
  });

  it("falls back to the generic hint for a parameter it does not know", () => {
    expect(paramValueHint(undefined)).toBe("value (numbers/booleans/[lists] auto-detected)");
  });
});
