import type React from "react";
import type { ComponentProps } from "react";
import { ResizeHandle } from "../../components/ui/ResizeHandle";
import { ProblemsPanel } from "../../components/Problems/ProblemsPanel";
import { SamplePreview } from "../../components/Pipeline/SamplePreview";
import { StreamingStatusPanel } from "../../components/Execution/StreamingStatusPanel";
import { InlineLogs } from "../../components/Execution/InlineLogs";
import type { Problem } from "../../api/queries/problems";
import type { DagCanvasItem } from "../../components/Pipeline/types";
import type { BottomPanelTab } from "../../store/uiStore";
import type { StreamSummary } from "../../utils/streaming";

const DOCK = { min: 120, max: 640, initial: 260 };

export interface PipelineDockProps {
  height: number;
  onHeightChange: (h: number) => void;
  onClose: () => void;
  tab: BottomPanelTab;
  onTabChange: (tab: BottomPanelTab) => void;
  counts: { errors: number; warnings: number };
  sample?: { node: string; execId: string | null; rows: number } | null;
  projectId?: string;
  itemById: Map<string, DagCanvasItem>;
  activeEnv: string;
  problems: Problem[];
  isChecking: boolean;
  onOpenProblem: (p: Problem) => void;
  onFixProblem: (p: Problem) => void;
  fixWithAI: React.ReactNode;
  activeExecutionId?: string | null;
  isExecuting: boolean;
  pipelineNodes: NonNullable<ComponentProps<typeof InlineLogs>["nodes"]>;
  executionStates: Record<string, string>;
  isStreamPipeline?: boolean;
  streamSummary?: StreamSummary | null;
}

export function PipelineDock({
  height,
  onHeightChange,
  onClose,
  tab,
  onTabChange,
  counts,
  sample,
  projectId,
  itemById,
  activeEnv,
  problems,
  isChecking,
  onOpenProblem,
  onFixProblem,
  fixWithAI,
  activeExecutionId,
  isExecuting,
  pipelineNodes,
  executionStates,
  isStreamPipeline = false,
  streamSummary = null,
}: PipelineDockProps) {
  // The tab the body really shows. A saved "preview" tab outlives its sample
  // (the tab is persisted, the sample is not): the body then falls back to the
  // logs, and the Logs tab must read as selected so one tab always is.
  const hasStream = Boolean(isStreamPipeline || activeExecutionId);
  const shown = tab === "problems"
    ? "problems"
    : tab === "preview" && sample && projectId
      ? "preview"
      : tab === "stream" && hasStream
        ? "stream"
        : "logs";

  return (
    <>
      <ResizeHandle
        orientation="horizontal"
        panelAfter
        label="Resize logs"
        value={height}
        min={DOCK.min}
        max={DOCK.max}
        defaultValue={DOCK.initial}
        onChange={onHeightChange}
      />
      <div className="pipeline-dock" style={{ height }}>
        <div className="pipeline-dock__tabs" role="tablist" aria-label="Bottom panel">
          <button
            type="button"
            role="tab"
            aria-selected={shown === "logs"}
            className={`pipeline-dock__tab${shown === "logs" ? " is-active" : ""}`}
            onClick={() => onTabChange("logs")}
          >
            Logs
          </button>
          {hasStream && (
            <button
              type="button"
              role="tab"
              aria-selected={shown === "stream"}
              className={`pipeline-dock__tab${shown === "stream" ? " is-active" : ""}`}
              onClick={() => onTabChange("stream")}
            >
              Stream
              {streamSummary && (
                <span className={`pipeline-dock__count${streamSummary.status === "running" ? " is-good" : " is-warn"}`}>
                  {streamSummary.up}/{streamSummary.total}
                </span>
              )}
            </button>
          )}
          <button
            type="button"
            role="tab"
            aria-selected={shown === "problems"}
            className={`pipeline-dock__tab${shown === "problems" ? " is-active" : ""}`}
            onClick={() => onTabChange("problems")}
          >
            Problems
            {(counts.errors > 0 || counts.warnings > 0) && (
              <span className={`pipeline-dock__count${counts.errors ? " is-bad" : " is-warn"}`}>
                {counts.errors + counts.warnings}
              </span>
            )}
          </button>
          {sample && (
            <button
              type="button"
              role="tab"
              aria-selected={shown === "preview"}
              className={`pipeline-dock__tab${shown === "preview" ? " is-active" : ""}`}
              onClick={() => onTabChange("preview")}
            >
              Sample · {sample.node}
            </button>
          )}
          <button
            type="button"
            className="pipeline-dock__close"
            aria-label="Close panel (⌘J)"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className="pipeline-dock__body">
          {shown === "problems" ? (
            <ProblemsPanel
              problems={problems}
              isChecking={isChecking}
              onOpen={onOpenProblem}
              onFix={onFixProblem}
              action={fixWithAI}
            />
          ) : shown === "preview" && sample && projectId ? (
            <SamplePreview
              projectId={projectId}
              sample={sample}
              outputs={(itemById.get(sample.node)?.outputs ?? []).map((o) => o.name)}
              env={activeEnv}
            />
          ) : shown === "stream" ? (
            activeExecutionId ? (
              <StreamingStatusPanel executionId={activeExecutionId} isActive={isExecuting} fullView />
            ) : (
              <div className="stream-idle-panel">
                <p>Stream is not currently running. Click <b>Start stream</b> above to launch the streaming queries.</p>
              </div>
            )
          ) : (
            <>
              {activeExecutionId && (
                <StreamingStatusPanel executionId={activeExecutionId} isActive={isExecuting} />
              )}
              <InlineLogs
                isRunning={isExecuting}
                onClose={onClose}
                mode="fill"
                nodes={pipelineNodes}
                executionStates={executionStates}
              />
            </>
          )}
        </div>
      </div>
    </>
  );
}
