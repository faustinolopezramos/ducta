import { useLayoutEffect, useRef, type RefObject } from "react";

const escapeId = (id: string) => id.replace(/["\\]/g, "\\$&");

/**
 * R's confirmation, beside the node it would run: R alone used to run the
 * selected node at once. Enter runs (the Run button has focus), Escape or a
 * click elsewhere cancels. Production keeps its typed confirmation instead;
 * the panel's Run node button runs directly — it is already a deliberate act.
 */
export function RunNodeConfirm({
  nodeId,
  nodeName,
  env,
  container,
  onRun,
  onCancel,
}: {
  nodeId: string;
  nodeName: string;
  env: string;
  /** The element the box is positioned in (the canvas area). */
  container: RefObject<HTMLElement | null>;
  onRun: () => void;
  onCancel: () => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const runRef = useRef<HTMLButtonElement>(null);

  // Placed under the node's card (or the List row), straight on the element:
  // where it goes is read from the layout, after it renders.
  useLayoutEffect(() => {
    const area = container.current;
    const box = boxRef.current;
    if (!area || !box) return;
    const bounds = area.getBoundingClientRect();
    const card =
      area.querySelector<HTMLElement>(`.react-flow__node[data-id="${escapeId(nodeId)}"]`) ??
      area.querySelector<HTMLElement>(`[data-row-id="${escapeId(nodeId)}"]`);
    const r = card?.getBoundingClientRect();
    box.style.top = `${r ? r.bottom - bounds.top + 8 : 64}px`;
    box.style.left = `${r ? Math.max(8, r.left - bounds.left) : Math.max(8, bounds.width / 2 - 160)}px`;
    box.style.visibility = "visible";
    runRef.current?.focus();
  }, [container, nodeId]);

  useLayoutEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) onCancel();
    };
    // Captured so the page's own Escape (deselect) does not also fire.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      onCancel();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [onCancel]);

  return (
    <div
      ref={boxRef}
      className="run-node-confirm"
      role="dialog"
      aria-label={`Run ${nodeName} in ${env}?`}
      style={{ visibility: "hidden" }}
    >
      <p>
        Run <strong>{nodeName}</strong> in <span className="run-node-confirm__env">{env}</span>? It reads its
        inputs as they are now.
      </p>
      <div className="run-node-confirm__actions">
        <button type="button" className="run-node-confirm__cancel" onClick={onCancel}>
          Cancel <kbd>Esc</kbd>
        </button>
        <button ref={runRef} type="button" className="run-node-confirm__run" onClick={onRun}>
          Run node <kbd>⏎</kbd>
        </button>
      </div>
    </div>
  );
}
