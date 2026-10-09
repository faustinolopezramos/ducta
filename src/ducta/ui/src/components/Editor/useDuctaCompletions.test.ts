import { describe, expect, it } from "vitest";
import { yamlCompletionKind } from "./useDuctaCompletions";

describe("yamlCompletionKind", () => {
  it("completes run targets after run:", () => {
    expect(yamlCompletionKind("    run: src.sil")).toBe("run");
    expect(yamlCompletionKind("    run: ")).toBe("run");
  });
  it("completes datasets where a value goes", () => {
    expect(yamlCompletionKind("    outputs: [silver.")).toBe("dataset");
    expect(yamlCompletionKind("    inputs: {student: bronze.edu")).toBe("dataset");
    expect(yamlCompletionKind("      - bronze.")).toBe("dataset");
  });
  it("offers nothing special while a key is being typed", () => {
    expect(yamlCompletionKind("    descr")).toBeNull();
  });
});
