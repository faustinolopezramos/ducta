import { describe, expect, it } from "vitest";
import { paramToText, textToParam } from "./checkParams";

describe("check parameter fields", () => {
  it("round-trips the common types", () => {
    expect(textToParam("12", { type: "integer" })).toBe(12);
    expect(() => textToParam("1.5", { type: "integer" })).toThrow("whole number");
    expect(textToParam("0.25", { type: "number" })).toBe(0.25);
    expect(textToParam("yes", { type: "boolean" })).toBe(true);
    expect(textToParam("a, b ,c", { type: "array" })).toEqual(["a", "b", "c"]);
    expect(paramToText(["a", "b"], { type: "array" })).toBe("a, b");
    expect(textToParam('{"k": 1}', { type: "object" })).toEqual({ k: 1 });
    expect(textToParam("", { type: "string" })).toBeUndefined();
    expect(textToParam("G3", { type: "string" })).toBe("G3");
  });
});
