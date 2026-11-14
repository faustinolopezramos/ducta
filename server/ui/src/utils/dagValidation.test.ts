import { describe, expect, it } from "vitest";
import { computeLevels, hasCycle, topologicalSort } from "./dagValidation";

describe("computeLevels", () => {
  it("puts every node at level 0 in a pipeline with no dependencies", () => {
    const nodes = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const levels = computeLevels(nodes);
    expect(levels).not.toBeNull();
    expect([...levels!.values()]).toEqual([0, 0, 0]);
  });

  it("stacks a linear chain one level per node", () => {
    const nodes = [
      { id: "a" },
      { id: "b", dependencies: ["a"] },
      { id: "c", dependencies: ["b"] },
    ];
    const levels = computeLevels(nodes);
    expect(levels!.get("a")).toBe(0);
    expect(levels!.get("b")).toBe(1);
    expect(levels!.get("c")).toBe(2);
  });

  it("keeps independent branches at the same level (side by side)", () => {
    const nodes = [
      { id: "a" },
      { id: "b" }, // no relation to "a" — same level
      { id: "c", dependencies: ["a"] },
      { id: "d", dependencies: ["b"] },
    ];
    const levels = computeLevels(nodes);
    expect(levels!.get("a")).toBe(0);
    expect(levels!.get("b")).toBe(0);
    expect(levels!.get("c")).toBe(1);
    expect(levels!.get("d")).toBe(1);
  });

  it("places a join node one level below its deepest dependency", () => {
    const nodes = [
      { id: "a" },
      { id: "b", dependencies: ["a"] },
      { id: "c", dependencies: ["a"] },
      { id: "d", dependencies: ["b", "c"] },
      { id: "e", dependencies: ["d"] },
    ];
    const levels = computeLevels(nodes);
    expect(levels!.get("a")).toBe(0);
    expect(levels!.get("b")).toBe(1);
    expect(levels!.get("c")).toBe(1);
    expect(levels!.get("d")).toBe(2);
    expect(levels!.get("e")).toBe(3);
  });

  it("resolves dependencies given by name instead of id", () => {
    const nodes = [
      { id: "n1", name: "extract" },
      { id: "n2", name: "transform", dependencies: ["extract"] },
    ];
    const levels = computeLevels(nodes);
    expect(levels!.get("n1")).toBe(0);
    expect(levels!.get("n2")).toBe(1);
  });

  it("returns null for a cyclic graph instead of throwing", () => {
    const nodes = [
      { id: "a", dependencies: ["b"] },
      { id: "b", dependencies: ["a"] },
    ];
    expect(hasCycle(nodes)).not.toBeNull();
    expect(computeLevels(nodes)).toBeNull();
  });

  it("agrees with topologicalSort on ordering for a branched graph", () => {
    const nodes = [
      { id: "a" },
      { id: "b", dependencies: ["a"] },
      { id: "c", dependencies: ["a"] },
      { id: "d", dependencies: ["b", "c"] },
    ];
    const levels = computeLevels(nodes)!;
    const sorted = topologicalSort(nodes)!;
    const sortedLevels = sorted.map((n) => levels.get(n.id));
    expect(sortedLevels).toEqual([...sortedLevels].sort((x, y) => (x ?? 0) - (y ?? 0)));
  });
});
