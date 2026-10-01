import { useQuery } from "@tanstack/react-query";
import client from "../client";
import type {
  Execution,
} from "../../types";
import { qk } from "../queryKeys";

// ── API Response types ────────────────────────────────────────────────

interface ExecutionListResponse {
  executions: Execution[];
  count: number;
  total?: number;
  skip?: number;
  limit?: number;
}

type ExecutionDetailResponse = Execution;

// ─────────────────────────────────────────────
// EXECUTION QUERIES
// ─────────────────────────────────────────────

export interface ExecutionListFilters {
  pipeline_name?: string;
  node_name?: string;
  status?: string;
  env?: string;
  /** ISO date/datetime — only executions started at or after this. */
  since?: string;
  /** ISO date/datetime — only executions started at or before this. */
  until?: string;
  /** Only executions belonging to this sweep group. */
  sweep_id?: string;
  project_id?: string;
  /** Free-text search — matches id, pipeline/node name, error message, certificate run id. */
  q?: string;
  skip?: number;
  limit?: number;
}

/**
 * GET /executions
 * Returns { executions: [...], count }. Supports optional filters.
 */
export const useExecutionList = (filters: ExecutionListFilters = {}) =>
  useQuery({
    queryKey: qk.executions.list(filters),
    queryFn: () =>
      client
        .get("/executions", {
          params: Object.fromEntries(
            Object.entries(filters).filter(([, v]) => v != null && v !== "")
          ),
        })
        .then((r) => r.data),
    staleTime: 10 * 1000,
    refetchInterval: (query: { state: { data?: ExecutionListResponse } }) => {
      const executions = query.state.data?.executions;
      const hasActive = executions?.some(
        (e) => e.status === "pending" || e.status === "running"
      );
      return hasActive ? 10_000 : false;
    },
  });

/**
 * GET /executions/queue
 * Returns { running, queued, max_concurrent, total_queued, total_completed }.
 */
export const useQueueStatus = () =>
  useQuery({
    queryKey: qk.executions.queue(),
    queryFn: () => client.get("/executions/queue").then((r) => r.data),
    staleTime: 5 * 1000,
    refetchInterval: 15_000,
  });

/**
 * GET /executions/{id}
 * Returns ExecutionResponse.
 *
 * Status is pushed in real time over the logs WebSocket (see useLogsWebSocket,
 * which writes execution_status messages straight into this query's cache). The
 * HTTP poll below is only a slow safety-net fallback for when the WS is down.
 */
export const useExecutionStatus = (executionId: string) => {
  return useQuery({
    queryKey: qk.executions.detail(executionId),
    queryFn: () => client.get(`/executions/${executionId}`).then((r) => r.data),
    enabled: !!executionId,
    refetchInterval: (query: { state: { data?: ExecutionDetailResponse } }) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 15000 : false;
    },
    staleTime: 0,
  });
};

/**
 * GET /executions/{id}/logs
 * Returns LogEntry[] via HTTP (non-streaming fallback).
 */
export const useExecutionLogs = (executionId: string) =>
  useQuery({
    queryKey: qk.executions.logs(executionId),
    queryFn: () => client.get(`/executions/${executionId}/logs`).then((r) => r.data),
    enabled: !!executionId,
    // Logs for a finished execution are immutable — use a long staleTime to
    // avoid unnecessary re-fetches. Active executions use WebSocket streaming
    // anyway, so HTTP log fetches are only the fallback/history path.
    staleTime: 60 * 1000,
  });

/**
 * GET /executions/{id}/errors
 * Returns categorized failures: { execution_id, error_count, warning_count,
 * has_critical_errors, errors: [{ error_type, message, category, traceback,
 * traceback_lines, node_id, attempt, hint }], warnings }.
 * Only meaningful for failed executions; empty counts otherwise.
 */
export interface ExecutionErrorDetail {
  timestamp: string;
  node_id: string | null;
  node_type: string | null;
  attempt: number;
  error_type: string;
  message: string;
  category: string;
  traceback: string;
  traceback_lines: string[];
  /** What to look at first for this category of failure. Advice only: nothing retries a run. */
  hint: string | null;
}

export interface ExecutionErrorsResponse {
  execution_id: string;
  error_count: number;
  warning_count: number;
  has_critical_errors: boolean;
  errors: ExecutionErrorDetail[];
  warnings: Array<{ timestamp: string; message: string }>;
}

export const useExecutionErrors = (executionId: string | null | undefined) =>
  useQuery({
    queryKey: qk.executions.errors(executionId),
    queryFn: () => client.get(`/executions/${executionId}/errors`).then((r) => r.data),
    enabled: !!executionId,
    // Failures are immutable once recorded; keep the cached result fresh enough
    // to pick up the terminal error_details pushed right after a failure.
    staleTime: 60 * 1000,
    retry: 2,
  });
