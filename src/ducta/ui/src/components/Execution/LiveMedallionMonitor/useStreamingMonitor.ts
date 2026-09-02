import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import client from "../../../api/client";
import { useToastStack } from "../../../hooks/useModalStack";
import type { StreamingStatus, PerformanceMetrics, MonitorState, RateSample } from "./types";
import { TERMINAL_EXEC_STATUSES } from "./types";
import { appendSample, classifyThroughput, rateScale, sumRates } from "./helpers";

/**
 * All stateful/polling logic for the Live Stream Monitor, separated from
 * rendering. Polls /streaming/status (and, throttled, /streaming/data),
 * derives performance metrics client-side, and exposes node restart /
 * checkpoint-clear actions.
 */
export function useStreamingMonitor(executionId?: string | null, executionStatus?: string | null) {
  const executionTerminal = !!executionStatus && TERMINAL_EXEC_STATUSES.has(executionStatus);
  const [status, setStatus]   = useState<StreamingStatus | null>(null);
  const [data, setData]       = useState<Record<string, unknown[]>>({});
  const [monitorState, setMonitorState] = useState<MonitorState>("waiting");
  const [errorMsg, setErrorMsg]         = useState<string | null>(null);
  const [lastUpdated, setLastUpdated]   = useState<Date | null>(null);
  const [confirmStop, setConfirmStop]   = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [restartingNodes, setRestartingNodes] = useState<Set<string>>(new Set());
  const [isClearingCheckpoints, setIsClearingCheckpoints] = useState(false);
  const toast = useToastStack();

  // A rolling window of throughput samples — the trend line, and the source of
  // the shared scale. This replaces a high-water mark that only ever grew: one
  // spike used to pin the scale for the rest of the session, flattening every
  // subsequent reading into an unreadable sliver.
  const [history, setHistory] = useState<RateSample[]>([]);

  // Last successful /streaming/data fetch. A ref (not state) so the 8s gate is
  // independent of the status/metrics cadence and doesn't destabilise fetchAll.
  const lastDataFetchRef = useRef<number>(0);

  // Single status fetch per tick (plus the throttled data preview). The
  // /streaming/metrics endpoint derives everything from the same status
  // snapshot the /status endpoint already returns (query_statuses.lastProgress),
  // so performance metrics are computed client-side in `pm` below — polling
  // both endpoints doubled the request volume for no extra information.
  // Must stay referentially stable (no component state in the closure): the
  // polling effect depends on it, so a new identity per response would tear the
  // interval down after every fetch and degenerate into continuous polling.
  const fetchAll = useCallback(async (signal: AbortSignal) => {
    if (!executionId) {
      setMonitorState("waiting");
      return;
    }
    const now = Date.now();
    const shouldFetchData = now - lastDataFetchRef.current >= 8000;

    const promises: Promise<any>[] = [
      client.get(`/executions/${executionId}/streaming/status`, { signal }),
    ];

    if (shouldFetchData) {
      promises.push(client.get(`/executions/${executionId}/streaming/data`, { signal }));
    }

    const results = await Promise.allSettled(promises);
    const [statusRes] = results;
    const dataRes = shouldFetchData ? results[1] : null;

    // If all are 404, the engine hasn't started yet — "waiting" state.
    const all404 = results.every(
      (r) => r.status === "rejected" && (r.reason?.response?.status === 404 || r.reason?.status === 404)
    );

    if (all404) {
      // A terminal execution whose engine has already unregistered should read
      // as "stopped", not "waiting" (which implies the engine is still warming up).
      setMonitorState(executionTerminal ? "stopped" : "waiting");
      setErrorMsg(null);
      return;
    }

    // Process status; surface real errors (non-404) only when status itself failed
    if (statusRes.status === "fulfilled") {
      setStatus(statusRes.value.data);
      setMonitorState("running");
      setErrorMsg(null);
      // Functional updater on purpose: `fetchAll` must not close over state, or
      // the polling effect below tears its interval down after every response.
      const rates = sumRates(statusRes.value.data);
      setHistory((prev) => appendSample(prev, { t: now, ...rates }));
    } else if (statusRes.reason?.response?.status !== 404) {
      const msg = statusRes.reason?.response?.data?.message ?? statusRes.reason?.message ?? "Error fetching stream status";
      setErrorMsg(msg);
      setMonitorState("error");
    }

    // Process data preview (less frequent)
    if (dataRes && dataRes.status === "fulfilled") {
      setData(dataRes.value.data || {});
      lastDataFetchRef.current = now;
    }

    setLastUpdated(new Date());
  }, [executionId, executionTerminal]);

  // Performance metrics derived from the status snapshot (same computation the
  // /streaming/metrics endpoint performs server-side).
  // `health_score` used to live here as (total - failed) / total. That is not a
  // health score, it is the "Failed Queries" tile expressed as a percentage —
  // the same fact twice — and with zero queries it reported a confident 100%.
  // Removed rather than reworked; the failure count already says it.
  const pm = useMemo<PerformanceMetrics | null>(() => {
    if (!status?.query_statuses) return null;
    const { input, processed } = sumRates(status);
    return {
      total_input_rate: input,
      total_processing_rate: processed,
      // Undefined, not 0, when nothing is arriving: there is no ratio to report
      // for an idle stream, and 0 read as a failure.
      processing_efficiency: input > 0 ? (processed / input) * 100 : undefined,
    };
  }, [status]);

  const scale = useMemo(() => rateScale(history), [history]);
  const verdict = classifyThroughput(pm?.total_input_rate ?? 0, pm?.total_processing_rate ?? 0);

  const handleRestartNode = async (nodeName: string) => {
    try {
      setRestartingNodes(prev => new Set(prev).add(nodeName));
      await client.post(`/executions/${executionId}/streaming/nodes/${nodeName}/restart`);
      toast.success(`Node '${nodeName}' restart initiated`);
      // Refresh status immediately
      await fetchAll(new AbortController().signal);
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message || "Failed to restart node";
      toast.error(`Restart error: ${msg}`);
    } finally {
      setRestartingNodes(prev => {
        const next = new Set(prev);
        next.delete(nodeName);
        return next;
      });
    }
  };

  const handleClearCheckpoints = async () => {
    setConfirmClear(false);
    try {
      setIsClearingCheckpoints(true);
      const res = await client.delete(`/executions/${executionId}/streaming/checkpoints`);
      toast.success(res.data.message || "Checkpoints cleared successfully");
    } catch (e: any) {
      const msg = e.response?.data?.detail || e.message || "Failed to clear checkpoints";
      toast.error(`Checkpoint error: ${msg}`);
    } finally {
      setIsClearingCheckpoints(false);
    }
  };

  // Prefer the live stream status; fall back to the execution-level status once
  // the engine has unregistered (e.g. "cancelled" → display as "stopped").
  const currentStatus =
    status?.status ??
    (executionTerminal ? (executionStatus === "cancelled" ? "stopped" : executionStatus ?? undefined) : undefined);
  const isTerminal =
    currentStatus === "stopped" ||
    currentStatus === "error" ||
    monitorState === "error" ||
    monitorState === "stopped" ||
    executionTerminal;

  // Adaptive cadence: 2s live, 4s while warming up, 15s once terminal — the
  // status can still change (node restarts), so don't stop polling entirely.
  const pollDelay = isTerminal ? 15000 : monitorState === "running" ? 2000 : 4000;

  useEffect(() => {
    const abortController = new AbortController();

    const tick = () => {
      if (document.visibilityState === "hidden") return;
      fetchAll(abortController.signal).catch(() => {});
    };

    tick();
    const intervalId = setInterval(tick, pollDelay);

    // Listen for visibility changes to resume immediately when coming back
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        tick();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      abortController.abort();
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [executionId, fetchAll, pollDelay]);

  // Derive the ordered node list from status → fallback to data keys
  const nodes: string[] = useMemo(() => {
    const fromStatus = status?.query_statuses ? Object.keys(status.query_statuses) : [];
    return fromStatus.length ? fromStatus : Object.keys(data);
  }, [status, data]);

  const isNodeActive = (n: string) => !!status?.query_statuses?.[n]?.isActive;
  const nodeError = (n: string) => status?.failed_nodes?.[n];
  const nodeRate = (n: string): number | undefined => {
    const p = status?.query_statuses?.[n]?.lastProgress;
    const v = p ? Number(p.processedRowsPerSecond ?? p.inputRowsPerSecond ?? NaN) : NaN;
    return Number.isFinite(v) ? v : undefined;
  };

  const dataNodes = useMemo(
    () => Object.keys(data).filter((n) => (data[n] as unknown[])?.length > 0),
    [data],
  );

  const uptime    = status?.uptime_seconds ?? 0;
  const isLoading = monitorState === "waiting";

  return {
    status,
    data,
    monitorState,
    errorMsg,
    lastUpdated,
    confirmStop,
    setConfirmStop,
    confirmClear,
    setConfirmClear,
    restartingNodes,
    isClearingCheckpoints,
    handleRestartNode,
    handleClearCheckpoints,
    currentStatus,
    isTerminal,
    nodes,
    isNodeActive,
    nodeError,
    nodeRate,
    dataNodes,
    uptime,
    isLoading,
    pm,
    history,
    scale,
    verdict,
  };
}
