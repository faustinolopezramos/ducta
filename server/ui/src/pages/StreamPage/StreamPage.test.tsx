import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamingStatusResponse } from "../../api/queries/executions";

const store: { run?: Record<string, unknown>; streaming?: StreamingStatusResponse; updatedAt: number; rows?: unknown } = { updatedAt: 1 };
const restart = vi.fn();
const cancel = vi.fn();
const rowsCall = vi.fn();

vi.mock("../../api/queries", () => ({
  useExecutionStatus: () => ({ data: store.run, isLoading: false }),
}));
vi.mock("../../api/queries/executions", () => ({
  STREAMING_POLL_MS: 5000,
  useExecutionStreaming: () => ({ data: store.streaming, dataUpdatedAt: store.updatedAt }),
}));
vi.mock("../../api/queries/streamRows", () => ({
  useStreamRows: (...args: unknown[]) => {
    rowsCall(...args);
    return { data: store.rows, dataUpdatedAt: store.updatedAt, isLoading: false };
  },
}));
vi.mock("../../api/mutations", () => ({
  useRestartStreamingNode: () => ({ mutate: restart, isPending: false }),
  useCancelExecution: () => ({ mutate: cancel, isPending: false }),
}));
vi.mock("../../hooks/usePermission", () => ({ usePermission: () => true, requiresPermission: () => "" }));

import { StreamPage } from "./index";

const node = (name: string, extra: Record<string, unknown> = {}) => ({
  node: name,
  state: "active",
  processed_rows_per_second: 100,
  source: "file_stream json data/events",
  sink: `parquet data/${name}`,
  ...extra,
});

const running = (nodes: unknown[], extra: Record<string, unknown> = {}): StreamingStatusResponse =>
  ({
    execution_id: "run-1",
    active: true,
    pipelines: [
      {
        stream_execution_id: "s1",
        pipeline_name: "events_stream",
        status: "running",
        uptime_seconds: 754,
        total_queries: nodes.length,
        active_queries: nodes.length,
        failed_queries: 0,
        nodes,
        ...extra,
      },
    ],
  }) as StreamingStatusResponse;

let client = new QueryClient();

function page(path = "/p/demo/streams/" + "a".repeat(32)) {
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/p/:projectId/streams/:runId" element={<StreamPage />} />
          <Route path="*" element={<div>elsewhere</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const renderPage = (path?: string) => render(page(path));

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  store.run = { id: "a".repeat(32), pipeline_name: "events_stream", env: "dev", status: "running", finished_at: null };
  store.streaming = running([node("ingest"), node("clean")]);
  store.rows = { node: "clean", available: true, sink: "parquet data/clean", format: "parquet", columns: [{ name: "id", type: "int64" }], rows: [{ id: 2 }, { id: 1 }], total_rows: 2, newest_at: "2026-11-16T12:00:00Z" };
  store.updatedAt = 1;
  restart.mockClear();
  cancel.mockClear();
  rowsCall.mockClear();
});

describe("StreamPage", () => {
  it("names the stream, says it runs, and shows its figures, nodes and live data", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("events_stream");
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Stream figures" })).toHaveTextContent("2 nodes running");
    expect(within(screen.getByRole("group", { name: "Nodes" })).getAllByRole("button")).toHaveLength(2);
    expect(screen.getByRole("region", { name: /Live data of/ })).toHaveTextContent("parquet data/clean");
  });

  it("shows the last node's data first: where the stream ends", () => {
    renderPage();
    expect(screen.getByRole("region", { name: "Live data of clean" })).toBeInTheDocument();
    expect(rowsCall).toHaveBeenCalledWith("a".repeat(32), "clean", 50, { live: true, paused: false, batch: null });
  });

  it("starts on the node that needs a look when one does", () => {
    store.streaming = running([node("ingest"), node("clean"), node("enrich", { state: "failed", error: "boom" })]);
    renderPage();
    expect(screen.getByRole("region", { name: "Live data of enrich" })).toBeInTheDocument();
  });

  it("opens the node named in the address", () => {
    renderPage("/p/demo/streams/" + "a".repeat(32) + "?node=ingest");
    expect(screen.getByRole("region", { name: "Live data of ingest" })).toBeInTheDocument();
  });

  it("changes the data when another node is picked, and keeps it in the address", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: /^ingest/ }));
    expect(screen.getByRole("region", { name: "Live data of ingest" })).toBeInTheDocument();
  });

  it("stops the stream only after asking", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Stop stream" }));
    expect(cancel).not.toHaveBeenCalled();
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stop stream" }));
    expect(cancel).toHaveBeenCalledWith("a".repeat(32), expect.anything());
  });

  it("restarts a failed node from the line under the nodes", async () => {
    store.streaming = running([node("ingest"), node("clean", { state: "failed", error: "boom" })]);
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Restart node clean" }));
    expect(restart).toHaveBeenCalledWith({ executionId: "a".repeat(32), streamExecutionId: "s1", node: "clean" });
  });

  it("is quiet while the queries start", () => {
    store.streaming = undefined;
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Starting the queries");
    expect(screen.getByText("starting")).toBeInTheDocument();
  });

  it("shows a stopped stream from its journal, with no Stop and rows read once", () => {
    store.run = { ...store.run, status: "cancelled", finished_at: "2026-11-16T12:00:00Z" };
    store.streaming = { ...running([node("ingest"), node("clean")], { status: "stopped", from_journal: true }), active: false };
    renderPage();
    expect(screen.queryByRole("button", { name: "Stop stream" })).toBeNull();
    expect(screen.getByText("stopped")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Stream figures" })).toBeNull(); // nothing runs: no rate to show
    expect(rowsCall).toHaveBeenCalledWith("a".repeat(32), "clean", 50, { live: false, paused: false, batch: null });
  });

  it("says a run with no stream has none, and points at the run", () => {
    store.run = { ...store.run, status: "success" };
    store.streaming = { execution_id: "x", active: false, pipelines: [] };
    renderPage();
    expect(screen.getByText("This run has no stream")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute("href", `/p/demo/runs/${"a".repeat(32)}`);
  });

  it("re-reads the rows by the selected node's batch, and counts the batches that land while paused", async () => {
    store.streaming = running([node("ingest"), node("clean", { last_batch_id: 40 })]);
    const view = renderPage();
    expect(rowsCall).toHaveBeenLastCalledWith("a".repeat(32), "clean", 50, { live: true, paused: false, batch: 40 });
    await userEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(rowsCall).toHaveBeenLastCalledWith("a".repeat(32), "clean", 50, { live: true, paused: true, batch: 40 });
    store.streaming = running([node("ingest"), node("clean", { last_batch_id: 43 })]);
    store.updatedAt = 2;
    view.rerender(page());
    expect(screen.getByText("3 new batches since paused")).toBeInTheDocument();
  });

  it("shows the latest batch among the figures", () => {
    store.streaming = running([node("ingest", { last_batch_id: 1283 }), node("clean", { last_batch_id: 1284 })]);
    renderPage();
    expect(screen.getByRole("region", { name: "Stream figures" })).toHaveTextContent("Last batch#1 284");
  });

  it("links to the run and its logs", () => {
    renderPage();
    expect(screen.getByRole("link", { name: /Run & logs/ })).toHaveAttribute("href", `/p/demo/runs/${"a".repeat(32)}`);
  });
});
