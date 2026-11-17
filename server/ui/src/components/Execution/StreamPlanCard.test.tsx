import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StreamPlan } from "../../api/queries/streamPlan";
import { StreamPlanFacts, StreamPlanList, planFires } from "./StreamPlanCard";
import { shortPath } from "../../utils/streaming";

const plan: StreamPlan = {
  pipeline: "events_stream",
  env: "dev",
  ok: false,
  issues: [{ level: "error", text: "two nodes share a checkpoint" }],
  nodes: [
    {
      name: "ingest",
      source: "file_stream json data/events",
      sink: "parquet data/bronze",
      trigger: "every 5 seconds",
      output_mode: "append",
      checkpoint: "data/_ckpt/ingest",
      after: [],
      issues: [],
    },
    {
      name: "clean",
      source: "file_stream parquet data/bronze",
      sink: "parquet data/silver",
      trigger: "every 5 seconds",
      output_mode: "append",
      checkpoint: "data/_ckpt/clean",
      after: ["ingest"],
      transform: "clean_events",
      issues: [
        { level: "error", text: "transform 'clean_events' is not registered" },
        { level: "warning", text: "source path 'data/bronze' does not exist yet" },
      ],
    },
  ],
};

describe("shortPath", () => {
  it("keeps the end of a long path, the part that tells nodes apart", () => {
    expect(shortPath("data/dev/_ckpt/clean/events_stream/clean")).toBe("…/events_stream/clean");
    expect(shortPath("data/_ckpt")).toBe("data/_ckpt");
  });
});

describe("StreamPlanFacts", () => {
  it("lists only what the node has: no Transform row for a node without one", () => {
    render(<StreamPlanFacts node={plan.nodes[0]} variant="grid" />);
    expect(screen.getByText("Reads")).toBeInTheDocument();
    expect(screen.getByText("Writes")).toBeInTheDocument();
    expect(screen.queryByText("Transform")).toBeNull();
    expect(screen.queryByText("After")).toBeNull();
    expect(screen.getByText(planFires(plan.nodes[0]))).toBeInTheDocument();
  });

  it("says its problems in words, errors and warnings alike", () => {
    render(<StreamPlanFacts node={plan.nodes[1]} variant="grid" />);
    expect(screen.getByText("transform 'clean_events' is not registered")).toBeInTheDocument();
    expect(screen.getByText("source path 'data/bronze' does not exist yet")).toBeInTheDocument();
  });
});

describe("StreamPlanFacts, in the node panel", () => {
  it("fits two lines: reads and writes, then transform, trigger and what it waits for", () => {
    render(<StreamPlanFacts node={plan.nodes[1]} />);
    expect(screen.getByText("data/silver", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("transform clean_events · every 5 seconds · append · after ingest")).toBeInTheDocument();
    expect(screen.queryByText("Reads")).toBeNull();
  });
});

describe("StreamPlanList", () => {
  it("marks a node with an error and leaves a healthy one alone, with the problems under it", () => {
    render(<StreamPlanList plan={plan} />);
    const rows = screen.getAllByRole("listitem").filter((li) => li.className.includes("stream-plan-list__row"));
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-bad", "false");
    expect(rows[1]).toHaveAttribute("data-bad", "true");
    expect(rows[1]).toHaveTextContent("transform 'clean_events' is not registered");
    expect(rows[1]).toHaveTextContent("does not exist yet");
  });

  it("shows the problems that belong to no node", () => {
    render(<StreamPlanList plan={plan} />);
    expect(screen.getByText("two nodes share a checkpoint")).toBeInTheDocument();
  });
});
