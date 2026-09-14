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
  /** Escape hatch used by ProjectPage to draw pipeline cards instead of nodes. */
  render?: (item: DagCanvasItem) => React.ReactNode;
  onSelect: (id: string) => void;
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
}: {
  count: number;
  type: "source" | "target";
  position: Position;
}) {
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
            left: `${((i + 1) / (Math.max(count, 1) + 1)) * 100}%`,
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
  const { item, render, onSelect } = d;

  const inCount = item.inputs?.length ?? 0;
  const outCount = item.outputs?.length ?? 0;

  // Semantic zoom, in three tiers: zoomed out you read the topology, mid-zoom
  // you follow the data, zoomed in you read the details. Subscribing to the
  // derived tier rather than the raw scale means a card re-renders when it
  // crosses a threshold, not on every wheel tick.
  const tier: ZoomTier = useStore((s) => zoomTier(s.transform[2]));

  return (
    <>
      <PortHandles count={inCount} type="target" position={Position.Top} />
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
          onClick={() => onSelect(item.id)}
        />
      )}
      <PortHandles count={outCount} type="source" position={Position.Bottom} />
    </>
  );
});
