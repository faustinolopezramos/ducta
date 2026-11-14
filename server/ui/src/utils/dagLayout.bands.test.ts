import { describe, expect, it } from "vitest";
import { layoutDag, type LayoutInputEdge, type LayoutInputNode } from "./dagLayout";

const node = (id: string, width = 200, height = 78): LayoutInputNode => ({ id, width, height });
const edge = (from: string, to: string): LayoutInputEdge => ({ from, to });

describe("layoutDag direction", () => {
  // Uneven card sizes, a fan-out, a fan-in and a layer-skipping edge.
  const nodes = [node("a"), node("b", 160, 120), node("c"), node("d", 240, 60)];
  const edges = [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "d"), edge("a", "d")];

  it("lays left-to-right as the exact transpose of top-to-bottom", () => {
    const swapped = nodes.map((n) => ({ ...n, width: n.height, height: n.width }));
    const tb = layoutDag(swapped, edges)!;
    const lr = layoutDag(nodes, edges, { direction: "LR" })!;

    for (const n of nodes) {
      const t = tb.nodes.get(n.id)!;
      const l = lr.nodes.get(n.id)!;
      expect([l.x, l.y]).toEqual([t.y, t.x]);
      expect([l.width, l.height]).toEqual([n.width, n.height]);
      expect(l.layer).toBe(t.layer);
    }
    expect([lr.width, lr.height]).toEqual([tb.height, tb.width]);
    expect(lr.crossings).toBe(tb.crossings);
    for (const e of lr.edges) {
      const twin = tb.edges.find((x) => x.id === e.id)!;
      expect(e.points).toEqual(twin.points.map((p) => ({ x: p.y, y: p.x })));
    }
  });

  it("leaves a card on its right side and enters the next on its left", () => {
    const lr = layoutDag(nodes, edges, { direction: "LR" })!;
    for (const e of lr.edges) {
      const from = lr.nodes.get(e.from)!;
      const to = lr.nodes.get(e.to)!;
      expect(e.points[0].x).toBeCloseTo(from.x + from.width, 5);
      expect(e.points[e.points.length - 1].x).toBeCloseTo(to.x, 5);
    }
  });

  it("advances each layer along x", () => {
    const lr = layoutDag(nodes, edges, { direction: "LR" })!;
    const a = lr.nodes.get("a")!;
    const b = lr.nodes.get("b")!;
    const d = lr.nodes.get("d")!;
    expect(b.x).toBeGreaterThanOrEqual(a.x + a.width);
    expect(d.x).toBeGreaterThanOrEqual(b.x + b.width);
  });
});

describe("layoutDag bands", () => {
  // Two ingestion nodes, a cleaning band where `lookup` has no dependencies of
  // its own (so on dependencies alone it would sit beside the ingestion), and a
  // model band fed straight from `raw` as well as from cleaning.
  const nodes = ["ingest_a", "ingest_b", "raw", "clean_a", "clean_b", "lookup", "model"].map((id) =>
    node(id)
  );
  const edges = [
    edge("ingest_a", "clean_a"),
    edge("ingest_b", "clean_b"),
    edge("clean_a", "model"),
    edge("clean_b", "model"),
    edge("raw", "model"),
  ];
  const band: Record<string, number> = {
    ingest_a: 0,
    ingest_b: 0,
    raw: 0,
    clean_a: 1,
    clean_b: 1,
    lookup: 1,
    model: 2,
  };
  const bandOf = (id: string) => band[id];
  const layersOf = (layout: NonNullable<ReturnType<typeof layoutDag>>, b: number) =>
    Object.keys(band)
      .filter((id) => band[id] === b)
      .map((id) => layout.nodes.get(id)!.layer);

  it("puts every node of a band before every node of the next", () => {
    const layout = layoutDag(nodes, edges, { bandOf })!;
    expect(Math.max(...layersOf(layout, 0))).toBeLessThan(Math.min(...layersOf(layout, 1)));
    expect(Math.max(...layersOf(layout, 1))).toBeLessThan(Math.min(...layersOf(layout, 2)));
  });

  it("does not let tightening pull a node out of its band", () => {
    // Without the cap, `raw` would be pulled down next to cleaning, just above `model`.
    const layout = layoutDag(nodes, edges, { bandOf })!;
    expect(layout.nodes.get("raw")!.layer).toBeLessThan(Math.min(...layersOf(layout, 1)));
  });

  it("reports each band's extent along the flow, without overlaps", () => {
    const layout = layoutDag(nodes, edges, { bandOf })!;
    expect(layout.bands.map((b) => b.band)).toEqual([0, 1, 2]);
    for (let i = 0; i < layout.bands.length; i++) {
      const b = layout.bands[i];
      expect(b.end).toBeGreaterThan(b.start);
      if (i > 0) expect(b.start).toBeGreaterThanOrEqual(layout.bands[i - 1].end);
    }
    // In top-to-bottom the extent is vertical: it brackets the band's cards.
    const model = layout.nodes.get("model")!;
    expect(model.y).toBeGreaterThanOrEqual(layout.bands[2].start);
    expect(model.y + model.height).toBeLessThanOrEqual(layout.bands[2].end + 1e-6);
  });

  it("measures band extents along x when laid out left to right", () => {
    const layout = layoutDag(nodes, edges, { bandOf, direction: "LR" })!;
    const model = layout.nodes.get("model")!;
    expect(model.x).toBeGreaterThanOrEqual(layout.bands[2].start);
    expect(model.x + model.width).toBeLessThanOrEqual(layout.bands[2].end + 1e-6);
  });

  it("ignores bands that a dependency runs backwards across", () => {
    const layout = layoutDag(nodes, [...edges, edge("model", "lookup")], { bandOf })!;
    expect(layout.bands).toEqual([]);
    expect(layout.nodes.get("lookup")!.layer).toBeGreaterThan(layout.nodes.get("model")!.layer);
  });

  it("reports no bands when none are asked for", () => {
    expect(layoutDag(nodes, edges)!.bands).toEqual([]);
  });
});
