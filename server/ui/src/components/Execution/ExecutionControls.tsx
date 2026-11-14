import type React from "react";
import {
  IconPlayerPlay, IconPlayerStop, IconReload, IconFlask,
  IconCircleCheck, IconCopy, IconSettings, IconTerminal2, IconX,
} from "@tabler/icons-react";
import { Button, Toolbar } from "../ui";
import { ExecutionStatus } from "./ExecutionStatus";
import { ExecutionErrorPanel } from "./ExecutionErrorPanel";
import { ExecutionParamsPanel } from "./ExecutionParamsPanel";
import { PreflightPanel } from "./PreflightPanel";
import { useExecutionState } from "./useExecutionState";

const envSelectStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: "var(--text-xs)",
  padding: "4px 8px",
  background: "var(--surface-elevated)",
  color: "var(--text)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius-sm)",
  cursor: "pointer",
  outline: "none",
};

const chipStyle = (active: boolean): React.CSSProperties => ({
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  fontFamily: "var(--font-mono)",
  fontSize: "var(--text-xs)",
  padding: "3px 8px",
  borderRadius: "var(--radius-pill)",
  background: active ? "var(--accent-a12)" : "var(--surface)",
  color: active ? "var(--primary)" : "var(--text-muted)",
  border: `1px solid ${active ? "var(--accent-a40)" : "var(--border)"}`,
  userSelect: "none",
});

export function ExecutionControls({
  pipelineName, projectId,
  onExecutionStatesChange, onStatusChange, onActiveIdChange,
}: {
  pipelineName: string;
  projectId: string;
  onExecutionStatesChange?: (states: Record<string, string>) => void;
  onStatusChange?: (status: string | null) => void;
  onActiveIdChange?: (activeId: string | null) => void;
}) {
  const {
    activeId, startDate, endDate, showParams, errorMsg, showError,
    modelVersion, hyperparams, sweepMode, paramsRef, preflightResult,
    logsOpen, setLogsOpen, currentLogs, activeEnv, setActiveEnv,
    sourceType, availableEnvs, execution, isStarting, isSweeping,
    isCancelling, isPreflighting, isQueued, isRunning, isActive, isDone, isFailed,
    preflightPipeline, setPreflightResult,
    setStartDate, setEndDate, setShowParams, setShowError,
    setModelVersion, setHyperparams, setSweepMode,
    handleRun, handleCopyCommand, handleCancel, handleClear, show,
  } = useExecutionState(pipelineName, projectId, onExecutionStatesChange, onStatusChange, onActiveIdChange);

  const datesSummary =
    startDate || endDate
      ? `${startDate ? startDate.slice(5) : "any"} → ${endDate ? endDate.slice(5) : "any"}`
      : "Params";

  return (
    <div ref={paramsRef} style={{ position: "relative" }}>
      <Toolbar
        aria-label={`Actions for ${pipelineName}`}
        end={
          <>
            <Button variant="ghost" size="sm"
              onClick={() => setShowParams(!showParams)}
              aria-expanded={showParams}
              title="Execution parameters (start date, end date)"
              leftIcon={<IconSettings size={15} />}>
              {datesSummary}
            </Button>

            <select value={activeEnv}
              onChange={(e) => setActiveEnv(e.target.value)}
              disabled={isActive}
              aria-label="Active environment"
              style={{ ...envSelectStyle, cursor: isActive ? "default" : "pointer", opacity: isActive ? 0.7 : 1 }}>
              {(availableEnvs.length ? availableEnvs : [activeEnv]).map((e) => (
                <option key={e} value={e}>{e}</option>
              ))}
            </select>

            {sourceType && (
              <span style={chipStyle(sourceType === "git")} title={sourceType === "git" ? "Workspace cloned from Git" : "Local workspace"}>
                {sourceType}
              </span>
            )}

            {activeId && (
              <Button variant="ghost" size="sm"
                onClick={() => setLogsOpen(!logsOpen)}
                aria-pressed={logsOpen}
                title={logsOpen ? "Hide logs" : "Show logs"}
                leftIcon={<IconTerminal2 size={15} />}>
                {currentLogs.length > 0 ? String(currentLogs.length) : "logs"}
              </Button>
            )}

            {isDone && (
              <Button variant="ghost" size="sm" iconOnly
                onClick={handleClear}
                title="Clear execution state"
                leftIcon={<IconX size={15} />} />
            )}
          </>
        }>
        <Button variant="primary" data-execute-btn
          onClick={() => handleRun(false)}
          loading={isStarting || isSweeping}
          disabled={isStarting || isSweeping || isActive}
          leftIcon={<IconPlayerPlay size={16} />}>
          {isQueued ? "Queued\u2026" : isRunning ? "Running\u2026" : sweepMode ? "Run Sweep" : "Execute Pipeline"}
        </Button>

        {(isActive || isDone) && (
          <button type="button" onClick={() => setLogsOpen(true)}
            style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}>
            <ExecutionStatus execution={execution} />
          </button>
        )}

        {isActive && (
          <Button variant="danger" size="sm"
            disabled={isCancelling} loading={isCancelling}
            onClick={handleCancel}
            title="Cancel running execution"
            leftIcon={<IconPlayerStop size={15} />}>
            Cancel
          </Button>
        )}

        {isDone && isFailed && (
          <Button variant="secondary" size="sm"
            onClick={() => handleRun(false)}
            disabled={isStarting}
            leftIcon={<IconReload size={15} />}>
            Retry
          </Button>
        )}

        <Button variant="secondary" size="sm"
          onClick={() => handleRun(true)}
          disabled={isStarting || isActive}
          title="Dry run — no side effects"
          leftIcon={<IconFlask size={15} />}>
          Dry Run
        </Button>

        <Button variant="secondary" size="sm" data-validate-btn
          loading={isPreflighting}
          onClick={() => {
            setPreflightResult(null);
            preflightPipeline(
              { projectId, pipelineName, env: activeEnv },
              {
                onSuccess: (result: any) => {
                  setPreflightResult(result);
                  if (result.ok && result.warnings.length === 0) {
                    show(`Preflight passed — ${pipelineName} is ready to run`, "success");
                  }
                },
                onError: (e) => show(e?.message || "Preflight failed", "error"),
              }
            );
          }}
          disabled={isStarting || isPreflighting || isActive}
          leftIcon={<IconCircleCheck size={15} />}>
          Validate
        </Button>

        <Button variant="secondary" size="sm"
          onClick={() => handleRun(false, false, true)}
          disabled={isStarting || isActive}
          leftIcon={<IconCircleCheck size={15} />}>
          Sanity
        </Button>

        <Button variant="ghost" size="sm"
          onClick={handleCopyCommand}
          leftIcon={<IconCopy size={15} />}>
          Copy CLI
        </Button>
      </Toolbar>

      {showParams && (
        <ExecutionParamsPanel
          startDate={startDate} endDate={endDate}
          onStartDateChange={setStartDate} onEndDateChange={setEndDate}
          onClearDates={() => { setStartDate(""); setEndDate(""); }}
          modelVersion={modelVersion} onModelVersionChange={setModelVersion}
          hyperparams={hyperparams} onHyperparamsChange={setHyperparams}
          hyperparamsError={null} sweepMode={sweepMode} onSweepModeChange={setSweepMode} />
      )}

      {showError && errorMsg && (
        <ExecutionErrorPanel errorMsg={errorMsg} onDismiss={() => setShowError(false)} executionId={activeId} />
      )}

      {preflightResult && (
        <PreflightPanel result={preflightResult} onClose={() => setPreflightResult(null)} />
      )}
    </div>
  );
}
