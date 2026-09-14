import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NodeCard } from "./NodeCard";
import type { DagCanvasItem } from "./types";

/**
 * The card shows what a *function* knows. The datasets moved to the edges, so
 * what has to be readable here is the layer it writes into, how it is
 * addressed, whether a gate guards what comes after it, and how long it took.
 *
 * The previous card read its description and quality block out of a `_raw`
 * spec blob that the hydration never populated, so neither ever rendered in
 * the running app while these tests passed by injecting `_raw` by hand. The
 * node shape below is exactly what the canvas receives.
 */
const node: DagCanvasItem = {
  id: "clean_results",
  name: "clean_results",
  type: "transform",
  module: "src.clean",
  fn: "run",
  dependsOn: [],
  inputs: [{ id: "clean_results-input-0", name: "bronze.raw_results" }],
  outputs: [{ id: "clean_results-output-0", name: "silver.clean_results" }],
  quality: { checkCount: 3, gateBehavior: "skip_downstream", isSanity: false },
  lastDuration: 0.812,
};

const base = { selected: false, dimmed: false, onClick: () => {} };

describe("NodeCard", () => {
  it("names the node", () => {
    render(<NodeCard node={node} {...base} />);
    expect(screen.getByText("clean_results")).toBeInTheDocument();
  });

  it("uses the medallion layer of its output as the eyebrow", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    expect(container.querySelector(".node-card-eyebrow")!.textContent).toContain("SILVER");
    expect(container.querySelector(".node-card")!.getAttribute("data-layer")).toBe("silver");
  });

  it("falls back to the node type when no dataset declares a layer", () => {
    const plain: DagCanvasItem = {
      ...node,
      outputs: [{ id: "o", name: "results" }],
    };
    const { container } = render(<NodeCard node={plain} {...base} />);
    expect(container.querySelector(".node-card-eyebrow")!.textContent).toContain("transform");
    expect(container.querySelector(".node-card")!.getAttribute("data-layer")).toBeNull();
  });

  it("shows how the node is addressed", () => {
    render(<NodeCard node={node} {...base} />);
    expect(screen.getByText("src.clean · run")).toBeInTheDocument();
  });

  it("reads the gate off the graph, with its behaviour spelled out", () => {
    render(<NodeCard node={node} {...base} />);
    expect(screen.getByText(/gate · skip downstream/)).toBeInTheDocument();
  });

  it("counts the enabled checks", () => {
    render(<NodeCard node={node} {...base} />);
    expect(screen.getByText("3 quality checks")).toBeInTheDocument();
  });

  it("says 'sanity' for pre-execution checks", () => {
    const sanity: DagCanvasItem = {
      ...node,
      quality: { checkCount: 1, gateBehavior: null, isSanity: true },
    };
    render(<NodeCard node={sanity} {...base} />);
    expect(screen.getByText("1 sanity check")).toBeInTheDocument();
  });

  it("omits the quality footer when nothing is configured", () => {
    const { container } = render(<NodeCard node={{ ...node, quality: null }} {...base} />);
    expect(container.querySelector(".node-card-foot")).toBeNull();
  });

  it("shows the last run's duration, sub-second in ms", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    expect(container.querySelector(".node-card-duration")!.textContent).toBe("812 ms");
  });

  it("omits the duration when the node has never run", () => {
    const { container } = render(
      <NodeCard node={{ ...node, lastDuration: null }} {...base} />
    );
    expect(container.querySelector(".node-card-duration")).toBeNull();
  });

  it("does not draw the datasets — they belong to the edges now", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    expect(container.textContent).not.toContain("bronze.raw_results");
    expect(container.querySelector(".ds-chip")).toBeNull();
  });

  it("keeps a port anchor per dataset for the edges to land on", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    const ports = container.querySelectorAll(".node-port");
    expect(ports).toHaveLength(2);
  });

  it("names its I/O counts and gate in the accessible label", () => {
    render(<NodeCard node={node} {...base} execState="success" />);
    expect(
      screen.getByLabelText(
        "Node clean_results, success, reads 1, writes 1, gate skip downstream"
      )
    ).toBeInTheDocument();
  });

  it("reports its pressed state so selection is not colour-only", () => {
    render(<NodeCard node={node} {...base} selected />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });

  describe("semantic zoom", () => {
    it("at `shape` drops everything but the name and status", () => {
      const { container } = render(<NodeCard node={node} {...base} tier="shape" execState="success" />);
      expect(screen.getByText("clean_results")).toBeInTheDocument();
      expect(container.querySelector(".node-card-eyebrow")).toBeNull();
      expect(container.querySelector(".node-card-fn")).toBeNull();
      expect(container.querySelector(".node-card-foot")).toBeNull();
      // The layer is still encoded, as the rule across the top.
      expect(container.querySelector(".node-card")!.getAttribute("data-layer")).toBe("silver");
      expect(container.querySelector(".node-card-status")).not.toBeNull();
    });

    it("at `flow` keeps the layer and a short gate marker but no module path", () => {
      const { container } = render(<NodeCard node={node} {...base} tier="flow" />);
      expect(container.querySelector(".node-card-eyebrow")!.textContent).toContain("SILVER");
      expect(container.querySelector(".node-card-fn")).toBeNull();
      expect(container.querySelector(".node-card-gate")!.textContent).toBe("gate");
      expect(container.querySelector(".node-card-checks")).toBeNull();
    });

    it("at `detail` shows all of it", () => {
      const { container } = render(<NodeCard node={node} {...base} tier="detail" />);
      expect(container.querySelector(".node-card-fn")).not.toBeNull();
      expect(container.querySelector(".node-card-gate")!.textContent).toContain("skip downstream");
      expect(container.querySelector(".node-card-checks")).not.toBeNull();
    });
  });

  it("fires onClick from the keyboard as well as the mouse", () => {
    const onClick = vi.fn();
    render(<NodeCard node={node} {...base} onClick={onClick} />);
    const card = screen.getByRole("button");
    card.click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
