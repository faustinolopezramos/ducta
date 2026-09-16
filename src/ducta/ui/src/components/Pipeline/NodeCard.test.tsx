import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NodeCard } from "./NodeCard";
import type { DagCanvasItem } from "./types";

/**
 * The card is what you scan a graph for: the function's name and how its run
 * went. How it is addressed, its checks and gate, and its datasets live in the
 * focus panel (and the datasets on the edges), so the card must not repeat them.
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

  it("marks the medallion layer of its output with a swatch", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    expect(container.querySelector(".node-card-swatch")).not.toBeNull();
    expect(container.querySelector(".node-card")!.getAttribute("data-layer")).toBe("silver");
  });

  it("drops the swatch when a band already names the layer", () => {
    const { container } = render(<NodeCard node={node} {...base} showLayer={false} />);
    expect(container.querySelector(".node-card-swatch")).toBeNull();
    // Still on the element for styling.
    expect(container.querySelector(".node-card")!.getAttribute("data-layer")).toBe("silver");
  });

  it("leaves the entry point, gate and checks to the focus panel", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    expect(container.textContent).not.toContain("src.clean:run");
    expect(container.textContent).not.toMatch(/gate/i);
    expect(container.textContent).not.toMatch(/check/i);
  });

  it("shows the last run's duration as its one fact", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    expect(container.querySelector(".node-card-fact")!.textContent).toBe("812 ms");
  });

  it("says the run failed instead of how long it took", () => {
    const { container } = render(<NodeCard node={node} {...base} execState="failed" />);
    const fact = container.querySelector(".node-card-fact")!;
    expect(fact.textContent).toBe("failed");
    expect(fact.classList.contains("node-card-fact--failed")).toBe(true);
  });

  it("omits the fact when the node has never run", () => {
    const { container } = render(<NodeCard node={{ ...node, lastDuration: null }} {...base} />);
    expect(container.querySelector(".node-card-fact")).toBeNull();
  });

  it("does not draw the datasets — they belong to the edges", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    expect(container.textContent).not.toContain("bronze.raw_results");
    expect(container.querySelector(".ds-chip")).toBeNull();
  });

  it("keeps a port anchor per dataset, along the top and bottom by default", () => {
    const { container } = render(<NodeCard node={node} {...base} />);
    const ports = container.querySelectorAll<HTMLElement>(".node-port");
    expect(ports).toHaveLength(2);
    expect(ports[0].style.left).toBe("50%");
    expect(ports[0].style.top).toBe("");
  });

  it("moves the ports to the sides when the layers run left to right", () => {
    const { container } = render(<NodeCard node={node} {...base} orientation="horizontal" />);
    const card = container.querySelector(".node-card")!;
    expect(card.getAttribute("data-orientation")).toBe("horizontal");
    const port = container.querySelector<HTMLElement>(".node-port-in")!;
    expect(port.style.top).toBe("50%");
    expect(port.style.left).toBe("");
  });

  it("names its I/O counts and gate in the accessible label", () => {
    render(<NodeCard node={node} {...base} execState="success" />);
    expect(
      screen.getByLabelText("Node clean_results, success, reads 1, writes 1, gate skip downstream")
    ).toBeInTheDocument();
  });

  it("reports its pressed state so selection is not colour-only", () => {
    render(<NodeCard node={node} {...base} selected />);
    expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true");
  });

  it("stays clickable as upstream context, unlike a dimmed card", () => {
    const onClick = vi.fn();
    const { container } = render(<NodeCard node={node} {...base} context onClick={onClick} />);
    expect(container.querySelector(".node-card")!.classList.contains("node-card--context")).toBe(true);
    screen.getByRole("button").click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  describe("semantic zoom", () => {
    it("at `shape` keeps only the name and status", () => {
      const { container } = render(
        <NodeCard node={node} {...base} tier="shape" execState="success" />
      );
      expect(screen.getByText("clean_results")).toBeInTheDocument();
      expect(container.querySelector(".node-card-swatch")).toBeNull();
      expect(container.querySelector(".node-card-fact")).toBeNull();
      expect(container.querySelector(".node-card-status")).not.toBeNull();
    });

    it("at `flow` keeps the swatch but not the fact", () => {
      const { container } = render(<NodeCard node={node} {...base} tier="flow" />);
      expect(container.querySelector(".node-card-swatch")).not.toBeNull();
      expect(container.querySelector(".node-card-fact")).toBeNull();
    });
  });

  it("fires onClick from the keyboard as well as the mouse", () => {
    const onClick = vi.fn();
    render(<NodeCard node={node} {...base} onClick={onClick} />);
    const card = screen.getByRole("button");
    card.focus();
    card.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    card.click();
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});
