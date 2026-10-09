import type React from "react";
import {
  IconArrowBackUp,
  IconArrowDown,
  IconArrowForwardUp,
  IconArrowRight,
  IconCode,
  IconLayoutList,
  IconMap,
  IconMaximize,
  IconPlus,
  IconSearch,
  IconSitemap,
  IconZoomIn,
  IconZoomOut,
} from "@tabler/icons-react";
import { useBuilderStore } from "../../store/builderStore";
import type { PipelineLens, PipelineOrientation } from "../../store/uiStore";

export type { PipelineLens, PipelineOrientation } from "../../store/uiStore";

/** A pipeline alone, or drawn with the upstream pipelines its run executes first. */
export type PipelineScope = "pipeline" | "chain";

interface HUDToolbarProps {
  lens: PipelineLens;
  onLensChange: (lens: PipelineLens) => void;
  orientation: PipelineOrientation;
  onOrientationChange: (orientation: PipelineOrientation) => void;
  scope?: PipelineScope;
  /** Absent when the pipeline has no upstream pipelines to show. */
  onScopeChange?: (scope: PipelineScope) => void;
  onAddNode: () => void;
  onFind: () => void;
  /** Canvas viewport, handed up by DagCanvas. Absent outside the Flow lens. */
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onFitView?: () => void;
  showMinimap?: boolean;
  /** Absent where the current lens has no minimap to toggle. */
  onToggleMinimap?: () => void;
  /** Undo/redo of the page's edits; without it, the builder's own history. */
  history?: { canUndo: boolean; canRedo: boolean; undo: () => void; redo: () => void };
}

const LENSES: Array<{ id: PipelineLens; label: string; icon: React.ComponentType<any>; hint: string }> = [
  { id: "flow", label: "Flow", icon: IconSitemap, hint: "The canvas: nodes, with each dataset on the edge it flows across" },
  { id: "list", label: "List", icon: IconLayoutList, hint: "Every node as a row: what it reads and writes, its checks and last run" },
  { id: "yaml", label: "YAML", icon: IconCode, hint: "The pipeline's YAML specification" },
];

/**
 * The controls that sit on the workspace itself, one cluster per corner so none
 * of them covers the graph: how you are looking top-left, editing top-right,
 * the viewport bottom-left. Running and the environment live in PipelineTopBar.
 *
 * The three lenses are three ways to work on the same pipeline; switching keeps
 * the selection, so a node picked in the list is the node focused on the canvas.
 */
