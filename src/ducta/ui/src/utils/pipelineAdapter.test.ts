import { describe, expect, it } from "vitest";
import { adaptApiNode, coerceFnSpec, deriveDatasetDependencies, inferNodeType } from "./pipelineAdapter";

describe("coerceFnSpec", () => {
  it("passes through a string fn", () => {
    expect(coerceFnSpec("run", "my.module")).toEqual({ fn: "run", module: "my.module" });
  });

  it("derives fn/module from a streaming function object {key, module}", () => {
    // The shape that previously crashed React (#31) when rendered as a child.
    const out = coerceFnSpec({ key: "detect_fraud", module: "transforms.fraud" }, undefined);
    expect(out).toEqual({ fn: "detect_fraud", module: "transforms.fraud" });
    expect(typeof out.fn).toBe("string");
    expect(typeof out.module).toBe("string");
  });

  it("prefers an explicit top-level module over the function object's module", () => {
    expect(coerceFnSpec({ key: "t" }, "top.module").module).toBe("top.module");
  });

  it("applies the default fn when missing", () => {
    expect(coerceFnSpec(undefined, undefined, "run").fn).toBe("run");
    expect(coerceFnSpec({}, undefined, "run").fn).toBe("run");
  });
});

describe("inferNodeType", () => {
  it("honours a valid explicit type", () => {
    expect(inferNodeType({ type: "sink", inputs: [1], outputs: [1] })).toBe("sink");
  });
  it("classifies a pure producer as source and a pure consumer as sink", () => {
    expect(inferNodeType({ inputs: [], outputs: [1] })).toBe("source");
    expect(inferNodeType({ inputs: [1], outputs: [] })).toBe("sink");
  });
  it("classifies a node with both in and out as transform", () => {
    expect(inferNodeType({ inputs: [1], outputs: [1] })).toBe("transform");
  });
  it("detects ml from module path or ml_stage over the I/O shape", () => {
    expect(inferNodeType({ module: "src.ml.tournament_simulator", inputs: [1], outputs: [1] })).toBe("ml");
    expect(inferNodeType({ ml_stage: "serving", inputs: [1], outputs: [1] })).toBe("ml");
    expect(inferNodeType({ fn: "train_model", inputs: [], outputs: [1] })).toBe("ml");
  });
  it("falls back to custom when there is nothing to go on", () => {
    expect(inferNodeType({})).toBe("custom");
  });
  it("does not misfire on unrelated words containing the hints", () => {
    // 'html' contains 'ml' but not at a word boundary — must stay transform.
    expect(inferNodeType({ module: "src.parse_html", inputs: [1], outputs: [1] })).toBe("transform");
  });
});

describe("deriveDatasetDependencies", () => {
  const node = (id: string, inputs: string[], outputs: string[], deps?: string[]) => ({
    id,
    inputs: inputs.map((name) => ({ name })),
    outputs: outputs.map((name) => ({ name })),
    ...(deps ? { dependencies: deps } : {}),
  });

  it("connects a consumer to the node that produces its input dataset", () => {
    // worldcup.simulation: tournament_simulator consumes group_stage_resolver's output.
    const out = deriveDatasetDependencies([
      node("group_stage_resolver", ["gold.match_features"], ["ml.sim.group_simulations"]),
      node("tournament_simulator", ["ml.sim.group_simulations", "gold.teams"], ["ml.sim.advancement"]),
    ]);
    expect(out.find((n) => n.id === "tournament_simulator")!.dependencies).toEqual(["group_stage_resolver"]);
    // A pure source (only external inputs) gets no intra-pipeline dependency.
    expect(out.find((n) => n.id === "group_stage_resolver")!.dependencies).toEqual([]);
  });

  it("ignores datasets not produced inside the pipeline (cross-layer inputs)", () => {
    // Every silver node reads bronze.* and writes silver.* — no intra edges.
    const out = deriveDatasetDependencies([
      node("clean_a", ["bronze.a"], ["silver.a"]),
      node("clean_b", ["bronze.b"], ["silver.b"]),
    ]);
    expect(out.every((n) => n.dependencies!.length === 0)).toBe(true);
  });

  it("unions derived dependencies with explicitly declared ones and dedupes", () => {
    const out = deriveDatasetDependencies([
      node("a", [], ["ds.x"]),
      node("b", ["ds.x"], [], ["a", "manual"]),
    ]);
    expect(out.find((n) => n.id === "b")!.dependencies!.sort()).toEqual(["a", "manual"]);
  });

  it("does not create a self-edge when a node consumes its own output", () => {
    const out = deriveDatasetDependencies([node("loopy", ["ds.x"], ["ds.x"])]);
    expect(out[0].dependencies).toEqual([]);
  });

  it("handles a diamond: two producers feeding one consumer", () => {
    const out = deriveDatasetDependencies([
      node("left", [], ["ds.l"]),
      node("right", [], ["ds.r"]),
      node("join", ["ds.l", "ds.r"], ["ds.out"]),
    ]);
    expect(out.find((n) => n.id === "join")!.dependencies!.sort()).toEqual(["left", "right"]);
  });
});

describe("adaptApiNode with streaming function object", () => {
  it("never yields an object for fn/module", () => {
    const node = adaptApiNode("silver", {
      function: { key: "transform_silver", module: "pkg.silver" },
      inputs: [],
      outputs: [],
    });
    expect(typeof node.fn).toBe("string");
    expect(typeof node.module).toBe("string");
    expect(node.fn).toBe("transform_silver");
    expect(node.module).toBe("pkg.silver");
  });
});
