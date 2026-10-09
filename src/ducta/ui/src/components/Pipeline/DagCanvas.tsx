import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  ViewportPortal,
  useReactFlow,
  useStore,
  type Edge,
  type Node,
  type NodeChange,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { IconAlertTriangle } from "@tabler/icons-react";
import { resolveDepId } from "../../utils/dagValidation";
import { layoutDag, type DagLayout, type LayoutInputEdge } from "../../utils/dagLayout";
import type { Lineage } from "../../utils/lineage";
import { zoomTier, type ZoomTier } from "../../utils/nodePresentation";
import type { Strata } from "../../utils/strata";
import { DuctaNode, type DuctaNodeData } from "./DuctaNode";
import { RoutedEdge, type RoutedEdgeData } from "./RoutedEdge";
import { useCanvasViewport, type CanvasViewport } from "./useCanvasViewport";
import type { CanvasDataset, CanvasSelection, DagCanvasItem } from "./types";

export type { DagCanvasItem } from "./types";
// Re-exported from its new home in utils/ so existing imports keep resolving.
export { edgePath } from "../../utils/edgePath";

interface DagCanvasProps {
  items: DagCanvasItem[];
  renderItem?: (item: DagCanvasItem) => React.ReactNode;
  /** Resolved dataset detail, keyed by reference name, for the edge chips. */
  datasets?: Map<string, CanvasDataset>;
  edgeLabel?: (from: string, to: string) => string | null;
  edgeClassName?: (from: string, to: string) => string;
  /** Applies only to the cycle fallback; the laid-out canvas sizes itself. */
  padding?: string;
  executionStates?: Record<string, string>;
  selection?: CanvasSelection;
  lineage?: Lineage | null;
  onSelect?: (selection: CanvasSelection) => void;
  /** Double-click on a node: open it (its code). */
  onOpenNode?: (id: string) => void;
  /**
   * Editable canvas: dragging from a node's out handle onto another node asks
   * for `to` to read what `from` writes. Edges still come from the data — the
   * caller edits the pipeline and the canvas redraws.
   */
  onConnectNodes?: (from: string, to: string) => void;
  /** Whether `from` → `to` may be connected (no cycle, not already connected). */
  canConnect?: (from: string, to: string) => boolean;
  /** Validation per node: its worst problem. */
  designStates?: ReadonlyMap<string, "error" | "warning">;
  /** Freshness per node against its last successful run. */
  freshness?: Readonly<Record<string, "fresh" | "stale" | "never">>;
  /** Open comment threads per node. */
  comments?: ReadonlyMap<string, number>;
  /** A search or filter is on: nodes outside this set are dimmed (not hidden — the graph keeps its shape). */
  highlight?: ReadonlySet<string> | null;
  /** Hide the dataset chips and draw plain edges. */
  hideDatasetChips?: boolean;
  /** Receives the canvas' viewport controls once React Flow is mounted. */
  onViewportReady?: (viewport: CanvasViewport) => void;
  /** Off by default: on most pipelines the whole graph already fits the view. */
  showMinimap?: boolean;
  /** Layers top to bottom (the default) or left to right — the viewer's preference. */
  orientation?: "vertical" | "horizontal";
  /** Draw a pipeline chain as bands, one per pipeline, in execution order. */
  strata?: Strata | null;
}

function notFresh(state: "fresh" | "stale" | "never" | undefined): "stale" | "never" | undefined {
  return state === "stale" || state === "never" ? state : undefined;
}

/** Space between two cards of the same layer, across the flow. */
const NODE_GAP_X = 40;
/**
 * Space between layers, along the flow. Left to right needs more: a dataset
 * chip sits in that gap, and a chip is wide where it is short.
 */
const LAYER_GAP = { vertical: 112, horizontal: 232 } as const;
const NODE_WIDTH = 208;
/** The card is a single line now; React Flow's measurement replaces this. */
const NODE_HEIGHT_ESTIMATE = 42;
const CANVAS_PADDING = 56;
const FIT_PADDING = 0.2;
/** Never zoom past 1:1 — the cards are designed at a size, not scaled up to fill. */
const FIT_MAX_ZOOM = 1;
/** How far a band reaches past its first and last cards, into the gap between bands. */
const BAND_INSET = 40;

