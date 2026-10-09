import { describe, expect, it } from "vitest";
import { fileRefs, foldJvmFrames } from "./logMessage";

describe("foldJvmFrames", () => {
  it("keeps two frames of each run and counts the rest", () => {
    const msg = ["Py4JJavaError: boom", ...Array.from({ length: 6 }, (_, i) => `\tat org.apache.X.m${i}(X.scala:${i})`), "Caused by: y"].join("\n");
    const { text, hidden } = foldJvmFrames(msg);
    expect(hidden).toBe(4);
    expect(text.split("\n")).toEqual([
      "Py4JJavaError: boom",
      "\tat org.apache.X.m0(X.scala:0)",
      "\tat org.apache.X.m1(X.scala:1)",
      "        … 4 more JVM frames",
      "Caused by: y",
    ]);
  });
  it("leaves a message without frames alone", () => {
    expect(foldJvmFrames("plain")).toEqual({ text: "plain", hidden: 0 });
  });
});

describe("fileRefs", () => {
  it("finds project files in Python traces and file:line references", () => {
    const text = 'File "/home/u/proj/src/silver.py", line 97, in clean\n  see pipelines/silver.clean.yaml:12';
    expect(fileRefs(text).map((r) => [r.file, r.line])).toEqual([
      ["src/silver.py", 97],
      ["pipelines/silver.clean.yaml", 12],
    ]);
  });
  it("ignores library code", () => {
    expect(fileRefs('File "/env/lib/python3.13/site-packages/pyspark/src/x.py", line 1')).toEqual([]);
  });
});
