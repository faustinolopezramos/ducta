import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useExecutePipeline, useSweepPipeline, useCancelExecution, apiErrorMessage } from "../../api/mutations";
import { useExecutionStatus, useEnvironments, useExecutionList } from "../../api/queries";
import { useSourceStore } from "../../store/workspace";
import { useBuilderStore } from "../../store/builderStore";
import { useLogsStore } from "../../store/logsStore";
import { useToastStack } from "../../hooks/useModalStack";
import { useLogsWebSocket } from "../../hooks/useLogsWebSocket";
import { usePreflightPipeline, type PreflightResult } from "../../api/certificatesApi";
import { buildStartCommand } from "../../utils/cliCommand";

export function useExecutionState(
  pipelineName: string,
  projectId: string,
  onExecutionStatesChange?: (states: Record<string, string>) => void,
  onStatusChange?: (status: string | null) => void,
  onActiveIdChange?: (activeId: string | null) => void,
) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [showParams, setShowParams] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showError, setShowError] = useState(false);
  const [modelVersion, setModelVersion] = useState("");
  const [hyperparams, setHyperparams] = useState("");
  const [sweepMode, setSweepMode] = useState(false);
  const paramsRef = useRef<HTMLDivElement>(null);
  const [preflightResult, setPreflightResult] = useState<PreflightResult | null>(null);

  const logsOpen = useLogsStore((s) => s.logsOpen);
  const setLogsOpen = useLogsStore((s) => s.setLogsOpen);
  const currentLogs = useLogsStore((s) => s.currentLogs);
  const saveExecutionLogs = useLogsStore((s) => s.saveExecutionLogs);

  const activeEnv = useSourceStore((s) => s.activeEnv) ?? "base";
  const setActiveEnv = useSourceStore((s) => s.setActiveEnv);
  const sourceType = useSourceStore((s) => s.sourceType);
  const { data: envsData } = useEnvironments();
  const availableEnvs: string[] = envsData?.environments ?? [];
  const { show } = useToastStack();

  const { mutate: executePipeline, isPending: isStarting } = useExecutePipeline();
  const { mutate: sweepPipeline, isPending: isSweeping } = useSweepPipeline();
  const { mutate: cancelExecution, isPending: isCancelling } = useCancelExecution();
  const { mutate: preflightPipeline, isPending: isPreflighting } = usePreflightPipeline();

  const parsedHyperparams = useMemo<{ value: Record<string, unknown> | null; error: string | null }>(() => {
    const text = hyperparams.trim();
    if (!text) return { value: null, error: null };
    try {
      const obj = JSON.parse(text);
      if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
        return { value: null, error: "Must be a JSON object" };
      }
      return { value: obj as Record<string, unknown>, error: null };
    } catch (e) {
      return { value: null, error: `Invalid JSON: ${(e as Error).message}` };
    }
  }, [hyperparams]);

  const { data: execution } = useExecutionStatus(activeId as any);
  const { data: execList } = useExecutionList();
  const adoptedRef = useRef(false);

  useEffect(() => {
    if (adoptedRef.current || activeId) return;
    const running = execList?.executions?.find(
      (e: any) => e.pipeline_name === pipelineName && e.status === "running"
    );
    if (running) {
      adoptedRef.current = true;
      setActiveId(running.id);
    }
  }, [execList, pipelineName, activeId]);

  useLogsWebSocket(activeId);

  const executionStates = useBuilderStore((s) => s.executionStates);
  const setExecutionStates = useBuilderStore((s) => s.setExecutionStates);

  const isQueued = execution?.status === "pending";
  const isRunning = execution?.status === "running";
  const isActive = isQueued || isRunning;
  const isDone = execution?.status === "success" || execution?.status === "failed" || execution?.status === "cancelled" || execution?.status === "skipped";
  const isFailed = execution?.status === "failed";

  useEffect(() => {
    if (onExecutionStatesChange) onExecutionStatesChange(executionStates);
  }, [executionStates]);

  useEffect(() => {
    if (onStatusChange) onStatusChange(execution?.status ?? null);
  }, [execution?.status]);

  useEffect(() => {
    if (!activeId) {
      setExecutionStates({});
      if (onExecutionStatesChange) onExecutionStatesChange({});
    }
  }, [activeId]);

  useEffect(() => {
    if (onActiveIdChange) onActiveIdChange(activeId);
  }, [activeId, onActiveIdChange]);

  useEffect(() => {
    if (isDone && activeId && currentLogs.length > 0) {
      saveExecutionLogs(activeId);
    }
  }, [isDone, activeId, currentLogs.length, saveExecutionLogs]);

  useEffect(() => {
    if (isFailed && execution?.error_message) {
      setErrorMsg(execution.error_message);
      setShowError(true);
    }
  }, [isFailed, execution?.error_message]);

  useEffect(() => {
    if (!showParams) return;
    const handler = (e: MouseEvent) => {
      if (paramsRef.current && !paramsRef.current.contains(e.target as Node)) {
        setShowParams(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showParams]);

  const handleRun = useCallback(
    (dryRun: boolean, validateOnly = false, sanityOnly = false) => {
      setErrorMsg(null);
      setShowError(false);
      if (parsedHyperparams.error) {
        show(parsedHyperparams.error, "error");
        return;
      }
      if (sweepMode && !validateOnly && !dryRun && !sanityOnly) {
        if (!parsedHyperparams.value) {
          show("Provide a sweep spec (JSON object of param → list of values)", "error");
          return;
        }
        sweepPipeline(
          { projectId, pipelineName, sweep: parsedHyperparams.value, env: activeEnv, startDate: startDate || undefined, endDate: endDate || undefined, modelVersion: modelVersion || undefined },
          {
            onSuccess: (data: any) => { setLogsOpen(true); setShowParams(false); show(`Sweep started — ${data.total} run(s) (${data.sweep_id})`, "success"); },
            onError: (e) => show(apiErrorMessage(e, "Failed to start sweep"), "error"),
          }
        );
        return;
      }
      executePipeline(
        { projectId, pipelineName, env: activeEnv, dryRun, validateOnly, sanityOnly, startDate: startDate || undefined, endDate: endDate || undefined, modelVersion: modelVersion || undefined, hyperparams: parsedHyperparams.value || undefined },
        {
          onSuccess: (data: any) => { setActiveId(data.id); setLogsOpen(true); setShowParams(false); show(`${validateOnly ? "Validation" : sanityOnly ? "Sanity check" : dryRun ? "Dry run" : "Execution"} started — ${pipelineName}`, "success"); },
          onError: (e) => show(apiErrorMessage(e, "Failed to start execution"), "error"),
        }
      );
    },
    [projectId, pipelineName, activeEnv, startDate, endDate, modelVersion, parsedHyperparams, sweepMode, executePipeline, sweepPipeline, setLogsOpen, show]
  );

  const handleCopyCommand = useCallback(async () => {
    const command = buildStartCommand({ pipelineName, env: activeEnv, startDate: startDate || undefined, endDate: endDate || undefined });
    try { await navigator.clipboard.writeText(command); show("CLI command copied — run it from the workspace root", "success"); }
    catch { show(command, "info"); }
  }, [pipelineName, activeEnv, startDate, endDate, show]);

  const handleCancel = useCallback(() => {
    if (activeId) {
      cancelExecution(activeId, {
        onSuccess: () => show(`Execution cancelled — ${pipelineName}`, "info"),
        onError: (e) => show(apiErrorMessage(e, "Cancel failed"), "error"),
      });
    }
  }, [activeId, cancelExecution, pipelineName, show]);

  const handleClear = useCallback(() => {
    setActiveId(null);
    setLogsOpen(false);
    setErrorMsg(null);
    setShowError(false);
    if (onExecutionStatesChange) onExecutionStatesChange({});
  }, [setLogsOpen, onExecutionStatesChange]);

  return {
    activeId, startDate, endDate, showParams, errorMsg, showError,
    modelVersion, hyperparams, sweepMode, paramsRef, preflightResult,
    logsOpen, setLogsOpen, currentLogs, activeEnv, setActiveEnv,
    sourceType, availableEnvs, execution, isStarting, isSweeping,
    isCancelling, isPreflighting, isQueued, isRunning, isActive, isDone, isFailed,
    executionStates, setExecutionStates, preflightPipeline, setPreflightResult,
    setStartDate, setEndDate, setShowParams, setErrorMsg, setShowError,
    setModelVersion, setHyperparams, setSweepMode, setActiveId,
    handleRun, handleCopyCommand, handleCancel, handleClear, show,
  };
}
