import { describe, expect, it } from "vitest";
import { attentionItems } from "./index";

const run = (id: string, pipeline_name: string, status: string) => ({ id, pipeline_name, status, started_at: null }) as never;

describe("attentionItems", () => {
  it("lists configuration errors first, linked to the line", () => {
    const items = attentionItems(
      "batch",
      [
        { severity: "warning", message: "no owner", code: "x", source: "config" },
        { severity: "error", message: "unknown dataset raw.x", code: "unknown_dataset", source: "config", file: "pipelines/a.yaml", line: 4 },
      ],
      [],
      [],
    );
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ tone: "danger", text: "unknown dataset raw.x", to: "/p/batch/code/pipelines/a.yaml?line=4" });
  });

  it("flags a pipeline only when its latest run failed", () => {
    const items = attentionItems(
      "batch",
      [],
      [run("r3", "silver.clean", "success"), run("r2", "silver.clean", "failed"), run("r1", "gold.x", "failed")],
      [],
    );
    expect(items.map((i) => i.to)).toEqual(["/p/batch/runs/r1"]);
  });

  it("drops a node run's failure once a later pipeline run re-ran that node", () => {
    const items = attentionItems(
      "batch",
      [],
      [
        { ...(run("r2", "golden.transformation", "success") as object), node_names: ["golden.universities"] } as never,
        run("r1", "golden.universities", "failed"),
      ],
      [],
    );
    expect(items).toEqual([]);
  });

  it("groups stale nodes by pipeline", () => {
    const items = attentionItems("batch", [], [], [
      { node: "a", pipeline: "silver.clean", state: "stale" },
      { node: "b", pipeline: "silver.clean", state: "stale" },
      { node: "c", pipeline: "silver.clean", state: "fresh" },
    ]);
    expect(items).toEqual([
      expect.objectContaining({ tone: "warning", text: "silver.clean: 2 nodes changed since the last good run" }),
    ]);
  });

  it("is empty when all is well", () => {
    expect(attentionItems("batch", [], [run("r1", "a", "success")], [])).toEqual([]);
  });

  it("groups runs stuck in the queue by pipeline", () => {
    const now = Date.parse("2026-10-09T12:00:00Z");
    const queued = (id: string, at: string) => ({ id, pipeline_name: "silver.clean", status: "pending", started_at: at }) as never;
    const items = attentionItems(
      "batch",
      [],
      [run("r9", "silver.clean", "success"), queued("q1", "2026-10-08T12:00:00Z"), queued("q2", "2026-10-08T11:00:00Z"), queued("q3", "2026-10-09T11:58:00Z")],
      [],
      now,
    );
    expect(items).toEqual([
      expect.objectContaining({ tone: "warning", text: "2 runs of silver.clean stuck in the queue", to: "/p/batch/runs?pipeline=silver.clean" }),
    ]);
  });
});
