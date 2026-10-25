import { describe, expect, it } from "vitest";
import { hasRowDensity } from "./StatusBar";

describe("hasRowDensity", () => {
  it("offers row density on table pages only", () => {
    expect(hasRowDensity("/p/batch/runs")).toBe(true);
    expect(hasRowDensity("/p/batch/quality")).toBe(true);
    expect(hasRowDensity("/workspace/certificates")).toBe(true);
    expect(hasRowDensity("/workspace/executions/")).toBe(true);
    expect(hasRowDensity("/projects")).toBe(false);
    expect(hasRowDensity("/p/batch/pipelines/silver.clean")).toBe(false);
    expect(hasRowDensity("/p/batch/runs/409109fd")).toBe(false);
    expect(hasRowDensity("/p/batch/code/src/x.py")).toBe(false);
  });
});
