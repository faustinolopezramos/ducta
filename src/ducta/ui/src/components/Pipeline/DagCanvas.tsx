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
  useStoreApi,
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
import { FIT_BAND_LABEL_PX, FIT_MAX_ZOOM, FIT_PADDING, FIT_TOP_PX } from "./canvasFit";
import { BandLabelNode, type BandLabelData } from "./BandLabelNode";
import {
  EXTERNAL_IN,
  EXTERNAL_OUT,
  ExternalNode,
  isExternalId,
  type ExternalEnd,
  type ExternalNodeData,
} from "./ExternalNode";
import { GROUP_PREFIX } from "./canvasGroups";
import { ZoomReporter } from "./canvasZoom";
import type { CanvasDataset, CanvasSelection, DagCanvasItem, StreamNodeBadge } from "./types";

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
  /** Live state of streaming nodes (keyed by node name) while their stream runs. */
  streamStates?: Record<string, StreamNodeBadge>;
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
  /**
   * Never frame the graph smaller than this: a tall graph is shown from its
   * top, readable, to be panned — instead of whole and illegible.
   */
  fitMinZoom?: number;
  /**
   * Room kept around the framed graph. The default clears the editor's
   * toolbars; a canvas embedded without them (a run's graph) passes less, or
   * its few cards land in a sliver at the bottom.
   */
  fitPadding?: { top: `${number}px`; right: `${number}px`; bottom: `${number}px`; left: `${number}px` };
  /**
   * Datasets crossing the drawing's border — read from another pipeline, or
   * written and read by nothing drawn — shown as boundary nodes on it.
   */
  externals?: ExternalEnd[];
  /** A boundary node's note leads to the pipeline that writes or reads it. */
  onOpenPipeline?: (pipeline: string) => void;
  /** Publish the zoom for the toolbar's readout (the pipeline page's canvas only). */
  reportZoom?: boolean;
}

function notFresh(state: "fresh" | "stale" | "never" | undefined): "stale" | "never" | undefined {
  return state === "stale" || state === "never" ? state : undefined;
}

/** Space between two cards of the same layer, across the flow. */
const NODE_GAP_X = 40;
/**
 * Space between layers, along the flow, at the least. Left to right needs
 * more: a dataset chip sits in that gap, and a chip is wide where it is short.
 * It grows with the chips a node stacks below itself (`layerGapFor`).
 */
const LAYER_GAP = { vertical: 112, horizontal: 280 } as const;
/**
 * Where a dataset's chip sits: just past its writer's out port, once per
 * dataset however many nodes read it — the edges fan out from the chip. One
 * chip per edge drew the same name twice for a dataset read twice, one copy
 * over the other. A writer of several datasets stacks their chips along the
 * flow (down the page) or across it (left to right).
 */
const CHIP_FIRST = 34;
const CHIP_STEP = 34;
const CHIP_HALF = 15;
/** Left to right: the chip starts this far past the port, and is this wide at most. */
const CHIP_LEAD = 12;
const CHIP_MAX_W = 240;
/** Room past the last chip before the next band starts. */
const CHIP_CLEAR = 10;

/** How far past its writer's port the chips reach, along the flow. */
function chipZone(orientation: "vertical" | "horizontal", stack: number): number {
  if (orientation === "horizontal") return CHIP_LEAD + CHIP_MAX_W + CHIP_CLEAR;
  return CHIP_FIRST + Math.max(stack - 1, 0) * CHIP_STEP + CHIP_HALF + CHIP_CLEAR;
}

function layerGapFor(orientation: "vertical" | "horizontal", stack: number): number {
  return Math.max(LAYER_GAP[orientation], chipZone(orientation, stack) + 46);
}

/** Room the chain bands' labels take in their left gutter, down the page. */
function bandGutter(strata: Strata | null | undefined): number {
  if (!strata?.bands.length) return 0;
  const chars = Math.max(...strata.bands.map((b) => (b.layer ? b.layer.length + 1 : 0) + b.pipeline.length));
  return Math.min(300, Math.round(chars * 7 + 44));
}
const NODE_WIDTH = 208;
/** The card is a single line now; React Flow's measurement replaces this. */
const NODE_HEIGHT_ESTIMATE = 42;
const CANVAS_PADDING = 56;
/** How far a band reaches past its first and last cards, into the gap between bands. */
const BAND_INSET = 40;

