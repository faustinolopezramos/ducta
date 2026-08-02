import { useMutation, useQueryClient } from "@tanstack/react-query";
import client, { executionClient } from "../client";
import { sourceKey } from "../utils";
import { defaultOnError } from "./errors";

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
}

/** Delete a pipeline from a project. */
export interface DeletePipelinePayload {
  projectId: string;
  name: string;
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
        queryKey: ["server-projects", sourceKey(), projectId, "pipelines"],
      });
      queryClient.invalidateQueries({
        queryKey: ["server-projects", sourceKey(), projectId],
      });
      queryClient.invalidateQueries({ queryKey: ["server-projects", sourceKey()] });
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
    mutationFn: ({ projectId, name, spec }: UpdatePipelinePayload) =>
      client
        .put(`/projects/${projectId}/pipelines/${name}`, { spec })
        .then((r) => r.data),
    onSuccess: (_data, { projectId }) => {
      queryClient.invalidateQueries({
        queryKey: ["server-projects", sourceKey(), projectId, "pipelines"],
      });
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
    mutationFn: ({ projectId, name }: DeletePipelinePayload) =>
      client.delete(`/projects/${projectId}/pipelines/${name}`).then(() => {}),
    onSuccess: (_data, { projectId }) => {
      queryClient.invalidateQueries({
        queryKey: ["server-projects", sourceKey(), projectId, "pipelines"],
      });
      queryClient.invalidateQueries({
        queryKey: ["server-projects", sourceKey(), projectId],
      });
      queryClient.invalidateQueries({ queryKey: ["server-projects", sourceKey()] });
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
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["executions"] });
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
      queryClient.invalidateQueries({ queryKey: ["executions"] });
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
      queryClient.invalidateQueries({ queryKey: ["executions"] });
    },
    onError: defaultOnError,
  });
};
