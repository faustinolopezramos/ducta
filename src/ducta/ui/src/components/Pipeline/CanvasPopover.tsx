import { useEffect, useId, useRef, useState, type ReactNode } from "react";

/**
 * A toolbar button that opens a small panel of controls (radios, checkboxes)
 * — the shared Menu is a list of actions, which these are not. Escape and a
 * click outside close it, and focus returns to the button.
 */
export function CanvasPopover({
  label,
  ariaLabel,
  title,
  children,
  align = "start",
}: {
  label: ReactNode;
  ariaLabel: string;
  title?: string;
  children: ReactNode;
  align?: "start" | "end";
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    // Escape closes it from anywhere inside; captured so the page's own
    // Escape (deselect) does not also fire.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || !rootRef.current?.contains(document.activeElement)) return;
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      buttonRef.current?.focus();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    rootRef.current?.querySelector<HTMLElement>(".canvas-popover__panel input, .canvas-popover__panel button")?.focus();
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  return (
    <div className="canvas-popover" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className="canvas-text-btn canvas-popover__trigger"
        aria-label={ariaLabel}
        title={title}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((v) => !v)}
      >
        {label}
        <span aria-hidden="true" className="canvas-popover__caret">▾</span>
      </button>
      {open && (
        <div
          id={id}
          className={`canvas-popover__panel canvas-popover__panel--${align}`}
          role="dialog"
          aria-label={ariaLabel}
        >
          {children}
        </div>
      )}
    </div>
  );
}
