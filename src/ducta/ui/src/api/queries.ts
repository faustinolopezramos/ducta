import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import client from "./client";
import axios from "axios";
import { sourceKey } from "./utils";
import type {
  Execution,
  WorkspaceProject,
  WorkspaceProjectList,
  WorkspaceProjectCreateRequest,
  WorkspaceProjectUpdateRequest,
} from "../types";
import type { WorkspaceInfo } from "../types/api";

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
// SOURCE QUERIES — TanStack Query hooks for
// reading source and config data from the API.
// ─────────────────────────────────────────────

/**
 * GET /workspace
 * Returns current source metadata (name, path, git info, active env).
 */
export const useSourceInfo = () =>
  useQuery<WorkspaceInfo>({
    queryKey: ["source", sourceKey()],
    queryFn: () => client.get<WorkspaceInfo>("/workspace").then((r) => r.data),
    staleTime: 2 * 60 * 1000, // 2 min
    retry: 1,
  });

/**
 * GET /environments
 * Returns { environments: string[], count } — all envs defined in environment.yaml.
 * `project`, when given, resolves the environments of a different project
 * than the one the connected source belongs to (see WorkspaceManager.for_project).
 */
export const useEnvironments = (project?: string) =>
  useQuery({
    queryKey: ["environments", sourceKey(), project ?? null],
    queryFn: () => client.get("/environments", { params: { project } }).then((r) => r.data),
    staleTime: 5 * 60 * 1000, // 5 min — envs rarely change
  });

/**
 * GET /health/platform  (no auth required)
 * Returns OS, architecture, Python version and git availability.
 * Uses a plain axios call (not the authed client) so it works before login.
 */
export const usePlatformInfo = () => {
  const baseURL = client.defaults.baseURL?.replace(/\/api$/, "") ?? "";
  return useQuery({
    queryKey: ["platform"],
    queryFn: () => axios.get(`${baseURL}/health/platform`).then((r) => r.data),
    staleTime: Infinity,   // platform info never changes during a session
    retry: 2,
  });
};

/**
 * GET /git/config
 * Returns { name, email, configured } from the workspace git config.
 */
