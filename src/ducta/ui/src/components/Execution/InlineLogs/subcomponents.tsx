import { useRef } from "react";

// ── ResizeHandle: draggable divider ────────────────────────────────────────────

export function ResizeHandle({ onResize }: { onResize: (delta: number) => void }) {
  const dragging = useRef(false);
  const startY = useRef(0);

  const onMouseDown = (e: React.MouseEvent) => {
    dragging.current = true;
    startY.current = e.clientY;
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      onResize(startY.current - ev.clientY);
      startY.current = ev.clientY;
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return (
    <button
      type="button"
      className="ilog__resize-handle"
      aria-label="Resize log panel"
      onMouseDown={onMouseDown}
      onKeyDown={(e) => {
        // Dragging is mouse-only otherwise; the arrows give the same control
        // in 16px steps.
        if (e.key === "ArrowUp") {
          e.preventDefault();
          onResize(16);
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          onResize(-16);
        }
      }}
    >
      <div className="ilog__resize-handle-bar" />
    </button>
  );
}
