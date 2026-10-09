import { describe, expect, it } from "vitest";
import { filterTree, groupDatasets } from "./explorerModel";

const tree = [
  { name: "silver.clean", nodes: ["silver.clean_student", "silver.clean_education"] },
  { name: "golden.transformation", nodes: ["golden.summary"] },
];

describe("explorer model", () => {
  it("keeps a whole pipeline when its name matches, else only its matching nodes", () => {
    expect(filterTree(tree, "")).toBe(tree);
    expect(filterTree(tree, "silver")).toEqual([tree[0]]);
    expect(filterTree(tree, "student")).toEqual([{ name: "silver.clean", nodes: ["silver.clean_student"] }]);
    expect(filterTree(tree, "nothing")).toEqual([]);
  });

  it("groups datasets by layer, bronze first, unknown last", () => {
    const groups = groupDatasets(
      [
        { name: "golden.b", layer: "gold" },
        { name: "x", layer: null },
        { name: "bronze.a", layer: "bronze" },
        { name: "silver.z", layer: "silver" },
        { name: "silver.a", layer: "silver" },
      ],
      "",
    );
    expect(groups.map((g) => g.layer)).toEqual(["bronze", "silver", "gold", "other"]);
    expect(groups[1].datasets).toEqual(["silver.a", "silver.z"]);
    expect(groupDatasets([{ name: "silver.a", layer: "silver" }], "gold")).toEqual([]);
  });
});
