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

/** One streaming node of a running execution (mirrors StreamingNodeStatus). */
export interface StreamingNodeStatus {
  node: string;
  /** active · failed · skipped (never started) · stopped */
  state: "active" | "failed" | "skipped" | "stopped" | string;
  error?: string | null;
  last_batch_id?: number | null;
  num_input_rows?: number | null;
  input_rows_per_second?: number | null;
  processed_rows_per_second?: number | null;
  trigger_execution_ms?: number | null;
  /** The model the query was pinned to when it started. */
  model?: { name?: string; version?: number; source?: string; [k: string]: unknown } | null;
}

export interface StreamingPipelineStatus {
  stream_execution_id: string;
  pipeline_name?: string | null;
  status: string;
  uptime_seconds?: number | null;
  total_queries: number;
  active_queries: number;
  failed_queries: number;
  error?: string | null;
  nodes: StreamingNodeStatus[];
}

export interface StreamingStatusResponse {
  execution_id: string;
  /** False once the execution holds no running engine. */
  active: boolean;
  pipelines: StreamingPipelineStatus[];
}

/** How often a running execution's streams are re-read. */
export const STREAMING_POLL_MS = 5000;

/**
 * GET /executions/{id}/streaming — polled while the execution is running and
 * holds a streaming engine; stops by itself once `active` turns false.
 */
export const useExecutionStreaming = (executionId: string, enabled: boolean) =>
  useQuery<StreamingStatusResponse>({
    queryKey: qk.executions.streaming(executionId),
    queryFn: () => client.get(`/executions/${executionId}/streaming`).then((r) => r.data),
    enabled: !!executionId && enabled,
    refetchInterval: (query: { state: { data?: StreamingStatusResponse } }) =>
      query.state.data?.active === false ? false : STREAMING_POLL_MS,
    staleTime: 0,
  });

export interface Diagnosis {
  execution_id: string;
  status: string;
  /** code | data | quality_gate | config | infra | unknown */
  kind: string;
  title: string;
  message?: string | null;
  node?: string | null;
  frame?: { file: string; line: number; function: string } | null;
  what_changed?: {
    since_run_id?: string | null;
    since?: string | null;
    since_commit?: string | null;
    code: string[];
    data: string[];
    config: boolean;
  } | null;
  suggestions: string[];
  hint?: string | null;
}

/** GET /executions/{id}/diagnosis — what kind of failure, where, and what changed. */
export const useDiagnosis = (executionId: string, enabled = true) =>
  useQuery<Diagnosis>({
    queryKey: [...qk.executions.detail(executionId), "diagnosis"],
    queryFn: () => client.get(`/executions/${executionId}/diagnosis`).then((r) => r.data),
    enabled: !!executionId && enabled,
    staleTime: 60 * 1000,
  });

export interface TrendPoint {
  at: string;
  status: string;
  seconds?: number | null;
}

export interface PipelineMetrics {
  pipeline: string;
  runs: number;
  success_rate?: number | null;
  p50_seconds?: number | null;
  p95_seconds?: number | null;
  last_status?: string | null;
  last_run_at?: string | null;
  last_success_at?: string | null;
  sla?: string | null;
  /** ok | late | no_sla | unknown */
  freshness: string;
  trend: TrendPoint[];
}

export interface NodeMetrics {
  node: string;
  pipeline: string;
  runs: number;
  failures: number;
  p50_seconds?: number | null;
  p95_seconds?: number | null;
  trend: TrendPoint[];
}

/** GET /projects/{id}/metrics — from the run certificates of `env`. */
export const useProjectMetrics = (projectId: string, env: string, days = 30) =>
  useQuery<{ days: number; pipelines: PipelineMetrics[]; nodes: NodeMetrics[] }>({
    queryKey: ["server-projects", projectId, "metrics", env, days],
    queryFn: () => client.get(`/projects/${projectId}/metrics`, { params: { env, days } }).then((r) => r.data),
    enabled: !!projectId,
    staleTime: 30 * 1000,
  });

export interface DebuggerInfo {
  available: boolean;
  reason?: string | null;
  host: string;
  port: number;
  /** The project's absolute path where the API runs — breakpoints are set by it. */
  root?: string;
  vscode: Record<string, unknown>;
}

/** GET /projects/{id}/debugger — polled while a debug run waits for the IDE. */
export const useDebugger = (projectId: string, poll = false) =>
  useQuery<DebuggerInfo>({
    queryKey: ["server-projects", projectId, "debugger"],
    queryFn: () => client.get(`/projects/${projectId}/debugger`).then((r) => r.data),
    enabled: !!projectId,
    refetchInterval: poll ? 2000 : false,
    retry: false,
  });
