import { describe, expect, it } from "vitest";
import { isRailItemActive, railItems } from "./Sidebar";

const labels = (items: { label: string }[]) => items.map((i) => i.label);

describe("railItems", () => {
  it("offers one item per concept inside a project", () => {
    expect(labels(railItems("batch"))).toEqual(["Overview", "Pipelines", "Code", "Runs", "Quality", "Settings", "Projects", "Certificates", "Git"]);
    expect(labels(railItems("batch", { hasModels: true }))).toContain("Models");
  });

  it("outside a project, only the workspace", () => {
    expect(labels(railItems(null))).toEqual(["Projects", "Certificates", "Git"]);
  });

  it("marks the section a page belongs to", () => {
    const items = railItems("batch");
    const active = (path: string) => items.filter((i) => isRailItemActive(i, path)).map((i) => i.label);
    expect(active("/p/batch")).toEqual(["Overview"]);
    expect(active("/p/batch/pipelines/silver.clean")).toEqual(["Pipelines"]);
    expect(active("/p/batch/datasets/raw.x")).toEqual(["Pipelines"]);
    expect(active("/p/batch/schedules")).toEqual(["Runs"]);
    expect(active("/p/batch/settings/connections")).toEqual(["Settings"]);
  });
});
