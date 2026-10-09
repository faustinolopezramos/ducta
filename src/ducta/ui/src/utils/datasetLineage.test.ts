import { describe, expect, it } from "vitest";
import { datasetLineage } from "./datasetLineage";
import type { ProjectDataset } from "../api/queries/datasets";

const ds = (name: string, producers: [string, string][], consumers: [string, string][]): ProjectDataset => ({
  name,
  declared_in: [],
  producers: producers.map(([node, pipeline]) => ({ node, pipeline })),
  consumers: consumers.map(([node, pipeline]) => ({ node, pipeline })),
});

// raw → [ingest] → bronze → [clean] → silver → [agg] → gold ; silver → [score] → ml
const project = [
  ds("raw", [], [["ingest", "bronze.p"]]),
  ds("bronze", [["ingest", "bronze.p"]], [["clean", "silver.p"]]),
  ds("silver", [["clean", "silver.p"]], [["agg", "gold.p"], ["score", "ml.p"]]),
  ds("gold", [["agg", "gold.p"]], []),
  ds("ml", [["score", "ml.p"]], []),
];

describe("datasetLineage", () => {
  it("walks upstream and downstream by hops, across pipelines", () => {
    const l = datasetLineage(project, "bronze");
    expect(l.upstream).toEqual([{ hop: 1, datasets: ["raw"] }]);
    expect(l.downstream).toEqual([
      { hop: 1, datasets: ["silver"] },
      { hop: 2, datasets: ["gold", "ml"] },
    ]);
  });

  it("limits the hops it shows, never the impact", () => {
    const l = datasetLineage(project, "bronze", 1);
    expect(l.downstream).toEqual([{ hop: 1, datasets: ["silver"] }]);
    expect(l.impact.pipelines).toEqual(["gold.p", "ml.p", "silver.p"]);
    expect(l.impact.datasets).toEqual(["gold", "ml", "silver"]);
  });

  it("a sink has no impact", () => {
    expect(datasetLineage(project, "gold").impact).toEqual({ nodes: [], pipelines: [], datasets: [] });
  });
});
