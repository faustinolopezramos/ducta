import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PipelineTopBar } from "./PipelineTopBar";

vi.mock("../../api/queries", () => ({
  useEnvironments: () => ({ data: { environments: ["base", "prod"] } }),
}));

const base = {
  projectId: "batch",
  projectName: "Batch project",
  pipelineId: "silver.clean",
  pipelineType: "batch",
  hasNodes: true,
  isExecuting: false,
  onExecute: () => {},
  onValidate: () => {},
  onCancel: () => {},
};

function renderBar(overrides: Partial<typeof base> & { runBlocked?: string | null } = {}) {
  return render(
    <MemoryRouter>
      <PipelineTopBar {...base} {...overrides} />
    </MemoryRouter>
  );
}

describe("PipelineTopBar", () => {
  it("does not offer a run the user may not start, and says why", () => {
    renderBar({ runBlocked: "prod is protected: running there takes an operator" });
    const run = screen.getByRole("button", { name: /Run/ });
    expect(run).toBeDisabled();
    expect(run).toHaveAttribute("title", "prod is protected: running there takes an operator");
  });

  it("links back through the project to the pipeline it is on", () => {
    renderBar();
    expect(screen.getByRole("link", { name: "Batch project" })).toHaveAttribute("href", "/p/batch");
    expect(screen.getByText("silver.clean")).toHaveAttribute("aria-current", "page");
  });

  it("shows the pipeline type as a tag, not a control", () => {
    renderBar({ pipelineType: "streaming" });
    expect(screen.getByText("streaming")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "streaming" })).toBeNull();
  });

  it("keeps Run and Validate disabled until the pipeline has nodes", () => {
    renderBar({ hasNodes: false });
    expect(screen.getByRole("button", { name: /^Run/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Validate" })).toBeDisabled();
  });

  it("offers Stop instead of Run while a run is in progress", () => {
    const onCancel = vi.fn();
    renderBar({ isExecuting: true, onCancel });
    expect(screen.queryByRole("button", { name: /^Run/ })).toBeNull();
    screen.getByRole("button", { name: "Stop" }).click();
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("names the environment it will run in — chosen once, in the header", () => {
    renderBar();
    expect(screen.getByRole("button", { name: /Run/ })).toHaveTextContent("base");
    expect(screen.queryByRole("combobox", { name: "Environment" })).toBeNull();
  });
});
