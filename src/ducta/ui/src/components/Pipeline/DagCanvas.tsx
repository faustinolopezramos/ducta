import React, { useLayoutEffect, useMemo, useRef, useState, useCallback } from "react";
import { resolveDepId } from "../../utils/dagValidation";
import { layoutDag, type LayoutInputEdge, type LayoutPoint } from "../../utils/dagLayout";
import type { Lineage } from "../../utils/lineage";
import { useBuilderStore } from "../../store/builderStore";
import { IconAlertTriangle } from "@tabler/icons-react";
import { NodeCard } from "./NodeCard";
import { MiniMap } from "./MiniMap";

export interface DagCanvasItem {
  id: string;
  name?: string;
  type?: string;
  module?: string;
  fn?: string;
  inputs?: { id: string; name: string; format?: string }[];
  outputs?: { id: string; name: string; format?: string }[];
  /** ids (or names) of items this one depends on. */
  dependsOn: string[];
  [key: string]: any;
}

interface DagCanvasProps {
  items: DagCanvasItem[];
  renderItem?: (item: DagCanvasItem) => React.ReactNode;
  edgeLabel?: (from: string, to: string) => string | null;
  edgeClassName?: (from: string, to: string) => string;
  /** Applies only to the cycle fallback; the laid-out canvas sizes itself. */
  padding?: string;
  executionStates?: Record<string, string>;
  selectedNodeId?: string | null;
  lineage?: Lineage | null;
  onNodeSelect?: (id: string) => void;
}

const NODE_GAP_X = 40;
const NODE_GAP_Y = 88;
const NODE_WIDTH = 200;
/** Placeholder height for the first paint, before the cards are measured. */
const NODE_HEIGHT_ESTIMATE = 96;
/** Clears the HUD toolbar, which floats over the top of the canvas. */
const CANVAS_PADDING = 56;
/** Breathing room under the last layer so the logs bar never covers a card. */
const BOTTOM_ROOM = 72;
/** Below this zoom the port format chips are unreadable, so they're hidden. */
const CHIP_ZOOM_FLOOR = 0.7;

interface NodeSize {
  w: number;
  h: number;
}

/**
 * Which ports an edge connects. Ducta declares `dependencies` separately from
 * `inputs`/`outputs` (see utils/pipelineAdapter.ts), so the link is recovered by
 * matching dataset names: the target input fed by one of the source's outputs.
 * Returns an empty object when nothing matches — the layout then falls back to
 * fan order, which is what the canvas did before ports were typed.
 */
function resolvePorts(
  source: DagCanvasItem,
  target: DagCanvasItem
): { fromPort?: number; toPort?: number } {
  const outputs = source.outputs ?? [];
  const inputs = target.inputs ?? [];
  for (let toPort = 0; toPort < inputs.length; toPort++) {
    const fromPort = outputs.findIndex((o) => o.name === inputs[toPort].name);
    if (fromPort >= 0) return { fromPort, toPort };
  }
  return {};
}

/**
 * Smooth path through an edge's waypoints. A direct hop keeps the soft elbow
 * the canvas has always drawn; a routed edge (one that skips layers) becomes a
 * Catmull-Rom spline through its waypoints, with vertical tangents at both ends
 * so it still leaves and enters a card perpendicular to its edge.
 */
