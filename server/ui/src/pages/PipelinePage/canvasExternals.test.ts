import { describe, expect, it } from "vitest";
import { externalEnds } from "./canvasExternals";

const items = [
  { id: "g1", dependsOn: [], inputs: [{ id: "i", name: "silver.a" }], outputs: [{ id: "o", name: "gold.a" }] },
  { id: "g2", dependsOn: [], inputs: [{ id: "i", name: "kafka:events" }], outputs: [{ id: "o", name: "gold.b" }] },
];
const datasets = [
  { name: "silver.a", declared_in: [], producers: [{ node: "s", pipeline: "silver.clean" }], consumers: [] },
  { name: "gold.a", declared_in: [], producers: [], consumers: [{ node: "m", pipeline: "ml.risk" }, { node: "n", pipeline: "ml.perf" }] },
  { name: "gold.b", declared_in: [], producers: [], consumers: [] },
];

describe("externalEnds", () => {
  it("says where each border dataset comes from and goes", () => {
    expect(externalEnds(items, datasets, "golden")).toEqual([
      { dataset: "kafka:events", side: "in", note: "external source", pipeline: null },
      { dataset: "silver.a", side: "in", note: "from silver.clean", pipeline: "silver.clean" },
      { dataset: "gold.a", side: "out", note: "to ml.risk, ml.perf", pipeline: "ml.risk" },
      { dataset: "gold.b", side: "out", note: "not read by any pipeline", pipeline: null },
    ]);
  });
});
