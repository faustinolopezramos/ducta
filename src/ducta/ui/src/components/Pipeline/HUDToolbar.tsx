import type React from "react";
import {
  IconArrowBackUp,
  IconArrowForwardUp,
  IconArrowsMaximize,
  IconArrowsMinimize,
  IconCode,
  IconLayoutList,
  IconPlus,
  IconSitemap,
  IconZoomIn,
  IconZoomOut,
} from "@tabler/icons-react";
import { useBuilderStore } from "../../store/builderStore";
import { useUIStore, type PipelineLens, type PipelineOrientation } from "../../store/uiStore";
import { CanvasPopover } from "./CanvasPopover";
import { useCanvasZoom } from "./canvasZoom";

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
  /** Namespaces that can collapse into one box, and whether any is collapsed. */
  groups?: { count: number; collapsed: number; onCollapseAll: () => void; onExpandAll: () => void };
  onAddNode: () => void;
  /** The pipeline a new node goes into, named on the button. */
  addNodeTarget?: string;
  /** The canvas search (find and filters), shown in the Flow lens. */
  search?: React.ReactNode;
  /** Canvas viewport, handed up by DagCanvas. Absent outside the Flow lens. */
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onFitView?: () => void;
  onResetZoom?: () => void;
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

export function ZoomReadout({ onReset }: { onReset?: () => void }) {
  const zoom = useCanvasZoom((s) => s.zoom);
  const pct = `${Math.round(zoom * 100)}%`;
  return (
    <button
      type="button"
      className="canvas-text-btn canvas-zoom-readout"
      onClick={onReset}
      aria-label={`Zoom ${pct}, reset to 100%`}
      title="Reset to 100%"
    >
      {pct}
    </button>
  );
}

/**
 * The controls that sit on the workspace itself, one cluster per corner so none
 * of them covers the graph: how you are looking top-left, finding and editing
 * top-right, the viewport bottom-left. Running and the environment live in
 * PipelineTopBar.
 *
 * Top-left holds only the lenses — three ways to work on the same pipeline;
 * switching keeps the selection. How the graph is drawn (what it includes,
 * which way it runs, groups) lives in one View menu that says what is on:
 * drawn as three more segmented controls, "Pipeline / Chain" read as a fourth
 * and fifth lens.
 */
