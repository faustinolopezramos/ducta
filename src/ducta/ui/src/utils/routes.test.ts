import { describe, expect, it } from "vitest";
import { projectIdFromPath, routes } from "./routes";

describe("routes", () => {
  it("puts everything a project owns under /p/:projectId", () => {
    expect(routes.project("batch")).toBe("/p/batch");
    expect(routes.pipeline("batch", "silver.clean")).toBe("/p/batch/pipelines/silver.clean");
    expect(routes.dataset("batch", "silver.x")).toBe("/p/batch/datasets/silver.x");
    expect(routes.runs("batch")).toBe("/p/batch/runs");
    expect(routes.run("batch", "abc")).toBe("/p/batch/runs/abc");
    expect(routes.section("batch", "settings", "environments")).toBe("/p/batch/settings/environments");
  });

  it("addresses a node through its pipeline, focused", () => {
    expect(routes.node("batch", "silver.clean", "silver.clean_student", "code")).toBe(
      "/p/batch/pipelines/silver.clean?focus=node%3Asilver.clean_student&panel=code",
    );
  });

  it("keeps a file path's slashes and adds the line", () => {
    expect(routes.code("batch", "src/my file.py", 12)).toBe("/p/batch/code/src/my%20file.py?line=12");
    expect(routes.code("batch")).toBe("/p/batch/code");
  });

  it("encodes ids and drops empty query values", () => {
    expect(routes.pipeline("a b", "c", { lens: null, focus: "" })).toBe("/p/a%20b/pipelines/c");
  });

  it("reads the project back from a path", () => {
    expect(projectIdFromPath("/p/a%20b/pipelines/c")).toBe("a b");
    expect(projectIdFromPath("/workspace/git")).toBeNull();
  });
});