export const useGitConfig = () =>
  useQuery({
    queryKey: ["git", sourceKey(), "config"],
    queryFn: () => client.get("/git/config").then((r) => r.data),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

/**
 * GET /configs/{env}
 * Returns all config files for the given environment as a
 * { [name]: ConfigFileResponse } map.
 * Only runs when env is provided.
 */
export const useWorkspaceConfigs = (env: string) =>
  useQuery({
    queryKey: ["configs", sourceKey(), env],
    queryFn: () => client.get(`/configs/${env}`).then((r) => r.data),
    staleTime: 60 * 1000, // 1 min
    enabled: !!env,
  });

/**
 * GET /configs/{env}/{name}
 * Returns a single config file for the given environment and name.
 */
export const useWorkspaceConfig = (env: string, name: string) =>
  useQuery({
    queryKey: ["configs", sourceKey(), env, name],
    queryFn: () => client.get(`/configs/${env}/${name}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!env && !!name,
  });

// ─────────────────────────────────────────────
// PIPELINE QUERIES  (project-scoped — canonical)
// ─────────────────────────────────────────────

/**
 * GET /projects/{projectId}/pipelines
 * Returns { project_id, pipelines: { [name]: spec }, count, commit_sha }.
 * `commit_sha` is the whole project's pipelines.yaml version — pass it back
 * as `expectedSha` on useUpdatePipeline/useDeletePipeline for OCC.
 */
export const useServerProjectPipelines = (projectId: string) =>
  useQuery({
    queryKey: ["server-projects", sourceKey(), projectId, "pipelines"],
    queryFn: () =>
      client.get(`/projects/${projectId}/pipelines`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

export interface ProjectDependencyEdge {
  from_pipeline: string;
  from_node: string;
  to_pipeline: string;
  to_node: string;
  dataset?: string | null;
  kind: "explicit" | "dataset" | string;
}

export interface ProjectDependencies {
  project_id: string;
  pipelines: Record<string, string[]>;
  edges: ProjectDependencyEdge[];
}

/**
 * GET /projects/{projectId}/dependencies
 * Node/pipeline dependency graph (explicit deps + shared datasets).
 */
export const useProjectDependencies = (projectId: string) =>
  useQuery<ProjectDependencies>({
    queryKey: ["server-projects", sourceKey(), projectId, "dependencies"],
    queryFn: () =>
      client.get(`/projects/${projectId}/dependencies`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

/**
 * GET /projects/{projectId}/pipelines/{name}
 * Returns { name, spec, project_id }.
 */
export const useProjectPipeline = (projectId: string, name: string) =>
  useQuery({
    queryKey: ["server-projects", sourceKey(), projectId, "pipelines", name],
    queryFn: () =>
      client.get(`/projects/${projectId}/pipelines/${name}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!projectId && !!name,
  });

// ─────────────────────────────────────────────
// DATASET QUERIES
// ─────────────────────────────────────────────

export interface DatasetEndpoint {
  node: string;
  pipeline?: string | null;
}

/**
 * A dataset with its `input_config` / `output_config` entry resolved.
 * Every nullable field is null when the registry does not declare it — an
 * answer, not a gap to fill with a default.
 */
export interface ProjectDataset {
  name: string;
  layer?: "bronze" | "silver" | "gold" | null;
  format?: string | null;
  path?: string | null;
  write_mode?: string | null;
  schema?: string | null;
  options?: Record<string, unknown> | null;
  declared_in: string[];
  producers: DatasetEndpoint[];
  consumers: DatasetEndpoint[];
}

export interface ProjectDatasets {
  project_id: string;
  datasets: ProjectDataset[];
  count: number;
}

/**
 * GET /projects/{projectId}/datasets
 * The project's dataset registry: format, path, write mode, schema, plus the
 * node that produces each dataset and every node that consumes it.
 */
export const useProjectDatasets = (projectId: string) =>
  useQuery<ProjectDatasets>({
    queryKey: ["server-projects", sourceKey(), projectId, "datasets"],
    queryFn: () =>
      client.get(`/projects/${projectId}/datasets`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

// ─────────────────────────────────────────────
// NODE SCHEMA
// ─────────────────────────────────────────────

export interface NodeSchemaIO {
  id: string;
  name: string;
  declared: boolean;
  format?: string | null;
  path?: string | null;
  write_mode?: string | null;
  schema?: string | null;
  layer?: "bronze" | "silver" | "gold" | null;
  description?: string | null;
}

export interface NodeSchema {
  name: string;
  node_id: string;
  type: string;
  module: string;
  fn: string;
  description?: string | null;
  inputs: NodeSchemaIO[];
  outputs: NodeSchemaIO[];
  dependencies: string[];
  file_path: string;
  file_size_bytes?: number | null;
  file_exists: boolean;
  quality?: {
    check_count: number;
    gate_behavior?: string | null;
    is_sanity: boolean;
  } | null;
  last_execution_status?: string | null;
  last_execution_time?: string | null;
  last_execution_duration?: number | null;
  last_execution_error_message?: string | null;
}

export interface PipelineNodeSchema {
  project_id: string;
  pipeline_name: string;
  node: NodeSchema;
}

/**
 * GET /projects/{projectId}/pipelines/{pipeline}/nodes/{node}/schema
 *
 * The node's full detail: datasets resolved against the registry, source-file
 * state, quality checks and gate, and the last run. This endpoint existed for
 * a long time and nothing called it, which is why the inspector could only
 * show a name and an invented format.
 */
export const useNodeSchema = (projectId: string, pipeline: string, node: string) =>
  useQuery<PipelineNodeSchema>({
    queryKey: ["server-projects", sourceKey(), projectId, "pipelines", pipeline, "nodes", node, "schema"],
    queryFn: () =>
      client
        .get(`/projects/${projectId}/pipelines/${pipeline}/nodes/${node}/schema`)
        .then((r) => r.data),
    staleTime: 15 * 1000,
    enabled: !!projectId && !!pipeline && !!node,
  });


// ─────────────────────────────────────────────

// NODE QUERIES
// ─────────────────────────────────────────────

/**
 * GET /nodes
 * Returns { nodes: { [name]: spec }, count }.
 */
export const useNodes = () =>
  useQuery({
    queryKey: ["nodes", sourceKey()],
    queryFn: () => client.get("/nodes").then((r) => r.data),
    staleTime: 60 * 1000,
  });

/**
 * GET /nodes/{name}
 * Returns { name, spec }.
 */
export const useNode = (name: string) =>
  useQuery({
    queryKey: ["nodes", sourceKey(), name],
    queryFn: () => client.get(`/nodes/${name}`).then((r) => r.data),
    staleTime: 60 * 1000,
    enabled: !!name,
  });

/**
 * GET /nodes/{name}/code
 * Returns { name, module_path, code, size_bytes, exists }.
 * Note: This endpoint may not be available in all server versions.
 * If unavailable, we gracefully handle the error and use code from pipeline store.
 */
export const useNodeCode = (name: string) =>
  useQuery({
    queryKey: ["nodes", sourceKey(), name, "code"],
    queryFn: async () => {
      try {
        const result = await client.get(`/nodes/${name}/code`);
        return result.data;
      } catch (error: any) {
        // If endpoint returns 404 or any error, return null instead of failing the query
        // The frontend will fall back to using code from the pipeline store
        if (error?.response?.status === 404 || error?.response?.status === 405) {
          return null;
        }
        throw error;
      }
    },
    staleTime: 30 * 1000,
    enabled: !!name,
  });

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
    queryKey: ["executions", sourceKey(), filters],
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
    queryKey: ["executions", sourceKey(), "queue"],
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
    queryKey: ["executions", sourceKey(), executionId],
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
    queryKey: ["executions", sourceKey(), executionId, "logs"],
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
 * traceback_lines, node_id, attempt, recovery_plan }], warnings }.
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
  recovery_plan: {
    primary: string;
    alternatives: string[];
    retry_delay: number | null;
    notes: string | null;
  } | null;
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
    queryKey: ["executions", sourceKey(), executionId, "errors"],
    queryFn: () => client.get(`/executions/${executionId}/errors`).then((r) => r.data),
    enabled: !!executionId,
    // Failures are immutable once recorded; keep the cached result fresh enough
    // to pick up the terminal error_details pushed right after a failure.
    staleTime: 60 * 1000,
    retry: 2,
  });

// ─────────────────────────────────────────────
// GIT QUERIES
// ─────────────────────────────────────────────

/**
 * GET /git/status
 * Returns { branch, commit, staged, unstaged, untracked }.
 */
export const useGitStatus = () =>
  useQuery({
    queryKey: ["git", sourceKey(), "status"],
    queryFn: () => client.get("/git/status").then((r) => r.data),
    staleTime: 5 * 1000,
    refetchInterval: 30_000,
  });

/**
 * GET /git/log
 * Returns { commits: CommitInfo[], count }.
 * CommitInfo: { sha, short_sha, author, email, message, timestamp,
 *               files_changed, insertions, deletions }
 * Optional params: path (filter by file), limit (default 50, max 500).
 */
export const useGitLog = ({ path, limit = 50 }: { path?: string; limit?: number } = {}) =>
  useQuery({
    queryKey: ["git", sourceKey(), "log", { path, limit }],
    queryFn: () =>
      client
        .get("/git/log", { params: { ...(path ? { path } : {}), limit } })
        .then((r) => r.data),
    staleTime: 30 * 1000,
  });

/**
 * GET /git/commit/{sha}
 * Returns CommitInfo for a single commit.
 */
export const useGitCommit = (sha: string) =>
  useQuery({
    queryKey: ["git", sourceKey(), "commit", sha],
    queryFn: () => client.get(`/git/commit/${sha}`).then((r) => r.data),
    enabled: !!sha,
    staleTime: Infinity, // commits are immutable
  });

/**
 * GET /git/diff/{sha}
 * Returns DiffResponse { commit_a, commit_b, diff } — diff vs parent.
 */
export const useGitDiff = (sha: string) =>
  useQuery({
    queryKey: ["git", sourceKey(), "diff", sha],
    queryFn: () => client.get(`/git/diff/${sha}`).then((r) => r.data),
    enabled: !!sha,
    staleTime: Infinity, // diffs are immutable
  });


// ─────────────────────────────────────────────
// PROJECT QUERIES  (Workspace → Project hierarchy)
// ─────────────────────────────────────────────

/**
 * GET /projects
 * Returns { projects: WorkspaceProject[], count }.
 * These are the server-persisted projects stored in Git under projects/{id}/.
 */
export const useServerProjects = () =>
  useQuery<WorkspaceProjectList>({
    queryKey: ["server-projects", sourceKey()],
    queryFn: () => client.get("/projects").then((r) => r.data),
    staleTime: 30 * 1000,
  });

/**
 * GET /projects/{id}
 */
export const useServerProject = (projectId: string) =>
  useQuery<WorkspaceProject>({
    queryKey: ["server-projects", sourceKey(), projectId],
    queryFn: () => client.get(`/projects/${projectId}`).then((r) => r.data),
    staleTime: 30 * 1000,
    enabled: !!projectId,
  });

/**
 * POST /projects/import — import an existing directory as a project.
 * The directory must already exist inside workspace/projects/.
 * Invalidates the project list on success.
 */
export const useImportServerProject = () => {
  const qc = useQueryClient();
  return useMutation<WorkspaceProject, Error, { path: string; name?: string; description?: string }>({
    mutationFn: (body) => client.post("/projects/import", body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["server-projects", sourceKey()] });
    },
  });
};

