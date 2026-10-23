import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PipelineDock, type PipelineDockProps } from "./PipelineDock";

// The panels have their own tests and data hooks; here only the tab logic matters.
vi.mock("../../components/Problems/ProblemsPanel", () => ({
  ProblemsPanel: () => <div>problems body</div>,
}));
vi.mock("../../components/Pipeline/SamplePreview", () => ({
  SamplePreview: () => <div>sample body</div>,
}));
vi.mock("../../components/Execution/StreamingStatusPanel", () => ({
  StreamingStatusPanel: ({ fullView }: { fullView?: boolean }) => <div>streaming panel {fullView ? "full" : "compact"}</div>,
}));
vi.mock("../../components/Execution/InlineLogs", () => ({
  InlineLogs: () => <div>logs body</div>,
}));

function renderDock(props: Partial<PipelineDockProps>) {
  const defaults: PipelineDockProps = {
    height: 260,
    onHeightChange: () => {},
    onClose: () => {},
    tab: "logs",
    onTabChange: () => {},
    counts: { errors: 0, warnings: 0 },
    sample: null,
    projectId: "p1",
    itemById: new Map(),
    activeEnv: "dev",
    problems: [],
    isChecking: false,
    onOpenProblem: () => {},
    onFixProblem: () => {},
    fixWithAI: null,
    activeExecutionId: null,
    isExecuting: false,
    pipelineNodes: [],
    executionStates: {},
  };
  return render(<PipelineDock {...defaults} {...props} />);
}

describe("PipelineDock tabs", () => {
  it("selects Logs when a saved preview tab has no sample left", () => {
    renderDock({ tab: "preview", sample: null });

    expect(screen.getByText("logs body")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Logs" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getAllByRole("tab", { selected: true })).toHaveLength(1);
  });

  it("selects the sample tab while a sample is shown", () => {
    renderDock({ tab: "preview", sample: { node: "clean", execId: null, rows: 10 } });

    expect(screen.getByText("sample body")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Sample/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Logs" })).toHaveAttribute("aria-selected", "false");
  });

  it("selects Problems on the problems tab", () => {
    renderDock({ tab: "problems" });

    expect(screen.getByText("problems body")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Problems" })).toHaveAttribute("aria-selected", "true");
  });

  it("offers and selects the Stream tab for a streaming pipeline", () => {
    renderDock({
      tab: "stream",
      isStreamPipeline: true,
      activeExecutionId: "e1",
      isExecuting: true,
      streamSummary: { status: "running", up: 3, total: 3, rate: 250 },
    });

    expect(screen.getByRole("tab", { name: /Stream/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("3/3")).toBeInTheDocument();
    expect(screen.getByText("streaming panel full")).toBeInTheDocument();
  });
});
