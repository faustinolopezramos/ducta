// ─────────────────────────────────────────────
// DAG LAYOUT — layered (Sugiyama-style) placement
//
// Turns a dependency graph into absolute coordinates plus a routed polyline
// per edge. Pure: no DOM, no React. The caller measures node sizes and feeds
// them in; everything here is deterministic in content coordinates, so zooming
// or panning never needs a re-layout.
//
// Pipeline of the algorithm:
//   1. layer       — longest-path layering (computeLevels) + tightening
//   2. dummies     — edges spanning >1 layer become chains of virtual cells,
//                    so long edges route *between* cards instead of over them
//   3. order       — median heuristic + transposition to cut edge crossings
//   4. x           — priority method; dummies outrank real nodes so long edges
//                    come out straight
//   5. y           — one band per layer, sized by its tallest node
//   6. route       — port anchor → dummy centers → port anchor
// ─────────────────────────────────────────────

import { computeLevels, type GraphNode } from "./dagValidation";

export interface LayoutInputNode {
  id: string;
  width: number;
  height: number;
  /** Declared input ports. Defaults to the number of incoming edges. */
  inPorts?: number;
  /** Declared output ports. Defaults to the number of outgoing edges. */
  outPorts?: number;
}

export interface LayoutInputEdge {
  from: string;
  to: string;
  /** Index into the source node's output ports. Falls back to fan order. */
  fromPort?: number;
  /** Index into the target node's input ports. Falls back to fan order. */
  toPort?: number;
  /**
   * Distinguishes parallel edges between the same pair of nodes.
   *
   * Edges are de-duplicated by this key, so two nodes wired by two different
   * datasets stay two lines instead of collapsing into one. Defaults to
   * `from->to`, which is the pair-dedupe the layout did before typed ports:
   * a node declaring the same dependency twice is still one line.
   */
  key?: string;
}

export interface LayoutPoint {
  x: number;
  y: number;
}

export interface PositionedNode {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  layer: number;
  /** Position within the layer, left to right. */
  order: number;
}

export interface RoutedEdge {
  id: string;
  from: string;
  to: string;
  /** Start (source port), one point per crossed layer, end (target port). */
  points: LayoutPoint[];
}

/**
 * Which way the layers run: `TB` stacks them top to bottom (edges leave a card's
 * bottom and enter the next card's top), `LR` lines them up left to right (edges
 * leave the right side and enter the left).
 */
export type LayoutDirection = "TB" | "LR";

export interface LayoutOptions {
  /** Space between one layer and the next, along the flow. */
  layerGap?: number;
  /** Minimum space between two cells in the same layer, across the flow. */
  nodeGap?: number;
  /** Space between the graph's bounding box and the canvas edge. */
  padding?: number;
  /** Defaults to `TB`. */
  direction?: LayoutDirection;
  /**
   * Groups nodes into ordered bands (e.g. the pipelines of a chain). Every node
   * of band `k` sits in a layer before every node of band `k + 1`, so a band
   * reads as one contiguous stretch of the canvas. Nodes without a band are
   * placed by their dependencies alone.
   */
  bandOf?: (id: string) => number | undefined;
}

/** Where a band landed, measured along the flow (y for `TB`, x for `LR`). */
export interface LayoutBand {
  band: number;
  firstLayer: number;
  lastLayer: number;
  /** Leading edge of the band's first layer. */
  start: number;
  /** Trailing edge of the band's last layer. */
  end: number;
}

export interface DagLayout {
  nodes: Map<string, PositionedNode>;
  edges: RoutedEdge[];
  width: number;
  height: number;
  /** Edge crossings left after ordering — surfaced for tests and telemetry. */
  crossings: number;
  /** One entry per band that has nodes, in band order. Empty without `bandOf`. */
  bands: LayoutBand[];
}

const DEFAULT_LAYER_GAP = 72;
const DEFAULT_NODE_GAP = 40;
const DEFAULT_PADDING = 40;

/** Median sweeps to run. Even iterations sweep down, odd ones sweep up. */
const ORDER_ITERATIONS = 8;
/** Passes of the x-coordinate priority method. */
const X_ITERATIONS = 8;

interface Cell {
  id: string;
  layer: number;
  order: number;
  x: number;
  y: number;
  width: number;
  height: number;
  dummy: boolean;
  /** Owning edge id, for dummies only. */
  edgeId: string;
  /** Neighbour cells one layer up. */
  up: Cell[];
  /** Neighbour cells one layer down. */
  down: Cell[];
}

