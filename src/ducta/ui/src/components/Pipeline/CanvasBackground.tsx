import { useRef, useCallback, useEffect, type ReactNode } from "react";
import { useBuilderStore } from "../../store/builderStore";

const MIN_SCALE = 0.25;
const MAX_SCALE = 3;
const GRID_SIZE = 28;

export function CanvasBackground({ children }: { children: ReactNode }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isPanning = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });
  const rafId = useRef<number | null>(null);

  const viewportScale = useBuilderStore((s) => s.viewportScale);
  const viewportX = useBuilderStore((s) => s.viewportX);
  const viewportY = useBuilderStore((s) => s.viewportY);
  const setViewport = useBuilderStore((s) => s.setViewport);

  const applyViewport = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const inner = el.firstElementChild as HTMLElement | null;
    if (!inner) return;
    inner.style.transform = `translate(${viewportX}px, ${viewportY}px) scale(${viewportScale})`;
  }, [viewportX, viewportY, viewportScale]);

  useEffect(() => {
    applyViewport();
  }, [applyViewport]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = container.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const delta = -e.deltaY * 0.001;
      const newScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, viewportScale * (1 + delta)));
      const ratio = newScale / viewportScale;
      setViewport(
        newScale,
        mouseX - (mouseX - viewportX) * ratio,
        mouseY - (mouseY - viewportY) * ratio,
      );
    };

    const onMouseDown = (e: MouseEvent) => {
      if (e.button !== 1 && e.button !== 0) return;
      const target = e.target as HTMLElement;
      if (target.closest("[data-no-pan]")) return;
      if (e.button === 0 && target.closest(".node-card, .dag-edges-overlay, .hud-toolbar, [role=button], button, input, textarea, select")) return;
      isPanning.current = true;
      lastPos.current = { x: e.clientX, y: e.clientY };
      container.style.cursor = "grabbing";
    };

    const onMouseMove = (e: MouseEvent) => {
      if (!isPanning.current) return;
      const dx = e.clientX - lastPos.current.x;
      const dy = e.clientY - lastPos.current.y;
      lastPos.current = { x: e.clientX, y: e.clientY };
      if (rafId.current) cancelAnimationFrame(rafId.current);
      rafId.current = requestAnimationFrame(() => {
        setViewport(viewportScale, viewportX + dx, viewportY + dy);
      });
    };

    const onMouseUp = () => {
      isPanning.current = false;
      if (container) container.style.cursor = "";
    };

    container.addEventListener("wheel", onWheel, { passive: false });
    container.addEventListener("mousedown", onMouseDown);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);

    return () => {
      container.removeEventListener("wheel", onWheel);
      container.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
      if (rafId.current) cancelAnimationFrame(rafId.current);
    };
  }, [viewportScale, viewportX, viewportY, setViewport]);

  return (
    <div
      ref={containerRef}
      className="canvas-background"
      style={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        cursor: "grab",
        backgroundImage: `radial-gradient(circle, var(--border) 1px, transparent 1px)`,
        backgroundSize: `${GRID_SIZE}px ${GRID_SIZE}px`,
        opacity: 0.22,
      }}
    >
      <div
        style={{
          transformOrigin: "0 0",
          width: "100%",
          height: "100%",
          willChange: "transform",
        }}
      >
        {children}
      </div>
    </div>
  );
}
