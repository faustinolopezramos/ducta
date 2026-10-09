import { describe, expect, it } from "vitest";
import { buildCommandIndex, fuzzyScore, searchCommands } from "./commandIndex";

const index = buildCommandIndex({
  projectId: "batch",
  pipelines: ["silver.clean", "golden.transformation"],
  nodes: [{ node: "silver.clean_student", pipeline: "silver.clean" }],
  datasets: [{ name: "silver.education.student_cleaned", layer: "silver" }],
  files: ["src/silver.py"],
  runs: [{ id: "abcdef1234", pipeline_name: "silver.clean", status: "failed", env: "dev" }],
  commands: [{ kind: "command", id: "cmd:density", label: "Toggle compact density", run: () => {} }],
});

describe("command index", () => {
  it("links each entity to its page", () => {
    const byId = Object.fromEntries(index.map((e) => [e.id, e.to]));
    expect(byId["node:silver.clean_student"]).toContain("/p/batch/pipelines/silver.clean");
    expect(byId["dataset:silver.education.student_cleaned"]).toBe("/p/batch/datasets/silver.education.student_cleaned");
    expect(byId["file:src/silver.py"]).toContain("/p/batch/code");
    expect(byId["run:abcdef1234"]).toBe("/p/batch/runs/abcdef1234");
  });

  it("matches fuzzily and ranks contiguous, word-start matches first", () => {
    expect(fuzzyScore("scs", "silver.clean_student")).toBeGreaterThan(0);
    expect(fuzzyScore("xyz", "silver.clean_student")).toBe(-1);
    const hits = searchCommands(index, "clean");
    expect(hits[0].label).toBe("silver.clean");
  });

  it("narrows by prefix: > commands, # datasets, @ nodes", () => {
    expect(searchCommands(index, ">dens").map((e) => e.kind)).toEqual(["command"]);
    expect(searchCommands(index, "#student").map((e) => e.kind)).toEqual(["dataset"]);
    expect(searchCommands(index, "@student").map((e) => e.kind)).toEqual(["node"]);
  });
});
