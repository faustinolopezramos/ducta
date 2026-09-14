import type { Execution } from './execution';

export interface NodeAdditionalFile {
  id: string;
  name: string;
  code?: string;
  fn?: string;
  module?: string;
  [key: string]: unknown;
}

/**
 * One side of a node's dataset wiring.
 *
 * `name` is a *reference* into `input_config` / `output_config`; the format,
 * path, write mode and schema live there and are fetched with
 * `useProjectDatasets`. They are deliberately absent here: carrying them
 * meant inventing them, and the hydration used to hard-code `"parquet"` for
 * every dataset in the app.
 */
export interface NodeInputOutput {
  id: string;
  /** Dataset reference name, e.g. `bronze.raw_results`. */
  name: string;
  [key: string]: unknown;
}

export interface Node {
  id: string;
  name: string;
  type: 'source' | 'transform' | 'ml' | 'sink' | 'custom';
  module: string;
  fn?: string;
  description?: string;
  config?: Record<string, any>;
  code?: string;
  inputs: NodeInputOutput[];
  outputs: NodeInputOutput[];
  active: boolean;
  status?: 'idle' | 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'active';
  dependencies?: string[];
  dataQuality?: Record<string, unknown>;
  executionConfig?: Record<string, unknown>;
  files?: NodeAdditionalFile[];
}

export interface Connection {
  id: string;
  name: string;
  type: string;
  config: Record<string, string>;
  description?: string;
}

export interface ProjectGlobalSettings {
  environment?: string;
  mode?: string;
  layer?: string;
  [key: string]: unknown;
}

export interface Project {
  id: string;
  name: string;
  description?: string;
  pipelines: Pipeline[];
  globalSettings?: ProjectGlobalSettings;
  workspace_path?: string;
  created_at: number;
  updated_at: number;
}

export interface Pipeline {
  id: string;
  name: string;
  description?: string;
  type?: string;
  tags?: string[];
  nodes: Node[];
  active: boolean;
  purpose?: 'etl' | 'ml' | 'dq' | 'reporting' | 'custom';
  temporal?: boolean;
  schedule?: {
    enabled: boolean;
    cron?: string;
  };
  streamingConfig?: Record<string, unknown>;
  createdAt: number;
  updatedAt: number;
  lastRun?: string | Execution;
  lastRunDuration?: string | number | null;
  runStatus?: 'idle' | 'running' | 'success' | 'failed';
  /** Set once `useServerPipelineHydration` has seen this pipeline come back
   *  from the server. A locally-created pipeline the server hasn't
   *  confirmed yet stays `undefined` so a later hydration that doesn't list
   *  it (still saving, or the create request hasn't landed) never deletes
   *  it — only a pipeline that *was* confirmed and later disappears from
   *  the server's list (deleted elsewhere) gets removed. */
  persisted?: boolean;
}
