import { beforeAll, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DagCanvas, edgePath } from "./DagCanvas";
import type { CanvasDataset, DagCanvasItem } from "./types";

/**
 * React Flow measures its own container and nodes through APIs jsdom does not
 * implement. Without these it renders an empty pane and every assertion below
 * fails for the wrong reason. This is React Flow's documented test setup, not a
 * workaround for anything in Ducta.
 */
beforeAll(() => {
  // An inert ResizeObserver is not enough: React Flow only registers a node as
  // measured when the observer actually reports a box, and it will not draw an
  // edge between two unmeasured nodes. So this one fires once on observe().
  //
  // The pane gets a realistic desktop box rather than a node-sized one. React
  // Flow derives the zoom from the pane's size, and a 200x96 pane makes
  // `fitView` zoom far enough out that the cards and dataset chips drop to
  // their `shape` tier — which is correct behaviour, but it is not the tier
  // most of these assertions are about.
  class ResizeObserverMock {
    constructor(private readonly cb: ResizeObserverCallback) {}
    observe(target: Element) {
      const isNode = target.classList?.contains("react-flow__node");
      const contentRect = isNode
        ? { width: 200, height: 96 }
        : { width: 1200, height: 800 };
      this.cb(
        [{ target, contentRect } as unknown as ResizeObserverEntry],
        this as unknown as ResizeObserver
      );
    }
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverMock as unknown as typeof ResizeObserver;

  if (!globalThis.DOMMatrixReadOnly) {
    class DOMMatrixReadOnlyMock {
      m22 = 1;
      constructor(readonly transform?: string) {}
    }
    // @ts-expect-error - minimal stand-in, only `m22` is read by React Flow.
    globalThis.DOMMatrixReadOnly = DOMMatrixReadOnlyMock;
  }

  // React Flow sizes its viewport from the pane's offset box, so the pane has
  // to report a desktop-sized one — otherwise `fitView` zooms out far enough
  // that every card and chip drops to its `shape` tier.
  Object.defineProperties(globalThis.HTMLElement.prototype, {
    offsetHeight: {
      get() {
        if (this.classList?.contains("react-flow__node")) return 96;
        return parseFloat(this.style.height) || 800;
      },
    },
    offsetWidth: {
      get() {
        if (this.classList?.contains("react-flow__node")) return 200;
        return parseFloat(this.style.width) || 1200;
      },
    },
  });
  (globalThis.SVGElement as unknown as { prototype: Record<string, unknown> }).prototype
    .getBBox = () => ({ x: 0, y: 0, width: 0, height: 0 });

  // React Flow will not draw an edge until it has measured both of its handles,
  // and jsdom reports every rect as zero-sized. Give handles a real box so the
  // edge layer has somewhere to attach.
  globalThis.Element.prototype.getBoundingClientRect = function (this: Element) {
    const isHandle = this.classList?.contains("react-flow__handle");
    const isNode = this.classList?.contains("react-flow__node");
    const box = isHandle
      ? { width: 1, height: 1 }
      : isNode
        ? { width: 200, height: 96 }
        : { width: 1200, height: 800 };
    return {
      x: 0, y: 0, top: 0, left: 0,
      right: box.width, bottom: box.height,
      ...box,
      toJSON() { return this; },
    } as DOMRect;
  };
});

/**
 * A three-node chain wired by datasets. The names are the wiring: `clean_events`
 * reads what `raw_events` writes, so the edge between them exists *because* of
 * `bronze.events`.
 */
const items: DagCanvasItem[] = [
  {
    id: "raw_events",
    name: "raw_events",
    type: "source",
    dependsOn: [],
    inputs: [],
    outputs: [{ id: "raw_events-output-0", name: "bronze.events" }],
  },
  {
    id: "clean_events",
    name: "clean_events",
    type: "transform",
    dependsOn: [],
    inputs: [{ id: "clean_events-input-0", name: "bronze.events" }],
    outputs: [{ id: "clean_events-output-0", name: "silver.events" }],
  },
  {
    id: "warehouse",
    name: "warehouse",
    type: "sink",
    dependsOn: [],
    inputs: [{ id: "warehouse-input-0", name: "silver.events" }],
    outputs: [],
  },
];

/** What `GET /projects/{id}/datasets` resolves those references to. */
const datasets = new Map<string, CanvasDataset>([
  [
    "bronze.events",
    { name: "bronze.events", declared: true, format: "parquet", writeMode: "overwrite", layer: "bronze" },
  ],
  [
    "silver.events",
    { name: "silver.events", declared: true, format: "delta", writeMode: "merge", layer: "silver" },
  ],
]);

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
  it("renders every node of the chain", () => {
    const { container } = render(<DagCanvas items={items} datasets={datasets} />);

    const nodes = container.querySelectorAll(".react-flow__node");
    expect(nodes).toHaveLength(3);
    for (const item of items) {
      expect(container.querySelector(`[data-id="${item.id}"]`)).not.toBeNull();
    }
  });

  it("places each node at the position the layout computed", () => {
    const { container } = render(<DagCanvas items={items} datasets={datasets} />);

    // A linear chain is one node per layer, so the y offsets must be strictly
    // increasing in dependency order. React Flow positions via a transform.
    const tops = items.map((item) => {
      const el = container.querySelector<HTMLElement>(`[data-id="${item.id}"]`);
      expect(el).not.toBeNull();
      const match = /translate\(([-\d.]+)px,\s*([-\d.]+)px\)/.exec(el!.style.transform);
      expect(match, `no transform on ${item.id}`).not.toBeNull();
      return parseFloat(match![2]);
    });

    expect(tops).toEqual([...tops].sort((a, b) => a - b));
    expect(new Set(tops).size).toBe(3);
  });

  it("derives an edge from the dataset wiring, with no declared dependencies", () => {
    // Every `dependsOn` above is empty: the graph comes from the names alone.
    const { container } = render(<DagCanvas items={items} datasets={datasets} />);

    const paths = container.querySelectorAll<SVGPathElement>(".react-flow__edge-path");
    expect(paths).toHaveLength(2);
    // Each is the spline `layoutDag` routed, not React Flow's default bezier.
    for (const path of paths) expect(path.getAttribute("d")).toMatch(/^M /);
  });

  /**
   * Which dataset a chip carries, read in a way that holds at every zoom tier.
   * At `shape` the chip is a bare dot, so its identity lives in `title` and
   * `data-format` rather than in text — what the chip renders per tier is
   * DatasetChip's own business, and DatasetChip.test.tsx covers it.
   */
  const chipIdentities = (root: HTMLElement) =>
    [...root.querySelectorAll<HTMLElement>(".ds-chip")].map((c) => ({
      name: c.getAttribute("title") ?? c.querySelector(".ds-chip-name")?.textContent,
      format: c.getAttribute("data-format"),
    }));

  it("puts each dataset on the edge it flows across, with its resolved format", () => {
    const { container } = render(<DagCanvas items={items} datasets={datasets} />);

    // parquet and delta are both tabular, but they are two *different*
    // declarations — the old canvas hard-coded "parquet" for every dataset.
    expect(chipIdentities(container)).toEqual([
      { name: "bronze.events", format: "table" },
      { name: "silver.events", format: "table" },
    ]);
  });

  it("resolves a streaming format distinctly from a tabular one", () => {
    const streaming = new Map(datasets);
    streaming.set("silver.events", {
      name: "silver.events",
      declared: true,
      format: "kafka",
      layer: "silver",
    });
    const { container } = render(<DagCanvas items={items} datasets={streaming} />);

    expect(chipIdentities(container)).toEqual([
      { name: "bronze.events", format: "table" },
      { name: "silver.events", format: "stream" },
    ]);
  });

  it("keeps two shared datasets as two edges with two chips", () => {
    // The old canvas de-duplicated by `from→to` pair, collapsing this into one
    // unlabelled line, so which datasets crossed it was unknowable.
    const twin: DagCanvasItem[] = [
      {
        id: "producer",
        name: "producer",
        dependsOn: [],
        inputs: [],
        outputs: [
          { id: "producer-output-0", name: "bronze.a" },
          { id: "producer-output-1", name: "bronze.b" },
        ],
      },
      {
        id: "consumer",
        name: "consumer",
        dependsOn: [],
        inputs: [
          { id: "consumer-input-0", name: "bronze.a" },
          { id: "consumer-input-1", name: "bronze.b" },
        ],
        outputs: [],
      },
    ];
    const { container } = render(<DagCanvas items={twin} />);

    expect(container.querySelectorAll(".react-flow__edge-path")).toHaveLength(2);
    expect(chipIdentities(container).map((c) => c.name)).toEqual(["bronze.a", "bronze.b"]);
  });

  it("marks a dataset reference that is not in the registry", () => {
    // Nothing declares these here, so no chip may claim a format — a dangling
    // reference is a config problem the user has to be told about.
    const { container } = render(<DagCanvas items={items} />);

    const chips = [...container.querySelectorAll(".ds-chip")];
    expect(chips).toHaveLength(2);
    for (const chip of chips) {
      expect(chip.className).toContain("ds-chip--undeclared");
      expect(chip.getAttribute("data-format")).toBe("unknown");
    }
  });

  it("still draws an explicit dependency that no dataset accounts for", () => {
    const ordered: DagCanvasItem[] = [
      { id: "first", name: "first", dependsOn: [], inputs: [], outputs: [] },
      { id: "second", name: "second", dependsOn: ["first"], inputs: [], outputs: [] },
    ];
    const { container } = render(<DagCanvas items={ordered} />);

    expect(container.querySelectorAll(".react-flow__edge-path")).toHaveLength(1);
    // No data flows across it, so there is nothing to put on it.
    expect(container.querySelector(".ds-chip")).toBeNull();
  });

  it("reports a node selection as a node", () => {
    const onSelect = vi.fn();
    render(<DagCanvas items={items} datasets={datasets} onSelect={onSelect} />);

    screen.getByLabelText(/Node clean_events/).click();
    expect(onSelect).toHaveBeenCalledWith({ kind: "node", id: "clean_events" });
  });

  it("leaves the chips inert while zoomed out to the `shape` tier", () => {
    // jsdom reports a pane small enough that `fitView` lands on `shape`, where
    // a chip is a bare dot: nothing to read, so nothing to press. That is the
    // designed behaviour, and it is what makes this a useful assertion rather
    // than an environment quirk to work around. The interactive path is
    // covered by DatasetChip.test.tsx, which drives each tier directly.
    const onSelect = vi.fn();
    const { container } = render(
      <DagCanvas items={items} datasets={datasets} onSelect={onSelect} />
    );

    const chip = container.querySelector<HTMLElement>(".ds-chip")!;
    expect(chip.className).toContain("ds-chip--shape");
    expect(chip.getAttribute("aria-hidden")).toBe("true");
    chip.click();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("marks the selected node and the selected dataset", () => {
    const { container: withNode } = render(
      <DagCanvas items={items} datasets={datasets} selection={{ kind: "node", id: "clean_events" }} />
    );
    expect(withNode.querySelector(".node-card.selected")).not.toBeNull();

    const { container: withDataset } = render(
      <DagCanvas
        items={items}
        datasets={datasets}
        selection={{ kind: "dataset", id: "bronze.events" }}
      />
    );
    const selected = withDataset.querySelector(".ds-chip.selected");
    expect(selected).not.toBeNull();
    expect(selected!.getAttribute("title")).toBe("bronze.events");
  });

  it("hides the chips when asked, for the dataset-as-node view", () => {
    const { container } = render(
      <DagCanvas items={items} datasets={datasets} hideDatasetChips />
    );
    expect(container.querySelector(".ds-chip")).toBeNull();
    // The edges themselves are unaffected.
    expect(container.querySelectorAll(".react-flow__edge-path")).toHaveLength(2);
  });

  it("explains the problem instead of drawing a graph when there is a cycle", () => {
    const cyclic: DagCanvasItem[] = [
      { id: "a", dependsOn: ["b"] },
      { id: "b", dependsOn: ["a"] },
    ];
    const { container } = render(<DagCanvas items={cyclic} />);

    // `layoutDag` returns null for a cyclic graph: there is no layering to draw,
    // and inventing one would look authoritative while being meaningless.
    expect(screen.getByText(/dependency cycle/i)).toBeInTheDocument();
    expect(container.querySelector(".react-flow")).toBeNull();
  });
});
