import { describe, expect, it } from "vitest";
import {
  ancestorsOf,
  dependsOnFromEdges,
  dependsOnFromSpecs,
  descendantsOf,
  orderPipelines,
  runChainOf,
} from "./pipelineChain";

// The demo workspace's batch project, as its pipelines.yml declares it.
const specs = {
  "bronze.ingestion": {},
  "silver.clean": { depends_on: ["bronze.ingestion"] },
  "golden.transformation": { depends_on: ["silver.clean"] },
  "ml.student_performance": { depends_on: ["golden.transformation"] },
  "ml.student_risk": { depends_on: "golden.transformation" },
  orphan: { depends_on: ["not.a.pipeline"] },
};

describe("pipelineChain", () => {
  const graph = dependsOnFromSpecs(specs);

  it("resolves the chain a run executes, dependencies first", () => {
    expect(runChainOf("ml.student_performance", graph)).toEqual([
      "bronze.ingestion",
      "silver.clean",
      "golden.transformation",
      "ml.student_performance",
    ]);
  });

  it("accepts depends_on as a single string", () => {
    expect(ancestorsOf("ml.student_risk", graph)).toContain("golden.transformation");
  });

  it("ignores dependencies on pipelines that do not exist", () => {
    expect(ancestorsOf("orphan", graph)).toEqual([]);
    expect(runChainOf("orphan", graph)).toEqual(["orphan"]);
  });

  it("finds every consumer downstream", () => {
    expect(descendantsOf("silver.clean", graph).sort()).toEqual([
      "golden.transformation",
      "ml.student_performance",
      "ml.student_risk",
    ]);
    expect(descendantsOf("ml.student_risk", graph)).toEqual([]);
  });

  it("orders by dependency and breaks ties by name", () => {
    expect(
      orderPipelines(["ml.student_risk", "ml.student_performance", "golden.transformation"], graph)
    ).toEqual(["golden.transformation", "ml.student_performance", "ml.student_risk"]);
  });

  it("keeps the input order when the pipelines form a cycle", () => {
    const cyclic = dependsOnFromSpecs({ a: { depends_on: ["b"] }, b: { depends_on: ["a"] } });
    expect(orderPipelines(["b", "a"], cyclic)).toEqual(["b", "a"]);
  });

  it("builds the same graph from the dependencies endpoint, skipping in-pipeline edges", () => {
    const fromEdges = dependsOnFromEdges(
      ["bronze.ingestion", "silver.clean"],
      [
        { from_pipeline: "bronze.ingestion", to_pipeline: "silver.clean" },
        { from_pipeline: "silver.clean", to_pipeline: "silver.clean" },
      ]
    );
    expect([...fromEdges.get("silver.clean")!]).toEqual(["bronze.ingestion"]);
    expect(fromEdges.get("bronze.ingestion")!.size).toBe(0);
  });
});
