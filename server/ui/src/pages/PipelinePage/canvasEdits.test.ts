import { describe, expect, it } from "vitest";
import { aliasFor, datasetsToConnect, moduleOf, nodeNameError, runError, wouldCycle } from "./canvasEdits";

describe("canvas edit rules", () => {
  const parents = new Map([
    ["c", ["b"]],
    ["b", ["a"]],
  ]);

  it("refuses a connection that would close a loop", () => {
    expect(wouldCycle("c", "a", parents)).toBe(true); // a already feeds c
    expect(wouldCycle("a", "c", parents)).toBe(false);
    expect(wouldCycle("a", "a", parents)).toBe(true);
  });

  it("connects only what is not read yet", () => {
    expect(datasetsToConnect(["x", "y"], ["x"])).toEqual(["y"]);
    expect(datasetsToConnect(["x"], ["x"])).toEqual([]);
  });

  it("checks names and run targets", () => {
    expect(nodeNameError("silver.clean_2", new Set())).toBeNull();
    expect(nodeNameError("2bad", new Set())).toMatch(/Start with/);
    expect(nodeNameError("a", new Set(["a"]))).toMatch(/already exists/);
    expect(runError("src.silver:clean")).toBeNull();
    expect(runError("src.silver.clean")).toMatch(/module.path:function/);
  });
});

describe("names derived for new nodes", () => {
  it("names an input after its dataset, as the server does", () => {
    expect(aliasFor("silver.education.student_cleaned")).toBe("student_cleaned");
    expect(aliasFor("x.2021")).toBe("_2021");
  });
  it("turns a file into its module", () => {
    expect(moduleOf("src/silver.py")).toBe("src.silver");
    expect(moduleOf("src/pkg/__init__.py")).toBe("src.pkg");
  });
});

import { datasetForParam, suggestNodeName } from "./canvasEdits";

describe("dropping a function on the canvas", () => {
  it("names the node after the module's layer and the function", () => {
    expect(suggestNodeName("src.silver:clean_orders")).toBe("silver.clean_orders");
    expect(suggestNodeName("pipelines.gold.agg:summarise")).toBe("agg.summarise");
  });
  it("reads the dataset its first parameter names", () => {
    const ds = ["bronze.sales.orders", "bronze.sales.customers"];
    expect(datasetForParam("orders", ds)).toBe("bronze.sales.orders");
    expect(datasetForParam("df", ds)).toBeUndefined();
  });
});
