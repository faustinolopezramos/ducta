import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLogsStore } from "../store/logsStore";
import { useBuilderStore } from "../store/builderStore";
import { sourceKey } from "../api/utils";
import { buildWsUrl, MAX_RECONNECT_ATTEMPTS } from "./wsUtils";

export function useLogsWebSocket(executionId: string | null) {
  const workerRef     = useRef<Worker | null>(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { addLogsBatch, setConnected, clearCurrentLogs, bumpReconnectSignal } = useLogsStore();
  const reconnectSignal    = useLogsStore((s) => s.reconnectSignal);
  const setExecutionStates = useBuilderStore((s) => s.setExecutionStates);
  const queryClient        = useQueryClient();

  // Runs its cleanup exactly once, on true unmount — separate from the effect
  // below (whose cleanup fires on every executionId/reconnectSignal change,
  // where terminating the worker would be wrong: it's reused across those).
  // Without this, navigating away mid-execution never calls terminate() and
  // the dedicated Worker thread leaks for the life of the tab.
  useEffect(() => {
    return () => {
      if (workerRef.current) {
        workerRef.current.postMessage({ type: "STOP" });
        workerRef.current.terminate();
        workerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (!executionId) {
      if (workerRef.current) {
        workerRef.current.postMessage({ type: "STOP" });
        workerRef.current.terminate();
        workerRef.current = null;
      }
      setConnected(false);
      return;
    }

    // Initialize worker if needed
    if (!workerRef.current) {
      // Vite syntax for worker
      workerRef.current = new Worker(
        new URL("../workers/logs.worker.ts", import.meta.url),
        { type: "module" }
      );
    }

    const worker = workerRef.current;

    worker.onmessage = (e) => {
      const { type, batch, states, entry, connected, code } = e.data;

      switch (type) {
        case "LOG_BATCH":
          addLogsBatch(batch);
          break;

        case "NODE_STATUS_UPDATE":
          setExecutionStates(states);
          break;

        case "EXECUTION_STATUS": {
          const ex = entry.extra;
          queryClient.setQueryData(
            ["executions", sourceKey(), executionId],
            (prev: Record<string, unknown> | undefined) => ({
              ...(prev ?? {}),
              id: executionId,
              status: ex.status,
              exit_code: ex.exit_code ?? null,
              duration_seconds: ex.duration_seconds ?? null,
              error_message: ex.error_message ?? null,
              error_details: ex.error_details ?? null,
              finished_at: ex.finished_at ?? null,
            })
          );
          break;
        }

        case "CONNECTED":
          setConnected(connected);
          if (connected) retryCountRef.current = 0;
          break;

        case "CLOSE":
          if (code === 1000 || code === 1001) return;
          if (retryCountRef.current < MAX_RECONNECT_ATTEMPTS) {
            const delay = 1000 * Math.pow(2, retryCountRef.current);
            retryCountRef.current += 1;
            retryTimerRef.current = setTimeout(() => bumpReconnectSignal(), delay);
          }
          break;
      }
    };

    // Clear on every (re)connection, not just first mount: the server replays
    // the execution's full log backlog from position 0 on each new WebSocket,
    // so keeping the old entries would duplicate everything. Clearing is
    // lossless — the replay repopulates the store.
    clearCurrentLogs();

    worker.postMessage({
      type: "START",
      payload: { executionId, wsUrl: buildWsUrl(executionId) }
    });

    const handleVisibility = () => {
      worker.postMessage({
        type: "VISIBILITY_CHANGE",
        payload: { hidden: document.visibilityState === "hidden" }
      });
    };

    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      if (retryTimerRef.current !== null) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
      // Stop but don't terminate immediately to allow reconnects
      worker.postMessage({ type: "STOP" });
    };
  // reconnectSignal intentionally included: bumping it re-runs the effect to reconnect
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [executionId, reconnectSignal]);
}
