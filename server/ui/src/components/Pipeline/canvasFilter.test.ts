import { describe, expect, it } from "vitest";
import { matchNodes } from "./canvasFilter";

const items = [
  { id: "silver.clean", fn: "clean", dependsOn: [], outputs: [{ id: "o", name: "silver.x" }] },
  { id: "gold.agg", fn: "agg", dependsOn: [], metadata: { tags: ["finance"] } },
  { id: "bronze.load", dependsOn: [] },
] as any[];
const layerOf = (i: any) => i.id.split(".")[0];

describe("matchNodes", () => {
  it("shows everything when nothing is filtered", () => {
    expect(matchNodes(items, { query: "", facets: [] }, {})).toBeNull();
  });
  it("searches names, functions, datasets and tags", () => {
    expect([...matchNodes(items, { query: "silver.x", facets: [] }, {})!]).toEqual(["silver.clean"]);
    expect([...matchNodes(items, { query: "finance", facets: [] }, {})!]).toEqual(["gold.agg"]);
  });
  it("widens within a kind, narrows across kinds", () => {
    const ctx = { layerOf, freshness: { "gold.agg": "stale", "bronze.load": "stale" } };
    expect([...matchNodes(items, { query: "", facets: ["gold", "bronze"] }, ctx)!].sort()).toEqual(["bronze.load", "gold.agg"]);
    expect([...matchNodes(items, { query: "", facets: ["stale", "gold"] }, ctx)!]).toEqual(["gold.agg"]);
  });
  it("filters on problems and failures", () => {
    const ctx = { problems: new Map([["silver.clean", "error"]]), runState: { "bronze.load": "failed" } };
    expect([...matchNodes(items, { query: "", facets: ["problems", "failed"] }, ctx)!].sort()).toEqual(["bronze.load", "silver.clean"]);
  });
});