interface Segment {
  u: Cell; // in layer l
  v: Cell; // in layer l + 1
}

const edgeId = (from: string, to: string) => `${from}->${to}`;
/** An edge's identity: its own `key` when it has one, else its node pair. */
const edgeKey = (e: LayoutInputEdge) => e.key ?? edgeId(e.from, e.to);
const centerX = (c: Cell) => c.x + c.width / 2;

/**
 * Port anchor on a node's edge: ports are spread evenly across the card so
 * port `i` of `n` sits at `width * (i + 1) / (n + 1)`. NodeCard positions its
 * port dots with the identical formula, so the line lands exactly on the dot.
 */
export function portOffset(width: number, index: number, count: number): number {
  if (count <= 0) return width / 2;
  const i = Math.min(Math.max(index, 0), count - 1);
  return (width * (i + 1)) / (count + 1);
}

/**
 * Lay out a dependency graph.
 *
 * Returns `null` when the graph has a cycle — layering is undefined there, and
 * the caller should fall back to an unordered render (as `computeLevels` does).
 */
export function layoutDag(
  nodes: LayoutInputNode[],
  edges: LayoutInputEdge[],
  options: LayoutOptions = {}
): DagLayout | null {
  if ((options.direction ?? "TB") === "TB") return layoutTopDown(nodes, edges, options);

  // Left to right is top to bottom transposed. Laying out in the rotated frame
  // (each card's height becomes the across-flow width) keeps one algorithm, and
  // every guarantee it gives — reserved channels, port anchors, crossings — holds
  // unchanged once x and y are swapped back.
  const rotated = layoutTopDown(
    nodes.map((n) => ({ ...n, width: n.height, height: n.width })),
    edges,
    options
  );
  if (!rotated) return null;

  const positioned = new Map<string, PositionedNode>();
  for (const [id, n] of rotated.nodes) {
    positioned.set(id, { ...n, x: n.y, y: n.x, width: n.height, height: n.width });
  }
  return {
    nodes: positioned,
    edges: rotated.edges.map((e) => ({ ...e, points: e.points.map((p) => ({ x: p.y, y: p.x })) })),
    width: rotated.height,
    height: rotated.width,
    crossings: rotated.crossings,
    bands: rotated.bands,
  };
}

