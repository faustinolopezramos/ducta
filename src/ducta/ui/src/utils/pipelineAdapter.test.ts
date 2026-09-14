import { describe, expect, it } from "vitest";
import { coerceFnSpec, inferNodeType, ioNames, nodeIoNames } from "./pipelineAdapter";

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

describe("ioNames", () => {
  it("passes a list of strings through", () => {
    expect(ioNames(["bronze.a", "bronze.b"])).toEqual(["bronze.a", "bronze.b"]);
  });

  it("wraps a bare string", () => {
    expect(ioNames("bronze.a")).toEqual(["bronze.a"]);
  });

  it("takes the keys of a dict-shaped registry", () => {
    expect(ioNames({ "bronze.a": {}, "bronze.b": {} })).toEqual(["bronze.a", "bronze.b"]);
  });

  it("reads name then id out of object entries", () => {
    expect(ioNames([{ name: "a" }, { id: "b" }])).toEqual(["a", "b"]);
  });

  it("drops entries with no name at all", () => {
    expect(ioNames([{ format: "parquet" }])).toEqual([]);
  });

  it("treats null and undefined as empty", () => {
    expect(ioNames(null)).toEqual([]);
    expect(ioNames(undefined)).toEqual([]);
  });
});

describe("nodeIoNames", () => {
  it("reads the canonical singular key", () => {
    expect(nodeIoNames({ input: ["a"] }, "input")).toEqual(["a"]);
    expect(nodeIoNames({ output: ["b"] }, "output")).toEqual(["b"]);
  });

  it("reads the plural key the API normalizes to", () => {
    expect(nodeIoNames({ inputs: ["a"] }, "input")).toEqual(["a"]);
  });

  it("prefers the plural key when a spec carries both", () => {
    expect(nodeIoNames({ inputs: ["a"], input: ["b"] }, "input")).toEqual(["a"]);
  });

  it("is empty for a spec that declares nothing", () => {
    expect(nodeIoNames({ module: "m" }, "input")).toEqual([]);
    expect(nodeIoNames(undefined, "input")).toEqual([]);
  });
});
