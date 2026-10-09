import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useExecutionList } from "../../api/queries";
import { apiErrorMessage, useCancelExecution, useExecutePipeline, useRunNode } from "../../api/mutations";
import { useLogsStore } from "../../store/logsStore";
import { useSourceStore } from "../../store/workspace";
import { useLogsWebSocket } from "../../hooks/useLogsWebSocket";
import { useToastStack } from "../../hooks/useModalStack";
import type { DagCanvasItem } from "../../components/Pipeline/types";
import type { RunOptions } from "../../components/Execution/RunOptionsDialog";

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
  const { mutate: executePipeline } = useExecutePipeline();
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

  /** Run part of the pipeline: some nodes, everything from one, or only what is stale. */
  /** A data breakpoint: the run pauses after this node, its output there to inspect. */
  const [breakpoint, setBreakpoint] = useState<{ node: string; execId: string | null } | null>(null);

  const runScoped = (scope: "selected" | "from" | "after" | "until" | "stale", nodes?: string[]) => {
    if (!projectId || !pipelineId) return;
    const what =
      scope === "stale" ? "stale nodes"
        : scope === "from" ? `from ${nodes?.[0]}`
          : scope === "until" ? `up to ${nodes?.[0]}`
            : scope === "after" ? `the rest after ${nodes?.[0]}`
              : (nodes ?? []).join(", ");
    executePipeline(
      { projectId, pipelineName: pipelineId, env: activeEnv, scope, nodes },
      {
        onSuccess: (data: any) => {
          showToast(`Running ${what} of ${pipelineId} in ${activeEnv}`, "success");
          setNodeExecId(data?.id ?? null);
          setBreakpoint(scope === "until" && nodes?.[0] ? { node: nodes[0], execId: data?.id ?? null } : null);
          useLogsStore.getState().setLogsOpen(true);
        },
        onError: (e: any) => showToast(apiErrorMessage(e, `Could not run ${what}`), "error"),
      },
    );
  };

  /** The node whose last sample run the Sample tab shows, and when it finished. */
  const [sample, setSample] = useState<{ node: string; execId: string | null; rows: number } | null>(null);

  /** Run one node on the first rows of its inputs; nothing real is written. */
  const runSample = (nodeId: string, rows = 100) => {
    if (!projectId) return;
    const pipelineName = itemById.get(nodeId)?.pipeline ?? pipelineId!;
    executePipeline(
      { projectId, pipelineName, env: activeEnv, nodeName: nodeId, sampleRows: rows },
      {
        onSuccess: (data: any) => {
          showToast(`Sample run of ${nodeId} on ${rows} rows started`, "success");
          setNodeExecId(data?.id ?? null);
          setSample({ node: nodeId, execId: data?.id ?? null, rows });
          useLogsStore.getState().setLogsOpen(true);
        },
        onError: (e: any) => showToast(apiErrorMessage(e, `Could not run ${nodeId} on a sample`), "error"),
      },
    );
  };

  /** A debug run: it waits for the IDE to attach, then breakpoints there stop it. */
  const [debugRun, setDebugRun] = useState<{ execId: string | null; node: string | null } | null>(null);
  const runDebug = (nodeId: string | null) => {
    if (!projectId || !pipelineId) return;
    executePipeline(
      { projectId, pipelineName: pipelineId, env: activeEnv, debug: true, ...(nodeId ? { scope: "selected" as const, nodes: [nodeId] } : {}) },
      {
        onSuccess: (data: any) => {
          setNodeExecId(data?.id ?? null);
          setDebugRun({ execId: data?.id ?? null, node: nodeId });
          useLogsStore.getState().setLogsOpen(true);
        },
        onError: (e: any) => showToast(apiErrorMessage(e, "Could not start a debug run"), "error"),
      },
    );
  };

  /** The whole pipeline, pausing after *node* until continued or stopped. */
  const runWithBreakpoint = (node: string) => {
    if (!projectId || !pipelineId) return;
    executePipeline(
      { projectId, pipelineName: pipelineId, env: activeEnv, pauseAfter: [node] },
      {
        onSuccess: (data: any) => {
          showToast(`Running ${pipelineId} in ${activeEnv} — it will pause after ${node}`, "success");
          setNodeExecId(data?.id ?? null);
          setBreakpoint({ node, execId: data?.id ?? null });
          useLogsStore.getState().setLogsOpen(true);
        },
        onError: (e: any) => showToast(apiErrorMessage(e, "Could not start the run"), "error"),
      },
    );
  };

  /** A run said in full in the Run-with-options dialog. */
  const runWithOptions = (o: RunOptions) => {
    if (!projectId || !pipelineId) return;
    executePipeline(
      {
        projectId,
        pipelineName: pipelineId,
        env: activeEnv,
        dryRun: o.dryRun,
        ...(o.scope !== "pipeline" ? { scope: o.scope } : {}),
        ...(o.node ? { nodes: [o.node] } : {}),
        ...(o.scope === "selected" && o.node && o.sampleRows ? { nodeName: o.node } : {}),
        ...(o.startDate ? { startDate: o.startDate } : {}),
        ...(o.endDate ? { endDate: o.endDate } : {}),
        ...(o.hyperparams ? { hyperparams: o.hyperparams } : {}),
        ...(o.sampleRows ? { sampleRows: o.sampleRows } : {}),
        ...(o.pauseAfter ? { pauseAfter: [o.pauseAfter] } : {}),
      },
      {
        onSuccess: (data: any) => {
          showToast(`Running ${pipelineId} in ${activeEnv}`, "success");
          setNodeExecId(data?.id ?? null);
          if (o.pauseAfter) setBreakpoint({ node: o.pauseAfter, execId: data?.id ?? null });
          useLogsStore.getState().setLogsOpen(true);
        },
        onError: (e: any) => showToast(apiErrorMessage(e, "Could not start the run"), "error"),
      },
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
    handleRunNode, handleExecute, handleValidate, handleCancel, runScoped,
    runSample, sample, sampleExecId: nodeExecId,
    breakpoint, clearBreakpoint: () => setBreakpoint(null),
    runDebug, debugRun, clearDebugRun: () => setDebugRun(null),
    runWithBreakpoint, runWithOptions,
  };
}
