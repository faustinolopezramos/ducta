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
  IconCode,
  IconActivity,
  IconSearch,
  IconCalendarClock,
} from "@tabler/icons-react";
import { useBuilderStore } from "../../store/builderStore";
import { Button } from "../ui/Button";

interface HUDToolbarProps {
  viewMode: "flow" | "yaml" | "streaming";
  onViewModeChange: (mode: "flow" | "yaml" | "streaming") => void;
  pipelineType: string;
  onPipelineTypeChange: (type: string) => void;
  hasNodes: boolean;
  isExecuting: boolean;
  onExecute: () => void;
  onCancel: () => void;
  onValidate: () => void;
  onAddNode: () => void;
  onFind: () => void;
}

const PIPELINE_TYPES = ["batch", "streaming", "ml", "hybrid"] as const;

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
}: HUDToolbarProps) {
  const canUndo = useBuilderStore((s) => s.historyIndex > 0);
  const canRedo = useBuilderStore((s) => s.historyIndex < s.history.length - 1);
  const undo = useBuilderStore((s) => s.undo);
  const redo = useBuilderStore((s) => s.redo);
  const zoomIn = useBuilderStore((s) => s.zoomIn);
  const zoomOut = useBuilderStore((s) => s.zoomOut);
  const resetViewport = useBuilderStore((s) => s.resetViewport);

  const views = [
    { id: "flow" as const, label: "Diagram", icon: IconSitemap },
    { id: "yaml" as const, label: "Config", icon: IconCode },
    { id: "streaming" as const, label: "Monitor", icon: IconActivity },
  ];

  return (
    <div className="hud-toolbar" data-no-pan>
      <div className="hud-section" role="tablist" aria-label="Pipeline view">
        {views.map((v) => (
          <button
            key={v.id}
            className={`hud-tab ${viewMode === v.id ? "active" : ""}`}
            onClick={() => onViewModeChange(v.id)}
            role="tab"
            aria-selected={viewMode === v.id}
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
        {isExecuting ? (
          <button className="hud-btn hud-btn-danger" onClick={onCancel} title="Cancel execution">
            <IconPlayerStop size={15} stroke={1.5} />
            <span>Stop</span>
          </button>
        ) : (
          <>
            <button className="hud-btn hud-btn-primary" onClick={onExecute} disabled={!hasNodes} title="Run pipeline">
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

      <div className="hud-section">
        <button className="hud-btn hud-icon-btn" onClick={zoomOut} title="Zoom out" aria-label="Zoom out">
          <IconZoomOut size={16} stroke={1.5} />
        </button>
        <span className="hud-zoom-level">{Math.round(useBuilderStore.getState().viewportScale * 100)}%</span>
        <button className="hud-btn hud-icon-btn" onClick={zoomIn} title="Zoom in" aria-label="Zoom in">
          <IconZoomIn size={16} stroke={1.5} />
        </button>
        <button className="hud-btn hud-icon-btn" onClick={resetViewport} title="Reset view" aria-label="Reset view">
          <IconMaximize size={15} stroke={1.5} />
        </button>
      </div>

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
