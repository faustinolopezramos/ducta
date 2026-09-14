import { memo } from "react";
import { BaseEdge, EdgeLabelRenderer, type EdgeProps } from "@xyflow/react";
import { edgePath } from "../../utils/edgePath";
import type { LayoutPoint } from "../../utils/dagLayout";
import { DatasetChip } from "./DatasetChip";
import type { CanvasDataset } from "./types";

export interface RoutedEdgeData extends Record<string, unknown> {
  /** Waypoints from `layoutDag`: start port, one per crossed layer, end port. */
  points: LayoutPoint[];
  /** The dataset flowing across this edge, when there is one. */
  dataset?: CanvasDataset | null;
  datasetSelected?: boolean;
  datasetDimmed?: boolean;
  tier?: "shape" | "flow" | "detail";
  onSelectDataset?: (name: string) => void;
  /** Plain text label, used by the project map for its shared-dataset summary. */
  label?: string | null;
}

/** Midpoint of a polyline, used to sit the chip clear of the cards. */
function midpoint(points: LayoutPoint[]): LayoutPoint {
  const mid = (points.length - 1) / 2;
  if (Number.isInteger(mid)) return points[mid];
  const a = points[Math.floor(mid)];
  const b = points[Math.ceil(mid)];
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * Draws the spline `layoutDag` routed, rather than React Flow's own bezier,
 * and carries the dataset that the edge exists because of.
 *
 * Keeping the layout engine is the whole reason it survived the React Flow
 * migration: an edge that skips layers is routed through a reserved channel
 * between the cards it passes, so it never crosses one. A default bezier drawn
 * straight from port to port would cut through every card in between.
 *
 * The dataset chip rides in React Flow's edge-label layer at the polyline's
 * midpoint — for a layer-skipping edge that midpoint is inside the reserved
 * channel, so the chip lands in clear space rather than over a card.
 *
 * Falls back to React Flow's endpoints when no route was computed (a node that
 * has not been measured yet on the very first paint).
 */
export const RoutedEdge = memo(function RoutedEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  markerEnd,
  style,
  data,
}: EdgeProps) {
  const d = data as RoutedEdgeData | undefined;
  const points =
    d?.points && d.points.length >= 2
      ? d.points
      : [
          { x: sourceX, y: sourceY },
          { x: targetX, y: targetY },
        ];

  const path = edgePath(points);
  const dataset = d?.dataset ?? null;
  const label = d?.label ?? null;
  const at = dataset || label ? midpoint(points) : null;

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      {at && (
        <EdgeLabelRenderer>
          <div
            className="dag-edge-slot"
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${at.x}px, ${at.y}px)`,
              // The wrapper must not swallow pointer events over the pane, but
              // the chip inside it has to stay clickable.
              pointerEvents: dataset ? "all" : "none",
            }}
          >
            {dataset ? (
              <DatasetChip
                dataset={dataset}
                selected={d?.datasetSelected}
                dimmed={d?.datasetDimmed}
                tier={d?.tier}
                onSelect={d?.onSelectDataset}
              />
            ) : (
              <span className="dag-edge-label">{label}</span>
            )}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});
