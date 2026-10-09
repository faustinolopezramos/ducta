import { useCallback, useMemo, useRef } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useUIStore, type PipelineLens, type PipelineOrientation } from "../../store/uiStore";
import type { CanvasSelection } from "../../components/Pipeline/types";
import type { PipelineScope } from "../../components/Pipeline/HUDToolbar";
import type { CanvasViewport } from "../../components/Pipeline/useCanvasViewport";
import { routes } from "../../utils/routes";

const LENSES: readonly PipelineLens[] = ["flow", "list", "yaml"];

/** `?lens=` — `config` was the YAML view's old name, so old links keep working. */
function parseLens(value: string | null): PipelineLens | null {
  if (value === "config") return "yaml";
  return value && (LENSES as readonly string[]).includes(value) ? (value as PipelineLens) : null;
}

function parseOrientation(value: string | null): PipelineOrientation | null {
  return value === "vertical" || value === "horizontal" ? value : null;
}

/** `?focus=node:<id>` or `?focus=dataset:<name>` — a selection anyone can link to. */
function parseFocus(value: string | null): CanvasSelection {
  if (!value) return null;
  const sep = value.indexOf(":");
  if (sep <= 0) return null;
  const kind = value.slice(0, sep);
  const id = value.slice(sep + 1);
  if (!id || (kind !== "node" && kind !== "dataset")) return null;
  return { kind, id };
}

function focusParam(selection: CanvasSelection): string | null {
  return selection ? `${selection.kind}:${selection.id}` : null;
}

/**
 * How the pipeline is being looked at: lens, orientation, scope, focused
 * object, and the canvas viewport.
 *
 * The lens, the scope and the focus live in the URL, so a link or a reload
 * lands exactly where the user was. The orientation is a personal preference
 * instead; `?orient=` only overrides it for one link.
 */
export function usePipelineView(projectId: string | undefined) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const preferredLens = useUIStore((s) => s.pipelineLens);
  const setPreferredLens = useUIStore((s) => s.setPipelineLens);
  const preferredOrientation = useUIStore((s) => s.pipelineOrientation);
  const setPreferredOrientation = useUIStore((s) => s.setPipelineOrientation);

  const updateParams = useCallback(
    (changes: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          for (const [key, value] of Object.entries(changes)) {
            if (value == null) next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        // Changing how you look at a pipeline is not a step worth a Back press.
        { replace: true }
      );
    },
    [setSearchParams]
  );

  const lens: PipelineLens = parseLens(searchParams.get("lens")) ?? preferredLens;
  const orientation: PipelineOrientation =
    parseOrientation(searchParams.get("orient")) ?? preferredOrientation;

  const setLens = useCallback(
    (next: PipelineLens) => {
      setPreferredLens(next);
      updateParams({ lens: next });
    },
    [setPreferredLens, updateParams]
  );

  const setOrientation = useCallback(
    (next: PipelineOrientation) => {
      setPreferredOrientation(next);
      updateParams({ orient: null });
    },
    [setPreferredOrientation, updateParams]
  );

  const toggleOrientation = useCallback(
    () => setOrientation(orientation === "vertical" ? "horizontal" : "vertical"),
    [orientation, setOrientation]
  );

  /** The scope asked for; the chain is the default, so only the exception is written down. */
  const requestedScope: PipelineScope = searchParams.get("scope") === "pipeline" ? "pipeline" : "chain";
  const setScope = useCallback(
    (next: PipelineScope) => updateParams({ scope: next === "chain" ? null : "pipeline" }),
    [updateParams]
  );

  const rawFocus = searchParams.get("focus");
  const selection = useMemo(() => parseFocus(rawFocus), [rawFocus]);
  const setSelection = useCallback(
    (next: CanvasSelection) => updateParams({ focus: focusParam(next) }),
    [updateParams]
  );
  const selectedNodeId = selection?.kind === "node" ? selection.id : null;
  const selectedDatasetName = selection?.kind === "dataset" ? selection.id : null;

  const clearSelection = useCallback(() => setSelection(null), [setSelection]);
  const selectNodeById = useCallback(
    (id: string | null) => setSelection(id ? { kind: "node", id } : null),
    [setSelection]
  );
  const selectDatasetByName = useCallback(
    (name: string) => setSelection({ kind: "dataset", id: name }),
    [setSelection]
  );

  /**
   * `?panel=code` — the focused node's source beside the canvas. In the URL
   * so "node X, with its code open" is a link like any other view.
   */
  const codeOpen = searchParams.get("panel") === "code" && selectedNodeId != null;
  const openCode = useCallback(
    (id: string) => updateParams({ focus: focusParam({ kind: "node", id }), panel: "code" }),
    [updateParams]
  );
  const closeCode = useCallback(() => updateParams({ panel: null }), [updateParams]);

  /** From the list: look at a node (or dataset) on the canvas, focused. */
  const showOnCanvas = useCallback(
    (id: string) => updateParams({ lens: "flow", focus: focusParam({ kind: "node", id }) }),
    [updateParams]
  );
  const focusDatasetOnCanvas = useCallback(
    (name: string) => updateParams({ lens: "flow", focus: focusParam({ kind: "dataset", id: name }) }),
    [updateParams]
  );

  /** Open another pipeline, optionally with something already in focus there. */
  const openPipeline = useCallback(
    (name: string, focus?: CanvasSelection) => {
      const params = new URLSearchParams();
      const value = focusParam(focus ?? null);
      if (value) params.set("focus", value);
      const query = params.toString();
      navigate(`${routes.pipeline(projectId ?? "", name)}${query ? `?${query}` : ""}`);
    },
    [navigate, projectId]
  );

  /**
   * Viewport controls, handed up by the canvas once React Flow has mounted.
   * Kept in a ref so the toolbar and the keyboard shortcuts share one instance
   * without re-rendering the page each time the canvas re-registers.
   */
  const viewportRef = useRef<CanvasViewport | null>(null);
  const onViewportReady = useCallback((v: CanvasViewport) => {
    viewportRef.current = v;
  }, []);
  const centerOnNode = useCallback((id: string, offsetX?: number, offsetY?: number) => {
    viewportRef.current?.centerOnNode(id, offsetX, offsetY);
  }, []);
  const fitCanvas = useCallback(() => viewportRef.current?.fitCanvas(), []);
  const zoomIn = useCallback(() => viewportRef.current?.zoomIn(), []);
  const zoomOut = useCallback(() => viewportRef.current?.zoomOut(), []);

  return {
    navigate,
    lens, setLens, orientation, setOrientation, toggleOrientation,
    requestedScope, setScope,
    selection, setSelection, selectedNodeId, selectedDatasetName,
    selectNodeById, selectDatasetByName, clearSelection,
    showOnCanvas, focusDatasetOnCanvas, openPipeline,
    codeOpen, openCode, closeCode,
    onViewportReady, centerOnNode, fitCanvas, zoomIn, zoomOut,
  };
}
