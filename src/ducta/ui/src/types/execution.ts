import type { ExecutionStatus } from "../components/ui/statusMeta";

export interface Execution {
  id: string;
  pipeline_name: string;
  project_id?: string;
  node_name?: string;
  /** The nodes a scoped run covered. */
  node_names?: string[];
  /** Rows per input, when this was a sample run. */
  sample_rows?: number;
  /** A debug run: the 127.0.0.1 port its process listens on. */
  debug_port?: number;
  /** Paused at a data breakpoint after this node. */
  paused_at?: string | null;
  user_id?: string;
  env: string;
  status: ExecutionStatus;
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number;
  dry_run: boolean;
  exit_code?: number;
  error_message?: string;
  logs?: string;
  model_version?: string;
  sweep_id?: string;
  sweep_index?: number;
  certificate_run_id?: string;
}

export interface NodeExecution {
  node_id: string;
  node_name: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'skipped';
  started_at?: string;
  finished_at?: string;
  duration_seconds?: number;
  error?: string;
  output?: Record<string, any>;
}
