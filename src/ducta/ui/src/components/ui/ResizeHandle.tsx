import { useRef, useState } from "react";

interface ResizeHandleProps {
  /** "vertical" sits between columns (drag left/right); "horizontal" between rows. */
  orientation: "vertical" | "horizontal";
  /** The size, in px, of the panel this handle resizes. */
  value: number;
  min: number;
  max: number;
  onChange: (px: number) => void;
  /** Accessible name, e.g. "Resize inspector". */
  label: string;
  /**
   * The panel is after the handle (right of it, or below): dragging toward it
   * shrinks it. False for a panel before the handle (left, or above).
   */
  panelAfter?: boolean;
  /** Double-click restores this size. */
  defaultValue?: number;
}

const STEP = 16;

/**
 * A separator that resizes the panel beside it — by pointer, or by keyboard
 * (arrows, Home/End), as a WAI-ARIA window splitter.
 */
export function ResizeHandle({
  orientation,
  value,
  min,
  max,
  onChange,
  label,
  panelAfter = false,
  defaultValue,
}: ResizeHandleProps) {
  const [dragging, setDragging] = useState(false);
  const start = useRef<{ pos: number; size: number } | null>(null);
  const clamp = (px: number) => Math.max(min, Math.min(max, Math.round(px)));
  const sign = panelAfter ? -1 : 1;

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture?.(e.pointerId);
    start.current = { pos: orientation === "vertical" ? e.clientX : e.clientY, size: value };
    setDragging(true);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    const pos = orientation === "vertical" ? e.clientX : e.clientY;
    onChange(clamp(start.current.size + sign * (pos - start.current.pos)));
  };
  const end = () => {
    start.current = null;
    setDragging(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const grow = orientation === "vertical" ? (panelAfter ? "ArrowLeft" : "ArrowRight") : panelAfter ? "ArrowUp" : "ArrowDown";
    const shrink = orientation === "vertical" ? (panelAfter ? "ArrowRight" : "ArrowLeft") : panelAfter ? "ArrowDown" : "ArrowUp";
    let next: number | null = null;
    if (e.key === grow) next = value + STEP;
    else if (e.key === shrink) next = value - STEP;
    else if (e.key === "Home") next = min;
    else if (e.key === "End") next = max;
    if (next != null) {
      e.preventDefault();
      onChange(clamp(next));
    }
  };

  return (
    // A focusable separator with a value is the WAI-ARIA window splitter — an
    // interactive widget, though jsx-a11y lists `separator` as non-interactive.
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="separator"
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      aria-label={label}
      aria-orientation={orientation}
      aria-valuenow={value}
      aria-valuemin={min}
      aria-valuemax={max}
      className={`split-handle${dragging ? " is-dragging" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onKeyDown={onKeyDown}
      onDoubleClick={defaultValue != null ? () => onChange(clamp(defaultValue)) : undefined}
      data-no-pan
    />
  );
}
