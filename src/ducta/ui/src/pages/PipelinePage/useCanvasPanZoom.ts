import { useRef, useCallback, useEffect } from "react";
import { useBuilderStore } from "../../store/builderStore";

/**
 * Wheel-zoom + drag-to-pan for the DAG canvas, plus a `centerOnNode` helper
 * used by keyboard navigation. `onEmptyCanvasClick` fires when a pan gesture
 * never actually moved the mouse — i.e. a plain click on empty canvas space —
 * so the caller can clear node selection.
 */
export function useCanvasPanZoom(onEmptyCanvasClick: () => void) {
  const flowRef = useRef<HTMLDivElement>(null);
  const isPanning = useRef(false);
  const lastPanPos = useRef({ x: 0, y: 0 });
  const panRaf = useRef<number | null>(null);
  const panMoved = useRef(false);

  const viewportScale = useBuilderStore((s) => s.viewportScale);
  const viewportX = useBuilderStore((s) => s.viewportX);
  const viewportY = useBuilderStore((s) => s.viewportY);
  const setViewport = useBuilderStore((s) => s.setViewport);
  const resetViewport = useBuilderStore((s) => s.resetViewport);

  // Keep the latest callback without making the pan/zoom effect re-run when
  // the caller passes a fresh inline function each render.
  const onEmptyCanvasClickRef = useRef(onEmptyCanvasClick);
  onEmptyCanvasClickRef.current = onEmptyCanvasClick;

  // Pan the viewport so the given node lands in the middle of the canvas
  // (with an optional horizontal offset to accommodate opening sidebar drawers).
  const centerOnNode = useCallback((id: string, offsetX: number = 0) => {
    const flow = flowRef.current;
    const el = flow?.querySelector(`[data-node-id="${CSS.escape(id)}"]`) as HTMLElement | null;
    if (!flow || !el) return;
    const { viewportScale: s, viewportX: vx, viewportY: vy } = useBuilderStore.getState();
    const flowRect = flow.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    const cx = (r.left + r.width / 2 - flowRect.left - vx) / s;
    const cy = (r.top + r.height / 2 - flowRect.top - vy) / s;
    setViewport(s, (flowRect.width / 2 + offsetX) - cx * s, flowRect.height / 2 - cy * s);
  }, [setViewport]);

  useEffect(() => {
    const el = flowRef.current;
    if (!el) return;

    const onWheel = (e: WheelEvent) => {
      if (!el.contains(e.target as Node)) return;
      const rect = el.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const delta = -e.deltaY * 0.001;
      const s = viewportScale;
      const newScale = Math.min(3, Math.max(0.25, s * (1 + delta)));
      const ratio = newScale / s;
      setViewport(newScale, mouseX - (mouseX - viewportX) * ratio, mouseY - (mouseY - viewportY) * ratio);
    };

    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 1 && e.button !== 0) return;
      const target = e.target as HTMLElement;
      if (target.closest("[data-no-pan], .node-card, .dag-edges-overlay, [role=button], button, input, textarea, select")) return;
      isPanning.current = true;
      panMoved.current = false;
      lastPanPos.current = { x: e.clientX, y: e.clientY };
      el.style.cursor = "grabbing";
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!isPanning.current) return;
      const dx = e.clientX - lastPanPos.current.x;
      const dy = e.clientY - lastPanPos.current.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) panMoved.current = true;
      lastPanPos.current = { x: e.clientX, y: e.clientY };
      if (panRaf.current) cancelAnimationFrame(panRaf.current);
      panRaf.current = requestAnimationFrame(() => setViewport(viewportScale, viewportX + dx, viewportY + dy));
    };

    const onMouseUp = () => {
      // A pan that never moved is a plain click on empty canvas: clear the selection.
      if (isPanning.current && !panMoved.current) onEmptyCanvasClickRef.current();
      isPanning.current = false;
      el.style.cursor = "";
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      if (panRaf.current) cancelAnimationFrame(panRaf.current);
    };
  }, [viewportScale, viewportX, viewportY, setViewport]);

  return { flowRef, centerOnNode, resetViewport };
}
