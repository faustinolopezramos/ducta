import { useMutation, useQueryClient } from "@tanstack/react-query";
import client, { executionClient } from "../client";
import { defaultOnError } from "./errors";
import { qk } from "../queryKeys";

// ── Pipeline mutation payloads (all project-scoped) ───────────────────────────

/** Create a new pipeline inside a project. */
export interface CreatePipelinePayload {
  projectId: string;
  name: string;
  spec: Record<string, unknown>;
}

/** Update an existing pipeline inside a project (upsert). */
export interface UpdatePipelinePayload {
  projectId: string;
  name: string;
  spec: Record<string, unknown>;
  /** Commit SHA last seen for this project's pipelines.yaml (from
   *  `useServerProjectPipelines`' `commit_sha`). Omit to skip the check;
   *  pass it to get a 409 instead of silently overwriting a concurrent edit. */
  expectedSha?: string;
}

/** Delete a pipeline from a project. */
export interface DeletePipelinePayload {
  projectId: string;
  name: string;
  expectedSha?: string;
}

/** Execute a pipeline inside a project. */
export interface ExecutePipelinePayload {
  projectId: string;
  pipelineName: string;
  env?: string;
  nodeName?: string;
  dryRun?: boolean;
  validateOnly?: boolean;
  sanityOnly?: boolean;
  startDate?: string;
  endDate?: string;
  modelVersion?: string;
  hyperparams?: Record<string, unknown>;
  /** What to run: some nodes, everything downstream of one, or only what is stale. */
  scope?: "pipeline" | "selected" | "from" | "after" | "until" | "stale";
  nodes?: string[];
  /** A sample run: this many rows of each input; outputs to the scratch area. */
  sampleRows?: number;
  /** Wait for an IDE debugger to attach before running (local servers). */
  debug?: boolean;
  /** Data breakpoints: pause after each of these nodes until resumed. */
  pauseAfter?: string[];
}

/** Launch a hyperparameter sweep (one execution per combination). */
export interface SweepPipelinePayload {
  projectId: string;
  pipelineName: string;
  sweep: Record<string, unknown>;
  env?: string;
  nodeName?: string;
  startDate?: string;
  endDate?: string;
  modelVersion?: string;
  baseHyperparams?: Record<string, unknown>;
}

/** Execute a single node within a pipeline. */
export interface RunNodePayload {
  projectId: string;
  pipelineName: string;
  nodeName: string;
  env?: string;
  startDate?: string;
  endDate?: string;
}

// ── Pipeline Mutations (project-scoped) ───────────────────────────────────────

/**
 * POST /projects/{projectId}/pipelines
 * Creates a new pipeline inside an existing project.
 * This is the ONLY way to create a pipeline — always scoped to a project.
 */
export const useCreatePipeline = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, name, spec }: CreatePipelinePayload) =>
      client
        .post(`/projects/${projectId}/pipelines`, { name, spec })
        .then((r) => r.data),
    onSuccess: (_data, { projectId }) => {
      queryClient.invalidateQueries({
        queryKey: qk.projects.pipelines(projectId),
      });
      queryClient.invalidateQueries({
        queryKey: qk.projects.detail(projectId),
      });
      queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};

/**
 * PUT /projects/{projectId}/pipelines/{name}
 * Updates (upserts) a pipeline spec inside a project.
 */
export const useUpdatePipeline = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, name, spec, expectedSha }: UpdatePipelinePayload) =>
      client
        .put(`/projects/${projectId}/pipelines/${name}`, { spec, expected_sha: expectedSha })
        .then((r) => r.data),
    onSuccess: (_data, { projectId }) => {
      // A pipeline edit can change which datasets it declares/consumes, and
      // the project's own summary (pipeline_count etc.) — invalidate the
      // whole project subtree, same as create/delete already do, not just
      // the narrow "pipelines" key.
      queryClient.invalidateQueries({
        queryKey: qk.projects.detail(projectId),
      });
      queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};

