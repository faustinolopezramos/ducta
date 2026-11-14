import { describe, expect, it } from "vitest";
import { pipelineOf, splitDiff } from "./diff";

describe("splitDiff", () => {
  it("splits a unified diff into files and computes additions and deletions", () => {
    const raw = `--- a/pipelines/clean.yaml
+++ b/pipelines/clean.yaml
@@ -1,4 +1,5 @@
 type: batch
-nodes: {}
+nodes:
+  clean_events:
 description: Clean pipeline
--- /dev/null
+++ b/pipelines/transforms.py
@@ -0,0 +1,3 @@
+def clean_events(df):
+    return df.dropDuplicates()
+`;
    const files = splitDiff(raw);
    expect(files).toHaveLength(2);

    // File 1
    expect(files[0].path).toBe("pipelines/clean.yaml");
    expect(files[0].additions).toBe(2);
    expect(files[0].deletions).toBe(1);

    // Check line numbers in File 1
    const lines1 = files[0].lines;
    expect(lines1[0].kind).toBe("hunk");
    expect(lines1[1]).toEqual({ kind: "ctx", text: " type: batch", oldLineNumber: 1, newLineNumber: 1 });
    expect(lines1[2]).toEqual({ kind: "del", text: "-nodes: {}", oldLineNumber: 2, newLineNumber: null });
    expect(lines1[3]).toEqual({ kind: "add", text: "+nodes:", oldLineNumber: null, newLineNumber: 2 });
    expect(lines1[4]).toEqual({ kind: "add", text: "+  clean_events:", oldLineNumber: null, newLineNumber: 3 });
    expect(lines1[5]).toEqual({ kind: "ctx", text: " description: Clean pipeline", oldLineNumber: 3, newLineNumber: 4 });

    // File 2 (all additions)
    expect(files[1].path).toBe("pipelines/transforms.py");
    expect(files[1].additions).toBe(3);
    expect(files[1].deletions).toBe(0);
    expect(files[1].lines[1].newLineNumber).toBe(1);
    expect(files[1].lines[2].newLineNumber).toBe(2);
    expect(files[1].lines[3].newLineNumber).toBe(3);
  });

  it("handles empty diff gracefully", () => {
    expect(splitDiff("")).toEqual([]);
  });
});

describe("pipelineOf", () => {
  it("extracts pipeline name from pipelines file path", () => {
    expect(pipelineOf(["src/utils.py", "pipelines/events.yaml"])).toBe("events");
    expect(pipelineOf(["pipelines/orders.yml"])).toBe("orders");
    expect(pipelineOf(["src/main.py"])).toBeNull();
  });
});
