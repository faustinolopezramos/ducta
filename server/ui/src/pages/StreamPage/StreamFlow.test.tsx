import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { StreamingNodeStatus } from "../../api/queries/executions";
import { StreamNotes, StreamTabs } from "./StreamFlow";

const nodes: StreamingNodeStatus[] = [
  { node: "ingest", state: "active", processed_rows_per_second: 1200, source: "file_stream json data/events", sink: "parquet data/bronze" },
  { node: "enrich", state: "failed", error: "AnalysisException: no column x" },
  { node: "score", state: "active", health: "stalled" },
  { node: "publish", state: "active", health: "idle", idle_seconds: 185 },
];

describe("StreamTabs", () => {
  it("draws the nodes in order, each with its rate or its state in words", () => {
    render(<StreamTabs nodes={nodes} selected="ingest" onSelect={vi.fn()} />);
    const tabs = within(screen.getByRole("group", { name: "Nodes" })).getAllByRole("button");
    expect(tabs.map((c) => c.textContent)).toEqual(["ingest1.2k/s", "enrichfailed", "scorestalled", "publishidle for 3 min"]);
  });

  it("marks the selected node and selects another on click", async () => {
    const onSelect = vi.fn();
    render(<StreamTabs nodes={nodes} selected="ingest" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: /^ingest/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^enrich/ })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: /^enrich/ }));
    expect(onSelect).toHaveBeenCalledWith("enrich");
  });
});

describe("StreamNotes", () => {
  function setup(canRestart = true) {
    const onRestart = vi.fn();
    const onViewLogs = vi.fn();
    render(<StreamNotes nodes={nodes} canRestart={canRestart} restartingNode={null} onRestart={onRestart} onViewLogs={onViewLogs} />);
    return { onRestart, onViewLogs };
  }

  it("says what is wrong in words, with Restart for the nodes that need a look", async () => {
    const { onRestart, onViewLogs } = setup();
    const notes = within(screen.getByRole("list", { name: "Nodes that need a look" })).getAllByRole("listitem");
    expect(notes).toHaveLength(2); // failed and stalled: an idle node is just quiet
    expect(notes[0]).toHaveTextContent("enrich AnalysisException: no column x");
    expect(notes[1]).toHaveTextContent("score No progress report");
    await userEvent.click(screen.getByRole("button", { name: "Restart node enrich" }));
    expect(onRestart).toHaveBeenCalledWith("enrich");
    await userEvent.click(within(notes[0]).getByRole("button", { name: "Logs" }));
    expect(onViewLogs).toHaveBeenCalled();
  });

  it("offers no Restart when the stream is not running", () => {
    setup(false);
    expect(screen.queryByRole("button", { name: /Restart node/ })).toBeNull();
  });

  it("draws nothing while every node is well", () => {
    const { container } = render(<StreamNotes nodes={[nodes[0], nodes[3]]} canRestart restartingNode={null} onRestart={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