const nodeTypes = { ducta: DuctaNode, bandLabel: BandLabelNode, external: ExternalNode };
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

type GraphEdge = LayoutInputEdge & {
  dataset: string | null;
  /** Several datasets drawn as one edge (between collapsed groups). */
  names?: string[];
};

function buildEdges(items: DagCanvasItem[]): GraphEdge[] {
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

  const edges: GraphEdge[] = [];
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

  return mergeGroupEdges(edges);
}

/**
 * A collapsed group reads and writes every dataset of its members, so two
 * groups were joined by one curve per dataset, side by side, with one chip
 * between them. Between a group and anything else, one edge per pair now
 * stands for all its datasets, labelled with how many.
 */
function mergeGroupEdges(edges: GraphEdge[]): GraphEdge[] {
  const isGroup = (id: string) => id.startsWith(GROUP_PREFIX);
  const byPair = new Map<string, GraphEdge[]>();
  for (const e of edges) {
    if (!e.dataset || !(isGroup(e.from) || isGroup(e.to))) continue;
    const pair = `${e.from}->${e.to}`;
    byPair.set(pair, [...(byPair.get(pair) ?? []), e]);
  }
  const merged = new Set<GraphEdge>();
  const out: GraphEdge[] = [];
  for (const e of edges) {
    const group = e.dataset ? byPair.get(`${e.from}->${e.to}`) : undefined;
    if (!group || group.length < 2) {
      out.push(e);
      continue;
    }
    if (merged.has(group[0])) continue;
    merged.add(group[0]);
    out.push({
      from: e.from,
      to: e.to,
      dataset: null,
      key: `${e.from}->${e.to}->datasets`,
      names: group.map((g) => g.dataset!),
    });
  }
  return out;
}

/** The boundary nodes, as canvas items wired by the datasets they stand for. */
function externalItems(externals: ExternalEnd[] | undefined): DagCanvasItem[] {
  return (externals ?? []).map((end) =>
    end.side === "in"
      ? {
          id: EXTERNAL_IN + end.dataset,
          name: end.dataset,
          type: "external",
          dependsOn: [],
          inputs: [],
          outputs: [{ id: `${EXTERNAL_IN}${end.dataset}-out`, name: end.dataset }],
          end,
        }
      : {
          id: EXTERNAL_OUT + end.dataset,
          name: end.dataset,
          type: "external",
          dependsOn: [],
          inputs: [{ id: `${EXTERNAL_OUT}${end.dataset}-in`, name: end.dataset }],
          outputs: [],
          end,
        },
  );
}

/** Each dataset's chip: its writer and the edges it fans out to, keyed by the edge that carries it. */
interface ChipSlot {
  carrier: string;
  members: string[];
  /** Its place among its writer's chips, and how many there are. */
  index: number;
  count: number;
}

function chipSlots(edges: GraphEdge[]): Map<string, ChipSlot> {
  const byWriter = new Map<string, Map<string, { port: number; edges: string[] }>>();
  for (const e of edges) {
    if (!e.dataset || isExternalId(e.from) || isExternalId(e.to)) continue;
    const writer = byWriter.get(e.from) ?? new Map();
    byWriter.set(e.from, writer);
    const slot = writer.get(e.dataset) ?? { port: e.fromPort ?? 0, edges: [] };
    slot.edges.push(e.key!);
    writer.set(e.dataset, slot);
  }
  const out = new Map<string, ChipSlot>();
  for (const writer of byWriter.values()) {
    const ordered = [...writer.values()].sort((a, b) => a.port - b.port);
    ordered.forEach((slot, index) => {
      out.set(slot.edges[0], { carrier: slot.edges[0], members: slot.edges, index, count: ordered.length });
    });
  }
  return out;
}

