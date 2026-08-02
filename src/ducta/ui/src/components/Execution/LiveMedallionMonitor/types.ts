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
  health_score?: number;
}

export type MonitorState = "waiting" | "loading" | "running" | "error" | "stopped";

export interface LiveMedallionMonitorProps {
  executionId?: string | null;
  onCancel: () => void;
  /** Execution-level status from the parent. When terminal, the monitor shows
      "stopped" instead of reverting to "waiting" once the engine unregisters. */
  executionStatus?: string | null;
}

export const TERMINAL_EXEC_STATUSES = new Set(["cancelled", "success", "failed", "skipped"]);