/**
 * POST /projects — create a server project.
 * Invalidates the project list on success.
 */
export const useCreateServerProject = () => {
  const qc = useQueryClient();
  return useMutation<WorkspaceProject, Error, WorkspaceProjectCreateRequest>({
    mutationFn: (body) => client.post("/projects", body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["server-projects", sourceKey()] });
    },
  });
};

/**
 * PATCH /projects/{id} — update project metadata.
 */
export const useUpdateServerProject = (projectId: string) => {
  const qc = useQueryClient();
  return useMutation<WorkspaceProject, Error, WorkspaceProjectUpdateRequest>({
    mutationFn: (body) => client.patch(`/projects/${projectId}`, body).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["server-projects", sourceKey()] });
    },
  });
};

/**
 * DELETE /projects/{id}
 */
export const useDeleteServerProject = () => {
  const qc = useQueryClient();
  return useMutation<void, Error, { projectId: string; force?: boolean }>({
    mutationFn: ({ projectId, force }) =>
      client.delete(`/projects/${projectId}`, { params: force ? { force: true } : {} }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["server-projects", sourceKey()] });
    },
  });
};

// ── Workspace File Browser ────────────────────────────────────────────────────

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number | null;
}

/**
 * GET /workspace/files?path=
 * Lists directory contents inside the workspace.
 */
export const useWorkspaceFiles = (path: string = "") =>
  useQuery<{ path: string; entries: FileEntry[] }>({
    queryKey: ["workspace-files", sourceKey(), path],
    queryFn: () =>
      client.get("/workspace/files", { params: { path } }).then((r) => r.data),
    staleTime: 10 * 1000,
  });

/**
 * GET /workspace/files/content?path=
 * Reads a text file from the workspace.
 */
export const useWorkspaceFileContent = (path: string) =>
  useQuery<{ path: string; content: string; size_bytes: number }>({
    queryKey: ["workspace-file-content", sourceKey(), path],
    queryFn: () =>
      client.get("/workspace/files/content", { params: { path } }).then((r) => r.data),
    staleTime: 15 * 1000,
    enabled: !!path,
  });