function layoutTopDown(
  nodes: LayoutInputNode[],
  edges: LayoutInputEdge[],
  options: LayoutOptions
): DagLayout | null {
  const layerGap = options.layerGap ?? DEFAULT_LAYER_GAP;
  const nodeGap = options.nodeGap ?? DEFAULT_NODE_GAP;
  const padding = options.padding ?? DEFAULT_PADDING;

  const byId = new Map(nodes.map((n) => [n.id, n]));

  // Keep only edges whose endpoints both exist, drop self-loops, and dedupe by
  // edge key (a node declaring the same dependency twice is one line, not two —
  // but two datasets flowing between the same pair are two lines).
  const seenPair = new Set<string>();
  const realEdges: LayoutInputEdge[] = [];
  for (const e of edges) {
    if (e.from === e.to || !byId.has(e.from) || !byId.has(e.to)) continue;
    const key = edgeKey(e);
    if (seenPair.has(key)) continue;
    seenPair.add(key);
    realEdges.push(e);
  }

  if (nodes.length === 0) {
    return {
      nodes: new Map(),
      edges: [],
      width: padding * 2,
      height: padding * 2,
      crossings: 0,
      bands: [],
    };
  }

  // ── 1. Layering ──────────────────────────────────────────────────────────
  const parents = new Map<string, string[]>(nodes.map((n) => [n.id, []]));
  const children = new Map<string, string[]>(nodes.map((n) => [n.id, []]));
  for (const e of realEdges) {
    parents.get(e.to)!.push(e.from);
    children.get(e.from)!.push(e.to);
  }

  const graphNodes: GraphNode[] = nodes.map((n) => ({ id: n.id, dependencies: parents.get(n.id) }));
  const levels = computeLevels(graphNodes);
  if (!levels) return null;

  const layerOf = new Map<string, number>(levels);

  // Bands: every node of band k lands in a layer before every node of band k+1.
  // A dependency running from a later band back into an earlier one makes that
  // impossible, so the bands are ignored rather than bent into a wrong drawing.
  const bandOf = options.bandOf;
  const bandIds = bandOf
    ? [...new Set(nodes.map((n) => bandOf(n.id)).filter((b): b is number => b !== undefined))].sort(
        (a, b) => a - b
      )
    : [];
  const bandsActive =
    bandOf !== undefined &&
    bandIds.length > 0 &&
    realEdges.every((e) => {
      const from = bandOf(e.from);
      const to = bandOf(e.to);
      return from === undefined || to === undefined || from <= to;
    });

  /** Deepest layer used by band `b` or any band before it — the band's tightening cap. */
  const bandCap = new Map<number, number>();
  if (bandsActive) {
    // Levels are a topological order, so one pass in that order settles every
    // parent before its child; floors only ever push nodes further along, so
    // repeating until nothing moves converges (at most once per band).
    const topo = [...nodes].sort((a, b) => layerOf.get(a.id)! - layerOf.get(b.id)!);
    for (let pass = 0; pass <= bandIds.length; pass++) {
      const floor = new Map<number, number>();
      let deepest = -1;
      for (const b of bandIds) {
        floor.set(b, deepest + 1);
        for (const n of nodes) {
          if (bandOf(n.id) === b) deepest = Math.max(deepest, layerOf.get(n.id)!);
        }
      }
      let moved = false;
      for (const n of topo) {
        let want = 0;
        for (const p of parents.get(n.id)!) want = Math.max(want, layerOf.get(p)! + 1);
        const b = bandOf(n.id);
        if (b !== undefined) want = Math.max(want, floor.get(b)!);
        if (want > layerOf.get(n.id)!) {
          layerOf.set(n.id, want);
          moved = true;
        }
      }
      if (!moved) break;
    }
    let deepest = -1;
    for (const b of bandIds) {
      for (const n of nodes) {
        if (bandOf(n.id) === b) deepest = Math.max(deepest, layerOf.get(n.id)!);
      }
      bandCap.set(b, deepest);
    }
  }

  // Tightening: a node whose consumers all sit far below is pulled down to just
  // above its earliest consumer. Fewer long edges means fewer dummies and a
  // more compact graph. Walking layers top-down (children first) keeps the
  // invariant layer(child) > layer(parent) — nodes only ever move *down*.
  // A banded node is never pulled past the end of its own band.
  const byDescendingLayer = [...nodes].sort((a, b) => layerOf.get(b.id)! - layerOf.get(a.id)!);
  for (const n of byDescendingLayer) {
    const kids = children.get(n.id)!;
    if (kids.length === 0) continue;
    let target = Math.min(...kids.map((c) => layerOf.get(c)!)) - 1;
    const band = bandsActive ? bandOf!(n.id) : undefined;
    if (band !== undefined) target = Math.min(target, bandCap.get(band)!);
    if (target > layerOf.get(n.id)!) layerOf.set(n.id, target);
  }

  // Tightening can empty a layer; compact so layer indices stay consecutive.
  const usedLayers = [...new Set(layerOf.values())].sort((a, b) => a - b);
  const compacted = new Map(usedLayers.map((l, i) => [l, i]));
  for (const [id, l] of layerOf) layerOf.set(id, compacted.get(l)!);
  const layerCount = usedLayers.length;

  // ── 2. Cells + dummy chains ──────────────────────────────────────────────
  const cells = new Map<string, Cell>();
  const layers: Cell[][] = Array.from({ length: layerCount }, () => []);

  for (const n of nodes) {
    const cell: Cell = {
      id: n.id,
      layer: layerOf.get(n.id)!,
      order: 0,
      x: 0,
      y: 0,
      width: n.width,
      height: n.height,
      dummy: false,
      edgeId: "",
      up: [],
      down: [],
    };
    cells.set(n.id, cell);
  }

  const segments: Segment[] = [];
  /** Edge id → its dummy cells, ordered top to bottom. */
  const chainOf = new Map<string, Cell[]>();

  const link = (u: Cell, v: Cell) => {
    u.down.push(v);
    v.up.push(u);
    segments.push({ u, v });
  };

  for (const e of realEdges) {
    const id = edgeKey(e);
    const source = cells.get(e.from)!;
    const target = cells.get(e.to)!;
    const span = target.layer - source.layer;

    if (span <= 1) {
      link(source, target);
      chainOf.set(id, []);
      continue;
    }

    const chain: Cell[] = [];
    let prev = source;
    for (let l = source.layer + 1; l < target.layer; l++) {
      const dummy: Cell = {
        id: `§${id}@${l}`,
        layer: l,
        order: 0,
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        dummy: true,
        edgeId: id,
        up: [],
        down: [],
      };
      cells.set(dummy.id, dummy);
      chain.push(dummy);
      link(prev, dummy);
      prev = dummy;
    }
    link(prev, target);
    chainOf.set(id, chain);
  }

  // ── 3. Initial order: DFS from the sources, over the expanded graph ──────
  const visited = new Set<string>();
  const visit = (cell: Cell) => {
    if (visited.has(cell.id)) return;
    visited.add(cell.id);
    layers[cell.layer].push(cell);
    for (const next of cell.down) visit(next);
  };
  for (const n of nodes) {
    const cell = cells.get(n.id)!;
    if (cell.up.length === 0) visit(cell);
  }
  for (const cell of cells.values()) visit(cell); // disconnected leftovers

  const reindex = () => {
    for (const layer of layers) layer.forEach((c, i) => (c.order = i));
  };
  reindex();

  // ── 4. Crossing minimisation ─────────────────────────────────────────────
  const segsByLayer: Segment[][] = Array.from({ length: Math.max(layerCount - 1, 0) }, () => []);
  for (const seg of segments) segsByLayer[seg.u.layer]?.push(seg);

  const bilayerCrossings = (segs: Segment[]): number => {
    let count = 0;
    for (let i = 0; i < segs.length; i++) {
      for (let j = i + 1; j < segs.length; j++) {
        const du = segs[i].u.order - segs[j].u.order;
        const dv = segs[i].v.order - segs[j].v.order;
        if (du * dv < 0) count++;
      }
    }
    return count;
  };
  const totalCrossings = () => segsByLayer.reduce((sum, segs) => sum + bilayerCrossings(segs), 0);

  /**
   * Weighted median of a cell's neighbour positions (Gansner et al.). Returns
   * -1 for a cell with no neighbours in the reference layer — those stay put
   * while the others sort around them.
   */
  const medianValue = (cell: Cell, dir: "up" | "down"): number => {
    const positions = (dir === "up" ? cell.up : cell.down).map((n) => n.order).sort((a, b) => a - b);
    const len = positions.length;
    if (len === 0) return -1;
    const mid = Math.floor(len / 2);
    if (len % 2 === 1) return positions[mid];
    if (len === 2) return (positions[0] + positions[1]) / 2;
    const left = positions[mid - 1] - positions[0];
    const right = positions[len - 1] - positions[mid];
    if (left + right === 0) return (positions[mid - 1] + positions[mid]) / 2;
    return (positions[mid - 1] * right + positions[mid] * left) / (left + right);
  };

  const medianSweep = (dir: "up" | "down") => {
    // "up" reorders each layer against the one above it, sweeping top-down;
    // "down" reorders against the layer below, sweeping bottom-up.
    const indices = [...layers.keys()];
    const targets = dir === "up" ? indices.slice(1) : indices.slice(0, -1).reverse();
    for (const l of targets) {
      const layer = layers[l];
      const medians = layer.map((c) => medianValue(c, dir));
      // Cells with no reference neighbour hold their slot; the rest are sorted
      // by median and dealt back into the slots that are left.
      const movable = layer.map((_, i) => i).filter((i) => medians[i] >= 0);
      const sorted = [...movable].sort((a, b) => medians[a] - medians[b] || a - b);
      const next = layer.slice();
      movable.forEach((slot, k) => (next[slot] = layer[sorted[k]]));
      layers[l] = next;
    }
    reindex();
  };

  /** Swap adjacent pairs while it reduces crossings in the touching bilayers. */
  const transpose = () => {
    for (let guard = 0; guard < 8; guard++) {
      let improved = false;
      for (let l = 0; l < layers.length; l++) {
        const layer = layers[l];
        const adjacent = () =>
          (l > 0 ? bilayerCrossings(segsByLayer[l - 1]) : 0) +
          (l < segsByLayer.length ? bilayerCrossings(segsByLayer[l]) : 0);
        for (let i = 0; i + 1 < layer.length; i++) {
          const a = layer[i];
          const b = layer[i + 1];
          const before = adjacent();
          layer[i] = b;
          layer[i + 1] = a;
          a.order = i + 1;
          b.order = i;
          if (adjacent() < before) {
            improved = true;
          } else {
            layer[i] = a;
            layer[i + 1] = b;
            a.order = i;
            b.order = i + 1;
          }
        }
      }
      if (!improved) break;
    }
  };

  const snapshot = () => layers.map((layer) => layer.map((c) => c.id));
  const restore = (snap: string[][]) => {
    snap.forEach((ids, l) => (layers[l] = ids.map((id) => cells.get(id)!)));
    reindex();
  };

  let bestOrder = snapshot();
  let bestCrossings = totalCrossings();
  for (let i = 0; i < ORDER_ITERATIONS && bestCrossings > 0; i++) {
    medianSweep(i % 2 === 0 ? "up" : "down");
    transpose();
    // The median heuristic is not monotonic — keep the best ordering seen, not
    // whatever the last sweep happened to produce.
    const crossings = totalCrossings();
    if (crossings < bestCrossings) {
      bestCrossings = crossings;
      bestOrder = snapshot();
    }
  }
  restore(bestOrder);

  // ── 5. X coordinates (priority method) ───────────────────────────────────
  // Dummies outrank every real node: keeping their chain vertical is what makes
  // a long edge come out as a straight line instead of a staircase.
  const priorityOf = (c: Cell) => (c.dummy ? 1e6 : c.up.length + c.down.length);

  for (const layer of layers) {
    let cursor = 0;
    for (const c of layer) {
      c.x = cursor;
      cursor += c.width + nodeGap;
    }
  }

  /** Shift cell `i` and the unplaced run beside it, stopping at placed cells. */
  const shift = (layer: Cell[], i: number, delta: number, placed: Set<number>) => {
    if (delta === 0) return;
    if (delta > 0) {
      let stop = layer.length;
      for (let j = i + 1; j < layer.length; j++) {
        if (placed.has(j)) {
          stop = j;
          break;
        }
      }
      // The whole run i..stop-1 moves rigidly, so only the gap before the first
      // placed cell on the right constrains it.
      const slack =
        stop === layer.length
          ? Infinity
          : layer[stop].x - nodeGap - (layer[stop - 1].x + layer[stop - 1].width);
      const move = Math.min(delta, Math.max(slack, 0));
      for (let j = i; j < stop; j++) layer[j].x += move;
    } else {
      let stop = -1;
      for (let j = i - 1; j >= 0; j--) {
        if (placed.has(j)) {
          stop = j;
          break;
        }
      }
      const slack = stop === -1 ? Infinity : layer[stop + 1].x - (layer[stop].x + layer[stop].width) - nodeGap;
      const move = Math.min(-delta, Math.max(slack, 0));
      for (let j = stop + 1; j <= i; j++) layer[j].x -= move;
    }
  };

  const placeLayer = (layer: Cell[], dir: "up" | "down") => {
    const byPriority = layer.map((_, i) => i).sort((a, b) => priorityOf(layer[b]) - priorityOf(layer[a]));
    const placed = new Set<number>();
    for (const i of byPriority) {
      const cell = layer[i];
      const neighbours = dir === "up" ? cell.up : cell.down;
      if (neighbours.length > 0) {
        const xs = neighbours.map(centerX).sort((a, b) => a - b);
        const mid = Math.floor(xs.length / 2);
        const target = xs.length % 2 === 1 ? xs[mid] : (xs[mid - 1] + xs[mid]) / 2;
        shift(layer, i, target - centerX(cell), placed);
      }
      placed.add(i);
    }
  };

  for (let pass = 0; pass < X_ITERATIONS; pass++) {
    if (pass % 2 === 0) {
      for (let l = 1; l < layers.length; l++) placeLayer(layers[l], "up");
    } else {
      for (let l = layers.length - 2; l >= 0; l--) placeLayer(layers[l], "down");
    }
  }

  // ── 6. Y coordinates ─────────────────────────────────────────────────────
  let top = padding;
  const bandTop: number[] = [];
  const bandBottom: number[] = [];
  for (const layer of layers) {
    const bandHeight = layer.reduce((max, c) => Math.max(max, c.height), 0);
    for (const c of layer) c.y = top + (bandHeight - c.height) / 2;
    bandTop.push(top);
    bandBottom.push(top + bandHeight);
    top += bandHeight + layerGap;
  }

  // Where each band landed along the flow, from the layers its nodes occupy.
  const bands: LayoutBand[] = [];
  if (bandsActive) {
    const span = new Map<number, { first: number; last: number }>();
    for (const n of nodes) {
      const b = bandOf!(n.id);
      if (b === undefined) continue;
      const l = cells.get(n.id)!.layer;
      const s = span.get(b);
      if (s) {
        s.first = Math.min(s.first, l);
        s.last = Math.max(s.last, l);
      } else {
        span.set(b, { first: l, last: l });
      }
    }
    for (const b of [...span.keys()].sort((p, q) => p - q)) {
      const { first, last } = span.get(b)!;
      bands.push({
        band: b,
        firstLayer: first,
        lastLayer: last,
        start: bandTop[first],
        end: bandBottom[last],
      });
    }
  }

  // Normalise so the graph starts at `padding` on both axes.
  let minX = Infinity;
  for (const c of cells.values()) minX = Math.min(minX, c.x);
  const dx = padding - (Number.isFinite(minX) ? minX : 0);
  for (const c of cells.values()) c.x += dx;

  // ── 7. Edge routing ──────────────────────────────────────────────────────
  // Fan order is the fallback when a node doesn't declare which port an edge
  // belongs to: spread the edges across the card in the order their far ends
  // appear left to right, so parallel edges stop stacking on the centre line.
  const outFan = new Map<string, string[]>();
  const inFan = new Map<string, string[]>();
  /** Edge key → its endpoints, so the fan anchor never has to parse the key. */
  const endsOf = new Map<string, { from: string; to: string }>();
  for (const e of realEdges) {
    const id = edgeKey(e);
    endsOf.set(id, { from: e.from, to: e.to });
    if (!outFan.has(e.from)) outFan.set(e.from, []);
    outFan.get(e.from)!.push(id);
    if (!inFan.has(e.to)) inFan.set(e.to, []);
    inFan.get(e.to)!.push(id);
  }
  /** First waypoint of an edge on the given side — what its fan sorts by. */
  const fanAnchor = (id: string, side: "out" | "in"): number => {
    const chain = chainOf.get(id)!;
    if (chain.length > 0) return centerX(side === "out" ? chain[0] : chain[chain.length - 1]);
    const ends = endsOf.get(id)!;
    return centerX(cells.get(side === "out" ? ends.to : ends.from)!);
  };
  for (const [, ids] of outFan) ids.sort((a, b) => fanAnchor(a, "out") - fanAnchor(b, "out"));
  for (const [, ids] of inFan) ids.sort((a, b) => fanAnchor(a, "in") - fanAnchor(b, "in"));

  const routed: RoutedEdge[] = realEdges.map((e) => {
    const id = edgeKey(e);
    const source = cells.get(e.from)!;
    const target = cells.get(e.to)!;
    const sourceNode = byId.get(e.from)!;
    const targetNode = byId.get(e.to)!;

    const outs = outFan.get(e.from)!;
    const ins = inFan.get(e.to)!;
    const fromCount = sourceNode.outPorts ?? outs.length;
    const toCount = targetNode.inPorts ?? ins.length;
    const fromIdx = e.fromPort ?? outs.indexOf(id);
    const toIdx = e.toPort ?? ins.indexOf(id);

    const points: LayoutPoint[] = [
      { x: source.x + portOffset(source.width, fromIdx, fromCount), y: source.y + source.height },
    ];
    // A dummy contributes two waypoints — the top and the bottom of its layer's
    // band — so the edge runs dead vertical for the full height of every layer
    // it passes, and only ever slants in the empty gap between two layers. A
    // single mid-band point would let the approaching diagonal clip the corner
    // of a card sitting beside the channel.
    for (const dummy of chainOf.get(id)!) {
      points.push({ x: dummy.x, y: bandTop[dummy.layer] });
      points.push({ x: dummy.x, y: bandBottom[dummy.layer] });
    }
    points.push({ x: target.x + portOffset(target.width, toIdx, toCount), y: target.y });

    return { id, from: e.from, to: e.to, points };
  });

  // ── Result ───────────────────────────────────────────────────────────────
  const positioned = new Map<string, PositionedNode>();
  let maxX = 0;
  for (const n of nodes) {
    const c = cells.get(n.id)!;
    positioned.set(n.id, {
      id: n.id,
      x: c.x,
      y: c.y,
      width: c.width,
      height: c.height,
      layer: c.layer,
      order: c.order,
    });
    maxX = Math.max(maxX, c.x + c.width);
  }
  for (const c of cells.values()) maxX = Math.max(maxX, c.x + c.width);

  return {
    nodes: positioned,
    edges: routed,
    width: maxX + padding,
    height: Math.max(top - layerGap + padding, padding * 2),
    crossings: bestCrossings,
    bands,
  };
}
