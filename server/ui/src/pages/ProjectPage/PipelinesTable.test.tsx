import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PipelinesView } from "./PipelinesTable";

const cancel = vi.fn();
const runs = vi.fn();

vi.mock("../../api/queries", () => ({
  useExecutionList: () => ({ data: runs(), isLoading: false }),
}));
vi.mock("../../api/mutations", () => ({
  useCancelExecution: () => ({ mutate: cancel, isPending: false, variables: undefined }),
}));
vi.mock("../../components/Execution/StreamLiveLine", () => ({
  StreamLiveLine: ({ executionId }: { executionId: string }) => <span>live {executionId}</span>,
}));

const project = { id: "p", name: "Demo" } as never;
const pipelines = [
  { id: "events_stream", name: "events_stream", type: "streaming", nodes: [{}, {}] },
  { id: "orders_etl", name: "orders_etl", type: "batch", nodes: [{}] },
] as never;

function renderView() {
  const onRun = vi.fn();
  render(
    <PipelinesView
      projectId="p"
      project={project}
      pipelines={pipelines}
      specs={{ events_stream: { type: "streaming" }, orders_etl: { type: "batch" } }}
      onOpen={() => {}}
      onRun={onRun}
      onDelete={() => {}}
      onCreate={() => {}}
    />,
  );
  return { onRun };
}

const now = new Date().toISOString();
const run = (over: Record<string, unknown>) => ({ id: "x", project_id: "p", env: "dev", started_at: now, ...over });

describe("PipelinesView, streams", () => {
  beforeEach(() => {
    cancel.mockClear();
    runs.mockReturnValue({ executions: [] });
  });

  it("offers to start a stream that is not running, not to run it", async () => {
    const { onRun } = renderView();
    expect(screen.getByText("Not running")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start stream events_stream" }));
    expect(onRun).toHaveBeenCalledWith("events_stream");
    expect(screen.getByRole("button", { name: "Run orders_etl" })).toBeInTheDocument();
  });

  it("shows a running stream as live, with Stop instead of Run", async () => {
    runs.mockReturnValue({ executions: [run({ id: "e1", pipeline_name: "events_stream", status: "running" })] });
    renderView();
    const row = screen.getByRole("row", { name: /events_stream/ });
    expect(within(row).getByText("live e1")).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: /Start stream|Run/ })).toBeNull();
    await userEvent.click(within(row).getByRole("button", { name: "Stop events_stream" }));
    expect(cancel).toHaveBeenCalledWith("e1");
  });

  it("does not take a running batch pipeline for a stream", () => {
    runs.mockReturnValue({ executions: [run({ id: "e2", pipeline_name: "orders_etl", status: "running" })] });
    renderView();
    expect(screen.queryByText("live e2")).toBeNull();
    expect(screen.getByRole("button", { name: "Run orders_etl" })).toBeInTheDocument();
  });
});
