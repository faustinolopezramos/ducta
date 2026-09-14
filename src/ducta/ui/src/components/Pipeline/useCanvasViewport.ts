import { useCallback } from "react";
import { useReactFlow } from "@xyflow/react";

/** How long a programmatic viewport move takes, in ms. */
const PAN_DURATION = 220;
/** Never zoom past 1:1 when framing — cards are designed at a size. */
const FIT_MAX_ZOOM = 1;
const FIT_PADDING = 0.2;

export interface CanvasViewport {
  /** Bring a node to the middle of the canvas, optionally offset horizontally. */
  centerOnNode: (id: string, offsetX?: number) => void;
  /** Frame the whole graph. */
  fitCanvas: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
}

/**
 * Viewport control for the DAG canvas.
 *
 * Must be called under a `DagCanvasProvider`. React Flow owns the transform, so
 * this delegates to it rather than keeping a parallel scale/offset of its own:
 * the previous `useCanvasPanZoom` wrote pan and zoom into `builderStore`, which
 * nothing applied to the DOM after the React Flow migration, and looked up
 * cards by `[data-node-id]` when React Flow renders `data-id` — so centring a
 * node, fitting the graph and the HUD's zoom buttons were all silent no-ops.
 */
export function useCanvasViewport(): CanvasViewport {
  const flow = useReactFlow();

  const centerOnNode = useCallback(
    (id: string, offsetX = 0) => {
      const node = flow.getNode(id);
      if (!node) return;
      const { x, y } = node.position;
      const width = node.measured?.width ?? 0;
      const height = node.measured?.height ?? 0;
      // `offsetX` shifts the node away from an opening drawer. It is in screen
      // pixels, so it has to be divided back out by the current zoom.
      const zoom = flow.getZoom();
      flow.setCenter(x + width / 2 - offsetX / zoom, y + height / 2, {
        zoom,
        duration: PAN_DURATION,
      });
    },
    [flow]
  );

  const fitCanvas = useCallback(() => {
    flow.fitView({ padding: FIT_PADDING, maxZoom: FIT_MAX_ZOOM, duration: PAN_DURATION });
  }, [flow]);

  const zoomIn = useCallback(() => flow.zoomIn({ duration: PAN_DURATION }), [flow]);
  const zoomOut = useCallback(() => flow.zoomOut({ duration: PAN_DURATION }), [flow]);

  return { centerOnNode, fitCanvas, zoomIn, zoomOut };
}
