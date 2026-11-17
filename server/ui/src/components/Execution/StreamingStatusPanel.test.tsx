import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamingStatusResponse } from "../../api/queries/executions";

const store: { data?: StreamingStatusResponse; enabled?: boolean; updatedAt?: number } = {};
const restart = vi.fn();
const cancel = vi.fn();

vi.mock("../../api/queries/executions", () => ({
  STREAMING_POLL_MS: 5000,
  useExecutionStreaming: (_id: string, enabled: boolean) => {
    store.enabled = enabled;
    return { data: store.data, dataUpdatedAt: store.updatedAt };
  },
}));
vi.mock("../../api/mutations", () => ({
  useRestartStreamingNode: () => ({ mutate: restart, isPending: false }),
  useCancelExecution: () => ({ mutate: cancel, isPending: false }),
}));
vi.mock("../../hooks/usePermission", () => ({ usePermission: () => true, requiresPermission: () => "" }));

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

/** The list item of a node, found by its name (a note under the name does not get in the way). */
const rowOf = (name: string): HTMLElement => {
  const li = Array.from(document.querySelectorAll<HTMLElement>(".stream-row")).find(
    (el) => el.querySelector(".stream-row__name")?.firstChild?.textContent === name,
  );
  if (!li) throw new Error(`no row for ${name}`);
  return li;
};
/** The button that opens a node's row. */
const row = (name: string) => within(rowOf(name)).getAllByRole("button")[0];
const rowNames = () => Array.from(document.querySelectorAll(".stream-row__name")).map((n) => n.firstChild?.textContent);

beforeEach(() => {
  store.data = undefined;
  store.updatedAt = undefined;
  restart.mockClear();
  cancel.mockClear();
});

describe("StreamingStatusPanel — compact (above the logs)", () => {
  it("says how many nodes run, in one line, and has one row per node", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    const stream = screen.getByRole("region", { name: "Stream live" });
    expect(stream).toHaveTextContent("3 of 4 nodes running · up 12m");
    expect(within(stream).getAllByRole("listitem")).toHaveLength(4);
  });

  it("says how fast the stream goes in its header, so the dock needs no other tab", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(screen.getByRole("region", { name: "Stream live" })).toHaveTextContent("1.4k rows/s · 3 of 4 nodes running · up 12m");
  });

  it("draws the stream's recent rate beside it once there are two polls", () => {
    store.data = running;
    store.updatedAt = 1;
    const { rerender } = render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(screen.queryByRole("img", { name: /whole stream/ })).toBeNull();
    store.updatedAt = 2;
    rerender(<StreamingStatusPanel executionId="e1" isActive />);
    expect(screen.getByRole("img", { name: /Rows per second of the whole stream/ })).toBeInTheDocument();
  });

  it("has no figures line nor chart", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(screen.queryByRole("region", { name: "Stream figures" })).toBeNull();
    expect(screen.queryByText("Collecting…")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("stops the whole stream, after asking", async () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    await userEvent.click(screen.getByRole("button", { name: "Stop stream" }));
    expect(cancel).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Stop live?");
    expect(dialog).toHaveTextContent("resumes each from its checkpoint");
    await userEvent.click(within(dialog).getByRole("button", { name: "Stop stream" }));
    expect(cancel).toHaveBeenCalledWith("e1", expect.anything());
  });

  it("does not stop anything when the question is dismissed", async () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    await userEvent.click(screen.getByRole("button", { name: "Stop stream" }));
    await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(cancel).not.toHaveBeenCalled();
  });

  it("a healthy row is its state, its name, what it moves and its rate", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    const ingest = rowOf("ingest");
    expect(ingest).toHaveTextContent("Running");
    expect(ingest).toHaveTextContent("file_stream");
    expect(ingest).toHaveTextContent("parquet");
    expect(ingest).toHaveTextContent("data/bronze");
    expect(ingest).toHaveTextContent("1.4k/s");
    expect(screen.queryByText(/checkpoint/)).toBeNull(); // the detail is closed
    expect(screen.queryByRole("button", { name: /Restart node ingest/ })).toBeNull(); // no button on a healthy node
  });

  it("says the state in words: idle, stalled, failed", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    expect(rowOf("quiet")).toHaveTextContent("Idle for 3 min");
    expect(rowOf("quiet")).toHaveTextContent("No new input");
    expect(rowOf("hung")).toHaveTextContent("Stalled");
    expect(rowOf("hung")).toHaveTextContent("No progress report for a long time");
    expect(rowOf("enrich")).toHaveTextContent("Failed");
    expect(rowOf("enrich")).toHaveTextContent("AnalysisException: no column x");
    expect(rowOf("quiet")).not.toHaveTextContent("Failed");
  });

  it("opens a row to what it reads and writes, its trigger, batch, model and checkpoint", async () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    await userEvent.click(row("ingest"));
    const li = rowOf("ingest");
    expect(row("ingest")).toHaveAttribute("aria-expanded", "true");
    expect(li).toHaveTextContent("Readsfile_stream json data/events");
    expect(li).toHaveTextContent("Writesparquet data/bronze");
    expect(li).toHaveTextContent("Triggerevery 5 seconds");
    expect(li).toHaveTextContent("Last batch#8 · 250 ms");
    expect(li).toHaveTextContent("Modelfraud v3");
    expect(li).toHaveTextContent("checkpoint data/_ckpt/ingest/live/ingest");
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
    expect(rowOf("late")).toHaveTextContent("Skipped");
    expect(rowOf("late")).toHaveTextContent("upstream failed");
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
    expect(within(rowOf("ingest")).getByRole("img", { name: /Processed rows per second/ })).toBeInTheDocument();
    expect(within(rowOf("quiet")).queryByRole("img")).toBeNull(); // an idle node has no trend to show
  });

  it("copies the checkpoint path to the clipboard", async () => {
    store.data = running;
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<StreamingStatusPanel executionId="e1" isActive />);
    await userEvent.click(row("ingest"));
    await userEvent.click(screen.getByRole("button", { name: "Copy checkpoint path" }));

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
