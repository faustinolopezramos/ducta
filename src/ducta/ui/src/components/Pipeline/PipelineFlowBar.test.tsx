import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { PipelineFlowBar } from "./PipelineFlowBar";
import type { DagCanvasItem } from "./types";
import { EMPTY_FILTER } from "./canvasFilter";

describe("PipelineFlowBar", () => {
  const sampleItems: DagCanvasItem[] = [
    {
      id: "node_ingest",
      name: "node_ingest",
      kind: "node",
      dependsOn: [],
      inputs: [{ id: "p1", name: "raw_files.csv" }],
      outputs: [{ id: "p2", name: "bronze.raw_orders" }],
    },
    {
      id: "node_clean",
      name: "node_clean",
      kind: "node",
      dependsOn: ["node_ingest"],
      inputs: [{ id: "p3", name: "bronze.raw_orders" }],
      outputs: [{ id: "p4", name: "silver.clean_orders" }],
    },
    {
      id: "node_aggregate",
      name: "node_aggregate",
      kind: "node",
      dependsOn: ["node_clean"],
      inputs: [{ id: "p5", name: "silver.clean_orders" }],
      outputs: [{ id: "p6", name: "gold.daily_metrics" }],
    },
  ];

  it("identifies external sources and terminal sinks correctly", () => {
    render(
      <PipelineFlowBar
        items={sampleItems}
        filter={EMPTY_FILTER}
        onFilterChange={vi.fn()}
      />
    );

    // Sources: raw_files.csv (1)
    expect(screen.getByText("Sources")).toBeInTheDocument();
    // Bronze: 1
    expect(screen.getByText("Bronze")).toBeInTheDocument();
    // Silver: 1
    expect(screen.getByText("Silver")).toBeInTheDocument();
    // Gold: 1
    expect(screen.getByText("Gold")).toBeInTheDocument();
    // Sinks: gold.daily_metrics (1)
    expect(screen.getByText("Sinks")).toBeInTheDocument();
  });

  it("toggles facet when clicking a medallion stage", () => {
    const onFilterChange = vi.fn();
    render(
      <PipelineFlowBar
        items={sampleItems}
        filter={EMPTY_FILTER}
        onFilterChange={onFilterChange}
      />
    );

    const silverBtn = screen.getByRole("button", { name: /Silver/i });
    fireEvent.click(silverBtn);

    expect(onFilterChange).toHaveBeenCalledWith({
      ...EMPTY_FILTER,
      facets: ["silver"],
    });
  });

  it("renders failed health badge when a stage has failed nodes", () => {
    render(
      <PipelineFlowBar
        items={sampleItems}
        executionStates={{ node_clean: "failed" }}
        filter={EMPTY_FILTER}
        onFilterChange={vi.fn()}
      />
    );

    expect(screen.getByTitle("1 failed")).toBeInTheDocument();
  });
});