export function HUDToolbar({
  lens,
  onLensChange,
  orientation,
  onOrientationChange,
  scope = "pipeline",
  onScopeChange,
  onAddNode,
  onFind,
  onZoomIn,
  onZoomOut,
  onFitView,
  showMinimap = false,
  onToggleMinimap,
  history,
}: HUDToolbarProps) {
  const builderCanUndo = useBuilderStore((s) => s.historyIndex > 0);
  const builderCanRedo = useBuilderStore((s) => s.historyIndex < s.history.length - 1);
  const builderUndo = useBuilderStore((s) => s.undo);
  const builderRedo = useBuilderStore((s) => s.redo);
  // The page's own history (edits to the pipeline file) when it gives one.
  const canUndo = history ? history.canUndo : builderCanUndo;
  const canRedo = history ? history.canRedo : builderCanRedo;
  const undo = history ? history.undo : builderUndo;
  const redo = history ? history.redo : builderRedo;

  // The zoom controls act on React Flow's own viewport, passed up from the
  // canvas. They used to call into `builderStore`, which nothing applied to the
  // DOM after the React Flow migration — so all three buttons did nothing.
  const canZoom = Boolean(onZoomIn && onZoomOut && onFitView);

  return (
    <>
      <div className="canvas-controls canvas-controls--top-left" data-no-pan>
        <div className="canvas-segmented" role="tablist" aria-label="Pipeline lens">
          {LENSES.map((v) => (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={lens === v.id}
              aria-label={v.label}
              title={v.hint}
              className={`canvas-segment${lens === v.id ? " active" : ""}`}
              onClick={() => onLensChange(v.id)}
            >
              <v.icon size={15} stroke={1.75} aria-hidden="true" />
              <span>{v.label}</span>
            </button>
          ))}
        </div>

        {lens !== "yaml" && onScopeChange && (
          <>
            <span className="canvas-controls-sep" aria-hidden="true" />
            <div className="canvas-segmented" role="group" aria-label="What to draw">
              <button
                type="button"
                className={`canvas-segment${scope === "pipeline" ? " active" : ""}`}
                aria-pressed={scope === "pipeline"}
                title="Only this pipeline's nodes"
                onClick={() => onScopeChange("pipeline")}
              >
                <span className="canvas-segment__keep">Pipeline</span>
              </button>
              <button
                type="button"
                className={`canvas-segment${scope === "chain" ? " active" : ""}`}
                aria-pressed={scope === "chain"}
                title="With the upstream pipelines a run executes first, one band each"
                onClick={() => onScopeChange("chain")}
              >
                <span className="canvas-segment__keep">Chain</span>
              </button>
            </div>
          </>
        )}

        {lens === "flow" && (
          <>
            <span className="canvas-controls-sep" aria-hidden="true" />
            <div className="canvas-segmented" role="group" aria-label="Layer direction">
              <button
                type="button"
                className="canvas-icon-btn"
                aria-pressed={orientation === "vertical"}
                aria-label="Layers top to bottom"
                title="Layers top to bottom (O)"
                onClick={() => onOrientationChange("vertical")}
              >
                <IconArrowDown size={16} stroke={1.75} />
              </button>
              <button
                type="button"
                className="canvas-icon-btn"
                aria-pressed={orientation === "horizontal"}
                aria-label="Layers left to right"
                title="Layers left to right (O)"
                onClick={() => onOrientationChange("horizontal")}
              >
                <IconArrowRight size={16} stroke={1.75} />
              </button>
            </div>
          </>
        )}
      </div>

      {lens !== "yaml" && (
        <div className="canvas-controls canvas-controls--top-right" data-no-pan>
          <button type="button" className="canvas-icon-btn" onClick={undo} disabled={!canUndo} title="Undo (Ctrl+Z)" aria-label="Undo">
            <IconArrowBackUp size={16} stroke={1.75} />
          </button>
          <button type="button" className="canvas-icon-btn" onClick={redo} disabled={!canRedo} title="Redo (Ctrl+Shift+Z)" aria-label="Redo">
            <IconArrowForwardUp size={16} stroke={1.75} />
          </button>
          <span className="canvas-controls-sep" aria-hidden="true" />
          <button type="button" className="canvas-icon-btn" onClick={onFind} title="Find node or pipeline (Ctrl/⌘+K)" aria-label="Find node or pipeline">
            <IconSearch size={16} stroke={1.75} />
          </button>
          <button type="button" className="canvas-text-btn" onClick={onAddNode} aria-label="Add node">
            <IconPlus size={15} stroke={2} aria-hidden="true" />
            <span>Add node</span>
          </button>
        </div>
      )}

      {canZoom && (
        <div className="canvas-controls canvas-controls--bottom-left" role="group" aria-label="Canvas viewport" data-no-pan>
          <button type="button" className="canvas-icon-btn" onClick={onZoomOut} title="Zoom out" aria-label="Zoom out">
            <IconZoomOut size={16} stroke={1.75} />
          </button>
          <button type="button" className="canvas-icon-btn" onClick={onZoomIn} title="Zoom in" aria-label="Zoom in">
            <IconZoomIn size={16} stroke={1.75} />
          </button>
          <button type="button" className="canvas-icon-btn" onClick={onFitView} title="Fit graph (F)" aria-label="Fit graph">
            <IconMaximize size={15} stroke={1.75} />
          </button>
          {onToggleMinimap && (
            <>
              <span className="canvas-controls-sep" aria-hidden="true" />
              <button
                type="button"
                className="canvas-icon-btn"
                onClick={onToggleMinimap}
                aria-pressed={showMinimap}
                title={showMinimap ? "Hide minimap" : "Show minimap"}
                aria-label="Minimap"
              >
                <IconMap size={16} stroke={1.75} />
              </button>
            </>
          )}
        </div>
      )}
    </>
  );
}
