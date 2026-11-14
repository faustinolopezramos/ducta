import { describe, expect, it } from "vitest";
import { isRailItemActive, railItems } from "./Sidebar";

const labels = (items: { label: string }[]) => items.map((i) => i.label);

describe("railItems", () => {
  it("offers one item per concept inside a project with Projects first", () => {
    expect(labels(railItems("batch"))).toEqual([
      "Projects",
      "Code",
      "Runs",
      "Quality",
      "Certificates",
      "Git",
      "Settings",
    ]);
    expect(labels(railItems("batch", { hasModels: true }))).toContain("Models");
  });

  it("outside an active project, provides complete stable navigation without disappearing modules", () => {
    expect(labels(railItems(null))).toEqual([
      "Projects",
      "Code",
      "Runs",
      "Quality",
      "Certificates",
      "Git",
      "Settings",
    ]);
    expect(labels(railItems(null, { hasModels: true }))).toContain("Models");
  });

  it("marks the section a page belongs to", () => {
    const items = railItems("batch");
    const active = (path: string) => items.filter((i) => isRailItemActive(i, path)).map((i) => i.label);
    expect(active("/p/batch")).toEqual(["Projects"]);
    expect(active("/p/batch/pipelines/silver.clean")).toEqual(["Projects"]);
    expect(active("/p/batch/datasets/raw.x")).toEqual(["Projects"]);
    expect(active("/p/batch/schedules")).toEqual(["Runs"]);
    expect(active("/p/batch/settings/connections")).toEqual(["Settings"]);
    expect(active("/workspace/executions")).toEqual(["Runs"]);
    expect(active("/workspace/quality")).toEqual(["Quality"]);
    expect(active("/workspace/certificates")).toEqual(["Certificates"]);
    expect(active("/verify-certificate")).toEqual(["Certificates"]);
    expect(active("/workspace/git")).toEqual(["Git"]);
    expect(active("/projects")).toEqual(["Projects"]);
  });
});
