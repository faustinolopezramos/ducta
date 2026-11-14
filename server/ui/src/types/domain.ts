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

/**
 * A project as the dashboard lists it: what `GET /projects` returns, minus the
 * wire-only fields. Pipelines are not carried here — they are their own query
 * (`useProjectPipelines`), fetched when a project is opened.
 */
export interface ProjectSummary {
  id: string;
  name: string;
  description?: string;
  /** The server's own count, so a card does not fetch a project's pipelines to count them. */
  pipelineCount?: number;
  createdAt?: string;
  updatedAt?: string;
  /** Why the configuration does not load, when it does not. */
  configError?: string | null;
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
}
