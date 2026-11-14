import { describe, expect, it } from "vitest";
import { diffLines, gutterMarks } from "./lineDiff";

describe("line diff", () => {
  it("finds the shortest script", () => {
    const ops = diffLines(["a", "b", "c"], ["a", "x", "c", "d"]);
    expect(ops.filter((o) => o.kind !== "equal").length).toBe(3);
    expect(diffLines(["a"], ["a"])).toEqual([{ kind: "equal", a: 0, b: 0 }]);
  });

  it("marks added, modified and deleted lines of the current text", () => {
    const base = "one\ntwo\nthree\nfour\nfive";
    const now = "one\nTWO\nthree\nfive\nsix\nseven";
    expect(gutterMarks(base, now)).toEqual([
      { kind: "modified", from: 2, to: 2 },
      { kind: "deleted", from: 4, to: 4 },
      { kind: "added", from: 5, to: 6 },
    ]);
    expect(gutterMarks(base, base)).toEqual([]);
  });
});
