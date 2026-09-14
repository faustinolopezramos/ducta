import type React from "react";
import {
  IconArrowBackUp,
  IconArrowForwardUp,
  IconPlus,
  IconZoomIn,
  IconZoomOut,
  IconMaximize,
  IconPlayerPlay,
  IconPlayerStop,
  IconCheck,
  IconSitemap,
  IconDatabase,
  IconCode,
  IconSearch,
} from "@tabler/icons-react";
import { useBuilderStore } from "../../store/builderStore";
import { useSourceStore } from "../../store/workspace";
import { useEnvironments } from "../../api/queries";

/** The three ways to look at a pipeline. */
export type PipelineViewMode = "flow" | "data" | "config";

interface HUDToolbarProps {
  viewMode: PipelineViewMode;
  onViewModeChange: (mode: PipelineViewMode) => void;
  pipelineType: string;
  onPipelineTypeChange: (type: string) => void;
  hasNodes: boolean;
  isExecuting: boolean;
  onExecute: () => void;
  onCancel: () => void;
  onValidate: () => void;
  onAddNode: () => void;
  onFind: () => void;
  /** Canvas viewport, handed up by DagCanvas. Absent in the Config view. */
  onZoomIn?: () => void;
  onZoomOut?: () => void;
  onFitView?: () => void;
}

const PIPELINE_TYPES = ["batch", "streaming", "ml", "hybrid"] as const;

const VIEWS: Array<{ id: PipelineViewMode; label: string; icon: React.ComponentType<any>; hint: string }> = [
  { id: "flow", label: "Flow", icon: IconSitemap, hint: "Nodes, with each dataset on the edge it flows across" },
  { id: "data", label: "Data", icon: IconDatabase, hint: "Datasets as the graph — lineage, across pipelines" },
  { id: "config", label: "Config", icon: IconCode, hint: "The pipeline's YAML specification" },
];

export function HUDToolbar({
  viewMode,
  onViewModeChange,
  pipelineType,
  onPipelineTypeChange,
  hasNodes,
  isExecuting,
  onExecute,
  onCancel,
  onValidate,
  onAddNode,
  onFind,
  onZoomIn,
  onZoomOut,
  onFitView,
}: HUDToolbarProps) {
  const canUndo = useBuilderStore((s) => s.historyIndex > 0);
  const canRedo = useBuilderStore((s) => s.historyIndex < s.history.length - 1);
  const undo = useBuilderStore((s) => s.undo);
  const redo = useBuilderStore((s) => s.redo);

  const activeEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const setActiveEnv = useSourceStore((s) => s.setActiveEnv);
  const { data: envsData } = useEnvironments();
  const envList: string[] = envsData?.environments ?? [];
  const availableEnvs = envList.length ? envList : [activeEnv];

  // The zoom controls act on React Flow's own viewport, passed up from the
  // canvas. They used to call into `builderStore`, which nothing applied to the
  // DOM after the React Flow migration — so all three buttons did nothing.
  const canZoom = Boolean(onZoomIn && onZoomOut && onFitView);

  return (
    <div className="hud-toolbar" data-no-pan>
      <div className="hud-section" role="tablist" aria-label="Pipeline view">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            className={`hud-tab ${viewMode === v.id ? "active" : ""}`}
            onClick={() => onViewModeChange(v.id)}
            role="tab"
            aria-selected={viewMode === v.id}
            title={v.hint}
          >
            <v.icon size={14} stroke={1.5} />
            <span>{v.label}</span>
          </button>
        ))}
      </div>

      <div className="hud-divider" />

      <div className="hud-section">
        <div className="hud-type-pills" role="group" aria-label="Pipeline type">
          {PIPELINE_TYPES.map((type) => (
            <button
              key={type}
              className={`hud-pill ${pipelineType === type ? "active" : ""}`}
              onClick={() => onPipelineTypeChange(type)}
              aria-pressed={pipelineType === type}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      <div className="hud-divider" />

      <div className="hud-section">
        <select
          className="hud-env-select"
          value={activeEnv}
          onChange={(e) => setActiveEnv(e.target.value)}
          disabled={isExecuting}
          aria-label="Environment to run in"
          title="Environment to run in"
        >
          {availableEnvs.map((e) => (
            <option key={e} value={e}>{e}</option>
          ))}
        </select>
        {isExecuting ? (
          <button className="hud-btn hud-btn-danger" onClick={onCancel} title="Cancel execution">
            <IconPlayerStop size={15} stroke={1.5} />
            <span>Stop</span>
          </button>
        ) : (
          <>
            <button className="hud-btn hud-btn-primary" onClick={onExecute} disabled={!hasNodes} title={`Run pipeline (${activeEnv})`}>
              <IconPlayerPlay size={15} stroke={1.5} />
              <span>Run</span>
            </button>
            <button className="hud-btn" onClick={onValidate} disabled={!hasNodes} title="Validate pipeline">
              <IconCheck size={15} stroke={1.5} />
              <span>Validate</span>
            </button>
          </>
        )}
      </div>

      <div className="hud-divider" />

      <div className="hud-section">
        <button className="hud-btn hud-icon-btn" onClick={undo} disabled={!canUndo} title="Undo (Ctrl+Z)" aria-label="Undo">
          <IconArrowBackUp size={16} stroke={1.5} />
        </button>
        <button className="hud-btn hud-icon-btn" onClick={redo} disabled={!canRedo} title="Redo (Ctrl+Shift+Z)" aria-label="Redo">
          <IconArrowForwardUp size={16} stroke={1.5} />
        </button>
      </div>

      {canZoom && (
        <div className="hud-section">
          <button className="hud-btn hud-icon-btn" onClick={onZoomOut} title="Zoom out" aria-label="Zoom out">
            <IconZoomOut size={16} stroke={1.5} />
          </button>
          <button className="hud-btn hud-icon-btn" onClick={onZoomIn} title="Zoom in" aria-label="Zoom in">
            <IconZoomIn size={16} stroke={1.5} />
          </button>
          <button className="hud-btn hud-icon-btn" onClick={onFitView} title="Fit graph (F)" aria-label="Fit graph">
            <IconMaximize size={15} stroke={1.5} />
          </button>
        </div>
      )}

      <div className="hud-divider" />

      <div className="hud-section">
        <button className="hud-btn hud-icon-btn" onClick={onFind} title="Find node or pipeline (Ctrl/⌘+K)" aria-label="Find node or pipeline">
          <IconSearch size={15} stroke={1.5} />
        </button>
      </div>

      <div className="hud-divider" />

      <div className="hud-section">
        <button className="hud-btn hud-btn-add" onClick={onAddNode} title="Add node">
          <IconPlus size={16} stroke={2} />
          <span>Add Node</span>
        </button>
      </div>
    </div>
  );
}
