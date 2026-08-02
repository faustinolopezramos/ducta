import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DagCanvas, edgePath, type DagCanvasItem } from "./DagCanvas";

const items: DagCanvasItem[] = [
  {
    id: "raw_events",
    name: "raw_events",
    type: "source",
    dependsOn: [],
    inputs: [],
    outputs: [{ id: "o1", name: "events", format: "parquet" }],
  },
  {
    id: "clean_events",
    name: "clean_events",
    type: "transform",
    dependsOn: ["raw_events"],
    inputs: [{ id: "i1", name: "events", format: "parquet" }],
    outputs: [{ id: "o2", name: "events_clean", format: "df" }],
  },
  {
    id: "warehouse",
    name: "warehouse",
    type: "sink",
    dependsOn: ["clean_events"],
    inputs: [{ id: "i2", name: "events_clean", format: "df" }],
    outputs: [],
  },
];

describe("edgePath", () => {
  it("draws a soft elbow for a direct hop", () => {
    const d = edgePath([
      { x: 0, y: 0 },
      { x: 100, y: 200 },
    ]);
    expect(d).toBe("M 0 0 C 0 80, 100 120, 100 200");
  });

  it("splines through the waypoints of a routed edge", () => {
    const d = edgePath([
      { x: 0, y: 0 },
      { x: 50, y: 100 },
      { x: 0, y: 200 },
    ]);
    // One curve per segment, ending on each waypoint in turn.
    expect(d.match(/C/g)).toHaveLength(2);
    expect(d).toContain("50 100");
    expect(d.endsWith("0 200")).toBe(true);
  });

  it("returns nothing for a degenerate edge", () => {
    expect(edgePath([{ x: 1, y: 1 }])).toBe("");
  });
});

describe("DagCanvas", () => {
  it("stacks a chain into layers and settles without re-render loops", () => {
    // If the measure → layout → measure cycle failed to converge this render
    // would never return.
    render(<DagCanvas items={items} />);

    const tops = items.map((item) => {
      const wrapper = document.querySelector<HTMLElement>(`[data-node-id="${item.id}"]`);
      expect(wrapper).not.toBeNull();
      expect(wrapper!.style.position).toBe("absolute");
      return parseFloat(wrapper!.style.top);
    });

    // One layer per node in a linear chain, top to bottom in dependency order.
    expect(tops).toEqual([...tops].sort((a, b) => a - b));
    expect(new Set(tops).size).toBe(3);
  });

  it("draws one edge path per dependency", () => {
    const { container } = render(<DagCanvas items={items} />);
    const paths = container.querySelectorAll("path.dag-edge");
    expect(paths).toHaveLength(2);
    for (const path of paths) expect(path.getAttribute("d")).toMatch(/^M /);
  });

  it("renders a typed port with its format chip on each side", () => {
    render(<DagCanvas items={items} />);

    // clean_events has one input and one output, each centred on its edge.
    const card = screen.getByLabelText(/Node clean_events/).closest(".node-card")!;
    const ports = card.querySelectorAll<HTMLElement>(".node-port");
    expect(ports).toHaveLength(2);
    expect(ports[0].className).toContain("node-port-in");
    expect(ports[0].style.left).toBe("50%");
    expect(ports[1].className).toContain("node-port-out");

    expect(card.querySelector(".node-port-in .port-chip")!.textContent).toBe("parquet");
    expect(card.querySelector(".node-port-out .port-chip")!.textContent).toBe("df");
  });

  it("falls back to an unpositioned row when the graph has a cycle", () => {
    const cyclic: DagCanvasItem[] = [
      { id: "a", dependsOn: ["b"] },
      { id: "b", dependsOn: ["a"] },
    ];
    const { container } = render(<DagCanvas items={cyclic} />);

    expect(screen.getByText(/Cycle detected/)).toBeInTheDocument();
    expect(container.querySelector(".dag-level-row")).not.toBeNull();
    expect(container.querySelectorAll("path.dag-edge")).toHaveLength(0);
  });
});
