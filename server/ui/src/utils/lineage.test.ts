import { describe, it, expect } from "vitest";
import { computeLineage, lensEdgeClass } from "./lineage";

// Diamond with a tail:
//   a → b → d → e
//   a → c → d
//   f (isolated)
const parents = new Map<string, string[]>([
  ["a", []],
  ["b", ["a"]],
  ["c", ["a"]],
  ["d", ["b", "c"]],
  ["e", ["d"]],
  ["f", []],
]);

describe("computeLineage", () => {
  it("returns null when nothing is selected", () => {
    expect(computeLineage(null, parents)).toBeNull();
    expect(computeLineage(undefined, parents)).toBeNull();
  });

  it("walks upstream with depth", () => {
    const lineage = computeLineage("d", parents)!;
    expect(lineage.upstream.get("b")).toBe(1);
    expect(lineage.upstream.get("c")).toBe(1);
    expect(lineage.upstream.get("a")).toBe(2);
    expect(lineage.upstream.has("e")).toBe(false);
    expect(lineage.upstream.has("f")).toBe(false);
  });

  it("walks downstream with depth", () => {
    const lineage = computeLineage("a", parents)!;
    expect(lineage.downstream.get("b")).toBe(1);
    expect(lineage.downstream.get("c")).toBe(1);
    expect(lineage.downstream.get("d")).toBe(2);
    expect(lineage.downstream.get("e")).toBe(3);
    expect(lineage.upstream.size).toBe(0);
  });

  it("never includes the selected node in either set", () => {
    const lineage = computeLineage("d", parents)!;
    expect(lineage.upstream.has("d")).toBe(false);
    expect(lineage.downstream.has("d")).toBe(false);
  });

  it("uses shortest distance on diamond joins", () => {
    // e's upstream: d=1, b=2, c=2, a=3 (via either branch)
    const lineage = computeLineage("e", parents)!;
    expect(lineage.upstream.get("a")).toBe(3);
  });
});

describe("lensEdgeClass", () => {
  const lineage = computeLineage("d", parents)!;

  it("is empty with no lens", () => {
    expect(lensEdgeClass(null, "a", "b")).toBe("");
  });

  it("marks edges on the upstream path", () => {
    expect(lensEdgeClass(lineage, "b", "d")).toBe("dag-edge-up");
    expect(lensEdgeClass(lineage, "a", "b")).toBe("dag-edge-up");
  });

  it("marks edges on the downstream path", () => {
    expect(lensEdgeClass(lineage, "d", "e")).toBe("dag-edge-down");
  });

  it("dims edges outside the lineage", () => {
    // f is unrelated to d entirely
    expect(lensEdgeClass(lineage, "f", "e")).toBe("dag-edge-dimmed");
  });
});
