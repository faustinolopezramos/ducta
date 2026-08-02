import type { Execution } from './execution';

export interface NodeAdditionalFile {
  id: string;
  name: string;
  code?: string;
  fn?: string;
  module?: string;
  [key: string]: unknown;
}

export interface NodeInputOutput {
  id: string;
  name: string;
  format: string;
  path?: string;
  schema?: Record<string, unknown>;
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

export interface Edge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  animated?: boolean;
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
  edges: Edge[];
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
}
