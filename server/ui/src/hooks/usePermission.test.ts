import { describe, expect, it } from "vitest";
import { hasPermission, requiresPermission } from "./usePermission";

describe("hasPermission", () => {
  it("grants a permission the user has", () => {
    expect(hasPermission(["project.read", "pipeline.read"], "project.read")).toBe(true);
  });

  it("refuses one the user lacks", () => {
    expect(hasPermission(["project.read"], "pipeline.execute")).toBe(false);
  });

  it("lets the admin wildcard grant everything", () => {
    expect(hasPermission(["*"], "model.delete")).toBe(true);
  });

  it("refuses everything until the user has loaded", () => {
    expect(hasPermission(undefined, "project.read")).toBe(false);
  });

  it("names the missing permission for the tooltip", () => {
    expect(requiresPermission("git.write")).toBe("Requires the 'git.write' permission");
  });
});
