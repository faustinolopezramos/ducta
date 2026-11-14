import { describe, expect, it } from "vitest";
import { collapseGroups, groupsOf, worstState } from "./canvasGroups";
import type { DagCanvasItem } from "./types";

const port = (name: string) => ({ id: name, name });
const items: DagCanvasItem[] = [
  { id: "bronze.ingest", inputs: [], outputs: [port("raw")], dependsOn: [] },
  { id: "silver.a", inputs: [port("raw")], outputs: [port("tmp")], dependsOn: ["bronze.ingest"] },
  { id: "silver.b", inputs: [port("tmp")], outputs: [port("clean")], dependsOn: ["silver.a"] },
  { id: "gold.agg", inputs: [port("clean")], outputs: [port("agg")], dependsOn: ["silver.b"] },
];

describe("canvas groups", () => {
  it("only namespaces with two or more nodes are groups", () => {
    expect([...groupsOf(items).keys()]).toEqual(["silver"]);
  });

  it("draws a collapsed group as one box with what crosses its border", () => {
    const out = collapseGroups(items, new Set(["silver"]));
    expect(out.map((i) => i.id)).toEqual(["bronze.ingest", "group:silver", "gold.agg"]);
    const box = out[1];
    expect(box.inputs!.map((p) => p.name)).toEqual(["raw"]);
    expect(box.outputs!.map((p) => p.name)).toEqual(["clean"]);
    expect(box.dependsOn).toEqual(["bronze.ingest"]);
    expect(out[2].dependsOn).toEqual(["group:silver"]);
  });

  it("leaves the canvas alone when nothing is collapsed", () => {
    expect(collapseGroups(items, new Set())).toBe(items);
  });

  it("takes the worst member state", () => {
    expect(worstState(["success", "failed", undefined])).toBe("failed");
    expect(worstState([undefined])).toBeUndefined();
  });
});