const nodeTypes = { ducta: DuctaNode };
const edgeTypes = { routed: RoutedEdge };

/**
 * The edges of the graph, one per dataset that crosses them.
 *
 * In ducta an edge exists *because* a dataset connects two nodes: a node that
 * writes `silver.clean` and one that reads it are wired by that name. So the
 * edge set is built from that matching, and two nodes sharing two datasets get
 * two edges with two chips — the old canvas de-duplicated by `from→to` pair and
 * silently collapsed them into one unlabelled line.
 *
 * An explicit `dependencies` entry with no dataset behind it still produces an
 * edge, just without a chip: ordering the runtime enforces is real information
 * even when no data flows across it.
 */
function edgeKeyFor(from: string, to: string, dataset: string | null): string {
  return `${from}->${to}->${dataset ?? "*"}`;
}

function buildEdges(items: DagCanvasItem[]): Array<LayoutInputEdge & { dataset: string | null }> {
  const known = items.map((it) => ({ id: it.id, name: it.name ?? it.id }));
  const byId = new Map(items.map((it) => [it.id, it]));

  // dataset name → ids of the nodes that write it
  const producers = new Map<string, string[]>();
  for (const item of items) {
    for (const out of item.outputs ?? []) {
      if (!out?.name) continue;
      const list = producers.get(out.name);
      if (list) list.push(item.id);
      else producers.set(out.name, [item.id]);
    }
  }

  const edges: Array<LayoutInputEdge & { dataset: string | null }> = [];
  const seen = new Set<string>();

  // Dataset-derived edges, with the port each end belongs to.
  for (const target of items) {
    const inputs = target.inputs ?? [];
    for (let toPort = 0; toPort < inputs.length; toPort++) {
      const name = inputs[toPort]?.name;
      if (!name) continue;
      for (const fromId of producers.get(name) ?? []) {
        if (fromId === target.id) continue;
        const key = edgeKeyFor(fromId, target.id, name);
        if (seen.has(key)) continue;
        seen.add(key);
        const source = byId.get(fromId);
        const fromPort = (source?.outputs ?? []).findIndex((o) => o.name === name);
        edges.push({
          from: fromId,
          to: target.id,
          dataset: name,
          key,
          ...(fromPort >= 0 ? { fromPort } : {}),
          toPort,
        });
      }
    }
  }

  // Explicit dependencies that no dataset already accounts for.
  for (const item of items) {
    for (const dep of item.dependsOn) {
      const fromId = resolveDepId(dep, known);
      if (!fromId || fromId === item.id) continue;
      const covered = edges.some((e) => e.from === fromId && e.to === item.id);
      if (covered) continue;
      const key = edgeKeyFor(fromId, item.id, null);
      if (seen.has(key)) continue;
      seen.add(key);
      edges.push({ from: fromId, to: item.id, dataset: null, key });
    }
  }

  return edges;
}

