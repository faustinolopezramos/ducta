import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PipelineTopBar } from "./PipelineTopBar";

vi.mock("../../api/queries", () => ({
  useEnvironments: () => ({ data: { environments: ["base", "dev"] } }),
}));

const base = {
  projectId: "batch",
  projectName: "Batch project",
  pipelineId: "golden.transformation",
  pipelineType: "batch",
  hasNodes: true,
  isExecuting: false,
  onExecute: () => {},
  onValidate: () => {},
  onCancel: () => {},
};

describe("PipelineTopBar chain strip", () => {
  it("shows the chain in execution order, with this pipeline marked", () => {
    render(
      <MemoryRouter>
        <PipelineTopBar
          {...base}
          chain={["bronze.ingestion", "silver.clean", "golden.transformation", "ml.student_performance"]}
          chainStatus={{ "ml.student_performance": "failed" }}
        />
      </MemoryRouter>
    );

    const strip = screen.getByRole("list", { name: "Pipeline chain, in execution order" });
    const items = within(strip).getAllByRole("listitem");
    expect(items.map((li) => li.textContent?.replace("→", ""))).toEqual([
      "bronze.ingestion",
      "silver.clean",
      "golden.transformation",
      "failedml.student_performance".replace("failed", ""),
    ]);

    expect(within(strip).getByText("golden.transformation")).toHaveAttribute("aria-current", "page");
    expect(within(strip).getByRole("link", { name: "bronze.ingestion" })).toHaveAttribute(
      "href",
      "/p/batch/pipelines/bronze.ingestion"
    );
    expect(within(strip).getByLabelText("failed")).toBeInTheDocument();
  });

  it("stays out of the way for a pipeline with no chain", () => {
    render(
      <MemoryRouter>
        <PipelineTopBar {...base} chain={["golden.transformation"]} />
      </MemoryRouter>
    );
    expect(screen.queryByRole("list", { name: /Pipeline chain/ })).toBeNull();
  });
});
