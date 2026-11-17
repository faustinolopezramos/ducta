import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { PipelineDock, type PipelineDockProps } from "./PipelineDock";

// The panels have their own tests and data hooks; here only the tab logic matters.
vi.mock("../../components/Problems/ProblemsPanel", () => ({
  ProblemsPanel: () => <div>problems body</div>,
}));
vi.mock("../../components/Pipeline/SamplePreview", () => ({
  SamplePreview: () => <div>sample body</div>,
}));
vi.mock("../../components/Execution/StreamingStatusPanel", () => ({
  StreamingStatusPanel: () => <div>streaming panel</div>,
}));
vi.mock("../../components/Execution/InlineLogs", () => ({
  InlineLogs: ({ logs, finalStatus }: { logs?: unknown[]; finalStatus?: string }) => (
    <div>
      logs body{logs ? ` · ${logs.length} past lines · ${finalStatus}` : ""}
    </div>
  ),
}));
const fetchedLogs = vi.hoisted(() => ({ calls: [] as string[] }));
vi.mock("../../api/queries", () => ({
  useExecutionLogs: (id: string) => {
    fetchedLogs.calls.push(id);
    return { data: id ? { logs: [{ timestamp: "2026-10-20T21:27:00Z", level: "info", message: "done" }] } : undefined };
  },
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
  return render(<MemoryRouter><PipelineDock {...defaults} {...props} /></MemoryRouter>);
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
    // The monitor is its own page: the tab is one line and a way in.
    expect(screen.getByRole("status")).toHaveTextContent("3 nodes running · 250 rows/s");
    expect(screen.getByRole("link", { name: /Open monitor/ })).toHaveAttribute("href", "/p/p1/streams/e1");
    expect(screen.queryByText("streaming panel")).toBeNull();
  });
});

describe("PipelineDock Stream tab around the run", () => {
  const stream = { tab: "stream" as const, isStreamPipeline: true };

  it("names the queries while the stream starts, before its first status", () => {
    renderDock({ ...stream, isExecuting: true, activeExecutionId: "e1", streamNodeNames: ["ingest", "enrich", "publish"] });
    expect(screen.getByRole("status")).toHaveTextContent("Starting 3 queries…");
    expect(screen.getByRole("link", { name: /Open monitor/ })).toHaveAttribute("href", "/p/p1/streams/e1");
    expect(screen.queryByText(/streaming panel/)).toBeNull();
  });

  it("says nothing was started yet, and offers to start", () => {
    const onStartStream = vi.fn();
    renderDock({ ...stream, onStartStream });
    expect(screen.getByText("Stream not started")).toBeInTheDocument();
    screen.getByRole("button", { name: "Start stream" }).click();
    expect(onStartStream).toHaveBeenCalledTimes(1);
  });

  it("after a run, says how it went: length, how it ended and how long ago", () => {
    const now = Date.now();
    renderDock({
      ...stream,
      onStartStream: () => {},
      lastRun: {
        status: "cancelled",
        started_at: new Date(now - (134 + 14) * 60_000).toISOString(),
        finished_at: new Date(now - 14 * 60_000).toISOString(),
      },
    });
    expect(screen.getByText("Stream stopped")).toBeInTheDocument();
    expect(screen.getByText("Last run: 2h 14m · cancelled · 14 min ago")).toBeInTheDocument();
  });

  it("does not offer to start what may not be started, and says why", () => {
    renderDock({ ...stream, onStartStream: () => {}, startBlocked: "prod is protected" });
    const start = screen.getByRole("button", { name: "Start stream" });
    expect(start).toBeDisabled();
    expect(start).toHaveAttribute("title", "prod is protected");
  });

  it("says how the stream is once the first status is in", () => {
    renderDock({
      ...stream,
      isExecuting: true,
      activeExecutionId: "e1",
      streamSummary: { status: "running", up: 1, total: 1, rate: 10 },
    });
    expect(screen.getByRole("status")).toHaveTextContent("1 node running · 10 rows/s");
  });

  it("after a run, offers its monitor too: the journal and the last rows stay readable", () => {
    renderDock({ ...stream, onStartStream: () => {}, lastRun: { id: "e0", status: "cancelled", finished_at: new Date().toISOString() } });
    expect(screen.getByRole("link", { name: /Open last monitor/ })).toHaveAttribute("href", "/p/p1/streams/e0");
  });

  it("does not leave a stopped stream's tab blank", () => {
    renderDock({ ...stream, activeExecutionId: "e1", isExecuting: false });
    expect(screen.getByText("Stream not started")).toBeInTheDocument();
  });
});

describe("PipelineDock logs before anything runs", () => {
  it("shows the pipeline's last run's logs instead of 'No logs'", () => {
    renderDock({ lastRun: { id: "run-1", status: "success" } });
    expect(screen.getByText("logs body · 1 past lines · success")).toBeInTheDocument();
  });

  it("shows the live logs while a run is going", () => {
    renderDock({ lastRun: { id: "run-1", status: "success" }, isExecuting: true });
    expect(screen.getByText("logs body")).toBeInTheDocument();
  });
});

describe("PipelineDock after a CLI run", () => {
  it("shows the latest run with stored logs and says the later one came from the CLI", () => {
    renderDock({
      lastRun: { status: "success" },
      lastServedRun: { id: "run-0", status: "success", started_at: "2026-10-20T21:27:00Z" },
    });
    expect(screen.getByText("logs body · 1 past lines · success")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("started from the CLI");
  });
});