function DagCanvasInner({
  items,
  renderItem,
  datasets,
  edgeLabel,
  edgeClassName,
  padding = "80px 40px 120px",
  executionStates,
  streamStates,
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
  fitMinZoom,
  fitPadding = FIT_PADDING,
  externals,
  onOpenPipeline,
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

  /** The drawing's own nodes plus the boundary nodes standing for what crosses its edge. */
  const allItems = useMemo(() => {
    const ext = externalItems(externals);
    return ext.length ? [...dedupedItems, ...ext] : dedupedItems;
  }, [dedupedItems, externals]);
  const graphEdges = useMemo(() => buildEdges(allItems), [allItems]);
  const slots = useMemo(() => chipSlots(graphEdges), [graphEdges]);
  /** The most chips one node stacks below itself: what the gap between layers must hold. */
  const chipStack = useMemo(() => Math.max(1, ...[...slots.values()].map((s) => s.count)), [slots]);
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

    const laid = layoutDag(
      allItems.map((it) => ({
        id: it.id,
        width: sizes.get(it.id)?.w ?? NODE_WIDTH,
        height: sizes.get(it.id)?.h ?? NODE_HEIGHT_ESTIMATE,
        inPorts: Math.max(it.inputs?.length ?? 0, inCount.get(it.id) ?? 0) || undefined,
        outPorts: Math.max(it.outputs?.length ?? 0, outCount.get(it.id) ?? 0) || undefined,
      })),
      graphEdges,
      {
        layerGap: layerGapFor(orientation, chipStack),
        nodeGap: NODE_GAP_X,
        padding: CANVAS_PADDING,
        direction,
        bandOf: strata?.bandOf,
      }
    );
    // Down the page the band labels get a gutter of their own on the left, so
    // no label sits on an edge entering its band.
    const shift = orientation === "vertical" ? Math.max(0, 12 + bandGutter(strata) + 16 - CANVAS_PADDING) : 0;
    if (!laid || shift === 0) return laid;
    const nodes = new Map([...laid.nodes].map(([id, n]) => [id, { ...n, x: n.x + shift }]));
    return {
      ...laid,
      nodes,
      edges: laid.edges.map((e) => ({ ...e, points: e.points.map((pt) => ({ x: pt.x + shift, y: pt.y })) })),
      width: laid.width + shift,
    };
  }, [allItems, graphEdges, sizes, orientation, direction, strata, chipStack]);

  /** Null only when the graph has a cycle — see the fallback at the bottom. */
  const isCycle = rawLayout === null && dedupedItems.length > 0;
  const layout = useMemo<DagLayout>(
    () => rawLayout ?? { nodes: new Map(), edges: [], width: 0, height: 0, crossings: 0, bands: [] },
    [rawLayout]
  );
  /** Where one band ends and the next begins: past the chips of the band above, never through them. */
  const bandSpans = useMemo(
    () => bandSpansOf(layout, chipZone(orientation, chipStack)),
    [layout, orientation, chipStack]
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

  /**
   * A selected dataset lights the node that writes it and the nodes that read
   * it — the lens's colours, writer as upstream, readers as downstream — and
   * dims the rest, as selecting a node does. Before, the canvas did not change
   * and only the panel said who wrote and read it.
   */
  const datasetLens = useMemo(() => {
    if (!selectedDataset || lineage) return null;
    const writers = new Set<string>();
    const readers = new Set<string>();
    for (const it of allItems) {
      if ((it.outputs ?? []).some((p) => p.name === selectedDataset)) writers.add(it.id);
      if ((it.inputs ?? []).some((p) => p.name === selectedDataset)) readers.add(it.id);
    }
    return { writers, readers };
  }, [selectedDataset, lineage, allItems]);

  /** Each boundary node's neighbours on the graph: it steps back when they all do. */
  const externalNeighbours = useMemo(() => {
    const out = new Map<string, string[]>();
    for (const e of graphEdges) {
      if (isExternalId(e.from)) out.set(e.from, [...(out.get(e.from) ?? []), e.to]);
      if (isExternalId(e.to)) out.set(e.to, [...(out.get(e.to) ?? []), e.from]);
    }
    return out;
  }, [graphEdges]);
  const isLit = useCallback(
    (id: string) =>
      (!lineage || id === lineage.selectedId || lineage.upstream.has(id) || lineage.downstream.has(id)) &&
      (!datasetLens || datasetLens.writers.has(id) || datasetLens.readers.has(id)) &&
      (highlight == null || highlight.has(id)),
    [lineage, datasetLens, highlight]
  );
  const externalNodes = useMemo<Node[]>(
    () =>
      allItems
        .filter((it) => isExternalId(it.id))
        .map((it) => {
          const pos = layout.nodes.get(it.id);
          const size = sizes.get(it.id);
          const data: ExternalNodeData = {
            end: it.end as ExternalEnd,
            orientation,
            selected: selectedDataset === (it.end as ExternalEnd).dataset,
            dimmed: !(externalNeighbours.get(it.id) ?? []).some(isLit),
            onSelectDataset: selectDataset,
            onOpenPipeline,
          };
          return {
            id: it.id,
            type: "external",
            position: { x: pos?.x ?? 0, y: pos?.y ?? 0 },
            ...(size ? { measured: { width: size.w, height: size.h } } : {}),
            data: data as unknown as Record<string, unknown>,
            draggable: false,
            connectable: false,
            selectable: false,
          };
        }),
    [allItems, layout, sizes, orientation, selectedDataset, externalNeighbours, isLit, selectDataset, onOpenPipeline]
  );

  const rfNodes = useMemo<Node[]>(
    () => [
      ...dedupedItems.map((item) => {
        const pos = layout.nodes.get(item.id);
        const lensDir = lineage
          ? lineage.upstream.has(item.id)
            ? ("up" as const)
            : lineage.downstream.has(item.id)
              ? ("down" as const)
              : null
          : datasetLens
            ? datasetLens.writers.has(item.id)
              ? ("up" as const)
              : datasetLens.readers.has(item.id)
                ? ("down" as const)
                : null
            : null;
        // With a lens active, anything outside it is dimmed rather than hidden:
        // the shape of the graph stays readable while the relevant path lifts.
        const dimmed =
          ((Boolean(lineage) || Boolean(datasetLens)) && !lensDir && item.id !== selectedNodeId) ||
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
          stream: streamStates?.[item.name || item.id],
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

        const size = sizes.get(item.id);
        return {
          id: item.id,
          type: "ducta",
          position: { x: pos?.x ?? 0, y: pos?.y ?? 0 },
          // The minimap draws only nodes that carry their size, and reads it
          // from these nodes, not from React Flow's own measurements: without
          // it the minimap was an empty box.
          ...(size ? { measured: { width: size.w, height: size.h } } : {}),
          data: data as unknown as Record<string, unknown>,
          // Dragging would desynchronise the cards from the routed edges, which
          // are drawn from the layout's own waypoints rather than from live
          // handle positions. The layout is the source of truth here.
          draggable: false,
          connectable: Boolean(onConnectNodes),
          selected: item.id === selectedNodeId,
        };
      }),
      ...externalNodes,
      ...bandLabelNodes(bandSpans, strata, orientation),
    ],
    [
      dedupedItems,
      externalNodes,
      bandSpans,
      layout,
      sizes,
      lineage,
      selectedNodeId,
      executionStates,
      streamStates,
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
      datasetLens,
    ]
  );

  /** Routed-edge id → the edge it was built from (its dataset, or the datasets it stands for). */
  const edgeById = useMemo(() => new Map(graphEdges.map((e) => [e.key!, e])), [graphEdges]);

  const rfEdges = useMemo<Edge[]>(() => {
    // `layoutDag` returns each edge under the `key` it was given, so the
    // dataset is recovered by id rather than by position — the layout drops
    // duplicates, so index alignment would silently shift.
    const lensOf = (from: string, to: string) =>
      isExternalId(from) || isExternalId(to) ? undefined : edgeClassName?.(from, to);
    // Off the lens's path, or with neither end matching the filter: the
    // edge and its chip step back with the nodes they join. An edge to a
    // boundary node goes with the node it joins.
    const dimmedOf = (from: string, to: string) => {
      if (isExternalId(from)) return !isLit(to);
      if (isExternalId(to)) return !isLit(from);
      // A selected dataset: only the edges that carry it stay lit.
      if (datasetLens) return !edgeById.has(`${from}->${to}->${selectedDataset}`);
      const lensClass = lensOf(from, to);
      return (
        lensClass === "dag-edge-dimmed" ||
        (Boolean(lineage) && !lensClass) ||
        (highlight != null && !highlight.has(from) && !highlight.has(to))
      );
    };
    const dimmedById = new Map(layout.edges.map((e) => [e.id, dimmedOf(e.from, e.to)]));

    return layout.edges.map((e) => {
      const graphEdge = edgeById.get(e.id);
      const slot = slots.get(e.id);
      const name = slot ? (graphEdge?.dataset ?? null) : null;
      const dataset: CanvasDataset | null =
        name && !hideDatasetChips
          ? (datasets?.get(name) ?? { name, declared: false })
          : null;

      // The chip sits past its writer's port; its writer's chips stack.
      let chipAt: RoutedEdgeData["chipAt"];
      if (dataset && slot) {
        const port = e.points[0];
        if (orientation === "horizontal") {
          const writer = layout.nodes.get(e.from);
          const centre = writer ? writer.y + writer.height / 2 : port.y;
          chipAt = { x: port.x + CHIP_LEAD, y: centre + (slot.index - (slot.count - 1) / 2) * CHIP_STEP, anchor: "start" };
        } else {
          chipAt = { x: port.x, y: port.y + CHIP_FIRST + slot.index * CHIP_STEP, anchor: "center" };
        }
      }

      // The edge feeding a node that is currently running animates, so the live
      // front of a run is visible on the graph itself rather than only in the
      // log pane. Dependency-lens classes still win where both apply: the lens
      // is something the user asked for, the run state is ambient.
      const running = executionStates?.[e.to] === "running";
      const streamBadge = streamStates?.[e.to];
      const isStreamActive = streamBadge?.state === "active";
      const isStreamStalled = streamBadge?.health === "stalled";
      const streamClass = isStreamActive
        ? isStreamStalled
          ? "dag-edge-streaming-stalled"
          : "dag-edge-streaming"
        : null;
      const lensClass = lensOf(e.from, e.to);
      const dimmed = dimmedById.get(e.id) ?? false;
      const merged = graphEdge?.names;

      const data: RoutedEdgeData = {
        points: e.points,
        dataset,
        datasetSelected: Boolean(name) && name === selectedDataset,
        // A chip read by several nodes steps back only when all its edges do.
        datasetDimmed: slot ? slot.members.every((id) => dimmedById.get(id)) : dimmed,
        datasetReaders: slot?.members.length,
        chipAt,
        tier,
        onSelectDataset: selectDataset,
        label: dataset
          ? null
          : merged
            ? `${merged.length} datasets`
            : graphEdge?.dataset || isExternalId(e.from) || isExternalId(e.to)
              ? null
              : (edgeLabel?.(e.from, e.to) ?? null),
        labelTitle: merged?.join("\n"),
        direction,
      };

      return {
        id: e.id,
        source: e.from,
        target: e.to,
        type: "routed",
        className: [
          lensClass,
          !lensClass ? (running ? "dag-edge-running" : streamClass) : null,
          dimmed && lensClass !== "dag-edge-dimmed" ? "dag-edge-dimmed" : null,
        ]
          .filter(Boolean)
          .join(" "),
        data: data as unknown as Record<string, unknown>,
      };
    });
  }, [
    layout,
    edgeById,
    slots,
    datasets,
    hideDatasetChips,
    edgeLabel,
    edgeClassName,
    executionStates,
    streamStates,
    selectedDataset,
    lineage,
    highlight,
    isLit,
    datasetLens,
    orientation,
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
  const { fitView, getViewport, setViewport, getNodesBounds, getNodes } = useReactFlow();
  const flowStore = useStoreApi();
  const itemsKey = useMemo(() => dedupedItems.map((it) => it.id).join("|"), [dedupedItems]);
  const fitKey = `${itemsKey}#${orientation}#${strata?.bands.length ?? 0}`;
  const measured = allItems.length > 0 && allItems.every((it) => sizes.has(it.id));
  const fittedFor = useRef<string | null>(null);
  /**
   * Whether the user has panned or zoomed since this drawing was framed.
   * Until they do, the frame follows the drawing: a later measurement pass
   * re-lays it out, and the canvas changes size when the tree, the dock or the
   * focus panel open — each of which left the graph off-centre (by up to a
   * third of the canvas) when the fit ran only once. After they do, nothing
   * moves the viewport from under them.
   */
  const userMoved = useRef(false);
  /** Our own fit is moving the viewport (anything else counts as the user's move). */
  const fitting = useRef(false);
  const fit = useCallback(() => {
    fitting.current = true;
    const bandRoom = strata?.bands.length ? FIT_BAND_LABEL_PX : 0;
    const padding = { ...fitPadding, top: `${parseInt(fitPadding.top, 10) + bandRoom}px` as `${number}px` };
    void fitView({ padding, maxZoom: FIT_MAX_ZOOM }).then(() => {
      if (!fitMinZoom || getViewport().zoom >= fitMinZoom) {
        fitting.current = false;
        return;
      }
      // Too small to read whole: show it from the top, centred across.
      const bounds = getNodesBounds(getNodes());
      const { width } = flowStore.getState();
      setViewport({
        zoom: fitMinZoom,
        x: (width - bounds.width * fitMinZoom) / 2 - bounds.x * fitMinZoom,
        y: FIT_TOP_PX + bandRoom - bounds.y * fitMinZoom,
      });
      fitting.current = false;
    });
  }, [fitView, fitMinZoom, fitPadding, getViewport, setViewport, getNodesBounds, getNodes, flowStore, strata?.bands.length]);
  useEffect(() => {
    if (!measured) return;
    if (fittedFor.current !== fitKey) {
      fittedFor.current = fitKey;
      userMoved.current = false;
    } else if (userMoved.current) {
      return;
    }
    fit();
  }, [measured, fitKey, layout, fit]);
  // The canvas itself changing size (a panel opening beside it) re-frames too.
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let frame = 0;
    let last = "";
    const observer = new ResizeObserver(([entry]) => {
      const size = `${Math.round(entry.contentRect.width)}x${Math.round(entry.contentRect.height)}`;
      if (size === last) return;
      const first = last === "";
      last = size;
      if (first || userMoved.current || fittedFor.current === null) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => fit());
    });
    observer.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [fit]);

  /**
   * Keyboard focus follows the selection while it is on the graph: the arrows
   * and Tab move the selection, and the focused card used to stay behind —
   * a screen reader announced nothing, and Enter acted on the old card.
   */
  useEffect(() => {
    const root = rootRef.current;
    if (!selectedNodeId || !root || !root.contains(document.activeElement)) return;
    const card = root.querySelector<HTMLElement>(
      `.react-flow__node[data-id="${selectedNodeId.replace(/["\\]/g, "\\$&")}"] [role="button"]`
    );
    if (card && card !== document.activeElement) card.focus({ preventScroll: true });
  }, [selectedNodeId]);

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
      ref={rootRef}
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
        // Any move that is not our own fit — a drag, the wheel, the zoom
        // buttons, centring on a node — stops the automatic re-framing for
        // this drawing.
        onMoveStart={() => {
          if (!fitting.current) userMoved.current = true;
        }}
        onNodeDoubleClick={onOpenNode ? (_e, node) => node.type === "ducta" && onOpenNode(node.id) : undefined}
        zoomOnDoubleClick={!onOpenNode}
        fitView
        fitViewOptions={{ padding: fitPadding, maxZoom: FIT_MAX_ZOOM }}
        minZoom={0.2}
        maxZoom={1.6}
        nodesDraggable={false}
        // The card is the node's one focus stop; React Flow's wrapper made it two.
        nodesFocusable={false}
        nodesConnectable={Boolean(onConnectNodes)}
        onConnect={onConnectNodes ? (c) => c.source && c.target && onConnectNodes(c.source, c.target) : undefined}
        isValidConnection={
          canConnect ? (c) => Boolean(c.source && c.target && c.source !== c.target && canConnect(c.source, c.target)) : undefined
        }
        connectionRadius={36}
        elementsSelectable
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="var(--canvas-dot)" />
        <StrataBands spans={bandSpans} layout={layout} strata={strata} orientation={orientation} />
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

interface BandSpan {
  band: number;
  /** Along the flow: where the band's ground starts and ends. */
  from: number;
  to: number;
}

/**
 * Where each band's ground runs. A band used to reach a fixed 40 px past its
 * last cards, so the line between two bands fell on the chips just below the
 * upper band's cards. The line now falls past those chips (`zone`), in the
 * gap before the next band's cards.
 */
function bandSpansOf(layout: DagLayout, zone: number): BandSpan[] {
  const bands = layout.bands;
  const lines = bands.slice(0, -1).map((b, i) => Math.min(b.end + zone, bands[i + 1].start - 12));
  return bands.map((b, i) => ({
    band: b.band,
    from: i === 0 ? b.start - BAND_INSET : lines[i - 1],
    to: i === bands.length - 1 ? b.end + BAND_INSET : lines[i],
  }));
}

/**
 * One label per chain band. Down the page it sits in the gutter left of the
 * cards, at the band's top, so no edge entering the band runs under it; left
 * to right it sits above the band. As nodes they render above the edges; they
 * are not selectable, draggable or measured into the layout.
 */
function bandLabelNodes(
  spans: BandSpan[],
  strata: Strata | null | undefined,
  orientation: "vertical" | "horizontal",
): Node[] {
  if (!strata || spans.length === 0) return [];
  return spans.flatMap((span) => {
    const band = strata.bands[span.band];
    if (!band) return [];
    const data: BandLabelData = {
      layer: band.layer ?? null,
      pipeline: band.pipeline,
      current: Boolean(band.current),
      sticky: orientation === "vertical",
    };
    return [
      {
        id: `band-label:${band.pipeline}`,
        type: "bandLabel",
        position: orientation === "vertical" ? { x: 12, y: span.from + 8 } : { x: span.from + 10, y: 10 },
        data: data as unknown as Record<string, unknown>,
        draggable: false,
        selectable: false,
        connectable: false,
        focusable: false,
        style: { pointerEvents: "none" },
      },
    ];
  });
}

/**
 * One band per pipeline of the chain, drawn in the canvas' own coordinates so
 * it pans and zooms with the cards. Across the flow a band spans the whole
 * drawing.
 */
function StrataBands({
  spans,
  layout,
  strata,
  orientation,
}: {
  spans: BandSpan[];
  layout: DagLayout;
  strata: Strata | null;
  orientation: "vertical" | "horizontal";
}) {
  if (!strata || spans.length === 0) return null;
  const vertical = orientation === "vertical";

  return (
    <ViewportPortal>
      {spans.map((span) => {
        const band = strata.bands[span.band];
        if (!band) return null;
        const length = span.to - span.from;
        const style: React.CSSProperties = vertical
          ? { transform: `translate(0px, ${span.from}px)`, width: layout.width, height: length }
          : { transform: `translate(${span.from}px, 0px)`, width: length, height: layout.height };
        return (
          // The label is a node of its own (bandLabelNodes), drawn above the edges.
          <div
            key={band.pipeline}
            className={`strata-band${band.current ? " current" : ""}`}
            data-orientation={orientation}
            data-layer={band.layer ?? undefined}
            data-testid="strata-band"
            style={style}
          />
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
export function DagCanvas({ onViewportReady, reportZoom = false, ...props }: DagCanvasProps) {
  return (
    <ReactFlowProvider>
      <ViewportBridge onReady={onViewportReady} />
      {reportZoom && <ZoomReporter />}
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
