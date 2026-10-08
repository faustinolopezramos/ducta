import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamingStatusResponse } from "../../api/queries/executions";

const store: { data?: StreamingStatusResponse; enabled?: boolean } = {};

vi.mock("../../api/queries/executions", () => ({
  useExecutionStreaming: (_id: string, enabled: boolean) => {
    store.enabled = enabled;
    return { data: store.data };
  },
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
      uptime_seconds: 125,
      total_queries: 2,
      active_queries: 1,
      failed_queries: 1,
      nodes: [
        {
          node: "score",
          state: "active",
          last_batch_id: 8,
          input_rows_per_second: 1500,
          processed_rows_per_second: 12.4,
          trigger_execution_ms: 250,
          model: { name: "fraud", version: 3 },
        },
        { node: "enrich", state: "failed", error: "AnalysisException: no column x" },
      ],
    },
  ],
};

beforeEach(() => {
  store.data = undefined;
});

describe("StreamingStatusPanel", () => {
  it("shows each query's state, throughput and model, and what failed", () => {
    store.data = running;
    render(<StreamingStatusPanel executionId="e1" isActive />);
    const stream = screen.getByRole("region", { name: "Stream live" });
    expect(stream).toHaveTextContent("1/2 queries active · up 2m 5s");
    const score = within(stream).getByText("score").closest("tr") as HTMLElement;
    expect(within(score).getByText("8")).toBeInTheDocument();
    expect(within(score).getByText("1.5k/s")).toBeInTheDocument();
    expect(within(score).getByText("12/s")).toBeInTheDocument();
    expect(within(score).getByText("250 ms")).toBeInTheDocument();
    expect(within(score).getByText("fraud v3")).toBeInTheDocument();
    expect(within(stream).getByRole("alert")).toHaveTextContent("enrich: AnalysisException: no column x");
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
