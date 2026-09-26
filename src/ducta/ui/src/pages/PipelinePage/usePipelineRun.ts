import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useExecutionList } from "../../api/queries";
import { apiErrorMessage, useCancelExecution, useRunNode } from "../../api/mutations";
import { useLogsStore } from "../../store/logsStore";
import { useSourceStore } from "../../store/workspace";
import { useLogsWebSocket } from "../../hooks/useLogsWebSocket";
import { useToastStack } from "../../hooks/useModalStack";
import type { DagCanvasItem } from "../../components/Pipeline/types";

/**
 * Running things from the pipeline page: a single node, the whole pipeline
 * (through ExecutionControls), cancelling, the chain's latest run statuses,
 * and the logs panel that follows a run.
 */
export function usePipelineRun({
  projectId,
  pipelineId,
  itemById,
}: {
  projectId: string | undefined;
  pipelineId: string | undefined;
  itemById: Map<string, DagCanvasItem>;
}) {
  const activeEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const { show: showToast } = useToastStack();
  const { mutate: runNode } = useRunNode();
  const { mutate: cancelExecution } = useCancelExecution();

  const [activeExecutionId, setActiveExecutionId] = useState<string | null>(null);
  const [runningNodeId, setRunningNodeId] = useState<string | null>(null);
  const [nodeExecId, setNodeExecId] = useState<string | null>(null);
  const [execStatus, setExecStatus] = useState<string | null>(null);
  const isExecuting = execStatus === "running" || execStatus === "pending";

  const logsOpen = useLogsStore((s) => s.logsOpen);
  const setLogsOpen = useLogsStore((s) => s.setLogsOpen);
  const errorCount = useLogsStore((s) => s.levelCounts.ERROR);
  useLogsWebSocket(nodeExecId);

  // ── Smart log auto-show/hide ──────────────────────────────────────────────
  // Tracks whether the user manually toggled the panel during the current
  // execution so we don't fight their intent.
  const prevExecStatusRef = useRef<string | null>(null);
  const userOverrideRef = useRef(false);
  const autoCloseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevErrorCountRef = useRef(0);

  // Wrap the store setter so we can detect manual vs programmatic toggles.
  const setLogsOpenSmart = useCallback((open: boolean, isAuto = false) => {
    if (!isAuto) userOverrideRef.current = true;
    setLogsOpen(open);
  }, [setLogsOpen]);

  useEffect(() => {
    const prev = prevExecStatusRef.current;
    const curr = execStatus;
    prevExecStatusRef.current = curr;

    // New execution started → reset override, auto-open
    const isStarting = (curr === "running" || curr === "pending") && prev !== curr && prev !== "running" && prev !== "pending";
    if (isStarting) {
      userOverrideRef.current = false;
      prevErrorCountRef.current = 0;
      if (autoCloseTimerRef.current) { clearTimeout(autoCloseTimerRef.current); autoCloseTimerRef.current = null; }
      if (!logsOpen) setLogsOpen(true);
      return;
    }

    // Errors arrived during execution → auto-open (unless user closed manually)
    if ((curr === "running" || curr === "pending") && errorCount > prevErrorCountRef.current) {
      prevErrorCountRef.current = errorCount;
      if (!userOverrideRef.current && !logsOpen) setLogsOpen(true);
      return;
    }
    prevErrorCountRef.current = errorCount;

    // Execution finished successfully → auto-close after 3s delay
    const justSucceeded = (curr === "success" || curr === "completed") && prev !== curr;
    if (justSucceeded && logsOpen && !userOverrideRef.current) {
      autoCloseTimerRef.current = setTimeout(() => {
        // Only close if still open and user hasn't intervened
        if (!userOverrideRef.current) setLogsOpen(false);
        autoCloseTimerRef.current = null;
      }, 3000);
      return;
    }

    // Execution failed → keep logs open (no auto-close), do nothing
  }, [execStatus, errorCount, logsOpen, setLogsOpen]);

  // ── The chain's latest runs, for the dots on the top bar's pills ─────────
  const { data: projectRuns } = useExecutionList({ project_id: projectId, limit: 50 });
  const chainStatus = useMemo(() => {
    const latest: Record<string, string> = {};
    const runs = (projectRuns?.executions ?? []) as Array<{ pipeline_name?: string | null; status: string }>;
    for (const run of runs) {
      if (run.pipeline_name && !(run.pipeline_name in latest)) latest[run.pipeline_name] = run.status;
    }
    return latest;
  }, [projectRuns]);

  const handleRunNode = (node: { id: string; name?: string }) => {
    // A node drawn from an upstream pipeline of the chain runs in its own pipeline.
    const pipelineName = itemById.get(node.id)?.pipeline ?? pipelineId!;
    setRunningNodeId(node.id);
    runNode(
      { projectId: projectId!, pipelineName, nodeName: node.name ?? node.id, env: activeEnv },
      {
        onSuccess: (data: any) => {
          showToast(`Node "${node.name ?? node.id}" started`, "success");
          setRunningNodeId(null);
          setNodeExecId(data?.id ?? null);
          useLogsStore.getState().setLogsOpen(true);
        },
        onError: (e: any) => {
          showToast(apiErrorMessage(e, `Failed to run node "${node.name ?? node.id}"`), "error");
          setRunningNodeId(null);
        },
      }
    );
  };

  const handleExecute = () => {
    const btn = document.querySelector('[data-execute-btn]') as HTMLButtonElement;
    btn?.click();
  };

  const handleValidate = () => {
    const btn = document.querySelector('[data-validate-btn]') as HTMLButtonElement;
    btn?.click();
  };

  const handleCancel = () => {
    if (activeExecutionId) {
      cancelExecution(activeExecutionId, {
        onSuccess: () => showToast("Stopping pipeline...", "info"),
        onError: (err: any) => showToast(err?.message || "Failed to stop pipeline", "error"),
      });
    }
  };

  return {
    activeEnv, showToast,
    activeExecutionId, setActiveExecutionId, runningNodeId, execStatus, setExecStatus, isExecuting,
    logsOpen, setLogsOpen: setLogsOpenSmart, chainStatus,
    handleRunNode, handleExecute, handleValidate, handleCancel,
  };
}
