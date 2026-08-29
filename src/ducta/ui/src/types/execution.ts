export interface Execution {
  id: string;
  pipeline_name: string;
  project_id?: string;
  node_name?: string;
  env: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled' | 'skipped';
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
