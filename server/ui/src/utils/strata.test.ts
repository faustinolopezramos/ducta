import { describe, expect, it } from "vitest";
import { buildStrata } from "./strata";

const out = (name: string) => [{ name }];

// The demo's student lane across the four pipelines of the ml chain.
const items = [
  { id: "bronze.ingest_student", pipeline: "bronze.ingestion", outputs: out("bronze.education.student") },
  { id: "silver.clean_student", pipeline: "silver.clean", outputs: out("silver.education.student_cleaned") },
  {
    id: "golden.transformation_student",
    pipeline: "golden.transformation",
    outputs: out("golden.education.student_summary"),
  },
  { id: "uc.performance_features", pipeline: "ml.student_performance", outputs: out("uc.ml.performance_features") },
  { id: "uc.student_performance", pipeline: "ml.student_performance", outputs: out("uc.student_performance.result") },
];

const order = ["bronze.ingestion", "silver.clean", "golden.transformation", "ml.student_performance"];

describe("buildStrata", () => {
  it("makes one band per pipeline, in chain order", () => {
    const strata = buildStrata(items, order, "ml.student_performance")!;
    expect(strata.bands.map((b) => b.pipeline)).toEqual(order);
    expect(strata.bands.map((b) => b.index)).toEqual([0, 1, 2, 3]);
    expect(strata.bands[3].nodeIds).toEqual(["uc.performance_features", "uc.student_performance"]);
  });

  it("colours a band by its medallion, reading `golden` as gold", () => {
    const strata = buildStrata(items, order)!;
    expect(strata.bands.map((b) => b.layer)).toEqual(["bronze", "silver", "gold", null]);
  });

  it("marks the page's own pipeline", () => {
    const strata = buildStrata(items, order, "ml.student_performance")!;
    expect(strata.bands.filter((b) => b.current).map((b) => b.pipeline)).toEqual([
      "ml.student_performance",
    ]);
  });

  it("maps each node to its band", () => {
    const strata = buildStrata(items, order)!;
    expect(strata.bandOf("silver.clean_student")).toBe(1);
    expect(strata.bandOf("uc.student_performance")).toBe(3);
    expect(strata.bandOf("unknown")).toBeUndefined();
  });

  it("skips pipelines with no nodes so band indices stay consecutive", () => {
    const strata = buildStrata(items, ["bronze.ingestion", "empty.pipeline", "silver.clean"])!;
    expect(strata.bands.map((b) => [b.index, b.pipeline])).toEqual([
      [0, "bronze.ingestion"],
      [1, "silver.clean"],
    ]);
  });

  it("has nothing to stratify for a single pipeline", () => {
    expect(buildStrata(items.slice(3), order)).toBeNull();
    expect(buildStrata([{ id: "loose" }], order)).toBeNull();
  });
});
