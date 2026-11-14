import { describe, expect, it } from "vitest";
import { resolveToken, tokenAt } from "./yamlNavigation";

const index = {
  datasets: { "silver.education.student_cleaned": { file: "catalog/silver.yaml", line: 5 } },
  nodes: { "silver.clean_student": { file: "pipelines/silver.clean.yaml", line: 12, pipeline: "silver.clean" } },
  functions: { "src.silver:clean_student": { file: "src/silver.py", line: 95 } },
};

describe("YAML navigation", () => {
  it("finds the token under the cursor, dots and colon included", () => {
    const line = "    run: src.silver:clean_student";
    expect(tokenAt(line, 15)?.text).toBe("src.silver:clean_student");
    expect(tokenAt("    outputs: [silver.education.student_cleaned]", 25)?.text).toBe("silver.education.student_cleaned");
    expect(tokenAt("    - x", 2)).toBeNull();
  });

  it("resolves functions, datasets and nodes", () => {
    expect(resolveToken("src.silver:clean_student", index)).toMatchObject({ kind: "function", at: { file: "src/silver.py", line: 95 } });
    expect(resolveToken("silver.education.student_cleaned", index)?.kind).toBe("dataset");
    expect(resolveToken("silver.clean_student", index)?.kind).toBe("node");
    expect(resolveToken("nothing", index)).toBeNull();
  });
});