export function HUDToolbar({
  lens,
  onLensChange,
  orientation,
  onOrientationChange,
  scope = "pipeline",
  onScopeChange,
  groups,
  onAddNode,
  addNodeTarget,
  search,
  onZoomIn,
  onZoomOut,
  onFitView,
  onResetZoom,
  showMinimap = false,
  onToggleMinimap,
  history,
}: HUDToolbarProps) {
  const builderCanUndo = useBuilderStore((s) => s.historyIndex > 0);
  const builderCanRedo = useBuilderStore((s) => s.historyIndex < s.history.length - 1);
  const builderUndo = useBuilderStore((s) => s.undo);
  const builderRedo = useBuilderStore((s) => s.redo);
  const canUndo = history ? history.canUndo : builderCanUndo;
  const canRedo = history ? history.canRedo : builderCanRedo;
  const undo = history ? history.undo : builderUndo;
  const redo = history ? history.redo : builderRedo;
  const zenMode = useUIStore((s) => s.zenMode);
  const toggleZenMode = useUIStore((s) => s.toggleZenMode);

  const canZoom = Boolean(onZoomIn && onZoomOut && onFitView);
  const onCanvas = lens === "flow";
  const showGroups = onCanvas && groups && groups.count > 0;
  const grouped = Boolean(groups && groups.collapsed > 0);

  const summary = [
    onScopeChange ? (scope === "chain" ? "with chain" : "this pipeline") : null,
    onCanvas ? (orientation === "vertical" ? "↓" : "→") : null,
    showGroups && grouped ? "grouped" : null,
  ].filter(Boolean);
  const hasView = lens !== "yaml" && (Boolean(onScopeChange) || onCanvas);

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

        {hasView && (
          <CanvasPopover
            label={
              <>
                <span className="canvas-view__name">
                  View<span className="canvas-view__colon">{summary.length > 0 ? ":" : ""}</span>
                </span>
                {summary.length > 0 && <span className="canvas-view__summary">{summary.join(" · ")}</span>}
              </>
            }
            ariaLabel={`View${summary.length ? `: ${summary.join(", ")}` : ""}`}
            title="What the graph includes, which way it runs, groups"
          >
            {onScopeChange && (
              <fieldset className="canvas-popover__group">
                <legend>Show</legend>
                <label>
                  <input type="radio" name="canvas-scope" checked={scope === "pipeline"} onChange={() => onScopeChange("pipeline")} />
                  Only this pipeline
                </label>
                <label>
                  <input type="radio" name="canvas-scope" checked={scope === "chain"} onChange={() => onScopeChange("chain")} />
                  With the upstream chain
                </label>
              </fieldset>
            )}
            {onCanvas && (
              <fieldset className="canvas-popover__group">
                <legend>Direction</legend>
                <label>
                  <input type="radio" name="canvas-direction" checked={orientation === "vertical"} onChange={() => onOrientationChange("vertical")} />
                  Top to bottom
                </label>
                <label>
                  <input type="radio" name="canvas-direction" checked={orientation === "horizontal"} onChange={() => onOrientationChange("horizontal")} />
                  Left to right <kbd className="canvas-popover__key">O</kbd>
                </label>
              </fieldset>
            )}
            {showGroups && (
              <fieldset className="canvas-popover__group">
                <legend>Groups</legend>
                <label>
                  <input
                    type="checkbox"
                    checked={grouped}
                    onChange={() => (grouped ? groups!.onExpandAll() : groups!.onCollapseAll())}
                  />
                  Collapse each namespace ({groups!.count})
                </label>
              </fieldset>
            )}
          </CanvasPopover>
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
          {onCanvas && search && (
            <>
              <span className="canvas-controls-sep" aria-hidden="true" />
              {search}
            </>
          )}
          <span className="canvas-controls-sep" aria-hidden="true" />
          <button
            type="button"
            className="canvas-text-btn"
            onClick={onAddNode}
            aria-label={addNodeTarget ? `Add node to ${addNodeTarget}` : "Add node"}
            title={addNodeTarget ? `Add a node to ${addNodeTarget}` : undefined}
          >
            <IconPlus size={15} stroke={2} aria-hidden="true" />
            <span>{addNodeTarget ? `Add node to ${addNodeTarget}` : "Add node"}</span>
          </button>
        </div>
      )}

      {canZoom && (
        <div className="canvas-controls canvas-controls--bottom-left" role="group" aria-label="Canvas viewport" data-no-pan>
          <button type="button" className="canvas-icon-btn" onClick={onZoomOut} title="Zoom out" aria-label="Zoom out">
            <IconZoomOut size={16} stroke={1.75} />
          </button>
          <ZoomReadout onReset={onResetZoom} />
          <button type="button" className="canvas-icon-btn" onClick={onZoomIn} title="Zoom in" aria-label="Zoom in">
            <IconZoomIn size={16} stroke={1.75} />
          </button>
          <span className="canvas-controls-sep" aria-hidden="true" />
          <button type="button" className="canvas-text-btn" onClick={onFitView} title="Fit the graph (F)" aria-label="Fit graph">
            Fit <kbd className="canvas-popover__key">F</kbd>
          </button>
          {onToggleMinimap && (
            <button
              type="button"
              className="canvas-text-btn"
              onClick={onToggleMinimap}
              aria-pressed={showMinimap}
              title={showMinimap ? "Hide minimap" : "Show minimap"}
              aria-label="Minimap"
            >
              Minimap
            </button>
          )}
          <button
            type="button"
            className="canvas-icon-btn"
            onClick={toggleZenMode}
            aria-pressed={zenMode}
            title={zenMode ? "Exit full screen (⌥Z)" : "Full screen canvas (⌥Z)"}
            aria-label="Full screen canvas"
          >
            {zenMode ? <IconArrowsMinimize size={16} stroke={1.75} /> : <IconArrowsMaximize size={16} stroke={1.75} />}
          </button>
        </div>
      )}
    </>
  );
}
