import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { StreamLiveLine } from "./StreamLiveLine";

const streaming = vi.fn();
vi.mock("../../api/queries/executions", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/queries/executions")>()),
  useExecutionStreaming: () => streaming(),
}));

const node = (over: Record<string, unknown>) => ({ node: "n", state: "active", processed_rows_per_second: 140, ...over });
const status = (nodes: unknown[], over: Record<string, unknown> = {}) => ({
  data: {
    execution_id: "e",
    active: true,
    pipelines: [{ status: "running", active_queries: nodes.length, total_queries: nodes.length, nodes, ...over }],
  },
  dataUpdatedAt: Date.parse("2026-11-16T12:14:00Z"),
});
const startedAt = "2026-11-16T12:00:00Z";

describe("StreamLiveLine", () => {
  beforeEach(() => streaming.mockReset());

  it("says how many nodes run, how fast, and for how long", () => {
    streaming.mockReturnValue(status([node({}), node({ node: "m", processed_rows_per_second: 140 })]));
    render(<StreamLiveLine executionId="e" startedAt={startedAt} />);
    expect(screen.getByRole("status")).toHaveTextContent("2 nodes running · 280 rows/s · up 14 min");
  });

  it("says the problem in words, not only by colour", () => {
    streaming.mockReturnValue(status([node({}), node({ node: "m", state: "failed" })], { active_queries: 1 }));
    render(<StreamLiveLine executionId="e" startedAt={startedAt} />);
    expect(screen.getByRole("status")).toHaveTextContent("1 of 2 nodes failed");
  });

  it("while the first status has not arrived: starting, with no figures", () => {
    streaming.mockReturnValue({ data: undefined, dataUpdatedAt: 0 });
    render(<StreamLiveLine executionId="e" startedAt={startedAt} />);
    expect(screen.getByRole("status")).toHaveTextContent("Starting…");
    expect(screen.getByRole("status")).not.toHaveTextContent("up ");
  });
});
