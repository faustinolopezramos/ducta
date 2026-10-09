import { useEffect, useState } from "react";
import { useBlocker } from "react-router-dom";
import { useBuilderStore } from "../../store/builderStore";

/**
 * The pipeline page's open popovers (add node, command palette) — and the guard
 * against leaving with unsaved canvas edits. Edits themselves are
 * `useCanvasEditing`'s; a node's code opens in the code pane (`?panel=code`).
 */
export function usePipelineEditing() {
  const [addNodeOpen, setAddNodeOpen] = useState(false);

  // ── Unsaved canvas edits ──────────────────────────────────────────────────
  // Rendered as a <ConfirmDialog> by the consuming page (PipelinePage) rather
  // than window.confirm() here — a hook has no JSX of its own to render one,
  // and window.confirm can't be styled and blocks the whole tab. Only leaving
  // the pipeline is blocked: switching lens or focus rewrites the query string,
  // and asking "leave without saving?" for that would fire on every click.
  const isDirty = useBuilderStore((s) => s.isDirty);
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      isDirty && currentLocation.pathname !== nextLocation.pathname
  );
  useEffect(() => {
    if (!isDirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  return {
    addNodeOpen, setAddNodeOpen,
    blocker,
  };
}
