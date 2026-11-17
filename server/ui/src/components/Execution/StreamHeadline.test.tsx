import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StreamingPipelineStatus } from "../../api/queries/executions";
import type { StreamHistory } from "../../hooks/useStreamHistory";
import { StreamHeadline } from "./StreamHeadline";

const history: StreamHistory = { total: [], input: [], nodes: {}, events: [], count: 0 };

const pipeline = (nodes: StreamingPipelineStatus["nodes"], active = nodes.length): StreamingPipelineStatus => ({
  stream_execution_id: "s1",
  pipeline_name: "live",
  status: "running",
  total_queries: nodes.length,
  active_queries: active,
  failed_queries: 0,
  nodes,
});

const nodes: StreamingPipelineStatus["nodes"] = [
  { node: "ingest", state: "active", input_rows_per_second: 1500, processed_rows_per_second: 1400, trigger_execution_ms: 250 },
  { node: "quiet", state: "active", health: "idle", idle_seconds: 185 },
  { node: "hung", state: "active", health: "stalled" },
  { node: "enrich", state: "failed", error: "boom" },
];

describe("StreamHeadline", () => {
  it("says rate, latency, nodes and what is wrong, in one line", () => {
    render(<StreamHeadline pipeline={pipeline(nodes, 3)} history={history} />);
    const line = screen.getByRole("region", { name: "Stream figures" });
    expect(line).toHaveTextContent("1.4 k rows/s");
    expect(line).toHaveTextContent("Latency250 ms");
    expect(line).toHaveTextContent("slowest ingest · 250 ms");
    expect(line).toHaveTextContent("3 of 4 nodes running");
    expect(line).toHaveTextContent("1 failed · 1 stalled · 1 idle");
  });

  it("leaves input out while the stream keeps up with it, and says so when it does not", () => {
    const { unmount } = render(<StreamHeadline pipeline={pipeline(nodes, 3)} history={history} />);
    expect(screen.getByRole("region", { name: "Stream figures" })).not.toHaveTextContent("input");
    unmount();
    const behind = structuredClone(nodes);
    behind[0].input_rows_per_second = 5000;
    render(<StreamHeadline pipeline={pipeline(behind, 3)} history={history} />);
    expect(screen.getByRole("region", { name: "Stream figures" })).toHaveTextContent("Input5.0 k rows/soutpaces processing by 257%");
  });

  it("says a rising or falling rate", () => {
    // The trend compares the last polls with those of five minutes before: 60 samples at 5 s.
    const rising: StreamHistory = { ...history, total: [...Array(60).fill(100), ...Array(6).fill(300)] };
    render(<StreamHeadline pipeline={pipeline([nodes[0]])} history={rising} />);
    expect(screen.getByRole("region", { name: "Stream figures" })).toHaveTextContent("▲");
  });
});
