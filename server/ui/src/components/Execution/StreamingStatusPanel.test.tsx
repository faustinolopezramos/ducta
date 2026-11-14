import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamingStatusResponse } from "../../api/queries/executions";

const store: { data?: StreamingStatusResponse; enabled?: boolean } = {};
const restart = vi.fn();

vi.mock("../../api/queries/executions", () => ({
  useExecutionStreaming: (_id: string, enabled: boolean) => {
    store.enabled = enabled;
    return { data: store.data };
  },
}));
vi.mock("../../api/mutations", () => ({
  useRestartStreamingNode: () => ({ mutate: restart, isPending: false }),
}));

import { StreamingStatusPanel, formatRate } from "./StreamingStatusPanel";

const running: StreamingStatusResponse = {
  execution_id: "e1",
  active: true,
  pipelines: [
    {
      stream_execution_id: "s1",
      pipeline_name: "live",
      status: "partial_failure",
      uptime_seconds: 754,
      total_queries: 4,
      active_queries: 3,
      failed_queries: 1,
      nodes: [
        {
          node: "ingest",
          state: "active",
          last_batch_id: 8,
          input_rows_per_second: 1500,
          processed_rows_per_second: 1400,
          trigger_execution_ms: 250,
          model: { name: "fraud", version: 3 },
          source: "file_stream json data/events",
          sink: "parquet data/bronze",
          trigger: "every 5 seconds",
          checkpoint: "data/_ckpt/ingest/live/ingest",
        },
        { node: "quiet", state: "active", health: "idle", idle_seconds: 185 },
        { node: "hung", state: "active", health: "stalled" },
        { node: "enrich", state: "failed", error: "AnalysisException: no column x" },
      ],
    },
  ],
};

const row = (name: RegExp | string) => screen.getByRole("button", { name: typeof name === "string" ? new RegExp(`^${name}`) : name });

beforeEach(() => {
  store.data = undefined;
  restart.mockClear();
});

describe("StreamingStatusPanel", () => {
  it("says how many nodes run, in one line, and has one row per node", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    const stream = screen.getByRole("region", { name: "Stream live" });
    expect(stream).toHaveTextContent("3 of 4 nodes running · up 12m");
    expect(within(stream).getAllByRole("listitem")).toHaveLength(4);
  });

  it("a healthy row is a name, what it moves, and its rate — nothing else", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    const ingest = row("ingest");
    expect(ingest).toHaveTextContent("file_stream → parquet");
    expect(ingest).toHaveTextContent("1.4k/s");
    expect(screen.queryByText(/checkpoint/)).toBeNull(); // the detail is closed
    expect(screen.queryByRole("button", { name: /Restart node ingest/ })).toBeNull(); // no button on a healthy node
  });

  it("says the state in words: idle, stalled, failed", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(row("quiet")).toHaveTextContent("idle for 3 min — no new input");
    expect(row("hung")).toHaveTextContent("stalled — no progress report for a long time");
    expect(row("enrich")).toHaveTextContent("failed — AnalysisException: no column x");
    expect(row("quiet")).not.toHaveTextContent("failed");
  });

  it("opens a row to what it reads and writes, its trigger, batch, model and checkpoint", async () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    await userEvent.click(row("ingest"));
    const detail = row("ingest").closest("li") as HTMLElement;
    expect(row("ingest")).toHaveAttribute("aria-expanded", "true");
    expect(detail).toHaveTextContent("reads file_stream json data/events · writes parquet data/bronze");
    expect(detail).toHaveTextContent("every 5 seconds · batch 8 · last 250 ms · fraud v3");
    expect(detail).toHaveTextContent("checkpoint data/_ckpt/ingest/live/ingest");
    await userEvent.click(row("ingest"));
    expect(screen.queryByText(/checkpoint/)).toBeNull();
  });

  it("offers Restart on a failed or hung node, right on its row", async () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(screen.getByRole("button", { name: "Restart node hung" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restart node enrich" }));
    expect(restart).toHaveBeenCalledWith({ executionId: "e1", streamExecutionId: "s1", node: "enrich" });
  });

  it("keeps Restart for a healthy node inside its detail", async () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    await userEvent.click(row("ingest"));
    await userEvent.click(screen.getByRole("button", { name: "Restart node ingest" }));
    expect(restart).toHaveBeenCalledWith({ executionId: "e1", streamExecutionId: "s1", node: "ingest" });
  });

  it("does not offer a restart for a node that never started", () => {
    store.data = {
      ...running,
      pipelines: [{ ...running.pipelines[0], nodes: [{ node: "late", state: "skipped", error: "upstream failed" }] }],
    };
    render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(row("late")).toHaveTextContent("skipped — upstream failed");
    expect(screen.queryByRole("button", { name: /Restart/ })).toBeNull();
  });

  it("draws the trend only for a healthy node, once there is more than one poll", () => {
    store.data = running;
    const { rerender } = render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(screen.queryByRole("img", { name: /Processed rows per second/ })).toBeNull();
    const next = structuredClone(running);
    next.pipelines[0].nodes[0].processed_rows_per_second = 40;
    next.pipelines[0].nodes[1].processed_rows_per_second = 40;
    store.data = next;
    rerender(<StreamingStatusPanel executionId="e1" isActive />);
    expect(within(row("ingest")).getByRole("img", { name: /Processed rows per second/ })).toBeInTheDocument();
    expect(within(row("quiet")).queryByRole("img")).toBeNull(); // an idle node has no trend to show
  });

  it("renders KPI cards and filters in fullView mode", async () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive fullView />);
    expect(screen.getByText("Throughput")).toBeInTheDocument();
    expect(screen.getByText("1.4k rows/s")).toBeInTheDocument();
    expect(screen.getByText("Avg Latency")).toBeInTheDocument();
    expect(screen.getByText("250 ms")).toBeInTheDocument();

    // Filters: All, Healthy, Alerting, Idle
    expect(screen.getByRole("button", { name: "All (4)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Healthy (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Alerting (2)" })).toBeInTheDocument();

    // Filter to Alerting
    await userEvent.click(screen.getByRole("button", { name: "Alerting (2)" }));
    expect(screen.getByRole("button", { name: "Restart node hung" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restart node enrich" })).toBeInTheDocument();
    expect(screen.queryByText("file_stream → parquet")).toBeNull(); // ingest hidden
  });

  it("copies checkpoint path to clipboard", async () => {
    store.data = running;
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<StreamingStatusPanel executionId="e1" isActive />);
    await userEvent.click(row("ingest"));
    const copyBtn = screen.getByRole("button", { name: "Copy checkpoint path" });
    await userEvent.click(copyBtn);

    expect(writeText).toHaveBeenCalledWith("data/_ckpt/ingest/live/ingest");
    expect(screen.getByText("Copied")).toBeInTheDocument();
  });

  it("renders nothing for an execution that streams nothing", () => {
    store.data = { execution_id: "e1", active: true, pipelines: [] };
    const { container } = render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(container).toBeEmptyDOMElement();
  });

  it("does not poll a finished execution", () => {
    store.data = running;
    const { container } = render(<StreamingStatusPanel executionId="e1" isActive={false} />);
    expect(store.enabled).toBe(false);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("formatRate", () => {
  it("keeps rates short", () => {
    expect(formatRate(null)).toBe("—");
    expect(formatRate(0.537)).toBe("0.54/s");
    expect(formatRate(42.4)).toBe("42/s");
    expect(formatRate(2345)).toBe("2.3k/s");
  });
});