function DagCanvasInner({
  items,
  renderItem,
  datasets,
  edgeLabel,
  edgeClassName,
  padding = "80px 40px 120px",
  executionStates,
  selection,
  lineage,
  onSelect,
  onOpenNode,
  onConnectNodes,
  canConnect,
  designStates,
  freshness,
  comments,
  highlight = null,
  hideDatasetChips = false,
  showMinimap = false,
  orientation = "vertical",
  strata = null,
}: DagCanvasProps) {
  /**
   * Card sizes, fed back from React Flow's own measurement into the layout.
   * React Flow already measures every node and reports it on the change event,
   * so this just listens rather than measuring anything itself.
   */
  const [sizes, setSizes] = useState<Map<string, { w: number; h: number }>>(new Map());

  const dedupedItems = useMemo(() => {
    const seen = new Set<string>();
    return items.filter((it) => {
      if (seen.has(it.id)) return false;
      seen.add(it.id);
      return true;
    });
  }, [items]);

  const graphEdges = useMemo(() => buildEdges(dedupedItems), [dedupedItems]);
  const direction = orientation === "horizontal" ? "LR" : "TB";

  const rawLayout = useMemo(() => {
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
      {
        layerGap: LAYER_GAP[orientation],
        nodeGap: NODE_GAP_X,
        padding: CANVAS_PADDING,
        direction,
        bandOf: strata?.bandOf,
      }
    );
  }, [dedupedItems, graphEdges, sizes, orientation, direction, strata]);

  /** Null only when the graph has a cycle — see the fallback at the bottom. */
  const isCycle = rawLayout === null && dedupedItems.length > 0;
  const layout = useMemo<DagLayout>(
    () => rawLayout ?? { nodes: new Map(), edges: [], width: 0, height: 0, crossings: 0, bands: [] },
    [rawLayout]
  );

  const selectedNodeId = selection?.kind === "node" ? selection.id : null;
  const selectedDataset = selection?.kind === "dataset" ? selection.id : null;

  const selectNode = useCallback(
    (id: string) => onSelect?.(id ? { kind: "node", id } : null),
    [onSelect]
  );
  const selectDataset = useCallback(
    (name: string) => onSelect?.({ kind: "dataset", id: name }),
    [onSelect]
  );

  /**
   * Nodes of the chain's other pipelines. They are the page pipeline's upstream
   * context: drawn quieter, but still selectable. Only meaningful when a band is
   * marked as the page's own pipeline.
   */
  const contextIds = useMemo(() => {
    if (!strata || !strata.bands.some((b) => b.current)) return new Set<string>();
    return new Set(strata.bands.filter((b) => !b.current).flatMap((b) => b.nodeIds));
  }, [strata]);

  const tier: ZoomTier = useStore((s) => zoomTier(s.transform[2]));

  const rfNodes = useMemo<Node[]>(
    () =>
      dedupedItems.map((item) => {
        const pos = layout.nodes.get(item.id);
        const lensDir = lineage
          ? lineage.upstream.has(item.id)
            ? ("up" as const)
            : lineage.downstream.has(item.id)
              ? ("down" as const)
              : null
          : null;
        // With a lens active, anything outside it is dimmed rather than hidden:
        // the shape of the graph stays readable while the relevant path lifts.
        const dimmed =
          (Boolean(lineage) && !lensDir && item.id !== selectedNodeId) ||
          (highlight != null && !highlight.has(item.id));

        const data: DuctaNodeData = {
          item,
          selected: item.id === selectedNodeId,
          dimmed,
          lensDir,
          lensDepth: lensDir
            ? (lensDir === "up" ? lineage?.upstream : lineage?.downstream)?.get(item.id)
            : undefined,
          execState: executionStates?.[item.id],
          orientation,
          // A band already says which layer a pipeline is; the swatch would repeat it.
          showLayer: !strata,
          context: contextIds.has(item.id),
          render: renderItem,
          onSelect: selectNode,
          onOpen: onOpenNode,
          connectable: Boolean(onConnectNodes),
          design: designStates?.get(item.id),
          freshness: notFresh(freshness?.[item.id]),
          comments: comments?.get(item.id) ?? 0,
        };

        return {
          id: item.id,
          type: "ducta",
          position: { x: pos?.x ?? 0, y: pos?.y ?? 0 },
          data: data as unknown as Record<string, unknown>,
          // Dragging would desynchronise the cards from the routed edges, which
          // are drawn from the layout's own waypoints rather than from live
          // handle positions. The layout is the source of truth here.
          draggable: false,
          connectable: Boolean(onConnectNodes),
          selected: item.id === selectedNodeId,
        };
      }),
    [
      dedupedItems,
      layout,
      lineage,
      selectedNodeId,
      executionStates,
      orientation,
      strata,
      contextIds,
      renderItem,
      selectNode,
      onOpenNode,
      onConnectNodes,
      designStates,
      freshness,
      comments,
      highlight,
    ]
  );

  /** Routed-edge id → the dataset that edge carries. */
  const datasetOfEdge = useMemo(() => {
    const map = new Map<string, string | null>();
    for (const e of graphEdges) map.set(e.key!, e.dataset);
    return map;
  }, [graphEdges]);

  const rfEdges = useMemo<Edge[]>(() => {
    // `layoutDag` returns each edge under the `key` it was given, so the
    // dataset is recovered by id rather than by position — the layout drops
    // duplicates, so index alignment would silently shift.
    return layout.edges.map((e) => {
      const name = datasetOfEdge.get(e.id) ?? null;
      const dataset: CanvasDataset | null =
        name && !hideDatasetChips
          ? (datasets?.get(name) ?? { name, declared: false })
          : null;

      // The edge feeding a node that is currently running animates, so the live
      // front of a run is visible on the graph itself rather than only in the
      // log pane. Dependency-lens classes still win where both apply: the lens
      // is something the user asked for, the run state is ambient.
      const running = executionStates?.[e.to] === "running";
      const lensClass = edgeClassName?.(e.from, e.to);

      const data: RoutedEdgeData = {
        points: e.points,
        dataset,
        datasetSelected: Boolean(name) && name === selectedDataset,
        datasetDimmed: Boolean(lineage) && Boolean(lensClass) === false,
        tier,
        onSelectDataset: selectDataset,
        label: dataset ? null : (edgeLabel?.(e.from, e.to) ?? null),
        direction,
      };

      return {
        id: e.id,
        source: e.from,
        target: e.to,
        type: "routed",
        className: [lensClass, running && !lensClass ? "dag-edge-running" : null]
          .filter(Boolean)
          .join(" "),
        data: data as unknown as Record<string, unknown>,
      };
    });
  }, [
    layout,
    datasetOfEdge,
    datasets,
    hideDatasetChips,
    edgeLabel,
    edgeClassName,
    executionStates,
    selectedDataset,
    lineage,
    tier,
    selectDataset,
    direction,
  ]);

  /**
   * Re-fit once the cards have been measured, and again whenever the drawing
   * itself changes shape (another orientation, bands on or off).
   *
   * `fitView` as a prop only runs on init, when every card is still the
   * placeholder size — so the graph was framed against an estimate and then
   * re-laid-out underneath the viewport. Refitting is keyed to what is drawn,
   * so it happens once per drawing and never yanks the viewport away from a
   * user who has panned.
   */
  const { fitView } = useReactFlow();
  const itemsKey = useMemo(() => dedupedItems.map((it) => it.id).join("|"), [dedupedItems]);
  const fitKey = `${itemsKey}#${orientation}#${strata?.bands.length ?? 0}`;
  const measured = dedupedItems.length > 0 && dedupedItems.every((it) => sizes.has(it.id));
  const fittedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!measured || fittedFor.current === fitKey) return;
    fittedFor.current = fitKey;
    fitView({ padding: FIT_PADDING, maxZoom: FIT_MAX_ZOOM });
  }, [measured, fitKey, fitView, layout]);

  /**
   * Pick up React Flow's measurements and re-run the layout with real sizes.
   * Only a genuine change is stored, so this settles after one extra pass
   * instead of oscillating between the estimate and the measured value.
   */
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    const measuredChanges = changes.filter(
      (c): c is Extract<NodeChange, { type: "dimensions" }> => c.type === "dimensions"
    );
    if (measuredChanges.length === 0) return;

    setSizes((prev) => {
      const next = new Map(prev);
      let changed = false;
      for (const c of measuredChanges) {
        const dims = c.dimensions;
        if (!dims || !dims.width || !dims.height) continue;
        const before = prev.get(c.id);
        if (!before || before.w !== dims.width || before.h !== dims.height) {
          next.set(c.id, { w: dims.width, h: dims.height });
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  // A cycle leaves the layout with no layering to draw. Say so plainly instead
  // of rendering an arbitrary arrangement that looks authoritative.
  if (isCycle) {
    return (
      <div className="dag-cycle-fallback" style={{ padding }}>
        <IconAlertTriangle size={18} stroke={1.5} />
        <span>
          These nodes form a dependency cycle, so they cannot be laid out as a graph. Break the
          cycle to see the pipeline.
        </span>
      </div>
    );
  }

  return (
    <div
      className="dag-canvas-root"
      data-orientation={orientation}
      style={{ width: "100%", height: "100%" }}
    >
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onPaneClick={() => onSelect?.(null)}
        onNodeDoubleClick={onOpenNode ? (_e, node) => onOpenNode(node.id) : undefined}
        zoomOnDoubleClick={!onOpenNode}
        fitView
        fitViewOptions={{ padding: FIT_PADDING, maxZoom: FIT_MAX_ZOOM }}
        minZoom={0.2}
        maxZoom={1.6}
        nodesDraggable={false}
        nodesConnectable={Boolean(onConnectNodes)}
        onConnect={onConnectNodes ? (c) => c.source && c.target && onConnectNodes(c.source, c.target) : undefined}
        isValidConnection={
          canConnect ? (c) => Boolean(c.source && c.target && c.source !== c.target && canConnect(c.source, c.target)) : undefined
        }
        connectionRadius={36}
        elementsSelectable
        proOptions={{ hideAttribution: false }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="var(--canvas-dot)" />
        <StrataBands layout={layout} strata={strata} orientation={orientation} />
        {showMinimap && (
          <MiniMap
            pannable
            zoomable
            ariaLabel="Pipeline minimap"
            nodeColor="var(--edge)"
            maskColor="var(--overlay-subtle)"
          />
        )}
      </ReactFlow>
    </div>
  );
}

/**
 * One band per pipeline of the chain, drawn in the canvas' own coordinates so
 * it pans and zooms with the cards. The layout says where each band starts and
 * ends along the flow; across the flow a band spans the whole drawing.
 */
function StrataBands({
  layout,
  strata,
  orientation,
}: {
  layout: DagLayout;
  strata: Strata | null;
  orientation: "vertical" | "horizontal";
}) {
  if (!strata || layout.bands.length === 0) return null;
  const vertical = orientation === "vertical";

  return (
    <ViewportPortal>
      {layout.bands.map((placed) => {
        const band = strata.bands[placed.band];
        if (!band) return null;
        const start = placed.start - BAND_INSET;
        const length = placed.end - placed.start + BAND_INSET * 2;
        const style: React.CSSProperties = vertical
          ? { transform: `translate(0px, ${start}px)`, width: layout.width, height: length }
          : { transform: `translate(${start}px, 0px)`, width: length, height: layout.height };
        return (
          <div
            key={band.pipeline}
            className={`strata-band${band.current ? " current" : ""}`}
            data-orientation={orientation}
            data-layer={band.layer ?? undefined}
            data-testid="strata-band"
            style={style}
          >
            <span className="strata-band-label">
              <span className="strata-band-swatch" aria-hidden="true" />
              {band.layer && <span>{band.layer}</span>}
              <span className="strata-band-pipe">{band.pipeline}</span>
            </span>
          </div>
        );
      })}
    </ViewportPortal>
  );
}

/**
 * Pipeline DAG canvas.
 *
 * React Flow owns the viewport, selection and minimap; `layoutDag` still owns
 * where the cards go and how the edges are routed. Keeping the layout engine
 * was deliberate — it is tuned to Ducta's semantics (typed ports, reserved
 * channels for edges that skip layers, median-sweep crossing reduction), none
 * of which a generic auto-layout reproduces.
 */
export function DagCanvas({ onViewportReady, ...props }: DagCanvasProps) {
  return (
    <ReactFlowProvider>
      <ViewportBridge onReady={onViewportReady} />
      <DagCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

/**
 * Hands the canvas' viewport controls out to the page.
 *
 * `useCanvasViewport` has to run under the provider, and the toolbar and
 * keyboard shortcuts live above it, so the controls are passed upward instead
 * of the page reaching down. Previously the page kept its *own* pan/zoom state
 * in `builderStore`, which React Flow never read — so the HUD's zoom buttons
 * and "centre this node" did nothing at all.
 */
function ViewportBridge({ onReady }: { onReady?: (v: CanvasViewport) => void }) {
  const viewport = useCanvasViewport();
  useEffect(() => {
    onReady?.(viewport);
  }, [onReady, viewport]);
  return null;
}
