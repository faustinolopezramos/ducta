import { describe, expect, it } from "vitest";
import { itemsFromPipelineYaml } from "./pipelineGraph";

describe("itemsFromPipelineYaml", () => {
  it("draws the nodes of a pipeline file, wired by data", () => {
    const items = itemsFromPipelineYaml(
      `nodes:
  silver.a:
    run: src.m:a
    inputs: {df: bronze.x}
    outputs: [silver.a]
  silver.b:
    run: src.m:b
    inputs: [silver.a]
    outputs: [silver.b]
`,
      "silver.clean",
    )!;
    expect(items.map((i) => i.id)).toEqual(["silver.a", "silver.b"]);
    expect(items[1].dependsOn).toEqual(["silver.a"]);
    expect(items[0].inputs!.map((p) => p.name)).toEqual(["bronze.x"]);
  });
  it("is null for something that is not a pipeline", () => {
    expect(itemsFromPipelineYaml("::: not yaml", "p")).toBeNull();
    expect(itemsFromPipelineYaml("a: 1", "p")).toBeNull();
  });
});
