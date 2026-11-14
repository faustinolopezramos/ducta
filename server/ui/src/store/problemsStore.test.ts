import { describe, expect, it } from "vitest";
import { countBySeverity, flattenProblems, nodesWithProblems, useProblemsStore } from "./problemsStore";
import type { Problem } from "../api/queries/problems";

const p = (over: Partial<Problem>): Problem => ({ severity: "error", message: "m", code: "c", source: "config", ...over });

describe("problems store", () => {
  it("replaces one source's problems, keeps the others, and resets on another project", () => {
    const s = useProblemsStore.getState();
    s.setProblems("a", "config", [p({ message: "1" })]);
    s.setProblems("a", "preflight", [p({ message: "2" })]);
    s.setProblems("a", "config", []);
    expect(Object.values(useProblemsStore.getState().bySource).flat().map((x) => x.message)).toEqual(["2"]);
    s.setProblems("b", "config", [p({ message: "3" })]);
    expect(Object.keys(useProblemsStore.getState().bySource)).toEqual(["config"]);
  });

  it("lists errors first, then by file and line, once", () => {
    const flat = flattenProblems({
      config: [p({ severity: "warning", file: "a", line: 1 }), p({ file: "b", line: 9 })],
      code: [p({ file: "a", line: 3 }), p({ file: "b", line: 9 })],
    });
    expect(flat.map((x) => `${x.severity}:${x.file}:${x.line}`)).toEqual(["error:a:3", "error:b:9", "warning:a:1"]);
    expect(countBySeverity(flat)).toEqual({ errors: 2, warnings: 1 });
  });

  it("marks a node by its worst problem", () => {
    const marks = nodesWithProblems([p({ node: "n", severity: "warning" }), p({ node: "n" }), p({ node: "m", severity: "warning" })]);
    expect(marks.get("n")).toBe("error");
    expect(marks.get("m")).toBe("warning");
  });
});
