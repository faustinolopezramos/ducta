import { describe, expect, it } from "vitest";
import { graphDepth } from "./RunGraph";

describe("graphDepth", () => {
  it("is one row for independent nodes", () => {
    expect(graphDepth([{ id: "a" }, { id: "b" }])).toBe(1);
  });

  it("follows the longest chain", () => {
    expect(graphDepth([{ id: "a" }, { id: "b", dependsOn: ["a"] }, { id: "c", dependsOn: ["b", "a"] }])).toBe(3);
  });

  it("survives a cycle", () => {
    expect(graphDepth([{ id: "a", dependsOn: ["b"] }, { id: "b", dependsOn: ["a"] }])).toBeGreaterThan(0);
  });
});
