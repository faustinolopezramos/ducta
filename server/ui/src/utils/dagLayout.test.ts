import { describe, expect, it } from "vitest";
import { layoutDag, portOffset, type LayoutInputEdge, type LayoutInputNode } from "./dagLayout";

const W = 200;
const H = 78;
const node = (id: string, extra: Partial<LayoutInputNode> = {}): LayoutInputNode => ({
  id,
  width: W,
  height: H,
  ...extra,
});
const edge = (from: string, to: string, extra: Partial<LayoutInputEdge> = {}): LayoutInputEdge => ({
  from,
  to,
  ...extra,
});

describe("portOffset", () => {
  it("centers a lone port", () => {
    expect(portOffset(200, 0, 1)).toBe(100);
  });

  it("spreads ports evenly across the card", () => {
    expect(portOffset(200, 0, 3)).toBe(50);
    expect(portOffset(200, 1, 3)).toBe(100);
    expect(portOffset(200, 2, 3)).toBe(150);
  });

  it("centers when there are no ports and clamps an out-of-range index", () => {
    expect(portOffset(200, 0, 0)).toBe(100);
    expect(portOffset(200, 9, 2)).toBe(portOffset(200, 1, 2));
  });
});

describe("layoutDag", () => {
  it("returns null for a cyclic graph", () => {
    const layout = layoutDag(
      [node("a"), node("b")],
      [edge("a", "b"), edge("b", "a")]
    );
    expect(layout).toBeNull();
  });

  it("survives an empty graph and a lone node", () => {
    expect(layoutDag([], [])!.nodes.size).toBe(0);

    const single = layoutDag([node("solo")], [])!;
    expect(single.nodes.get("solo")).toMatchObject({ layer: 0, order: 0 });
    expect(single.width).toBeGreaterThan(W);
    expect(single.height).toBeGreaterThan(H);
  });

  it("straightens a linear chain onto one column", () => {
    const layout = layoutDag(
      [node("a"), node("b"), node("c"), node("d")],
      [edge("a", "b"), edge("b", "c"), edge("c", "d")]
    )!;

    const xs = ["a", "b", "c", "d"].map((id) => layout.nodes.get(id)!.x);
    expect(new Set(xs).size).toBe(1);

    const ys = ["a", "b", "c", "d"].map((id) => layout.nodes.get(id)!.y);
    expect(ys).toEqual([...ys].sort((p, q) => p - q));
    expect(layout.crossings).toBe(0);
  });

  it("lays out the reference pipeline without crossings", () => {
    // raw_events → clean_events ┐
    //                           ├→ join_users → churn_model → warehouse
    // users_csv ────────────────┘
    const layout = layoutDag(
      [
        node("raw_events"),
        node("users_csv"),
        node("clean_events"),
        node("join_users"),
        node("churn_model"),
        node("warehouse"),
      ],
      [
        edge("raw_events", "clean_events"),
        edge("clean_events", "join_users"),
        edge("users_csv", "join_users"),
        edge("join_users", "churn_model"),
        edge("churn_model", "warehouse"),
      ]
    )!;

    expect(layout.crossings).toBe(0);

    // Tightening pulls users_csv down next to clean_events instead of leaving
    // it stranded at layer 0 with a two-layer edge.
    expect(layout.nodes.get("users_csv")!.layer).toBe(layout.nodes.get("clean_events")!.layer);
    for (const e of layout.edges) expect(e.points).toHaveLength(2);
  });

  it("reorders siblings to remove avoidable crossings", () => {
    // A depth-first pass lands the lower layer as [c, d] — and then a→d has to
    // cross b→c. Swapping to [d, c] costs nothing and removes the crossing, so
    // this only passes if the median/transpose stage actually runs.
    const layout = layoutDag(
      [node("a"), node("b"), node("c"), node("d")],
      [edge("a", "c"), edge("a", "d"), edge("b", "c")]
    )!;

    expect(layout.crossings).toBe(0);
    expect(layout.nodes.get("d")!.order).toBeLessThan(layout.nodes.get("c")!.order);
  });

  it("routes a layer-skipping edge around the nodes it would cross", () => {
    // "skip" must stay at layer 0 because it also feeds "mid" — so skip→sink
    // spans two layers and needs a waypoint.
    const nodes = [node("skip"), node("mid"), node("sink")];
    const layout = layoutDag(nodes, [
      edge("skip", "mid"),
      edge("mid", "sink"),
      edge("skip", "sink"),
    ])!;

    expect(layout.nodes.get("skip")!.layer).toBe(0);
    expect(layout.nodes.get("mid")!.layer).toBe(1);
    expect(layout.nodes.get("sink")!.layer).toBe(2);

    const long = layout.edges.find((e) => e.from === "skip" && e.to === "sink")!;
    expect(long.points.length).toBeGreaterThanOrEqual(3);

    // No waypoint may fall inside an intermediate card.
    const mid = layout.nodes.get("mid")!;
    for (const p of long.points.slice(1, -1)) {
      const insideX = p.x > mid.x && p.x < mid.x + mid.width;
      const insideY = p.y > mid.y && p.y < mid.y + mid.height;
      expect(insideX && insideY).toBe(false);
    }
  });

  it("never routes an edge across a card it doesn't touch", () => {
    // The reference pipeline plus audit_log, which pins raw_events to layer 0
    // and forces a four-layer edge down the side of the graph.
    const layout = layoutDag(
      [
        node("raw_events"),
        node("users_csv"),
        node("clean_events"),
        node("join_users"),
        node("churn_model"),
        node("warehouse"),
        node("audit_log"),
      ],
      [
        edge("raw_events", "clean_events"),
        edge("clean_events", "join_users"),
        edge("users_csv", "join_users"),
        edge("join_users", "churn_model"),
        edge("churn_model", "warehouse"),
        edge("raw_events", "audit_log"),
        edge("churn_model", "audit_log"),
      ],
      { layerGap: 88, nodeGap: 40, padding: 56 }
    )!;

    const hits: string[] = [];
    for (const e of layout.edges) {
      for (let i = 0; i + 1 < e.points.length; i++) {
        const a = e.points[i];
        const b = e.points[i + 1];
        for (let t = 0; t <= 1; t += 0.02) {
          const x = a.x + (b.x - a.x) * t;
          const y = a.y + (b.y - a.y) * t;
          for (const [id, n] of layout.nodes) {
            if (id === e.from || id === e.to) continue;
            if (x > n.x && x < n.x + n.width && y > n.y && y < n.y + n.height) hits.push(`${e.id} over ${id}`);
          }
        }
      }
    }

    expect(hits).toEqual([]);
    expect(layout.crossings).toBe(0);
  });

  it("holds a routed edge dead vertical while it passes a layer", () => {
    const layout = layoutDag(
      [node("top"), node("mid"), node("bottom")],
      [edge("top", "mid"), edge("mid", "bottom"), edge("top", "bottom")]
    )!;

    const long = layout.edges.find((e) => e.from === "top" && e.to === "bottom")!;
    const mid = layout.nodes.get("mid")!;
    // The two waypoints for the layer it skips share an x and bracket the band,
    // so the slanted part is confined to the gaps above and below.
    const inBand = long.points.filter((p) => p.y >= mid.y && p.y <= mid.y + mid.height);
    expect(inBand).toHaveLength(2);
    expect(inBand[0].x).toBe(inBand[1].x);
    expect(inBand[0].y).toBeCloseTo(mid.y, 5);
    expect(inBand[1].y).toBeCloseTo(mid.y + mid.height, 5);
  });

  it("keeps siblings apart by at least the node gap", () => {
    const layout = layoutDag(
      [node("root"), node("a"), node("b"), node("c")],
      [edge("root", "a"), edge("root", "b"), edge("root", "c")],
      { nodeGap: 40 }
    )!;

    const row = ["a", "b", "c"]
      .map((id) => layout.nodes.get(id)!)
      .sort((p, q) => p.x - q.x);
    for (let i = 1; i < row.length; i++) {
      expect(row[i].x - (row[i - 1].x + row[i - 1].width)).toBeGreaterThanOrEqual(40 - 1e-6);
    }
  });

  it("anchors edges on the declared ports when the node exposes them", () => {
    const layout = layoutDag(
      [node("src", { outPorts: 2 }), node("dst", { inPorts: 3 })],
      [edge("src", "dst", { fromPort: 1, toPort: 2 })]
    )!;

    const src = layout.nodes.get("src")!;
    const dst = layout.nodes.get("dst")!;
    const [start, end] = layout.edges[0].points;

    expect(start.x).toBeCloseTo(src.x + portOffset(W, 1, 2), 5);
    expect(start.y).toBeCloseTo(src.y + src.height, 5);
    expect(end.x).toBeCloseTo(dst.x + portOffset(W, 2, 3), 5);
    expect(end.y).toBeCloseTo(dst.y, 5);
  });

  it("fans undeclared ports across the card instead of stacking them", () => {
    const layout = layoutDag(
      [node("root"), node("a"), node("b")],
      [edge("root", "a"), edge("root", "b")]
    )!;

    const starts = layout.edges.map((e) => e.points[0].x);
    expect(new Set(starts).size).toBe(2);
  });

  it("ignores self-loops, duplicate pairs and dangling endpoints", () => {
    const layout = layoutDag(
      [node("a"), node("b")],
      [edge("a", "a"), edge("a", "b"), edge("a", "b"), edge("a", "ghost")]
    )!;

    expect(layout.edges).toHaveLength(1);
    expect(layout.nodes.get("b")!.layer).toBe(1);
  });

  it("respects per-node heights when sizing layer bands", () => {
    const layout = layoutDag(
      [node("tall", { height: 200 }), node("short", { height: 40 }), node("below")],
      [edge("tall", "below"), edge("short", "below")]
    )!;

    const tall = layout.nodes.get("tall")!;
    const short = layout.nodes.get("short")!;
    const below = layout.nodes.get("below")!;

    // Same band, centred against each other; the next layer clears the tallest.
    expect(tall.y + tall.height / 2).toBeCloseTo(short.y + short.height / 2, 5);
    expect(below.y).toBeGreaterThanOrEqual(tall.y + tall.height);
  });
});
