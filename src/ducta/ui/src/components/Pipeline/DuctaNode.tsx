import { memo } from "react";
import { Handle, Position, useStore, type NodeProps } from "@xyflow/react";
import { NodeCard } from "./NodeCard";
import { zoomTier, type ZoomTier } from "../../utils/nodePresentation";
import type { DagCanvasItem } from "./types";

export interface DuctaNodeData extends Record<string, unknown> {
  item: DagCanvasItem;
  selected: boolean;
  dimmed: boolean;
  lensDir?: "up" | "down" | null;
  lensDepth?: number;
  execState?: string;
  /** Ports sit top/bottom when layers run down the page, left/right when they run across. */
  orientation?: "vertical" | "horizontal";
  /** False when a band already names the layer (the strata view). */
  showLayer?: boolean;
  /** A node from another pipeline of the chain: quieter, still selectable. */
  context?: boolean;
  /** Escape hatch used by ProjectPage to draw pipeline cards instead of nodes. */
  render?: (item: DagCanvasItem) => React.ReactNode;
  onSelect: (id: string) => void;
  onOpen?: (id: string) => void;
  /** Editable canvas: show the handles that connect this node to another. */
  connectable?: boolean;
  design?: "error" | "warning";
  freshness?: "stale" | "never";
  /** Open comment threads on it. */
  comments?: number;
}

/**
 * Port handles are laid out with the same `(i + 1) / (count + 1)` rule as
 * `portOffset` in utils/dagLayout.ts and the dots in NodeCard's PortRail. All
 * three have to agree or an edge lands next to its dot instead of on it.
 *
 * They are rendered transparent and non-interactive: the visible connector is
 * NodeCard's own dot. React Flow only needs a positioned anchor to attach the
 * edge to.
 */
function PortHandles({
  count,
  type,
  position,
  orientation,
}: {
  count: number;
  type: "source" | "target";
  position: Position;
  orientation?: "vertical" | "horizontal";
}) {
  // Handles spread across the edge the flow crosses: along the width when the
  // layers run down the page, along the height when they run across it.
  const across = orientation === "horizontal" ? "top" : "left";
  return (
    <>
      {Array.from({ length: Math.max(count, 1) }, (_, i) => (
        <Handle
          key={`${type}-${i}`}
          id={`${type}-${i}`}
          type={type}
          position={position}
          isConnectable={false}
          style={{
            [across]: `${((i + 1) / (Math.max(count, 1) + 1)) * 100}%`,
            width: 1,
            height: 1,
            minWidth: 0,
            minHeight: 0,
            background: "transparent",
            border: "none",
            opacity: 0,
          }}
        />
      ))}
    </>
  );
}

/**
 * The canvas' node type. React Flow owns position, selection and viewport; the
 * card's appearance stays in NodeCard so the DAG and the data graph keep
 * rendering nodes identically.
 */
export const DuctaNode = memo(function DuctaNode({ data }: NodeProps) {
  const d = data as unknown as DuctaNodeData;
  const { item, render, onSelect, onOpen } = d;

  const inCount = item.inputs?.length ?? 0;
  const outCount = item.outputs?.length ?? 0;

  // Semantic zoom, in three tiers: zoomed out you read the topology, mid-zoom
  // you follow the data, zoomed in you read the details. Subscribing to the
  // derived tier rather than the raw scale means a card re-renders when it
  // crosses a threshold, not on every wheel tick.
  const tier: ZoomTier = useStore((s) => zoomTier(s.transform[2]));

  const horizontal = d.orientation === "horizontal";

  return (
    <>
      <PortHandles
        count={inCount}
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        orientation={d.orientation}
      />
      {render ? (
        // A custom renderer brings its own interactive element (the project
        // map's supernode is a button that opens the pipeline), so this stays a
        // plain box. Wrapping it in a second role="button" would put a dead
        // focus stop and a nested control around every card.
        <div>{render(item)}</div>
      ) : (
        <NodeCard
          node={item}
          selected={d.selected}
          dimmed={d.dimmed}
          lensDir={d.lensDir}
          lensDepth={d.lensDepth}
          execState={d.execState}
          tier={tier}
          orientation={d.orientation}
          showLayer={d.showLayer}
          context={d.context}
          onClick={() => onSelect(item.id)}
          onOpen={onOpen ? () => onOpen(item.id) : undefined}
          design={d.design}
          freshness={d.freshness}
          comments={d.comments}
        />
      )}
      <PortHandles
        count={outCount}
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        orientation={d.orientation}
      />
      {d.connectable && !d.context && (
        <>
          {/* Drag from the out handle to another node: it will read what this one writes. */}
          <Handle
            id="connect-out"
            type="source"
            position={horizontal ? Position.Right : Position.Bottom}
            isConnectable
            className="node-connect node-connect--out"
            title="Drag to a node to make it read this node's output"
          />
          <Handle
            id="connect-in"
            type="target"
            position={horizontal ? Position.Left : Position.Top}
            isConnectable
            className="node-connect node-connect--in"
          />
        </>
      )}
    </>
  );
});
