export interface StreamingStatus {
  pipeline_name?: string;
  status?: "starting" | "running" | "partial_failure" | "error" | "stopped";
  active_queries?: number;
  total_queries?: number;
  failed_queries?: number;
  uptime_seconds?: number;
  query_statuses?: Record<string, { isActive: boolean; lastProgress?: any }>;
  failed_nodes?: Record<string, string>;
}

export interface PerformanceMetrics {
  total_input_rate?: number;
  total_processing_rate?: number;
  processing_efficiency?: number;
}

/** One poll's throughput reading, kept in a rolling window for the sparkline. */
export interface RateSample {
  /** Epoch ms of the poll that produced this sample. */
  t: number;
  input: number;
  processed: number;
}

/**
 * Whether processing is keeping up with arrival — the question a streaming
 * monitor exists to answer.
 *
 * `idle` is deliberately its own verdict rather than 0%: nothing arriving and
 * nothing processed is a healthy resting stream, and reporting it as a zero
 * efficiency made a quiet pipeline look broken.
 */
export type ThroughputVerdict = "idle" | "keeping-up" | "slipping" | "behind";

export type MonitorState = "waiting" | "loading" | "running" | "error" | "stopped";

export interface LiveMedallionMonitorProps {
  executionId?: string | null;
  onCancel: () => void;
  /** Execution-level status from the parent. When terminal, the monitor shows
      "stopped" instead of reverting to "waiting" once the engine unregisters. */
  executionStatus?: string | null;
}

export const TERMINAL_EXEC_STATUSES = new Set(["cancelled", "success", "failed", "skipped"]);