/**
 * DELETE /projects/{projectId}/pipelines/{name}
 * Removes a pipeline from a project.
 */
export const useDeletePipeline = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, name, expectedSha }: DeletePipelinePayload) =>
      client
        .delete(`/projects/${projectId}/pipelines/${name}`, {
          params: { expected_sha: expectedSha },
        })
        .then(() => {}),
    onSuccess: (_data, { projectId }) => {
      queryClient.invalidateQueries({
        queryKey: qk.projects.pipelines(projectId),
      });
      queryClient.invalidateQueries({
        queryKey: qk.projects.detail(projectId),
      });
      queryClient.invalidateQueries({ queryKey: qk.projects.all() });
      queryClient.invalidateQueries({ queryKey: qk.git.all() });
    },
    onError: defaultOnError,
  });
};

/**
 * POST /projects/{projectId}/pipelines/{pipelineName}/execute
 * Starts an async pipeline execution scoped to a project.
 */
export const useExecutePipeline = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      pipelineName,
      env = "base",
      nodeName,
      dryRun = false,
      validateOnly = false,
      sanityOnly = false,
      startDate,
      endDate,
      modelVersion,
      hyperparams,
      scope,
      nodes,
      sampleRows,
      debug,
      pauseAfter,
    }: ExecutePipelinePayload) =>
      executionClient
        .post(`/projects/${projectId}/pipelines/${pipelineName}/execute`, {
          env,
          dry_run: dryRun,
          validate_only: validateOnly,
          sanity_only: sanityOnly,
          ...(nodeName  ? { node_name:  nodeName  } : {}),
          ...(startDate ? { start_date: startDate } : {}),
          ...(endDate   ? { end_date:   endDate   } : {}),
          ...(modelVersion ? { model_version: modelVersion } : {}),
          ...(hyperparams  ? { hyperparams } : {}),
          ...(scope ? { scope } : {}),
          ...(nodes?.length ? { nodes } : {}),
          ...(sampleRows ? { sample_rows: sampleRows } : {}),
          ...(debug ? { debug: true } : {}),
          ...(pauseAfter?.length ? { pause_after: pauseAfter } : {}),
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.executions.all() });
    },
    onError: defaultOnError,
  });
};

/**
 * POST /projects/{projectId}/pipelines/{pipelineName}/sweep
 * Launches a hyperparameter sweep — one execution per combination, all tagged
 * with a shared sweep_id.
 */
export const useSweepPipeline = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      pipelineName,
      sweep,
      env = "base",
      nodeName,
      startDate,
      endDate,
      modelVersion,
      baseHyperparams,
    }: SweepPipelinePayload) =>
      executionClient
        .post(`/projects/${projectId}/pipelines/${pipelineName}/sweep`, {
          env,
          sweep,
          ...(nodeName  ? { node_name:  nodeName  } : {}),
          ...(startDate ? { start_date: startDate } : {}),
          ...(endDate   ? { end_date:   endDate   } : {}),
          ...(modelVersion    ? { model_version: modelVersion } : {}),
          ...(baseHyperparams ? { base_hyperparams: baseHyperparams } : {}),
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.executions.all() });
    },
    onError: defaultOnError,
  });
};

/**
 * POST /projects/{projectId}/pipelines/{pipelineName}/execute
 * Executes a single node within a pipeline.
 */
export const useRunNode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      pipelineName,
      nodeName,
      env = "base",
      startDate,
      endDate,
    }: RunNodePayload) =>
      executionClient
        .post(`/projects/${projectId}/pipelines/${pipelineName}/execute`, {
          env,
          node_name: nodeName,
          ...(startDate ? { start_date: startDate } : {}),
          ...(endDate   ? { end_date:   endDate   } : {}),
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: qk.executions.all() });
    },
    onError: defaultOnError,
  });
};
