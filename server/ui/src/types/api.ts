export interface WorkspaceInfo {
  name: string;
  path?: string;
  git_remote?: string;
  warning?: string;
  workspace?: string;
  source_type?: string;
  active_env?: string;
  available_envs?: string[];
  has_git: boolean;
  has_project: boolean;
  environments: string[];
}

export interface WorkspaceProject {
  id: string;
  name: string;
  description?: string;
  workspace: string;
  /** The project directory relative to the workspace root; "" when the workspace is the project. */
  root?: string;
  pipeline_count: number;
  /** "invalid" when the configuration does not load; listed anyway so it can be fixed. */
  config_status?: "ok" | "invalid";
  config_error?: string | null;
  variables: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  _links?: Record<string, string>;
}

export interface WorkspaceProjectList {
  projects: WorkspaceProject[];
  count: number;
  total?: number;
  skip?: number;
  limit?: number;
}

export interface WorkspaceProjectCreateRequest {
  name: string;
  description?: string;
  variables?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface WorkspaceProjectUpdateRequest {
  description?: string;
  variables?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, any>;
}

export interface WsLogEntry {
  timestamp?: string;
  level?: string;
  message?: string;
  extra?: {
    type?: string;
    node_id?: string;
    status?: string;
  };
}