export function edgePath(points: LayoutPoint[]): string {
  if (points.length < 2) return "";

  if (points.length === 2) {
    const [a, b] = points;
    const pull = Math.min(Math.max(Math.abs(b.y - a.y) * 0.5, 24), 80);
    return `M ${a.x} ${a.y} C ${a.x} ${a.y + pull}, ${b.x} ${b.y - pull}, ${b.x} ${b.y}`;
  }

  const last = points.length - 1;
  const tangents = points.map((p, i) => {
    if (i === 0) return { x: 0, y: points[1].y - p.y };
    if (i === last) return { x: 0, y: p.y - points[last - 1].y };
    // A point that starts or ends a vertical run gets a vertical tangent, so
    // the run is drawn perfectly straight instead of bowing out of its channel
    // and back into a card. Curvature stays in the gaps between layers.
    const vertical = points[i - 1].x === p.x || points[i + 1].x === p.x;
    return {
      x: vertical ? 0 : (points[i + 1].x - points[i - 1].x) / 2,
      y: (points[i + 1].y - points[i - 1].y) / 2,
    };
  });

  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < last; i++) {
    const p1 = points[i];
    const p2 = points[i + 1];
    const c1x = p1.x + tangents[i].x / 3;
    const c1y = p1.y + tangents[i].y / 3;
    const c2x = p2.x - tangents[i + 1].x / 3;
    const c2y = p2.y - tangents[i + 1].y / 3;
    d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.x} ${p2.y}`;
  }
  return d;
}

/** Midpoint of a polyline, used to sit the edge label clear of the cards. */
function edgeMidpoint(points: LayoutPoint[]): LayoutPoint {
  const mid = (points.length - 1) / 2;
  if (Number.isInteger(mid)) return points[mid];
  const a = points[Math.floor(mid)];
  const b = points[Math.ceil(mid)];
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

export function DagCanvas({
  items,
  renderItem,
  edgeLabel,
  edgeClassName,
  padding = "80px 40px 120px",
  executionStates,
  selectedNodeId,
  lineage,
  onNodeSelect,
}: DagCanvasProps) {
  const viewportScale = useBuilderStore((s) => s.viewportScale);
  const viewportX = useBuilderStore((s) => s.viewportX);
  const viewportY = useBuilderStore((s) => s.viewportY);

  const dedupedItems = useMemo(() => {
    const seen = new Set<string>();
    return items.filter((it) => {
      if (seen.has(it.id)) return false;
      seen.add(it.id);
      return true;
    });
  }, [items]);

  const itemRefs = useRef(new Map<string, HTMLDivElement>());
  const [sizes, setSizes] = useState<Map<string, NodeSize>>(new Map());

  // Resolved dependency edges, with the port each end belongs to.
  const graphEdges = useMemo<LayoutInputEdge[]>(() => {
    const byId = new Map(dedupedItems.map((it) => [it.id, it]));
    const known = dedupedItems.map((it) => ({ id: it.id, name: it.name ?? it.id }));
    const edges: LayoutInputEdge[] = [];
    const seen = new Set<string>();
    for (const item of dedupedItems) {
      for (const dep of item.dependsOn) {
        const fromId = resolveDepId(dep, known);
        if (!fromId || fromId === item.id) continue;
        const key = `${fromId}->${item.id}`;
        if (seen.has(key)) continue;
        seen.add(key);
        edges.push({ from: fromId, to: item.id, ...resolvePorts(byId.get(fromId)!, item) });
      }
    }
    return edges;
  }, [dedupedItems]);

  const layout = useMemo(() => {
    // A node's port count is the larger of what it declares and how many edges
    // actually land on it, so an undeclared dependency still gets its own slot
    // instead of stacking on the card's centre line.
    const inCount = new Map<string, number>();
    const outCount = new Map<string, number>();
    for (const e of graphEdges) {
      inCount.set(e.to, (inCount.get(e.to) ?? 0) + 1);
      outCount.set(e.from, (outCount.get(e.from) ?? 0) + 1);
    }

    return layoutDag(
      dedupedItems.map((it) => ({
        id: it.id,
        width: sizes.get(it.id)?.w ?? NODE_WIDTH,
        height: sizes.get(it.id)?.h ?? NODE_HEIGHT_ESTIMATE,
        inPorts: Math.max(it.inputs?.length ?? 0, inCount.get(it.id) ?? 0) || undefined,
        outPorts: Math.max(it.outputs?.length ?? 0, outCount.get(it.id) ?? 0) || undefined,
      })),
      graphEdges,
      { layerGap: NODE_GAP_Y, nodeGap: NODE_GAP_X, padding: CANVAS_PADDING }
    );
  }, [dedupedItems, graphEdges, sizes]);

  // Measure the rendered cards and feed their real sizes back into the layout.
  // `offsetWidth`/`offsetHeight` ignore the canvas' zoom transform and are whole
  // pixels, so this settles after one pass instead of oscillating.
  useLayoutEffect(() => {
    const next = new Map<string, NodeSize>();
    for (const item of dedupedItems) {
      const el = itemRefs.current.get(item.id);
      if (!el) continue;
      const size = { w: el.offsetWidth, h: el.offsetHeight };
      next.set(item.id, size);
    }
    // Comparing `next` against `sizes` (never against the item count) keeps this
    // from looping forever if an item somehow never renders a ref.
    const changed =
      next.size !== sizes.size ||
      [...next].some(([id, s]) => {
        const prev = sizes.get(id);
        return !prev || prev.w !== s.w || prev.h !== s.h;
      });
    if (changed) setSizes(next);
  });

  const contentSize = layout
    ? { width: layout.width, height: layout.height + BOTTOM_ROOM }
    : { width: undefined, height: undefined };

  const miniMapNodes = useMemo(
    () =>
      layout
        ? dedupedItems.flatMap((item) => {
            const pos = layout.nodes.get(item.id);
            return pos ? [{ id: item.id, x: pos.x + pos.width / 2, y: pos.y, type: item.type }] : [];
          })
        : [],
    [layout, dedupedItems]
  );

  const defaultRender = useCallback(
    (node: DagCanvasItem) => {
      const execState = executionStates?.[node.id];
      const lensDir = lineage
        ? lineage.upstream.has(node.id) ? "up" as const
        : lineage.downstream.has(node.id) ? "down" as const
        : null
        : null;
      const lensDepth = lensDir === "up"
        ? lineage!.upstream.get(node.id)
        : lensDir === "down"
        ? lineage!.downstream.get(node.id)
        : undefined;
      const dimmed = lineage ? node.id !== lineage.selectedId && !lensDir : false;
      return (
        <NodeCard
          node={node}
          selected={selectedNodeId === node.id}
          dimmed={dimmed}
          lensDir={lensDir}
          lensDepth={lensDepth}
          execState={execState}
          onClick={() => onNodeSelect?.(node.id)}
        />
      );
    },
    [executionStates, lineage, selectedNodeId, onNodeSelect]
  );

  const usedRender = renderItem || defaultRender;

  const renderNode = (item: DagCanvasItem, style?: React.CSSProperties) => (
    <div
      key={item.id}
      className="node-wrapper"
      data-node-id={item.id}
      style={style}
      ref={(el) => {
        if (el) itemRefs.current.set(item.id, el);
        else itemRefs.current.delete(item.id);
      }}
    >
      {usedRender(item)}
    </div>
  );

  return (
    <>
      {!layout && (
        <div
          style={{
            margin: "16px 24px 0",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 14px",
            borderRadius: "var(--radius)",
            border: "1px solid var(--red)",
            background: "var(--red-light, rgba(220,38,38,0.08))",
            color: "var(--red)",
            fontSize: 13,
            position: "relative",
            zIndex: 20,
          }}
        >
          <IconAlertTriangle size={16} />
          Cycle detected in dependencies — showing items without a dependency layout.
        </div>
      )}

      <div
        className={`dag-content${viewportScale < CHIP_ZOOM_FLOOR ? " dag-zoomed-out" : ""}`}
        style={{
          position: "relative",
          padding: layout ? 0 : padding,
          width: contentSize.width,
          height: contentSize.height,
          // Centres a graph narrower than the viewport; collapses to 0 once the
          // graph outgrows it, so wide pipelines still start at the left edge.
          margin: layout ? "0 auto" : undefined,
          minHeight: "100%",
          transformOrigin: "0 0",
          transform: `translate(${viewportX}px, ${viewportY}px) scale(${viewportScale})`,
        }}
      >
        <svg className="dag-edges-overlay" role="img" aria-label="Pipeline dependency connections">
          {layout?.edges.map((edge) => {
            const label = edgeLabel?.(edge.from, edge.to) ?? null;
            const extra = edgeClassName?.(edge.from, edge.to) ?? "";
            const isRunning =
              executionStates?.[edge.to] === "running" ||
              executionStates?.[edge.from] === "running";
            const cls = [extra, isRunning ? "dag-edge-running" : ""].filter(Boolean).join(" ");
            const mid = edgeMidpoint(edge.points);
            return (
              <g key={edge.id} role="graphics-symbol" aria-label={`Connection from ${edge.from} to ${edge.to}`}>
                <path className={`dag-edge ${cls}`.trim()} d={edgePath(edge.points)} fill="none">
                  <title>{`Connection: ${edge.from} → ${edge.to}${label ? ` (${label})` : ""}`}</title>
                </path>
                {label && (
                  <text className="dag-edge-label" x={mid.x} y={mid.y - 4} textAnchor="middle">
                    {label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {layout
          ? dedupedItems.map((item) => {
              const pos = layout.nodes.get(item.id);
              if (!pos) return null;
              return renderNode(item, { position: "absolute", left: pos.x, top: pos.y });
            })
          : (
            <div className="dag-level-row">{dedupedItems.map((item) => renderNode(item))}</div>
          )}
      </div>

      <MiniMap
        nodes={miniMapNodes}
        containerWidth={contentSize.width ?? 0}
        containerHeight={contentSize.height ?? 0}
      />
    </>
  );
}
