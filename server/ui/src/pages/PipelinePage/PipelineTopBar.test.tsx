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

describe("PipelineTopBar for a streaming pipeline", () => {
  const stream = { pipelineType: "streaming" };

  it("starts a stream rather than running a pipeline, with no partial-run menu", () => {
    renderBar({ ...stream, runOptions: [{ label: "Only what changed", onSelect: () => {} }] } as never);
    expect(screen.getByRole("button", { name: /Start stream/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Run/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Run part of the pipeline" })).toBeNull();
  });

  it("keeps the partial-run menu for a batch pipeline", () => {
    renderBar({ runOptions: [{ label: "Only what changed", onSelect: () => {} }] } as never);
    expect(screen.getByRole("button", { name: "Run part of the pipeline" })).toBeInTheDocument();
  });

  it("says how many queries are up and what they process while it runs", () => {
    renderBar({
      ...stream,
      isExecuting: true,
      streamSummary: { status: "running", up: 2, total: 2, rate: 280 },
    } as never);
    expect(screen.getByRole("status")).toHaveTextContent("2 nodes running · 280 rows/s");
    expect(screen.getByRole("button", { name: /Stop stream/ })).toBeInTheDocument();
  });

  it("says so when a node is down", () => {
    renderBar({
      ...stream,
      isExecuting: true,
      streamSummary: { status: "partial_failure", up: 1, total: 2, rate: null },
    } as never);
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 nodes running");
  });

  it("says it is starting before the first status arrives", () => {
    renderBar({ ...stream, isExecuting: true } as never);
    expect(screen.getByRole("status")).toHaveTextContent("Starting…");
  });

  it("invokes onOpenStream when clicking the stream pill", () => {
    const onOpenStream = vi.fn();
    renderBar({
      ...stream,
      isExecuting: true,
      streamSummary: { status: "running", up: 2, total: 2, rate: 280 },
      onOpenStream,
    } as never);
    screen.getByRole("button", { name: /2 nodes running/ }).click();
    expect(onOpenStream).toHaveBeenCalledTimes(1);
  });

  it("still says Stop, plainly, for a batch run", () => {
    renderBar({ isExecuting: true });
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });
});
